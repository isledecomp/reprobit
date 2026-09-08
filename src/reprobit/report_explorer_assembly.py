"""Presentation-only assembly captured from receipt-matched intermediate objects.

The capture happens before a composed object is overwritten. Disassembly follows
control flow and compiler line anchors; bytes that cannot be identified this way
remain explicitly undecoded. These views add no semantic proof or build authority.
"""

from __future__ import annotations

import difflib
import struct
from collections.abc import Mapping
from hashlib import sha256
from typing import Any

import capstone  # type: ignore[import-untyped]
from capstone import x86_const

from reprobit.binary import ByteIdentityError
from reprobit.classic.coff import function_symbol
from reprobit.coff_format import CoffObject, coff_body, coff_table, detailed_relocations
from reprobit.costs import InterventionCost, intervention_cost_row_digest
from reprobit.intervention_metadata import ClassicRecipeRole
from reprobit.model import Certificate, Digest
from reprobit.schema import (
    ClassicRecipeIntervention,
    intervention_authority_digest,
)
from reprobit.strict_json import canonical_json

_MAX_OBJECT = 64 * 1024 * 1024
_MAX_BODY = 256 * 1024
_MAX_INSTRUCTIONS = 12000
_MAX_CAPTURE = 12 * 1024 * 1024
_MAX_RANGES = 4096


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _digest(value: object) -> object:
    return Digest.from_bytes(canonical_json(value)).model_dump(mode="json")


def _pin(payload: bytes) -> dict[str, object]:
    return {"digest": Digest.from_bytes(payload).model_dump(mode="json"), "size": len(payload)}


def _ranges(intervention: ClassicRecipeIntervention) -> list[dict[str, object]]:
    parameters = {field.name: field.value for field in intervention.parameters}
    values = parameters.get("instruction_ranges")
    result: list[dict[str, object]] = []
    if not isinstance(values, list) or len(values) > _MAX_RANGES:
        return result
    for index, raw in enumerate(values):
        item = _mapping(raw)
        start, end = item.get("start"), item.get("end")
        before_start, before_end = start, end
        if start is None:
            start, end = item.get("target_start"), item.get("target_end")
            before_start, before_end = None, None
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= _MAX_BODY:
            continue
        result.append(
            {
                "index": index + 1,
                "before_start": before_start,
                "before_end": before_end,
                "after_start": start,
                "after_end": end,
                "donor": item.get("donor", parameters.get("instruction_donor")),
            }
        )
    return result


def _line_roots(coff: CoffObject, section: dict[str, Any], symbol: str) -> set[int]:
    """Only accept line boundaries belonging to this exact COFF function."""
    data = coff_table(coff, section, "lines")
    if len(data) < 12 or len(data) % 6:
        return set()
    index, marker = struct.unpack_from("<IH", data)
    owner_index, _ = function_symbol(coff, symbol, section["number"])
    if marker or index != owner_index:
        return set()
    roots: set[int] = set()
    previous = -1
    for position in range(6, len(data), 6):
        offset, line = struct.unpack_from("<IH", data, position)
        if not line or not previous <= offset < section["raw_size"]:
            return set()
        roots.add(offset)
        previous = offset
    return roots


def _gaps(covered: bytearray) -> list[dict[str, int]]:
    result: list[dict[str, int]] = []
    start: int | None = None
    for offset, value in enumerate(covered):
        if not value and start is None:
            start = offset
        if value and start is not None:
            result.append({"start": start, "end": offset})
            start = None
    if start is not None:
        result.append({"start": start, "end": len(covered)})
    return result


