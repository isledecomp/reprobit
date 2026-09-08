"""Bounded source-change excerpts from immutable compiler-epoch inputs."""

from __future__ import annotations

import copy
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict
from difflib import SequenceMatcher
from hashlib import sha256
from pathlib import PurePosixPath
from typing import Any

from reprobit.classic.overlay_document import render_classic_overlay_proposal
from reprobit.classic.semantic_contracts import ProjectOverlaySourcePair
from reprobit.classic_donors import _render_overlay_carrier
from reprobit.report import Report
from reprobit.report_explorer_mechanics import _generator_is_bounded
from reprobit.report_explorer_source_rendering import render_source_rows
from reprobit.strict_json import canonical_json

_MAX_PAIRS = 1024
_MAX_PAIR_BYTES = 4 * 1024 * 1024
_MAX_SIDE_CHARACTERS = 32_000
_MAX_TOTAL_CHARACTERS = 2_000_000


def source_rendering(
    context: dict[str, Any],
    before: bytes,
    after: bytes,
    *,
    before_start_line: int | None = 1,
    after_start_line: int | None = 1,
) -> dict[str, Any]:
    """Share one bounded aligned-source display budget across all captures."""
    budget = context.setdefault("source_rendering_coverage", {"rows": 0, "characters": 0})
    rendering = render_source_rows(
        before,
        after,
        before_start_line=before_start_line,
        after_start_line=after_start_line,
        # The character budget bounds retained source globally. A second global
        # row cap starved later edits even while most character space was free.
        max_rows=400,
        max_characters=max(0, min(64_000, _MAX_TOTAL_CHARACTERS - budget["characters"])),
    )
    budget["rows"] += len(rendering["rows"])
    budget["characters"] += rendering["characters"]
    return rendering


def _line_at(payload: bytes, offset: int) -> int:
    return 1 + sum(match.end() <= offset for match in re.finditer(rb"\r\n|\r|\n", payload))


def _carrier_is_bounded(carrier: Mapping[str, object]) -> bool:
    kind = carrier.get("kind")
    if kind in {"force_included_shape_v1", "force_included_pad_shape_v1"}:
        return True  # These shapes do not alter the source byte stream.
    seats = ("header", "seat") if kind == "extern_run_pair_v1" else ("pre", "post", "eof")
    if kind not in {"extern_run_pair_v1", "declaration_run_triple_v1"}:
        return False
    width = carrier.get("width")
    if type(width) is not int or not 0 <= width <= 100:
        return False
    estimate = 0
    for seat in seats:
        count, prefix = carrier.get(seat + "_count"), carrier.get(seat + "_prefix")
        if type(count) is not int or not 0 <= count <= 10_000 or not isinstance(prefix, str):
            return False
        estimate += count * (len(prefix.encode("utf-8")) + width + 32)
    return estimate <= _MAX_PAIR_BYTES


def source_pairs(
    declaration: Mapping[str, Any], statement: Mapping[str, Any]
) -> list[tuple[str, object, object]]:
    """Use exact named source receipts, never similar paths or file contents."""

    def mapping(value: object) -> dict[str, Any]:
        return dict(value) if isinstance(value, Mapping) else {}

    def rows(value: object) -> list[dict[str, Any]]:
        return (
            [mapping(item) for item in value if isinstance(item, Mapping)]
            if isinstance(value, (list, tuple))
            else []
        )

    parameters = {
        str(item["name"]): item.get("value")
        for item in rows(declaration.get("parameters"))
        if isinstance(item.get("name"), str)
    }
    result = [
        (str(item["path"]), item.get("clean"), item.get("effective"))
        for item in rows(parameters.get("outputs"))
        if isinstance(item.get("path"), str)
    ]
    request = mapping(mapping(statement.get("compiler_statement")).get("request_receipt"))
    inputs, outputs = mapping(request.get("input_digests")), mapping(request.get("output_digests"))
    owners = [name.removeprefix("effective:") for name in inputs if name.startswith("effective:")]
    for name, after in outputs.items():
        path = name.removeprefix("inc/source/")
        if name == "s.cpp":
            if len(owners) != 1:
                continue
            path = owners[0]
        before = inputs.get(f"effective:{path}", inputs.get(f"clean:{path}"))
        if before is not None:
            result.append((path, before, after))
    known_paths = {item[0] for item in result}
    result.extend(
        pair for pair in donor_source_pairs(declaration, statement) if pair[0] not in known_paths
    )
    return result


