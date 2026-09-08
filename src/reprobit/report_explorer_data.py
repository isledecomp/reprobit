"""Pure, lossless intervention inventory for the visual build explorer.

This is a presentation projection, not additional authenticity evidence. Coordinate
spaces remain explicit; object offsets never become image addresses by inference.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping
from difflib import SequenceMatcher
from typing import Any

from reprobit.classic.overlay_generator import render_classic_overlay_generator
from reprobit.costs import InterventionCost
from reprobit.model import Certificate, Digest, ProvenanceKind, Scope
from reprobit.report import Report
from reprobit.report_explorer_assembly import verified_assembly_diff
from reprobit.report_explorer_mechanics import (
    _generator_is_bounded,
    describe_intervention,
    evidence_details,
)
from reprobit.report_explorer_sources import donor_source_pairs
from reprobit.report_explorer_sources import source_pairs as _source_pairs
from reprobit.report_html_format import readable_function
from reprobit.schema import candidate_auxiliary_donor_ids
from reprobit.strict_json import canonical_json


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _rows(value: object) -> list[dict[str, Any]]:
    return (
        [_mapping(item) for item in value if isinstance(item, Mapping)]
        if isinstance(value, (list, tuple))
        else []
    )


def _integer(value: object) -> int | None:
    if isinstance(value, str):
        try:
            value = int(value, 16 if value.lower().startswith("0x") else 10)
        except ValueError:
            return None
    # JSON numbers above this boundary lose precision in the browser.
    return value if type(value) is int and 0 <= value <= 2**53 - 1 else None


def _scope(scope: Scope) -> dict[str, object]:
    return {"target": scope.target, "tu": scope.translation_unit, "function": scope.function}


def _location(
    space: str, start: int, end: int | None, label: str, basis: str, relation: str = "direct"
) -> dict[str, object]:
    return {
        "space": space,
        "start": start,
        "end": end,
        "label": label,
        "basis": basis,
        "relation": relation,
    }


def _symbol_locations(
    scope: Scope, context: Mapping[str, dict[str, Any]], *, relation: str = "direct"
) -> list[dict[str, object]]:
    if scope.function is None:
        return []
    target = context.get(scope.target, {})
    matches = [
        symbol
        for symbol in _rows(target.get("symbols"))
        if symbol.get("name") == scope.function
        and (symbol.get("tu") is None or symbol.get("tu") == scope.translation_unit)
    ]
    owned = [item for item in matches if item.get("tu") == scope.translation_unit]
    if owned:
        matches = owned
    mapped = [item for item in matches if item.get("space", "va") == "va"]
    if mapped:
        matches = mapped
    # Repeated public aliases at one address are harmless; distinct addresses
    # without an owner identity are ambiguous and must not be guessed.
    positions = {(item.get("space", "va"), _integer(item.get("va"))) for item in matches}
    if len(positions) != 1:
        return []
    symbol = matches[0]
    start = _integer(symbol.get("va"))
    if start is None:
        return []
    size = _integer(symbol.get("size"))
    space = str(symbol.get("space", "va"))
    if space not in {"va", "debug-va", "reference-va", "linked-va"}:
        return []
    return [
        _location(
            space,
            start,
            start + size if size else None,
            readable_function(scope.function),
            str(symbol.get("basis", target.get("basis", "Receipt-checked symbol address"))),
            relation,
        )
    ]


def _changed_ranges(offsets: object, limit: int | None) -> list[tuple[int, int]]:
    if not isinstance(offsets, list):
        return []
    values = sorted(
        {
            offset
            for value in offsets
            if (offset := _integer(value)) is not None and (limit is None or offset < limit)
        }
    )
    ranges: list[tuple[int, int]] = []
    for value in values:
        if ranges and value == ranges[-1][1]:
            ranges[-1] = (ranges[-1][0], value + 1)
        else:
            ranges.append((value, value + 1))
    return ranges


def _parameters(declaration: Mapping[str, Any]) -> dict[str, Any]:
    return {
        str(item["name"]): item.get("value")
        for item in _rows(declaration.get("parameters"))
        if isinstance(item.get("name"), str)
    }


def _declared_dependencies(
    cost: InterventionCost,
    certificate: Certificate | None,
    declaration: object | None,
    known_ids: set[str],
) -> list[str]:
    """Include the exact secondary donor choices admitted by the runtime grammar."""

    raw, statement, _output = evidence_details(cost, certificate, declaration=declaration)
    dependencies = raw.get("dependencies", [])
    primary = (
        [value for value in dependencies if isinstance(value, str)]
        if isinstance(dependencies, list)
        else []
    )
    if cost.kind != "classic_recipe" or cost.scope.function is None:
        return primary

    def identity_values(values: dict[str, Any]) -> dict[str, Any]:
        # Semantic candidate records also carry measured body/metadata fields.
        # Those do not alter a donor's identity and are not recipe conflicts.
        variants = values.get("donor_variants")
        if isinstance(variants, list):
            values = {
                **values,
                "donor_variants": [
                    {"donor": item["donor"]} if isinstance(item, dict) and "donor" in item else item
                    for item in variants
                ],
            }
        return values

    try:
        auxiliary = candidate_auxiliary_donor_ids(
            identity_values(_parameters(raw)),
            identity_values(_mapping(statement.get("candidate_constraints"))),
        )
    except ValueError:
        # Failed or incomplete reports retain their inventory without promoting
        # conflicting or malformed candidate declarations to navigation edges.
        auxiliary = ()
    return list(
        dict.fromkeys(
            [
                *primary,
                *(
                    identity
                    for identity in auxiliary
                    if identity in known_ids and identity != cost.intervention_id
                ),
            ]
        )
    )


def _source_excerpt(text: str, *, size: object = None, new_file: bool = False) -> str:
    if text:
        return text
    if new_file:
        return "(new file)"
    return "(empty file)" if type(size) is int and size == 0 else "(no text in this excerpt)"


def _source_previews(
    cost: InterventionCost,
    certificate: Certificate | None,
    sources: dict[str, Any],
    *,
    declaration: object | None = None,
    source_diffs: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    declaration, statement, _output = evidence_details(cost, certificate, declaration=declaration)
    captured: dict[tuple[str, str | None, str], list[dict[str, Any]]] = defaultdict(list)
    for item in source_diffs or []:
        path, before_digest, after_digest = (
            item.get("path"),
            item.get("before_digest"),
            item.get("after_digest"),
        )
        if (
            isinstance(path, str)
            and isinstance(after_digest, str)
            and (before_digest is None or isinstance(before_digest, str))
            and isinstance(item.get("before"), str)
            and isinstance(item.get("after"), str)
        ):
            captured[(path, before_digest, after_digest)].append(item)
    previews = []
    for path, before_digest, after_digest in _source_pairs(declaration, statement):
        if not isinstance(after_digest, str):
            continue
        if before_digest is None or isinstance(before_digest, str):
            matches = captured.get((path, before_digest, after_digest), [])
            if len(matches) == 1:
                pair = matches[0]
                note = str(pair.get("note", "Captured source pair bound to the recorded digests."))
                if pair.get("truncated"):
                    note += " This is a bounded excerpt; additional source changes may be omitted."
                previews.append(
                    {
                        "title": path,
                        "before": _source_excerpt(
                            pair["before"],
                            size=pair.get("before_size"),
                            new_file=before_digest is None,
                        ),
                        "after": _source_excerpt(pair["after"], size=pair.get("after_size")),
                        "note": note,
                        "source_path": path,
                        "preview_kind": "file",
                        "source_rendering": _mapping(pair.get("source_rendering")),
                    }
                )
                continue
        before = _mapping(sources.get(before_digest)) if isinstance(before_digest, str) else {}
        after = _mapping(sources.get(after_digest))
        if not isinstance(after.get("text"), str) or (
            before_digest is not None and not isinstance(before.get("text"), str)
        ):
            continue
        left = str(before.get("text", "")).splitlines()
        right = str(after["text"]).splitlines()
        if left == right:
            continue
        groups = list(SequenceMatcher(None, left, right, autojunk=False).get_grouped_opcodes(3))
        before_lines: list[str] = []
        after_lines: list[str] = []
        shown_groups = 0
        clipped = False
        for group in groups:
            # Truncated input ends are not actual file ends: never present a
            # truncation boundary as a source deletion or insertion.
            if (before.get("truncated") and group[-1][2] >= len(left)) or (
                after.get("truncated") and group[-1][4] >= len(right)
            ):
                continue
            if shown_groups == 8 or max(len(before_lines), len(after_lines)) > 120:
                break
            if shown_groups:
                before_lines.append("…")
                after_lines.append("…")
            for operation, left_start, left_end, right_start, right_end in group:
                clipped = clipped or left_end - left_start > 120 or right_end - right_start > 120
                before_lines.extend(
                    f"{number + 1:4} {' ' if operation == 'equal' else '-'} {left[number]}"
                    for number in range(left_start, min(left_end, left_start + 120))
                )
                after_lines.extend(
                    f"{number + 1:4} {' ' if operation == 'equal' else '+'} {right[number]}"
                    for number in range(right_start, min(right_end, right_start + 120))
                )
            shown_groups += 1
        if not shown_groups:
            continue
        before_text = "\n".join(before_lines)
        after_text = "\n".join(after_lines)
        clipped = clipped or len(before_text) > 16000 or len(after_text) > 16000
        note = (
            "Recorded source contents checked against their digests; line numbers show the edits."
        )
        if (
            clipped
            or shown_groups < len(groups)
            or before.get("truncated")
            or after.get("truncated")
        ):
            note += " This is a bounded excerpt; additional source changes may be omitted."
        previews.append(
            {
                "title": path,
                "before": _source_excerpt(
                    before_text[:16000],
                    size=before.get("size"),
                    new_file=before_digest is None,
                ),
                "after": _source_excerpt(after_text[:16000], size=after.get("size")),
                "note": note,
                "source_path": path,
                "preview_kind": "file",
            }
        )
    return previews


def _source_action_previews(
    cost: InterventionCost,
    certificate: Certificate | None,
    previews: list[dict[str, Any]],
    captures: list[dict[str, Any]],
    *,
    declaration: object | None = None,
) -> list[dict[str, Any]]:
    declaration, statement, output = evidence_details(cost, certificate, declaration=declaration)
    declared = {
        (path, before, after)
        for path, before, after in _source_pairs(declaration, statement)
        if (before is None or isinstance(before, str)) and isinstance(after, str)
    }
    donor_pairs = set(donor_source_pairs(declaration, statement))
    declared.update(donor_pairs)
    validation = _mapping(_mapping(output.get("project_overlay_epoch")).get("source_validation"))
    receipts: dict[tuple[str, str], list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    for receipt in _rows(validation.get("render_receipts")):
        for operation in _rows(receipt.get("operations")):
            if isinstance(receipt.get("path"), str) and isinstance(
                operation.get("operation_id"), str
            ):
                receipts[(receipt["path"], operation["operation_id"])].append((receipt, operation))
    result = []
    for preview in previews:
        path, action_id, action = (
            preview.get("source_path"),
            preview.get("action_id"),
            preview.get("operation"),
        )
        matches = [
            item
            for item in captures
            if item.get("intervention_id") == cost.intervention_id
            and item.get("path") == path
            and item.get("action_id") == action_id
            and item.get("operation") == action
        ]
        held = receipts.get((str(path), str(action_id)), [])
        if len(matches) == 1 and not held and matches[0].get("basis") == "donor-render-replay":
            capture = matches[0]
            originals = [
                op
                for rendering in _rows(_parameters(declaration).get("renderings"))
                if rendering.get("path") == path
                for ordinal, op in enumerate(_rows(rendering.get("operations")))
                if op.get("id", f"{path}#{ordinal}") == action_id and op.get("op") == action
            ]
            if len(originals) == 1:
                original = originals[0]
                generator = _mapping(original.get("gen"))
                try:
                    fragment = (
                        render_classic_overlay_generator(generator)
                        if _generator_is_bounded(generator)
                        else None
                    )
                except (ValueError, TypeError, KeyError, OverflowError):
                    fragment = None
                pair_key = path, capture.get("before_digest"), capture.get("after_digest")
                if (
                    all(isinstance(part, str) for part in pair_key)
                    and pair_key in donor_pairs
                    and capture.get("operation_declaration_digest")
                    == Digest.from_bytes(canonical_json(original)).value
                    and fragment is not None
                    and capture.get("fragment_digest") == Digest.from_bytes(fragment).value
                    and capture.get("fragment_size") == len(fragment)
                ):
                    removed = _mapping(original.get("removed"))
                    held = [
                        (
                            {"input_digest": pair_key[1], "output_digest": pair_key[2]},
                            {
                                "action": action,
                                "removed_digest": removed.get("sha256"),
                                "removed_size": removed.get("size"),
                                "fragment_digest": Digest.from_bytes(fragment).value,
                                "fragment_size": len(fragment),
                            },
                        )
                    ]
        if len(matches) != 1 or len(held) != 1:
            result.append(preview)
            continue
        capture, (receipt, operation) = matches[0], held[0]
        source_key = path, receipt.get("input_digest"), receipt.get("output_digest")
        pins = ("removed_digest", "removed_size", "fragment_digest", "fragment_size")
        if (
            not isinstance(path, str)
            or not (source_key[1] is None or isinstance(source_key[1], str))
            or not isinstance(source_key[2], str)
            or source_key not in declared
            or capture.get("before_digest") != source_key[1]
            or capture.get("after_digest") != source_key[2]
            or operation.get("action") != action
            or any(capture.get(pin) != operation.get(pin) for pin in pins)
            or not isinstance(capture.get("before"), str)
            or not isinstance(capture.get("after"), str)
        ):
            result.append(preview)
            continue
        before, after = capture["before"], capture["after"]
        if capture.get("truncated") is not True:
            removed_digest = operation.get("removed_digest")
            valid_before = (
                _complete_source_text(before, removed_digest, operation.get("removed_size"))
                if isinstance(removed_digest, str)
                else before == ""
            )
            valid_after = (
                after == ""
                if action == "delete"
                else _complete_source_text(
                    after, str(operation.get("fragment_digest")), operation.get("fragment_size")
                )
            )
            if not valid_before or not valid_after:
                result.append(preview)
                continue
        result.append(
            {
                **preview,
                "before": before,
                "after": after,
                "note": str(capture.get("note", "Exact source text from the recorded edit.")),
                "source_rendering": _mapping(capture.get("source_rendering")),
                "source_captured": True,
                "preview_kind": "action",
            }
        )
    return result


def _complete_source_text(text: str, digest: str, size: object) -> bool:
    """Confirm a decoded display contains the complete declared byte stream."""
    for encoding in ("utf-8", "cp1252"):
        try:
            payload = text.encode(encoding)
        except UnicodeEncodeError:
            continue
        if type(size) is int and len(payload) != size:
            continue
        if Digest.from_bytes(payload).value == digest:
            return True
    return False


def _generated_tu_previews(
    cost: InterventionCost,
    certificate: Certificate | None,
    previews: list[dict[str, Any]],
    sources: dict[str, Any],
    source_diffs: list[dict[str, Any]],
    *,
    declaration: object | None = None,
) -> list[dict[str, Any]]:
    """Put generated source on its costed action while retaining build placement."""
    if not any(item.get("operation") == "generated_tus" for item in previews):
        return previews
    raw, _statement, _output = evidence_details(cost, certificate, declaration=declaration)
    parameters = _parameters(raw)
    units = _rows(_mapping(parameters.get("graph")).get("generated_tus"))
    outputs = _rows(parameters.get("outputs"))
    actions = {f"generated_tus#{index}": unit for index, unit in enumerate(units, 1)}
    result = []
    for original in previews:
        unit = actions.get(str(original.get("action_id")))
        if original.get("operation") != "generated_tus" or unit is None:
            result.append(original)
            continue
        preview = {
            **original,
            "build_context": unit,
            "content_complete": False,
            "content_available": False,
        }
        path = unit.get("path")
        matching_outputs = [item for item in outputs if item.get("path") == path]
        if not isinstance(path, str) or len(matching_outputs) != 1:
            preview["after"] = "Source contents are not available in this report."
            result.append(preview)
            continue
        output = matching_outputs[0]
        before_digest, after_digest = output.get("clean"), output.get("effective")
        if not isinstance(after_digest, str):
            preview["after"] = "Source contents are not available in this report."
            result.append(preview)
            continue
        matches = [
            item
            for item in source_diffs
            if item.get("path") == path
            and item.get("before_digest") == before_digest
            and item.get("after_digest") == after_digest
            and isinstance(item.get("after"), str)
        ]
        captured = matches[0] if len(matches) == 1 else {}
        snapshot = _mapping(sources.get(after_digest))
        captured_text = str(captured.get("after", ""))
        candidates: list[tuple[str, bool]] = []
        if isinstance(snapshot.get("text"), str):
            candidates.append((snapshot["text"], not snapshot.get("truncated", False)))
        if captured and before_digest is None:
            first, separator, remainder = captured_text.partition("\n")
            if separator and re.fullmatch(r"@@ lines 1-[0-9]+ @@", first):
                captured_text = remainder
            candidates.append((captured_text, not captured.get("truncated", False)))
        complete = next(
            (
                text
                for text, untruncated in candidates
                if untruncated and _complete_source_text(text, after_digest, output.get("size"))
            ),
            None,
        )
        if complete is not None:
            preview.update(
                {
                    "before": "(new compilation unit)",
                    "after": complete or "(empty file)",
                    "content_complete": True,
                    "content_available": True,
                    "note": (
                        "Complete generated source; its bytes match the recorded output digest. "
                        "Build placement is shown separately."
                    ),
                }
            )
        elif captured or isinstance(snapshot.get("text"), str):
            preview.update(
                {
                    "before": "(new compilation unit)",
                    "after": (captured_text if captured else str(snapshot.get("text", "")))
                    or "(no text in this excerpt)",
                    "content_available": True,
                    "note": (
                        "Recorded generated source excerpt; the complete file is not available "
                        "in this report. Build placement is shown separately."
                    ),
                }
            )
        else:
            preview.update(
                {
                    "after": "Source contents are not available in this report.",
                    "note": (
                        "Recorded generated unit and its build placement; source was not captured."
                    ),
                }
            )
        result.append(preview)
    return result


def _present_previews(
    previews: list[dict[str, Any]], *, assembly_available: bool
) -> list[dict[str, Any]]:
    measurements = {
        "Changed byte positions",
        "Function size",
        "Instruction size changes",
        "Reference positions",
    }
    assembly_records = (
        "Register roles",
        "Stack locations",
        "Registers for selected values",
        "Instruction order",
        "Floating-point sum order",
        "Floating-point pointer exchanges",
        "Squared addend exchanges",
        "Operand order changes",
        "Stack argument exchanges",
        "Comparison encodings",
        "Selected instruction ranges",
    )
    return [
        {
            **preview,
            "presentation": (
                "technical"
                if preview.get("presentation") == "technical"
                or preview.get("title") in measurements
                or (
                    assembly_available
                    and str(preview.get("title", "")).startswith(assembly_records)
                )
                else "primary"
            ),
        }
        for preview in previews
    ]


def _intervention_locations(
    cost: InterventionCost,
    certificate: Certificate | None,
    report: Report,
    context: Mapping[str, dict[str, Any]],
    *,
    declaration: object | None = None,
) -> tuple[list[dict[str, object]], int | None, int | None]:
    declaration, _input, output = evidence_details(cost, certificate, declaration=declaration)
    trace = _mapping(output.get("validator_trace"))
    parameters = _parameters(declaration)
    locations = _symbol_locations(cost.scope, context)
    for beneficiary in cost.beneficiaries:
        locations.extend(_symbol_locations(beneficiary, context, relation="beneficiary"))

    body_size = next(
        (
            value
            for key in ("body_length", "donor_length")
            if (value := _integer(trace.get(key))) is not None
        ),
        None,
    )
    changed = _changed_ranges(trace.get("body_changed_offsets"), body_size)
    changed_bytes = (
        sum(end - start for start, end in changed)
        if isinstance(trace.get("body_changed_offsets"), list)
        else _integer(trace.get("changed_byte_count"))
    )
    if cost.scope.function is not None:
        # The measured output-body extent is not a linked-image symbol extent:
        # debug companions can describe a pre-repack layout or an alias.
        if body_size:
            locations.append(
                _location(
                    "function",
                    0,
                    body_size,
                    readable_function(cost.scope.function),
                    "Measured object function body; offset starts at the function entry",
                )
            )
        locations.extend(
            _location(
                "function",
                start,
                end,
                "Changed body bytes",
                "Validator body_changed_offsets; object function coordinates",
                "changed",
            )
            for start, end in changed
        )

    for quarantine in report.verdict.quarantines:
        if quarantine.id != cost.intervention_id:
            continue
        space = "file" if quarantine.coordinate_space == "artifact-file" else "function"
        for interval in quarantine.ranges:
            locations.append(
                _location(
                    space,
                    interval.offset,
                    interval.end,
                    "Reference-derived bytes",
                    f"Quarantine disclosure ({quarantine.coordinate_space})",
                    "changed",
                )
            )
        if quarantine.base_address is not None and space == "function":
            locations.append(
                _location(
                    "reference-va",
                    quarantine.base_address,
                    None,
                    "Reference function address",
                    "Declared reference address; final candidate placement is unverified",
                )
            )
        changed_bytes = quarantine.byte_count

    if cost.family is not None and cost.family.value == "image_metadata":
        for write in _rows(trace.get("writes")):
            offset = _integer(write.get("file_offset"))
            if offset is not None:
                locations.append(
                    _location(
                        "file",
                        offset,
                        offset + 4,
                        "Image timestamp field",
                        "Certified PE timestamp write; four-byte field",
                        "changed",
                    )
                )
    repack = _mapping(parameters.get("text_repack"))
    for piece in _rows(repack.get("pieces")):
        start, end = _integer(piece.get("src_lo")), _integer(piece.get("src_hi"))
        if start is not None and end is not None and end > start:
            locations.append(
                _location(
                    "linked-va",
                    start,
                    end,
                    "Repacked source bytes",
                    "Declared source virtual-address interval before the final repack",
                    "moved",
                )
            )
            shift = _integer(piece.get("shift"))
            if shift is not None and start >= shift:
                locations.append(
                    _location(
                        "va",
                        start - shift,
                        end - shift,
                        "Repacked destination bytes",
                        "Declared destination virtual-address interval after the final repack",
                        "moved",
                    )
                )
    fill = _mapping(repack.get("vacated_fill"))
    start, length = _integer(fill.get("va")), _integer(fill.get("length"))
    if start is not None and length:
        locations.append(
            _location(
                "va",
                start,
                start + length,
                "Vacated space",
                "Declared final image fill interval",
                "changed",
            )
        )
    imports = _mapping(parameters.get("import_order"))
    base, rva, size = (
        _integer(imports.get(key))
        for key in ("image_base", "import_directory_rva", "import_directory_size")
    )
    if base is not None and rva is not None and size:
        locations.append(
            _location(
                "va",
                base + rva,
                base + rva + size,
                "Import directory",
                "Declared import table location; indirect operand repairs can occur elsewhere",
            )
        )
    locations.extend(_file_locations(locations, context.get(cost.scope.target, {})))
    unique: dict[tuple[object, ...], dict[str, object]] = {}
    for item in locations:
        key = tuple(item[field] for field in ("space", "start", "end", "label", "relation"))
        unique.setdefault(key, item)
    return list(unique.values()), changed_bytes, body_size


def _file_locations(
    locations: list[dict[str, object]], context: dict[str, Any]
) -> list[dict[str, object]]:
    """Project final VAs only through one unambiguous, raw-backed PE section."""

    sections = _rows(context.get("sections"))
    result: list[dict[str, object]] = []
    for location in locations:
        if location.get("space") != "va":
            continue
        start = _integer(location.get("start"))
        end = _integer(location.get("end"))
        if start is None or (end is not None and end <= start):
            continue
        probe_end = end if end is not None else start + 1
        mappings: list[tuple[int, int | None]] = []
        overlapping_virtual_sections = 0
        for section in sections:
            va, size, file_offset, file_size = (
                _integer(section.get(key)) for key in ("va", "size", "file_offset", "file_size")
            )
            if None in (va, size, file_offset, file_size):
                continue
            assert va is not None and size is not None and file_offset is not None
            assert file_size is not None
            if start < va + size and va < probe_end:
                overlapping_virtual_sections += 1
            if va <= start and probe_end <= va + min(size, file_size):
                mappings.append((file_offset + start - va, file_offset + end - va if end else None))
        if len(mappings) != 1 or overlapping_virtual_sections != 1:
            continue
        offset, file_end = mappings[0]
        probe_file_end = file_end if file_end is not None else offset + 1
        raw_overlaps = sum(
            offset < raw_offset + raw_size and raw_offset < probe_file_end
            for section in sections
            if (raw_offset := _integer(section.get("file_offset"))) is not None
            and (raw_size := _integer(section.get("file_size"))) is not None
        )
        if raw_overlaps != 1:
            continue
        result.append(
            _location(
                "file",
                offset,
                file_end,
                str(location.get("label", "Mapped image location")),
                "Mapped from a final virtual address through a receipt-checked PE section",
                str(location.get("relation", "direct")),
            )
        )
    return result


def _add_declared_reference_spans(
    report: Report,
    context: dict[str, dict[str, Any]],
    certificates: Mapping[str, Certificate],
) -> list[dict[str, object]]:
    """Retain explicit reference spans from signed function candidate constraints."""

    targets = {target.id: target for target in report.targets}
    diagnostics: list[dict[str, object]] = []
    for cost in report.costs.interventions:
        if cost.scope.function is None:
            continue
        _declaration, statement, _output = evidence_details(
            cost, certificates.get(cost.intervention_id)
        )
        span = _mapping(_mapping(statement.get("candidate_constraints")).get("retail_oracle"))
        target = targets.get(cost.scope.target)
        if target is None or span.get("verdict") != "MATCH":
            continue
        image = span.get("image")
        if not isinstance(image, str) or image.replace("\\", "/").rsplit("/", 1)[-1].casefold() != (
            target.artifact.replace("\\", "/").rsplit("/", 1)[-1].casefold()
        ):
            continue
        start, size = _integer(span.get("address")), _integer(span.get("length"))
        if start is None or not size or start + size > 2**53 - 1:
            continue
        row = context.setdefault(target.id, {"id": target.id})
        symbols = _rows(row.get("symbols"))
        matched = [
            symbol
            for symbol in symbols
            if (
                symbol.get("name") == cost.scope.function
                and symbol.get("tu") in {None, cost.scope.translation_unit}
                and symbol.get("space", "va") == "va"
            )
        ]
        if any(symbol.get("va") != start for symbol in matched):
            diagnostics.append(
                {
                    "kind": "reference-address-conflict",
                    "target_id": target.id,
                    "message": f"Declared reference span for {cost.scope.function} conflicts with "
                    "a mapped symbol and was not used for the map.",
                }
            )
            continue
        if matched:
            continue
        space = "va" if target.byte_exact else "reference-va"
        if any(
            symbol.get("name") == cost.scope.function
            and symbol.get("va") == start
            and symbol.get("space", "va") == space
            for symbol in symbols
        ):
            continue
        symbols.append(
            {
                "name": cost.scope.function,
                "tu": cost.scope.translation_unit,
                "va": start,
                "size": size,
                "space": space,
                "basis": (
                    "Proof-declared reference span; candidate matches the reference byte for byte"
                    if target.byte_exact
                    else "Proof-declared reference span; candidate placement is unverified"
                ),
            }
        )
        row["symbols"] = symbols
    return diagnostics


def _artifact_targets(report: Report) -> dict[str, list[str]]:
    artifacts = {item.id: item for item in report.proof.artifacts}
    owners: dict[str, set[str]] = defaultdict(set)
    for target in report.targets:
        pending = [
            item.id
            for item in artifacts.values()
            if (
                item.logical_path == target.artifact
                and item.digest == target.candidate_digest
                and item.size == target.candidate_size
            )
        ]
        visited: set[str] = set()
        while pending:
            identity = pending.pop()
            if identity in visited:
                continue
            visited.add(identity)
            owners[identity].add(target.id)
            if identity in artifacts:
                pending.extend(artifacts[identity].inputs)
    return {identity: sorted(targets) for identity, targets in owners.items()}


def _operations(report: Report, context: dict[str, object]) -> list[dict[str, object]]:
    owners = _artifact_targets(report)
    artifacts = {item.id: item for item in report.proof.artifacts}
    specifications = _rows(context.get("object_transforms"))
    result: list[dict[str, object]] = []
    for node in report.proof.provenance:
        if node.intervention_id is not None or node.kind not in {
            ProvenanceKind.OBJECT_TRANSFORM,
            ProvenanceKind.METADATA_TRANSFORM,
        }:
            continue
        artifact = artifacts.get(node.artifact_id)
        targets = owners.get(node.artifact_id, [])
        locations = (
            []
            if node.byte_range is None
            else [
                _location(
                    "artifact",
                    node.byte_range.offset,
                    node.byte_range.end,
                    artifact.logical_path if artifact else node.artifact_id,
                    "Byte interval in the named intermediate artifact",
                )
            ]
        )
        specification: dict[str, Any] = {}
        if artifact is not None and node.kind is ProvenanceKind.OBJECT_TRANSFORM:
            for candidate in specifications:
                if not isinstance(candidate.get("tu"), str) or candidate.get("operation") != (
                    node.operation
                ):
                    continue
                # The runtime artifact identity binds the source unit, output
                # digest and size. Match it rather than guessing from filenames.
                identity = (
                    "artifact."
                    + Digest.from_bytes(
                        canonical_json(
                            (
                                "object-transform",
                                candidate["tu"],
                                artifact.digest,
                                artifact.size,
                            )
                        )
                    ).value[:24]
                )
                if identity == artifact.id:
                    specification = candidate
                    break
        title = {
            "restore_comdat_group_order": "Restore object section order",
            "swap_comdat_group_order": "Swap object section order",
        }.get(node.operation, node.operation.replace("_", " ").capitalize())
        result.append(
            {
                "id": node.id,
                "title": title,
                "stage": "object" if node.kind is ProvenanceKind.OBJECT_TRANSFORM else "image",
                "target": targets[0] if len(targets) == 1 else None,
                "targets": targets,
                "cost": 0,
                "locations": locations,
                "kind": node.kind.value,
                "artifact": artifact.logical_path if artifact else node.artifact_id,
                "summary": (
                    "Reorder the listed compiled function groups within the source unit's object; "
                    "no additional intervention charge."
                    if specification
                    else "Recorded build preparation; no additional intervention charge."
                ),
                "detail": specification,
            }
        )
    for supplemental in report.proof.supplemental_outputs:
        for file in supplemental.files:
            for category in file.categories:
                result.append(
                    {
                        "id": f"{supplemental.id}:{file.role}:{category.category}",
                        "title": category.category.replace("_", " "),
                        "stage": "debug",
                        "target": supplemental.target_id,
                        "targets": [supplemental.target_id],
                        "cost": 0,
                        "kind": "debug_normalization",
                        "artifact": file.logical_path,
                        "changed_bytes": category.changed_bytes,
                        "range_count": category.changed_range_count,
                        "omitted_ranges": category.omitted_changed_ranges,
                        "locations": [
                            _location(
                                "supplemental-file",
                                interval.offset,
                                interval.end,
                                file.logical_path,
                                "Debug companion file offset; outside the final candidate binary",
                                "changed",
                            )
                            for interval in category.changed_ranges
                        ],
                        "summary": "Deterministic debug companion bookkeeping; zero cost points.",
                    }
                )
    return result


def build_explorer_data(
    report: Report, *, context: dict[str, object] | None = None
) -> dict[str, object]:
    """Project every charged intervention and auxiliary transform into one inventory.

    ``context`` is optional receipt-checked local enrichment. Omitting it keeps
    rendering entirely independent of the filesystem and still covers the ledger.
    """
    local = report.exploration if context is None else context
    target_context = {str(item["id"]): item for item in _rows(local.get("targets")) if "id" in item}
    certificates = {item.intervention_id: item for item in report.proof.certificates}
    declarations = {
        **_mapping(report.exploration.get("declarations")),
        **_mapping(local.get("declarations")),
    }
    diagnostics = _add_declared_reference_spans(report, target_context, certificates)
    sources = _mapping(local.get("sources"))
    source_diffs = _rows(local.get("source_diffs"))
    source_operations = _rows(local.get("source_operations"))
    translation_units: dict[tuple[str, str], set[str]] = defaultdict(set)
    for unit in _rows(local.get("translation_units")):
        if all(isinstance(unit.get(key), str) for key in ("target", "tu", "source_path")):
            translation_units[(unit["target"], unit["tu"])].add(unit["source_path"])
    assembly_captures = _mapping(local.get("assembly"))
    known_ids = {cost.intervention_id for cost in report.costs.interventions}
    interventions: list[dict[str, Any]] = []
    for cost in report.costs.interventions:
        certificate = certificates.get(cost.intervention_id)
        locations, changed_bytes, body_size = _intervention_locations(
            cost,
            certificate,
            report,
            target_context,
            declaration=declarations.get(cost.intervention_id),
        )
        description = describe_intervention(
            cost, certificate, declaration=declarations.get(cost.intervention_id)
        )
        description["dependencies"] = _declared_dependencies(
            cost, certificate, declarations.get(cost.intervention_id), known_ids
        )
        source_previews = (
            _source_previews(
                cost,
                certificate,
                sources,
                declaration=declarations.get(cost.intervention_id),
                source_diffs=source_diffs,
            )
            if sources or source_diffs
            else []
        )
        action_previews = _generated_tu_previews(
            cost,
            certificate,
            _rows(description.get("previews")),
            sources,
            source_diffs,
            declaration=declarations.get(cost.intervention_id),
        )
        action_previews = _source_action_previews(
            cost,
            certificate,
            action_previews,
            source_operations,
            declaration=declarations.get(cost.intervention_id),
        )
        source_paths = {
            str(item["source_path"])
            for item in [*source_previews, *action_previews]
            if isinstance(item.get("source_path"), str)
        }
        unit_paths = translation_units.get(
            (cost.scope.target, cost.scope.translation_unit or ""), set()
        )
        if len(unit_paths) == 1:
            source_paths.update(unit_paths)
        description["source_paths"] = sorted(source_paths)
        assembly = verified_assembly_diff(
            cost, certificate, assembly_captures.get(cost.intervention_id)
        )
        description["previews"] = _present_previews(
            [*source_previews, *action_previews], assembly_available=assembly is not None
        )
        interventions.append(
            {
                **description,
                "id": cost.intervention_id,
                **_scope(cost.scope),
                "display_function": readable_function(cost.scope.function)
                if cost.scope.function
                else None,
                "kind": cost.kind,
                "family": cost.family.value if cost.family is not None else None,
                "assembly": assembly,
                "cost": cost.cost,
                "cost_class": cost.cost_class.value,
                "units": [unit.model_dump(mode="json") for unit in cost.units],
                "beneficiaries": [_scope(scope) for scope in cost.beneficiaries],
                "status": "missing"
                if certificate is None
                else ("passed" if certificate.passed else "failed"),
                "checks": [
                    obligation.model_dump(mode="json") for obligation in certificate.obligations
                ]
                if certificate is not None
                else [],
                "artifact_ids": list(certificate.artifact_ids) if certificate is not None else [],
                "locations": locations,
                "changed_bytes": changed_bytes,
                "body_size": body_size,
            }
        )
    targets: list[dict[str, object]] = []
    for target in report.targets:
        extra = target_context.get(target.id, {})
        rows = [row for row in interventions if row["target"] == target.id]
        targets.append(
            {
                **extra,
                "id": target.id,
                "artifact": target.artifact,
                "size": target.candidate_size,
                "byte_exact": target.byte_exact,
                "sections": _rows(extra.get("sections")),
                "symbols": _rows(extra.get("symbols")),
                "cost": sum(row["cost"] for row in rows),
                "intervention_count": len(rows),
            }
        )
    functions = []
    for function in report.costs.by_function:
        total = function.allocated_shared_cost.as_fraction() + function.direct_cost
        functions.append(
            {
                **_scope(function.scope),
                "display_function": readable_function(str(function.scope.function)),
                "direct_cost": function.direct_cost,
                "allocated_shared_cost": function.allocated_shared_cost.model_dump(mode="json"),
                "total_cost": {"numerator": total.numerator, "denominator": total.denominator},
                "exposure_cost": function.exposure_cost,
                "locations": _symbol_locations(function.scope, target_context),
            }
        )
    operations = _operations(report, local)
    mapped = sum(
        any(location["space"] in {"va", "file"} for location in row["locations"])
        for row in interventions
    )
    relative = sum(
        not any(location["space"] in {"va", "file"} for location in row["locations"])
        and any(location["space"] == "function" for location in row["locations"])
        for row in interventions
    )
    return {
        "schema": 1,
        "project_id": report.project_id,
        "run_id": report.run_id.value,
        "summary": {
            "total_cost": report.costs.project_total,
            "intervention_count": len(interventions),
            "unit_count": sum(
                unit.count for cost in report.costs.interventions for unit in cost.units
            ),
            "mapped_interventions": mapped,
            "function_relative_interventions": relative,
            "unlocated_interventions": len(interventions) - mapped - relative,
            "operation_count": len(operations),
        },
        "targets": targets,
        "interventions": interventions,
        "functions": functions,
        "operations": operations,
        "diagnostics": [*_rows(local.get("diagnostics")), *diagnostics],
        "sources": _mapping(local.get("sources")),
    }


__all__ = ["build_explorer_data"]