def _relocated_operands(instruction: Any, relocations: list[dict[str, Any]]) -> str:
    """Replace address placeholders with COFF symbols, retaining the operand shape."""
    if not relocations:
        return str(instruction.op_str)
    operands = str(instruction.op_str).split(", ")
    matched: set[int] = set()
    for relocation in relocations:
        relative = relocation["offset"] - instruction.address
        symbol = str(relocation["target"])
        addend = relocation["addend"]
        if addend:
            symbol += f" + 0x{addend:x}"
        replacement = f"<{symbol}>"
        for index, operand in enumerate(instruction.operands):
            if index >= len(operands):
                continue
            if operand.type == x86_const.X86_OP_IMM and relative == instruction.imm_offset:
                operands[index] = replacement
                matched.add(relocation["ordinal"])
                break
            if operand.type == x86_const.X86_OP_MEM and relative == instruction.disp_offset:
                memory = operand.mem
                terms: list[str] = []
                if memory.base:
                    terms.append(instruction.reg_name(memory.base))
                if memory.index:
                    term = instruction.reg_name(memory.index)
                    terms.append(term if memory.scale == 1 else f"{term}*{memory.scale}")
                terms.append(replacement)
                prefix = operands[index].split("[", 1)[0]
                operands[index] = prefix + "[" + " + ".join(terms) + "]"
                matched.add(relocation["ordinal"])
                break
    if len(matched) != len(relocations):
        # Unusual relocations are displayed as symbolic unresolved operands; raw
        # decoder placeholders remain available only in the technical evidence.
        return "<linker operands: " + ", ".join(str(r["target"]) for r in relocations) + ">"
    return ", ".join(operands)


def _decode(
    coff: CoffObject,
    symbol: str,
    ranges: list[dict[str, object]],
    side: str,
) -> tuple[dict[str, object], list[dict[str, Any]]]:
    section = coff.function_section(symbol)
    body = coff_body(coff, section)
    if not body or len(body) > _MAX_BODY:
        raise ValueError("function body exceeds the assembly capture limit")
    relocations = detailed_relocations(coff, section)
    roots = _line_roots(coff, section, symbol) | {0}
    selected = [
        (item[f"{side}_start"], item[f"{side}_end"])
        for item in ranges
        if type(item.get(f"{side}_start")) is int and type(item.get(f"{side}_end")) is int
    ]
    # The closed candidate validator has already checked these declared whole
    # instruction boundaries. They also reach switch cases absent from line rows.
    roots.update(int(start) for start, _ in selected if isinstance(start, int))
    decoder = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    decoder.syntax = capstone.CS_OPT_SYNTAX_INTEL
    decoder.detail = True
    decoder.skipdata = False
    pending = sorted(roots, reverse=True)
    covered = bytearray(len(body))
    decoded: dict[int, dict[str, Any]] = {}
    terminal_ids = {
        x86_const.X86_INS_HLT,
        x86_const.X86_INS_INT3,
        x86_const.X86_INS_UD2,
    }
    while pending and len(decoded) < _MAX_INSTRUCTIONS:
        offset = pending.pop()
        while 0 <= offset < len(body) and not covered[offset]:
            if len(decoded) >= _MAX_INSTRUCTIONS:
                break
            instruction = next(decoder.disasm(body[offset : offset + 15], offset, count=1), None)
            if instruction is None:
                break
            end = offset + instruction.size
            if end > len(body) or any(covered[offset:end]):
                break
            overlapping = [
                r for r in relocations if r["offset"] < end and offset < r["offset"] + r["width"]
            ]
            if any(r["offset"] < offset or r["offset"] + r["width"] > end for r in overlapping):
                break
            operands = _relocated_operands(instruction, overlapping)
            row = {
                "offset": offset,
                "size": instruction.size,
                "bytes": bytes(instruction.bytes).hex(),
                "mnemonic": str(instruction.mnemonic),
                "operands": operands,
                "text": (str(instruction.mnemonic) + " " + operands).rstrip(),
                "raw_operands": str(instruction.op_str),
                "relocations": overlapping,
                "selected": any(
                    isinstance(start, int) and isinstance(stop, int) and start <= offset < stop
                    for start, stop in selected
                ),
            }
            decoded[offset] = row
            covered[offset:end] = b"\x01" * instruction.size
            jump = instruction.group(capstone.CS_GRP_JUMP)
            if jump and not overlapping and instruction.operands:
                target = instruction.operands[0]
                if target.type == x86_const.X86_OP_IMM and 0 <= target.imm < len(body):
                    pending.append(target.imm)
            if (
                instruction.group(capstone.CS_GRP_RET)
                or instruction.group(capstone.CS_GRP_IRET)
                or instruction.id in terminal_ids
                or instruction.id in {x86_const.X86_INS_JMP, x86_const.X86_INS_LJMP}
            ):
                break
            offset = end
    gaps = _gaps(covered)
    selected_complete = all(
        isinstance(start, int)
        and isinstance(end, int)
        and 0 <= start < end <= len(body)
        and start in decoded
        and all(covered[start:end])
        and (end == len(body) or not covered[end] or end in decoded)
        for start, end in selected
    )
    metadata: dict[str, object] = {
        **_pin(coff.data),
        "body_digest": Digest.from_bytes(body).model_dump(mode="json"),
        "body_size": len(body),
        "section_number": section["number"],
        "object_offset": section["raw_offset"],
        "decoded_bytes": sum(covered),
        "undecoded_ranges": gaps,
        "selected_ranges_complete": selected_complete,
        "instruction_count": len(decoded),
        "instruction_limit_reached": len(decoded) >= _MAX_INSTRUCTIONS,
        "undecoded_previews": [
            {
                **gap,
                "bytes": body[gap["start"] : min(gap["end"], gap["start"] + 64)].hex(),
                "truncated": gap["end"] - gap["start"] > 64,
            }
            for gap in gaps[:256]
        ],
        "omitted_undecoded_previews": max(0, len(gaps) - 256),
    }
    return metadata, [decoded[offset] for offset in sorted(decoded)]