def donor_source_pairs(
    declaration: Mapping[str, Any], statement: Mapping[str, Any]
) -> list[tuple[str, str, str]]:
    """Donor overlay anchors resolve against the named clean input versions."""
    if declaration.get("family") != "donor_source_overlay":
        return []
    parameters = {
        item["name"]: item.get("value")
        for item in declaration.get("parameters", [])
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    compiler = statement.get("compiler_statement", {})
    request = compiler.get("request_receipt", {}) if isinstance(compiler, Mapping) else {}
    if not isinstance(request, Mapping) or request.get("intervention_id") != declaration.get("id"):
        return []
    inputs, outputs = request.get("input_digests", {}), request.get("output_digests", {})
    if not isinstance(inputs, Mapping) or not isinstance(outputs, Mapping):
        return []
    owners = [name.removeprefix("effective:") for name in inputs if name.startswith("effective:")]
    result = []
    renderings = parameters.get("renderings", [])
    if not isinstance(renderings, list):
        return []
    for raw in renderings:
        if not isinstance(raw, Mapping) or not isinstance(raw.get("path"), str):
            continue
        path = raw["path"]
        before = inputs.get("clean:" + path)
        after = outputs.get("inc/source/" + path)
        if owners == [path]:
            after = outputs.get("s.cpp", after)
        elif after is None and parameters.get("include_projection", "none") in {
            "none",
            "source_root_mirror_v1",
        }:
            basename = PurePosixPath(path).name
            matches = [
                item
                for item in renderings
                if isinstance(item, Mapping)
                and isinstance(item.get("path"), str)
                and item["path"] not in owners
                and PurePosixPath(item["path"]).name.casefold() == basename.casefold()
            ]
            if len(matches) == 1:
                after = outputs.get("inc/" + basename)
        if isinstance(before, str) and isinstance(after, str):
            result.append((path, before, after))
    return result


def _declared_pairs(report: Report) -> set[tuple[str, str | None, str, int]]:
    result: set[tuple[str, str | None, str, int]] = set()
    for certificate in report.proof.certificates:
        for proof in certificate.semantic_proofs:
            statement = proof.input_statement
            if not isinstance(statement, dict):
                continue
            intervention = statement.get("intervention", {})
            parameters = (
                intervention.get("parameters", []) if isinstance(intervention, dict) else []
            )
            for parameter in parameters if isinstance(parameters, list) else []:
                if not isinstance(parameter, dict) or parameter.get("name") != "outputs":
                    continue
                outputs = parameter.get("value", [])
                for output in outputs if isinstance(outputs, list) else []:
                    if not isinstance(output, dict):
                        continue
                    path, before, after, size = (
                        output.get("path"),
                        output.get("clean"),
                        output.get("effective"),
                        output.get("size"),
                    )
                    if (
                        isinstance(path, str)
                        and (before is None or isinstance(before, str))
                        and isinstance(after, str)
                        and type(size) is int
                        and size >= 0
                    ):
                        result.add((path, before, after, size))
    return result


def _decode(payload: bytes) -> str:
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError:
        return payload.decode("cp1252", errors="replace")


def _excerpts(before: bytes, after: bytes, limit: int) -> tuple[str, str, bool]:
    left, right = (
        _decode(before).splitlines(keepends=True),
        _decode(after).splitlines(keepends=True),
    )
    before_parts: list[str] = []
    after_parts: list[str] = []
    used_left = used_right = 0
    clipped = False
    # Autogenerated source contains long repeated runs. The default autojunk
    # heuristic bounds that common case while every emitted edit remains exact.
    groups = SequenceMatcher(None, left, right).get_grouped_opcodes(3)
    for group in groups:
        a, b, c, d = group[0][1], group[-1][2], group[0][3], group[-1][4]
        old = (f"@@ lines {a + 1}-{b} @@\n" if b > a else "") + "".join(left[a:b])
        new = (f"@@ lines {c + 1}-{d} @@\n" if d > c else "") + "".join(right[c:d])
        if before_parts:
            old, new = "\n…\n" + old, "\n…\n" + new
        available_left, available_right = limit - used_left, limit - used_right
        before_parts.append(old[:available_left])
        after_parts.append(new[:available_right])
        used_left += min(len(old), available_left)
        used_right += min(len(new), available_right)
        if len(old) > available_left or len(new) > available_right:
            clipped = True
            break
    return "".join(before_parts), "".join(after_parts), clipped


def _operation_fragments(
    receipt: Mapping[str, Any], before: bytes, after: bytes
) -> list[tuple[dict[str, Any], bytes, bytes]] | None:
    """Recover exact edit payloads from recorded positions, never text search."""
    if (
        receipt.get("input_digest") != (sha256(before).hexdigest() if before else None)
        and receipt.get("input_digest") != sha256(before).hexdigest()
    ) or receipt.get("output_digest") != sha256(after).hexdigest():
        return None
    expected_input_size = None if receipt.get("input_digest") is None else len(before)
    if receipt.get("input_size") != expected_input_size or receipt.get("output_size") != len(after):
        return None
    raw = receipt.get("operations")
    if not isinstance(raw, (list, tuple)) or len(raw) > 2048:
        return None
    resolved: list[tuple[int, int, int, dict[str, Any]]] = []
    ids: set[str] = set()
    for ordinal, operation in enumerate(raw):
        if not isinstance(operation, dict):
            return None
        operation_id, action = operation.get("operation_id"), operation.get("action")
        if not isinstance(operation_id, str) or operation_id in ids:
            return None
        ids.add(operation_id)
        anchors = operation.get("anchors")
        if not isinstance(anchors, (list, tuple)) or any(
            not isinstance(item, dict) for item in anchors
        ):
            return None
        if any(not isinstance(item.get("role"), str) for item in anchors):
            return None
        positions = {item.get("role"): item.get("byte_offset") for item in anchors}
        if len(positions) != len(anchors):
            return None
        start: Any
        end: Any
        if action == "append":
            start = end = len(before)
        elif action in {"insert", "replace", "delete"}:
            start = positions.get("start")
            end = start if action == "insert" else positions.get("end")
        else:
            return None
        if type(start) is not int or type(end) is not int or not 0 <= start <= end <= len(before):
            return None
        size = operation.get("fragment_size")
        if type(size) is not int or not 0 <= size <= _MAX_PAIR_BYTES:
            return None
        removed = before[start:end]
        if action in {"replace", "delete"} and (
            operation.get("removed_size") != len(removed)
            or operation.get("removed_digest") != sha256(removed).hexdigest()
        ):
            return None
        resolved.append((start, end, ordinal, operation))
    old_at = new_at = 0
    fragments: dict[int, tuple[dict[str, Any], bytes, bytes]] = {}
    for start, end, ordinal, operation in sorted(resolved, key=lambda item: item[:3]):
        if start < old_at:
            return None
        unchanged = before[old_at:start]
        if after[new_at : new_at + len(unchanged)] != unchanged:
            return None
        new_at += len(unchanged)
        removed = before[start:end]
        payload_size = 0 if operation["action"] == "delete" else operation["fragment_size"]
        inserted = after[new_at : new_at + payload_size]
        if len(inserted) != payload_size:
            return None
        if operation["action"] != "delete" and (
            sha256(inserted).hexdigest() != operation.get("fragment_digest")
        ):
            return None
        # A relocation deletion's fragment describes the held range, while an
        # ordinary deletion's fragment is empty. Neither inserts bytes here.
        if operation["action"] == "delete" and (
            operation.get("fragment_digest"),
            operation.get("fragment_size"),
        ) not in {(sha256(b"").hexdigest(), 0), (sha256(removed).hexdigest(), len(removed))}:
            return None
        fragments[ordinal] = (
            {
                **operation,
                "before_start_line": _line_at(before, start),
                "after_start_line": _line_at(after, new_at),
            },
            removed,
            inserted,
        )
        old_at, new_at = end, new_at + payload_size
    if before[old_at:] != after[new_at:]:
        return None
    return [fragments[index] for index in range(len(raw))]


def collect_donor_source_operations(
    report: Report, context: dict[str, Any], load: Callable[[str], bytes | None]
) -> None:
    """Replay declared donor edits solely against receipt-checked byte inputs."""
    statements = [
        proof.input_statement
        for certificate in report.proof.certificates
        for proof in certificate.semantic_proofs
        if isinstance(proof.input_statement, dict)
    ]
    canonical: dict[tuple[str, str, str, str], list[list[dict[str, Any]]]] = {}
    for statement in statements:
        declaration = statement.get("intervention", {})
        if not isinstance(declaration, dict):
            continue
        target = declaration.get("scope", {}).get("target")
        for field in declaration.get("parameters", []):
            if not isinstance(field, dict) or field.get("name") != "outputs":
                continue
            for output in field.get("value", []):
                if not isinstance(output, dict):
                    continue
                key = target, output.get("path"), output.get("clean"), output.get("effective")
                ops = output.get("ops")
                if all(isinstance(part, str) for part in key) and isinstance(ops, list):
                    canonical.setdefault(
                        (str(key[0]), str(key[1]), str(key[2]), str(key[3])), []
                    ).append(ops)
    captures = context.setdefault("source_operations", [])
    seen = {
        (item.get("intervention_id"), item.get("path"), item.get("action_id"))
        for item in captures
        if isinstance(item, dict)
    }
    characters = sum(len(item.get("before", "")) + len(item.get("after", "")) for item in captures)
    missing: list[dict[str, str]] = []
    for statement in statements:
        declaration = statement.get("intervention", {})
        if not isinstance(declaration, dict):
            continue
        identities = donor_source_pairs(declaration, statement)
        if not identities:
            continue
        parameters = {
            item["name"]: item.get("value")
            for item in declaration.get("parameters", [])
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        }
        raw_renderings = parameters.get("renderings", [])
        if not isinstance(raw_renderings, list) or len(raw_renderings) != len(identities):
            continue
        expected_operations = {
            (declaration.get("id"), item.get("path"), op.get("id", f"{item.get('path')}#{ordinal}"))
            for item in raw_renderings
            if isinstance(item, dict)
            for ordinal, op in enumerate(item.get("operations", []))
            if isinstance(op, dict)
        }
        if expected_operations <= seen:
            continue
        request = statement["compiler_statement"]["request_receipt"]
        prepared: list[dict[str, Any]] = []
        inputs: dict[str, bytes] = {}
        outputs: dict[str, bytes] = {}
        prefixes: dict[str, int] = {}
        try:
            for index, ((path, before_digest, after_digest), raw) in enumerate(
                zip(identities, raw_renderings, strict=True)
            ):
                before, after = load(before_digest), load(after_digest)
                if before is None or after is None:
                    raise ValueError("An exact recorded source input is unavailable.")
                if len(before) + len(after) > _MAX_PAIR_BYTES:
                    raise ValueError("A source pair exceeds the capture byte limit.")
                if (
                    sha256(before).hexdigest() != before_digest
                    or sha256(after).hexdigest() != after_digest
                ):
                    raise ValueError("Retained source bytes differ from their recorded hashes.")
                ops = copy.deepcopy(raw.get("operations"))
                if not isinstance(ops, list) or len(ops) > 2048 or not _generator_is_bounded(ops):
                    raise ValueError("Source operations exceed the bounded renderer limits.")
                prefixes[path] = 0
                if index == 0 and parameters.get("canonical_overlay_replay") is not None:
                    if parameters["canonical_overlay_replay"] != "owning_translation_unit_v1":
                        raise ValueError("The recorded source replay mode is unsupported.")
                    key = (
                        declaration.get("scope", {}).get("target"),
                        path,
                        before_digest,
                        request["input_digests"].get("effective:" + path),
                    )
                    candidates = canonical.get(key, [])
                    if len(candidates) != 1:
                        raise ValueError("The original source overlay is absent or ambiguous.")
                    prefixes[path] = len(candidates[0])
                    ops = copy.deepcopy(candidates[0]) + ops
                if len(ops) > 2048 or not _generator_is_bounded(ops):
                    raise ValueError(
                        "Combined source operations exceed the bounded renderer limits."
                    )
                prepared.append(
                    {"path": path, "clean": before_digest, "effective": after_digest, "ops": ops}
                )
                inputs[path], outputs[path] = before, after
            rendered = render_classic_overlay_proposal(prepared, inputs)
            carrier = parameters.get("compiler_state_carrier")
            for path, value in rendered.outputs.items():
                final = value
                if carrier is not None:
                    if (
                        len(rendered.outputs) != 1
                        or not isinstance(carrier, Mapping)
                        or not _generator_is_bounded(carrier)
                        or not _carrier_is_bounded(carrier)
                    ):
                        raise ValueError("The compiler-state source rendering is unsupported.")
                    final = _render_overlay_carrier(value, carrier)
                if final != outputs[path]:
                    raise ValueError(
                        "Replayed source edits differ from the complete recorded output."
                    )
            receipts_by_path = {receipt.path: receipt for receipt in rendered.receipts}
            for raw, identity in zip(raw_renderings, identities, strict=True):
                path, before_digest, after_digest = identity
                receipt = receipts_by_path[path]
                fragments = _operation_fragments(
                    asdict(receipt), inputs[path], rendered.outputs[path]
                )
                if fragments is None:
                    raise ValueError(
                        "Resolved edit bytes differ from their fresh rendering receipts."
                    )
                for ordinal, ((operation, before, after), original) in enumerate(
                    zip(fragments[prefixes[path] :], raw["operations"], strict=True)
                ):
                    action_id = original.get("id", f"{path}#{ordinal}")
                    operation_key = declaration["id"], path, action_id
                    if operation_key in seen:
                        continue
                    remaining = _MAX_TOTAL_CHARACTERS - characters
                    if remaining < 2 or len(captures) >= 2048:
                        raise ValueError("Source action text exceeds the capture display limit.")
                    limit = min(_MAX_SIDE_CHARACTERS, remaining // 2)
                    left, right = _decode(before), _decode(after)
                    old, new = left[:limit], right[:limit]
                    characters += len(old) + len(new)
                    after_line = (
                        operation["after_start_line"]
                        if rendered.outputs[path] == outputs[path]
                        else None
                    )
                    captures.append(
                        {
                            "intervention_id": declaration["id"],
                            "path": path,
                            "action_id": action_id,
                            "operation": original["op"],
                            "before_digest": before_digest,
                            "after_digest": after_digest,
                            "before": old,
                            "after": new,
                            "removed_digest": operation.get("removed_digest"),
                            "removed_size": operation.get("removed_size"),
                            "fragment_digest": operation["fragment_digest"],
                            "fragment_size": operation["fragment_size"],
                            "operation_declaration_digest": sha256(
                                canonical_json(original)
                            ).hexdigest(),
                            "basis": "donor-render-replay",
                            "truncated": len(old) != len(left) or len(new) != len(right),
                            "source_rendering": source_rendering(
                                context,
                                before,
                                after,
                                before_start_line=operation["before_start_line"],
                                after_start_line=after_line,
                            ),
                            "note": (
                                "Exact donor edit replayed from recorded source and parameters; "
                                "the complete generated source matches the build output."
                                + (
                                    " Text is clipped to the report display limit."
                                    if len(old) != len(left) or len(new) != len(right)
                                    else ""
                                )
                            ),
                        }
                    )
                    seen.add(operation_key)
        except (ValueError, TypeError, KeyError, OverflowError, AssertionError) as exc:
            missing.append(
                {"intervention_id": str(declaration.get("id")), "reason": str(exc)[:300]}
            )
    if missing:
        context.setdefault("diagnostics", []).append(
            {
                "kind": "donor-source-operation-unavailable",
                "count": len(missing),
                "message": (
                    f"{len(missing)} donor edit groups could not be replayed "
                    "from recorded source bytes."
                ),
                "details": missing[:32],
            }
        )


def _capture_operations(
    report: Report, pairs: Sequence[ProjectOverlaySourcePair], context: dict[str, Any]
) -> None:
    by_identity = {
        (
            pair.path,
            sha256(pair.clean_payload).hexdigest() if pair.clean_payload is not None else None,
            sha256(pair.effective_payload).hexdigest(),
        ): pair
        for pair in pairs
        if len(pair.clean_payload or b"") + len(pair.effective_payload) <= _MAX_PAIR_BYTES
    }
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    characters = omitted = rejected = 0
    for certificate in report.proof.certificates:
        for proof in certificate.semantic_proofs:
            statement = proof.input_statement
            output = getattr(proof, "output_statement", None)
            if not isinstance(statement, dict) or not isinstance(output, dict):
                continue
            declaration = statement.get("intervention", {})
            if not isinstance(declaration, dict) or not isinstance(declaration.get("id"), str):
                continue
            intervention_id = declaration["id"]
            declared_pairs = {
                (path, before, after)
                for path, before, after in source_pairs(declaration, statement)
                if (before is None or isinstance(before, str)) and isinstance(after, str)
            }
            epoch = output.get("project_overlay_epoch", {})
            validation = epoch.get("source_validation", {}) if isinstance(epoch, dict) else {}
            receipts = validation.get("render_receipts", []) if isinstance(validation, dict) else []
            for receipt in receipts if isinstance(receipts, list) else []:
                if not isinstance(receipt, dict):
                    continue
                key = receipt.get("path"), receipt.get("input_digest"), receipt.get("output_digest")
                if (
                    not isinstance(key[0], str)
                    or (key[1] is not None and not isinstance(key[1], str))
                    or not isinstance(key[2], str)
                ):
                    rejected += 1
                    continue
                if key not in declared_pairs or key not in by_identity:
                    rejected += 1
                    continue
                pair = by_identity[key]
                fragments = _operation_fragments(
                    receipt, pair.clean_payload or b"", pair.effective_payload
                )
                if fragments is None:
                    rejected += 1
                    continue
                for operation, before, after in fragments:
                    operation_key = intervention_id, pair.path, operation["operation_id"]
                    if operation_key in seen:
                        continue
                    seen.add(operation_key)
                    remaining = _MAX_TOTAL_CHARACTERS - characters
                    if len(result) >= 2048 or remaining < 2:
                        omitted += 1
                        continue
                    limit = min(_MAX_SIDE_CHARACTERS, remaining // 2)
                    left, right = _decode(before), _decode(after)
                    old, new = left[:limit], right[:limit]
                    clipped = len(old) != len(left) or len(new) != len(right)
                    characters += len(old) + len(new)
                    result.append(
                        {
                            "intervention_id": intervention_id,
                            "path": pair.path,
                            "action_id": operation["operation_id"],
                            "operation": operation["action"],
                            "before_digest": key[1],
                            "after_digest": key[2],
                            "removed_digest": operation.get("removed_digest"),
                            "removed_size": operation.get("removed_size"),
                            "fragment_digest": operation["fragment_digest"],
                            "fragment_size": operation["fragment_size"],
                            "before_start_line": operation["before_start_line"],
                            "after_start_line": operation["after_start_line"],
                            "source_rendering": source_rendering(
                                context,
                                before,
                                after,
                                before_start_line=operation["before_start_line"],
                                after_start_line=operation["after_start_line"],
                            ),
                            "before": old,
                            "after": new,
                            "truncated": clipped,
                            "note": "Exact source text at the recorded edit positions; "
                            "the original and inserted bytes match the recorded hashes."
                            + (" Text is clipped to the report display limit." if clipped else ""),
                        }
                    )
    context["source_operations"] = result
    if omitted or rejected:
        context.setdefault("diagnostics", []).append(
            {
                "kind": "source-operation-capture",
                "omitted": omitted,
                "rejected": rejected,
                "message": f"{omitted} source actions exceeded capture limits; "
                f"{rejected} source receipts did not match retained source bytes.",
            }
        )


def collect_source_diff_context(
    report: Report, *, pairs: Sequence[ProjectOverlaySourcePair]
) -> dict[str, object]:
    """Capture clean/effective differences without re-reading overwritten files.

    The runtime already retains these exact byte pairs for compiler-epoch proof.
    Both hashes and the effective size must match the report's source declaration
    before snippets can enter its noncertifying exploration payload.
    """
    context: dict[str, Any] = copy.deepcopy(report.exploration)
    declared = _declared_pairs(report)
    diffs: list[dict[str, Any]] = []
    diagnostics = context.setdefault("diagnostics", [])
    characters = omitted = rejected = 0
    seen = set()
    for pair in sorted(pairs, key=lambda item: item.path):
        if len(diffs) >= _MAX_PAIRS or characters >= _MAX_TOTAL_CHARACTERS:
            omitted += 1
            continue
        before = pair.clean_payload or b""
        after = pair.effective_payload
        if len(before) + len(after) > _MAX_PAIR_BYTES:
            omitted += 1
            continue
        old_digest = sha256(before).hexdigest() if pair.clean_payload is not None else None
        new_digest = sha256(after).hexdigest()
        key = (pair.path, old_digest, new_digest, len(after))
        if key not in declared:
            rejected += 1
            continue
        if key in seen or before == after:
            continue
        seen.add(key)
        budget = min(_MAX_SIDE_CHARACTERS, (_MAX_TOTAL_CHARACTERS - characters) // 2)
        if budget == 0:
            omitted += 1
            continue
        old, new, clipped = _excerpts(before, after, budget)
        characters += len(old) + len(new)
        diffs.append(
            {
                "path": pair.path,
                "before_digest": old_digest,
                "after_digest": new_digest,
                "before_size": len(before),
                "after_size": len(after),
                "before": old,
                "after": new,
                "truncated": clipped,
                "source_rendering": source_rendering(context, before, after),
                "note": (
                    "Exact source excerpts captured during this build; "
                    "complete files match the recorded hashes and size."
                    + (" Excerpts are clipped to the report display limit." if clipped else "")
                    + (" This file did not exist before the change." if old_digest is None else "")
                ),
            }
        )
    context["source_diffs"] = diffs
    # Some donor edits use the original clean version even after the overlay
    # has overwritten its only path. Retain only originals still needed by a
    # different declared change; ordinary clean/effective pairs have excerpts.
    covered = {(item["path"], item["before_digest"], item["after_digest"]) for item in diffs}
    needed: set[str] = set()
    for certificate in report.proof.certificates:
        for proof in certificate.semantic_proofs:
            statement = proof.input_statement
            if not isinstance(statement, dict):
                continue
            declaration = statement.get("intervention", {})
            if not isinstance(declaration, dict):
                continue
            for path, pair_before, pair_after in source_pairs(declaration, statement):
                if (
                    isinstance(pair_before, str)
                    and isinstance(pair_after, str)
                    and pair_before != pair_after
                    and (path, pair_before, pair_after) not in covered
                ):
                    needed.add(pair_before)
            needed.update(
                before for _path, before, _after in donor_source_pairs(declaration, statement)
            )
    snapshots = context.setdefault("sources", {})
    snapshot_characters = sum(len(item.get("text", "")) for item in snapshots.values())
    for pair in pairs:
        if pair.clean_payload is None or len(pair.clean_payload) > _MAX_PAIR_BYTES:
            continue
        digest = sha256(pair.clean_payload).hexdigest()
        if digest not in needed or digest in snapshots:
            continue
        if not any(item[0] == pair.path and item[1] == digest for item in declared):
            continue
        try:
            text, encoding = pair.clean_payload.decode("utf-8"), "utf-8"
        except UnicodeDecodeError:
            try:
                text, encoding = pair.clean_payload.decode("cp1252"), "cp1252"
            except UnicodeDecodeError:
                continue
        if snapshot_characters + len(text) > _MAX_TOTAL_CHARACTERS:
            continue
        snapshot_characters += len(text)
        snapshots[digest] = {
            "path": pair.path,
            "text": text,
            "size": len(pair.clean_payload),
            "encoding": encoding,
            "truncated": False,
            "basis": "Original source bytes captured before edits and checked against the receipt",
        }
    _capture_operations(report, pairs, context)
    if rejected:
        diagnostics.append(
            {
                "kind": "source-pair-mismatch",
                "count": rejected,
                "message": (
                    f"{rejected} in-memory source pairs did not match recorded declarations."
                ),
            }
        )
    if omitted:
        diagnostics.append(
            {
                "kind": "source-diff-limit",
                "count": omitted,
                "message": f"{omitted} source changes exceeded the bounded excerpt budget.",
            }
        )
    return context


__all__ = ["collect_source_diff_context", "source_pairs", "source_rendering"]
