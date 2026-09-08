from __future__ import annotations

import pytest

from reprobit.report_explorer_source_rendering import render_source_rows


def test_source_changes_align_lines_and_preserve_exact_line_numbers() -> None:
    view = render_source_rows(b"first\nold\nlast\n", b"first\nnew\nextra\nlast\n")
    rows = view["rows"]
    assert [row["kind"] for row in rows] == ["equal", "replace", "insert", "equal"]
    assert rows[1]["before"]["line"] == rows[1]["after"]["line"] == 2
    assert rows[1]["before"]["text"] == "old"
    assert rows[1]["after"]["text"] == "new"
    assert rows[2]["before"] is None
    assert rows[2]["after"]["line"] == 3
    assert rows[3]["before"]["line"] == 3
    assert rows[3]["after"]["line"] == 4
    assert not view["truncated"]


def test_deleted_line_has_no_after_and_empty_file_has_no_phantom_line() -> None:
    view = render_source_rows(b"old\n", b"")
    assert view["after_line_count"] == 0
    assert view["rows"][0]["kind"] == "delete"
    assert view["rows"][0]["after"] is None
    assert render_source_rows(b"", b"")["rows"] == []


def test_long_unchanged_regions_have_context_gaps_with_real_following_numbers() -> None:
    before = b"".join(f"line {n}\n".encode() for n in range(100))
    after = before.replace(b"line 50\n", b"changed\n")
    view = render_source_rows(before, after, context_lines=2)
    rows = view["rows"]
    assert rows[0] == {
        "kind": "gap",
        "before": None,
        "after": None,
        "count": 48,
        "reason": "unchanged",
    }
    assert rows[1]["before"]["line"] == 49
    assert rows[3]["kind"] == "replace"
    assert rows[3]["before"]["line"] == 51
    assert rows[-1]["count"] == 47
    assert not view["truncated"]


def test_insertion_in_repeated_generated_run_does_not_replace_the_tail() -> None:
    before = b"declaration;\n" * 1000
    after = b"declaration;\n" * 500 + b"new;\n" + b"declaration;\n" * 500
    rows = render_source_rows(before, after)["rows"]
    assert [row["kind"] for row in rows if row["kind"] not in {"equal", "gap"}] == ["insert"]
    changed = next(row for row in rows if row["kind"] == "insert")
    assert changed["after"]["line"] == 501


def test_line_ending_and_final_newline_changes_are_not_hidden() -> None:
    rows = render_source_rows(b"same\r\nlast", b"same\nlast\n")["rows"]
    assert [row["kind"] for row in rows] == ["replace", "replace"]
    assert rows[0]["before"]["text"] == rows[0]["after"]["text"] == "same"
    assert rows[0]["before"]["line_ending"] == "crlf"
    assert rows[0]["after"]["line_ending"] == "lf"
    assert rows[1]["before"]["line_ending"] == "none"


def test_fragment_coordinates_do_not_invent_file_line_numbers() -> None:
    view = render_source_rows(b"old\n", b"new\n", before_start_line=None, after_start_line=None)
    assert view["before_coordinates"] == view["after_coordinates"] == "fragment"
    assert view["rows"][0]["before"]["line"] is None
    assert view["rows"][0]["before"]["local_line"] == 1
    known = render_source_rows(b"old\n", b"new\n", before_start_line=74, after_start_line=82)
    assert known["rows"][0]["before"]["line"] == 74
    assert known["rows"][0]["after"]["line"] == 82


def test_row_limit_is_explicit_and_does_not_turn_clipping_into_deletions() -> None:
    view = render_source_rows(b"old\n" * 30, b"new\n" * 30, max_rows=4)
    assert len(view["rows"]) == 4
    assert [row["kind"] for row in view["rows"]] == ["replace"] * 3 + ["gap"]
    assert view["rows"][-1]["reason"] == "limit"
    assert view["rows"][-1]["count"] == view["omitted_rows"] == 27
    assert view["truncated"]


def test_long_line_and_total_character_limits_are_explicit() -> None:
    view = render_source_rows(b"A" * 10000, b"B" * 10000, max_line_characters=10)
    assert view["characters"] == 20
    assert view["rows"][0]["kind"] == "replace"
    assert view["rows"][0]["before"]["text_truncated"]
    assert view["rows"][0]["before"]["full_characters"] == 10000
    assert view["truncated"]
    limited = render_source_rows(b"abc\ndef", b"xyz\npqr", max_characters=4)
    assert limited["characters"] <= 4
    assert limited["rows"][-1]["reason"] == "limit"


def test_zero_budget_returns_limit_gap_and_non_utf8_keeps_source_line_boundaries() -> None:
    view = render_source_rows(b"before\n", b"after\n", max_characters=0)
    assert view["rows"][0]["reason"] == "limit"
    assert view["characters"] == 0
    encoded = render_source_rows(b"old\x85value\n", b"new\x85value\n")
    assert encoded["before_encoding"] == "cp1252"
    assert encoded["before_line_count"] == 1
    assert encoded["rows"][0]["before"]["text"] == "old…value"


def test_oversized_input_is_refused_without_fabricated_edits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("reprobit.report_explorer_source_rendering._MAX_INPUT_BYTES", 4)
    view = render_source_rows(b"original", b"replacement")
    assert view["rows"] == []
    assert view["unavailable_reason"] == "input byte limit"
    assert view["truncated"]


def test_undefined_legacy_bytes_are_escaped_explicitly_instead_of_replaced() -> None:
    row = render_source_rows(b"old\x81\n", b"new\x81\n")["rows"][0]
    assert row["before"]["text"] == "old\\x81"
    assert row["before"]["undecodable_bytes_escaped"] is True


@pytest.mark.parametrize(
    "options", [{"max_rows": 0}, {"before_start_line": 0}, {"context_lines": -1}]
)
def test_invalid_bounds_are_refused(options: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        render_source_rows(b"a", b"b", **options)