def _instruction_key(row: dict[str, Any]) -> str:
    # Relocation-only changes must appear even when their placeholder bytes match.
    relocations = [
        {
            key: value
            for key, value in item.items()
            if key not in {"ordinal", "symbol_index", "offset"}
        }
        for item in row["relocations"]
    ]
    return str(row["bytes"]) + str(row["text"]) + canonical_json(relocations).decode("utf-8")


def _align(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> list[dict[str, object]]:
    matcher = difflib.SequenceMatcher(
        None, [_instruction_key(row) for row in before], [_instruction_key(row) for row in after]
    )
    rows: list[dict[str, object]] = []
    for tag, left_start, left_end, right_start, right_end in matcher.get_opcodes():
        for index in range(max(left_end - left_start, right_end - right_start)):
            left = before[left_start + index] if left_start + index < left_end else None
            right = after[right_start + index] if right_start + index < right_end else None
            kind = (
                "equal"
                if tag == "equal"
                else "replace"
                if left and right
                else ("delete" if left else "insert")
            )
            rows.append(
                {
                    "kind": kind,
                    "before": left,
                    "after": right,
                    "selected": bool((left and left["selected"]) or (right and right["selected"])),
                }
            )
    return rows


def _undecoded_changes(
    before_object: bytes,
    after_object: bytes,
    before: dict[str, object],
    after: dict[str, object],
    left: list[dict[str, Any]],
    right: list[dict[str, Any]],
) -> int | None:
    """Count exact offset-wise changes only when both body extents are the same."""
    if before["body_size"] != after["body_size"]:
        return None
    size = int(str(before["body_size"]))
    start = int(str(before["object_offset"]))
    other_start = int(str(after["object_offset"]))
    first = before_object[start : start + size]
    second = after_object[other_start : other_start + size]
    masks = []
    for instructions in (left, right):
        mask = bytearray(size)
        for row in instructions:
            mask[row["offset"] : row["offset"] + row["size"]] = b"\x01" * row["size"]
        masks.append(mask)
    return sum(
        byte != second[offset] and not (masks[0][offset] and masks[1][offset])
        for offset, byte in enumerate(first)
    )


def capture_assembly_diff(
    intervention: ClassicRecipeIntervention,
    before_object: bytes,
    after_object: bytes,
    *,
    input_statement: object,
    output_statement: object,
) -> dict[str, object] | None:
    """Capture exact intermediate function changes, or refuse unavailable evidence."""
    if intervention.role is not ClassicRecipeRole.FUNCTION or not intervention.symbol:
        return None
    if not isinstance(before_object, bytes) or not isinstance(after_object, bytes):
        return None
    if max(len(before_object), len(after_object)) > _MAX_OBJECT:
        return None
    inputs, outputs = _mapping(input_statement), _mapping(output_statement)
    if (
        inputs.get("intervention") != intervention.model_dump(mode="json")
        or inputs.get("seed") != _pin(before_object)
        or outputs.get("candidate") != _pin(after_object)
    ):
        return None
    try:
        ranges = _ranges(intervention)
        before, left = _decode(CoffObject(before_object), intervention.symbol, ranges, "before")
        after, right = _decode(CoffObject(after_object), intervention.symbol, ranges, "after")
        rows = _align(left, right)
        undecoded_changes = _undecoded_changes(
            before_object, after_object, before, after, left, right
        )
        notes = [
            "Offsets start at this function in each intermediate object; "
            "they are not final addresses.",
            "Instructions are decoded from the function entry, compiler line boundaries, and "
            "the checked selected ranges. Unreached bytes remain data or undecoded bytes.",
        ]
        if any(row["relocations"] for row in left + right):
            notes.append(
                "Names in angle brackets are references filled in by the linker. "
                "Their raw object bytes do not contain final addresses."
            )
        if not before["selected_ranges_complete"] or not after["selected_ranges_complete"]:
            notes.append(
                "Some selected ranges could not be decoded completely; see the raw evidence."
            )
        if undecoded_changes:
            notes.append(
                f"{undecoded_changes:,} changed bytes are outside decoded instructions; "
                "the remaining-byte records show their object bytes."
            )
        elif undecoded_changes is None and (
            before["undecoded_ranges"] or after["undecoded_ranges"]
        ):
            notes.append(
                "The function changes size and has undecoded bytes; remaining-byte records "
                "show each side separately without assuming their offsets align."
            )
        result: dict[str, object] = {
            "schema": 1,
            "intervention_id": intervention.id,
            "authority_digest": intervention_authority_digest(intervention).model_dump(mode="json"),
            "input_statement_digest": _digest(inputs),
            "output_statement_digest": _digest(outputs),
            "coordinate_space": "function",
            "before_label": "Before this intervention",
            "after_label": "After this intervention",
            "decoder": f"Capstone {capstone.__version__}; x86, 32 bit, Intel syntax",
            "before": before,
            "after": after,
            "rows": rows,
            "selected_ranges": ranges,
            "changed_rows": sum(row["kind"] != "equal" for row in rows),
            "undecoded_byte_changes": undecoded_changes,
            "truncated": before["instruction_limit_reached"] or after["instruction_limit_reached"],
            "notes": notes,
        }
        encoded = canonical_json(result)
        if len(encoded) > _MAX_CAPTURE:
            return None
        result["capture_digest"] = sha256(encoded).hexdigest()
        return result
    except (ByteIdentityError, ValueError, TypeError, KeyError, UnicodeError, struct.error):
        return None


def verified_assembly_diff(
    cost: InterventionCost,
    certificate: Certificate | None,
    value: object,
) -> dict[str, object] | None:
    """Bind presentation capture to this report's exact semantic receipt and cost."""
    capture = _mapping(value)
    if (
        not capture
        or capture.get("schema") != 1
        or capture.get("intervention_id") != cost.intervention_id
        or capture.get("coordinate_space") != "function"
        or certificate is None
        or certificate.intervention_id != cost.intervention_id
        or certificate.intervention_authority_digest != cost.intervention_authority_digest
        or certificate.intervention_cost_digest != intervention_cost_row_digest(cost)
        or capture.get("authority_digest")
        != cost.intervention_authority_digest.model_dump(mode="json")
    ):
        return None
    try:
        payload = {key: item for key, item in capture.items() if key != "capture_digest"}
        encoded = canonical_json(payload)
        if len(encoded) > _MAX_CAPTURE or sha256(encoded).hexdigest() != capture.get(
            "capture_digest"
        ):
            return None
        before, after = _mapping(capture.get("before")), _mapping(capture.get("after"))
        for proof in certificate.semantic_proofs:
            inputs, outputs = _mapping(proof.input_statement), _mapping(proof.output_statement)
            if (
                capture.get("input_statement_digest")
                != proof.input_statement_digest.model_dump(mode="json")
                or capture.get("output_statement_digest")
                != proof.output_statement_digest.model_dump(mode="json")
                or _digest(inputs) != capture.get("input_statement_digest")
                or _digest(outputs) != capture.get("output_statement_digest")
                or inputs.get("seed") != {key: before.get(key) for key in ("digest", "size")}
                or outputs.get("candidate") != {key: after.get(key) for key in ("digest", "size")}
            ):
                continue
            declaration = _mapping(inputs.get("intervention"))
            if _digest(
                {"schema": "reprobit-intervention-authority-v1", "intervention": declaration}
            ) != capture.get("authority_digest"):
                continue
            return capture
    except (ValueError, TypeError, RecursionError):
        return None
    return None
