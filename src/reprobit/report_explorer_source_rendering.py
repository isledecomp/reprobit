"""Bounded, aligned source lines derived from complete immutable byte payloads.

Clipping is a presentation operation applied after alignment. Omitted context
and limits have explicit gap rows; they can never become apparent source edits.
"""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any

_MAX_INPUT_BYTES = 8 * 1024 * 1024
_MAX_INPUT_LINES = 100_000


def _encoding(payload: bytes) -> str:
    try:
        payload.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        return "cp1252"


def _opcodes(left: list[bytes], right: list[bytes]) -> list[tuple[str, int, int, int, int]]:
    # Trim identical boundaries first. This keeps an insertion in a long generated
    # run local even when the remaining input needs SequenceMatcher's size heuristic.
    prefix = 0
    while prefix < min(len(left), len(right)) and left[prefix] == right[prefix]:
        prefix += 1
    suffix = 0
    while (
        suffix < min(len(left), len(right)) - prefix
        and left[len(left) - suffix - 1] == right[len(right) - suffix - 1]
    ):
        suffix += 1
    left_end, right_end = len(left) - suffix, len(right) - suffix
    result = [("equal", 0, prefix, 0, prefix)] if prefix else []
    matcher = SequenceMatcher(
        None,
        left[prefix:left_end],
        right[prefix:right_end],
        autojunk=max(left_end - prefix, right_end - prefix) > 10_000,
    )
    result.extend(
        (kind, a + prefix, b + prefix, c + prefix, d + prefix)
        for kind, a, b, c, d in matcher.get_opcodes()
    )
    if suffix:
        result.append(("equal", left_end, len(left), right_end, len(right)))
    return result


def _descriptors(
    left: list[bytes], right: list[bytes], context: int
) -> list[tuple[str, int | None, int | None, int]]:
    result: list[tuple[str, int | None, int | None, int]] = []
    opcodes = _opcodes(left, right)
    for position, (kind, a, b, c, d) in enumerate(opcodes):
        size = max(b - a, d - c)
        if kind == "equal":
            head = min(size, context) if position else 0
            tail = min(size - head, context) if position + 1 < len(opcodes) else 0
            if size <= head + tail:
                result.extend((kind, a + n, c + n, 1) for n in range(size))
                continue
            result.extend((kind, a + n, c + n, 1) for n in range(head))
            result.append(("gap", a + head, c + head, size - head - tail))
            result.extend((kind, b - tail + n, d - tail + n, 1) for n in range(tail))
            continue
        for index in range(size):
            before = a + index if a + index < b else None
            after = c + index if c + index < d else None
            role = (
                "replace"
                if before is not None and after is not None
                else ("delete" if before is not None else "insert")
            )
            result.append((role, before, after, 1))
    return result


def _line(
    payload: bytes,
    index: int,
    start: int | None,
    encoding: str,
    limit: int,
) -> dict[str, object]:
    ending = "none"
    for suffix, name in ((b"\r\n", "crlf"), (b"\n", "lf"), (b"\r", "cr")):
        if payload.endswith(suffix):
            payload = payload[: -len(suffix)]
            ending = name
            break
    try:
        text = payload.decode(encoding)
        escaped = False
    except UnicodeDecodeError:
        text = payload.decode(encoding, errors="backslashreplace")
        escaped = True
    return {
        "line": start + index if start is not None else None,
        "local_line": index + 1,
        "text": text[:limit],
        "line_ending": ending,
        "text_truncated": len(text) > limit,
        "full_characters": len(text),
        "undecodable_bytes_escaped": escaped,
    }


def render_source_rows(
    before: bytes,
    after: bytes,
    *,
    before_start_line: int | None = 1,
    after_start_line: int | None = 1,
    context_lines: int = 3,
    max_rows: int = 400,
    max_characters: int = 64_000,
    max_line_characters: int = 2000,
) -> dict[str, Any]:
    """Align whole byte inputs, using ``None`` starts for fragment-only coordinates."""
    if not isinstance(before, bytes) or not isinstance(after, bytes):
        raise TypeError("source rendering requires complete byte payloads")
    if any(
        type(start) is not int or start < 1
        for start in (before_start_line, after_start_line)
        if start is not None
    ):
        raise ValueError("source line starts must be positive integers or None")
    if not 0 <= context_lines <= 100 or not 1 <= max_rows <= 20_000:
        raise ValueError("source context or row limit is outside its bounded range")
    if not 0 <= max_characters <= 2_000_000 or not 1 <= max_line_characters <= 32_000:
        raise ValueError("source character limit is outside its bounded range")
    result: dict[str, Any] = {
        "rows": [],
        "truncated": False,
        "omitted_rows": 0,
        "omitted_unchanged_rows": 0,
        "characters": 0,
        "before_line_count": None,
        "after_line_count": None,
        "before_encoding": None,
        "after_encoding": None,
        "before_coordinates": "file" if before_start_line is not None else "fragment",
        "after_coordinates": "file" if after_start_line is not None else "fragment",
    }
    if len(before) + len(after) > _MAX_INPUT_BYTES:
        result.update(truncated=True, unavailable_reason="input byte limit")
        return result
    left, right = before.splitlines(keepends=True), after.splitlines(keepends=True)
    result.update(before_line_count=len(left), after_line_count=len(right))
    if max(len(left), len(right)) > _MAX_INPUT_LINES:
        result.update(truncated=True, unavailable_reason="input line limit")
        return result
    encodings = _encoding(before), _encoding(after)
    result.update(before_encoding=encodings[0], after_encoding=encodings[1])
    descriptors = _descriptors(left, right, context_lines)
    rows: list[dict[str, Any]] = result["rows"]
    for index, (kind, old, new, count) in enumerate(descriptors):
        if (len(rows) >= max_rows - 1 and index < len(descriptors) - 1) or (
            kind != "gap" and result["characters"] >= max_characters
        ):
            omitted = sum(item[3] for item in descriptors[index:])
            rows.append(
                {"kind": "gap", "before": None, "after": None, "count": omitted, "reason": "limit"}
            )
            result.update(truncated=True, omitted_rows=omitted)
            break
        if kind == "gap":
            rows.append(
                {
                    "kind": "gap",
                    "before": None,
                    "after": None,
                    "count": count,
                    "reason": "unchanged",
                }
            )
            result["omitted_unchanged_rows"] += count
            continue
        row: dict[str, Any] = {"kind": kind, "before": None, "after": None}
        present = int(old is not None) + int(new is not None)
        allowance = min(max_line_characters, (max_characters - result["characters"]) // present)
        for side, at, lines, start, encoding in (
            ("before", old, left, before_start_line, encodings[0]),
            ("after", new, right, after_start_line, encodings[1]),
        ):
            if at is None:
                continue
            item = _line(lines[at], at, start, encoding, allowance)
            row[side] = item
            result["characters"] += len(str(item["text"]))
            result["truncated"] |= item["text_truncated"]
        rows.append(row)
    return result
