from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest
from test_report_explorer_context import _image, _receipt, _report, _source

from reprobit.classic.semantic_contracts import ProjectOverlaySourcePair
from reprobit.model import Certificate, SemanticProof
from reprobit.report import Report
from reprobit.report_explorer_context import collect_explorer_context
from reprobit.report_explorer_sources import _line_at, collect_source_diff_context


def _pair_report(tmp_path: Path, pairs: tuple[ProjectOverlaySourcePair, ...]) -> Report:
    report = _report(_receipt(tmp_path / "sample.exe", _image()))
    outputs = [
        {
            "path": pair.path,
            "clean": sha256(pair.clean_payload).hexdigest()
            if pair.clean_payload is not None
            else None,
            "effective": sha256(pair.effective_payload).hexdigest(),
            "size": len(pair.effective_payload),
        }
        for pair in pairs
    ]
    semantic = SemanticProof.model_construct(
        input_statement={"intervention": {"parameters": [{"name": "outputs", "value": outputs}]}}
    )
    certificate = Certificate.model_construct(semantic_proofs=(semantic,))
    return report.model_copy(
        update={"proof": report.proof.model_copy(update={"certificates": (certificate,)})}
    )


def test_immutable_source_pair_retains_actual_removed_and_replacement_text(tmp_path: Path) -> None:
    pair = ProjectOverlaySourcePair("unit.cpp", b"int value = 1;\n", b"int value = 2;\n")
    report = _pair_report(tmp_path, (pair,))
    result = collect_source_diff_context(report, pairs=(pair,))
    diff = result["source_diffs"][0]

    assert "int value = 1;" in diff["before"]
    assert "int value = 2;" in diff["after"]
    assert diff["before_digest"] == sha256(pair.clean_payload).hexdigest()
    assert diff["after_digest"] == sha256(pair.effective_payload).hexdigest()
    assert diff["path"] == "unit.cpp"
    assert diff["truncated"] is False
    assert "source_diffs" not in report.exploration


@pytest.mark.parametrize("change", ("path", "before", "after"))
def test_unbound_source_pairs_are_not_displayed(tmp_path: Path, change: str) -> None:
    pair = ProjectOverlaySourcePair("unit.cpp", b"before", b"after")
    report = _pair_report(tmp_path, (pair,))
    altered = ProjectOverlaySourcePair(
        "different.cpp" if change == "path" else pair.path,
        b"other!" if change == "before" else pair.clean_payload,
        b"other" if change == "after" else pair.effective_payload,
    )
    result = collect_source_diff_context(report, pairs=(altered,))

    assert result["source_diffs"] == []
    assert result["diagnostics"][0]["kind"] == "source-pair-mismatch"


def test_new_source_file_explicitly_has_no_before_text(tmp_path: Path) -> None:
    pair = ProjectOverlaySourcePair("generated.cpp", None, b"int generated;\n")
    result = collect_source_diff_context(_pair_report(tmp_path, (pair,)), pairs=(pair,))
    diff = result["source_diffs"][0]

    assert diff["before"] == ""
    assert diff["before_digest"] is None
    assert diff["before_size"] == 0
    assert "did not exist" in diff["note"]


def test_large_source_changes_have_explicit_bounded_excerpts(tmp_path: Path) -> None:
    pair = ProjectOverlaySourcePair("large.cpp", b"old line\n" * 6000, b"new line\n" * 6000)
    result = collect_source_diff_context(_pair_report(tmp_path, (pair,)), pairs=(pair,))
    diff = result["source_diffs"][0]

    assert len(diff["before"]) == len(diff["after"]) == 32_000
    assert diff["truncated"] is True
    assert "clipped" in diff["note"]
    assert diff["before_size"] == len(pair.clean_payload)


def test_captured_clean_diff_avoids_reading_an_intentionally_overwritten_source(
    tmp_path: Path,
) -> None:
    pair = ProjectOverlaySourcePair("unit.cpp", b"int old;", b"int new_value;")
    report = _pair_report(tmp_path, (pair,))
    artifact = _source(tmp_path, "unit.cpp", pair.clean_payload.decode())
    Path(artifact.receipt_path).write_bytes(pair.effective_payload)
    report = report.model_copy(
        update={"proof": report.proof.model_copy(update={"artifacts": (artifact,)})}
    )
    report = report.model_copy(
        update={"exploration": collect_source_diff_context(report, pairs=(pair,))}
    )
    context = collect_explorer_context(report)

    assert "int old;" in context["source_diffs"][0]["before"]
    assert not any(item["kind"] == "stale-file" for item in context["diagnostics"])


def test_same_source_pair_is_not_duplicated(tmp_path: Path) -> None:
    pair = ProjectOverlaySourcePair("unit.cpp", b"old", b"new")
    context = collect_source_diff_context(_pair_report(tmp_path, (pair,)), pairs=(pair, pair))
    assert len(context["source_diffs"]) == 1


def _operation_receipt(
    operation_id: str, action: str, start: int, end: int, before: bytes, inserted: bytes
) -> dict[str, object]:
    removed = before[start:end]
    anchors = [] if action == "append" else [{"role": "start", "byte_offset": start}]
    if action in {"replace", "delete"}:
        anchors.append({"role": "end", "byte_offset": end})
    return {
        "operation_id": operation_id,
        "action": action,
        "fragment_digest": sha256(inserted).hexdigest(),
        "fragment_size": len(inserted),
        "removed_digest": sha256(removed).hexdigest() if action in {"replace", "delete"} else None,
        "removed_size": len(removed) if action in {"replace", "delete"} else None,
        "anchors": anchors,
    }


def _with_operations(report: Report, pair: ProjectOverlaySourcePair) -> Report:
    before = pair.clean_payload or b""
    receipts = [
        {
            "path": pair.path,
            "input_digest": sha256(before).hexdigest(),
            "input_size": len(before),
            "output_digest": sha256(pair.effective_payload).hexdigest(),
            "output_size": len(pair.effective_payload),
            "operations": [
                _operation_receipt("insert", "insert", 1, 1, before, b"X"),
                _operation_receipt("replace", "replace", 1, 3, before, b"Y"),
                _operation_receipt("delete", "delete", 4, 5, before, b""),
                _operation_receipt("append", "append", 6, 6, before, b"!"),
            ],
        }
    ]
    proof = report.proof.certificates[0].semantic_proofs[0]
    statement = {**proof.input_statement}
    statement["intervention"] = {**statement["intervention"], "id": "overlay"}
    proof = proof.model_copy(
        update={
            "input_statement": statement,
            "output_statement": {
                "project_overlay_epoch": {
                    "source_validation": {
                        "render_receipts": receipts,
                    }
                }
            },
        }
    )
    certificate = Certificate.model_construct(semantic_proofs=(proof,))
    return report.model_copy(
        update={
            "proof": report.proof.model_copy(update={"certificates": (certificate,)}),
        }
    )


def test_action_capture_uses_exact_positions_for_adjacent_and_repeated_edits(
    tmp_path: Path,
) -> None:
    pair = ProjectOverlaySourcePair("unit.cpp", b"abcdef", b"aXYdf!")
    report = _with_operations(_pair_report(tmp_path, (pair,)), pair)
    context = collect_source_diff_context(report, pairs=(pair,))
    actions = context["source_operations"]

    assert [item["before"] for item in actions] == ["", "bc", "e", ""]
    assert [item["after"] for item in actions] == ["X", "Y", "", "!"]
    assert all(item["intervention_id"] == "overlay" for item in actions)
    assert all(item["before_digest"] == sha256(b"abcdef").hexdigest() for item in actions)
    assert all(item["after_digest"] == sha256(b"aXYdf!").hexdigest() for item in actions)
    assert all(item["truncated"] is False for item in actions)
    row = actions[1]["source_rendering"]["rows"][0]
    assert row["kind"] == "replace"
    assert row["before"]["text"] == "bc"
    assert row["after"]["text"] == "Y"
    assert row["before"]["line"] == row["after"]["line"] == 1


@pytest.mark.parametrize("change", ("offset", "removed", "fragment", "input", "output"))
def test_action_capture_rejects_unverified_positions_or_bytes(tmp_path: Path, change: str) -> None:
    pair = ProjectOverlaySourcePair("unit.cpp", b"abcdef", b"aXYdf!")
    report = _with_operations(_pair_report(tmp_path, (pair,)), pair)
    output = report.proof.certificates[0].semantic_proofs[0].output_statement
    receipt = output["project_overlay_epoch"]["source_validation"]["render_receipts"][0]
    if change == "offset":
        receipt["operations"][1]["anchors"][0]["byte_offset"] = 2
    elif change in {"removed", "fragment"}:
        receipt["operations"][1][change + "_digest"] = "0" * 64
    else:
        receipt[change + "_digest"] = "0" * 64
    context = collect_source_diff_context(report, pairs=(pair,))

    assert context["source_operations"] == []
    assert any(item["kind"] == "source-operation-capture" for item in context["diagnostics"])


def test_clean_original_reused_by_a_donor_is_retained_before_its_path_is_overwritten(
    tmp_path: Path,
) -> None:
    pair = ProjectOverlaySourcePair("unit.cpp", b"original", b"overlay")
    report = _pair_report(tmp_path, (pair,))
    donor = _source(tmp_path, "donor.cpp", "donor")
    original = _source(tmp_path, "unit.cpp", "original")
    Path(original.receipt_path).write_bytes(b"overlay")
    donor_proof = SemanticProof.model_construct(
        input_statement={
            "compiler_statement": {
                "request_receipt": {
                    "input_digests": {"effective:unit.cpp": original.digest.value},
                    "output_digests": {"s.cpp": donor.digest.value},
                },
            }
        }
    )
    certificates = (
        *report.proof.certificates,
        Certificate.model_construct(
            semantic_proofs=(donor_proof,),
        ),
    )
    report = report.model_copy(
        update={
            "proof": report.proof.model_copy(
                update={
                    "certificates": certificates,
                    "artifacts": (original, donor),
                }
            )
        }
    )
    report = report.model_copy(
        update={
            "exploration": collect_source_diff_context(report, pairs=(pair,)),
        }
    )
    context = collect_explorer_context(report)

    assert context["sources"][original.digest.value]["text"] == "original"
    assert len(context["source_diffs"]) == 2
    assert context["source_diffs"][1]["before"].endswith("original")
    assert context["source_diffs"][1]["after"].endswith("donor")
    assert context["source_coverage"]["unavailable_changes"] == 0
    assert context["diagnostics"] == []


def test_action_capture_rejects_unrecorded_edits_to_untouched_source(tmp_path: Path) -> None:
    pair = ProjectOverlaySourcePair("unit.cpp", b"abcdef", b"zXYdf!")
    report = _with_operations(_pair_report(tmp_path, (pair,)), pair)
    context = collect_source_diff_context(report, pairs=(pair,))

    assert context["source_operations"] == []
    assert context["diagnostics"][0]["kind"] == "source-operation-capture"


def test_action_capture_discloses_fragment_clipping(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("reprobit.report_explorer_sources._MAX_SIDE_CHARACTERS", 1)
    pair = ProjectOverlaySourcePair("unit.cpp", b"abcdef", b"aXYdf!")
    report = _with_operations(_pair_report(tmp_path, (pair,)), pair)
    context = collect_source_diff_context(report, pairs=(pair,))
    replacement = context["source_operations"][1]

    assert replacement["before"] == "b"
    assert replacement["removed_size"] == 2
    assert replacement["truncated"] is True
    assert "clipped" in replacement["note"]


def test_recorded_byte_offsets_count_complete_line_terminators() -> None:
    source = b"one\r\ntwo\rthree\nfour"
    assert _line_at(source, 4) == 1  # The CRLF terminator has not finished yet.
    assert _line_at(source, 5) == 2
    assert _line_at(source, 9) == 3
    assert _line_at(source, 15) == 4


def _donor_replay_fixture(
    tmp_path: Path, *, replay: bool = True
) -> tuple[Report, ProjectOverlaySourcePair]:
    from test_classic_overlay import _seat_digest, _simple_declaration

    declaration, clean, effective = _simple_declaration()
    path = "src/unit.cpp"
    before = clean[path]
    after = (b"class Spare;\n" if replay else b"") + b"class Donor;\n"
    pair = ProjectOverlaySourcePair(path, before, effective)
    report = _pair_report(tmp_path, (pair,))
    overlay = report.proof.certificates[0].semantic_proofs[0]
    overlay = overlay.model_copy(
        update={
            "input_statement": {
                "intervention": {
                    "id": "project-overlay",
                    "scope": {"target": "sample"},
                    "parameters": [{"name": "outputs", "value": [declaration]}],
                }
            }
        }
    )
    replacement = {
        "id": "op_replace_original",
        "op": "replace",
        "from": {
            "ctx": _seat_digest(["<SEAT>", "int", "value", ";"]),
            "b": 0,
            "a": 3,
            "at": "start",
        },
        "to": {"ctx": _seat_digest(["int", "value", ";", "<SEAT>"]), "b": 3, "a": 0, "at": "end"},
        "removed": {"sha256": sha256(before).hexdigest(), "size": len(before)},
        "gen": {"k": "fwd", "id": "Donor"},
    }
    parameters = [{"name": "renderings", "value": [{"path": path, "operations": [replacement]}]}]
    if replay:
        parameters.append(
            {"name": "canonical_overlay_replay", "value": "owning_translation_unit_v1"}
        )
    original = _source(tmp_path, "original.cpp", before.decode())
    donor = _source(tmp_path, "donor.cpp", after.decode())
    donor_proof = SemanticProof.model_construct(
        input_statement={
            "intervention": {
                "id": "donor",
                "family": "donor_source_overlay",
                "scope": {"target": "sample"},
                "parameters": parameters,
            },
            "compiler_statement": {
                "request_receipt": {
                    "intervention_id": "donor",
                    "input_digests": {
                        "clean:" + path: original.digest.value,
                        "effective:" + path: sha256(effective if replay else before).hexdigest(),
                    },
                    "output_digests": {"s.cpp": donor.digest.value},
                }
            },
        }
    )
    certificates = (
        Certificate.model_construct(semantic_proofs=(overlay,)),
        Certificate.model_construct(semantic_proofs=(donor_proof,)),
    )
    report = report.model_copy(
        update={
            "proof": report.proof.model_copy(
                update={
                    "certificates": certificates,
                    "artifacts": (original, donor),
                }
            )
        }
    )
    return report, pair


@pytest.mark.parametrize("replay", [False, True])
def test_donor_operation_replay_preserves_original_source_and_signed_output(
    tmp_path: Path,
    replay: bool,
) -> None:
    report, pair = _donor_replay_fixture(tmp_path, replay=replay)
    context = collect_source_diff_context(report, pairs=(pair,))
    context["source_operations"] = [
        {
            "intervention_id": "existing",
            "path": "old.cpp",
            "action_id": "saved",
            "before": "",
            "after": "",
        }
    ]
    # Reproduce the end-of-build overwrite: only generation capture retains the
    # exact original bytes required by the donor's contextual anchors.
    original = report.proof.artifacts[0]
    Path(original.receipt_path).write_bytes(pair.effective_payload)
    report = report.model_copy(update={"exploration": context})
    captured = collect_explorer_context(report)
    operations = captured["source_operations"]

    assert operations[0]["intervention_id"] == "existing"
    assert len(operations) == 2
    assert operations[1]["action_id"] == "op_replace_original"
    assert operations[1]["before"] == "int value;\n"
    assert operations[1]["after"] == "class Donor;\n"
    assert operations[1]["basis"] == "donor-render-replay"
    assert operations[1]["source_rendering"]["rows"][0]["after"]["line"] == (2 if replay else 1)
    assert not any(
        item["kind"] == "donor-source-operation-unavailable" for item in captured["diagnostics"]
    )


@pytest.mark.parametrize("change", ["input", "output", "anchor", "removed", "target"])
def test_donor_replay_rejects_mismatched_input_output_or_declared_operation(
    tmp_path: Path,
    change: str,
) -> None:
    report, pair = _donor_replay_fixture(tmp_path)
    statement = report.proof.certificates[1].semantic_proofs[0].input_statement
    operation = statement["intervention"]["parameters"][0]["value"][0]["operations"][0]
    if change == "input":
        statement["compiler_statement"]["request_receipt"]["input_digests"][
            "clean:src/unit.cpp"
        ] = "0" * 64
    elif change == "output":
        statement["compiler_statement"]["request_receipt"]["output_digests"]["s.cpp"] = "0" * 64
    elif change == "anchor":
        operation["from"]["ctx"] = "0" * 64
    elif change == "removed":
        operation["removed"]["sha256"] = "0" * 64
    else:
        statement["intervention"]["scope"]["target"] = "wrong-target"
    report = report.model_copy(
        update={"exploration": collect_source_diff_context(report, pairs=(pair,))}
    )
    captured = collect_explorer_context(report)

    assert not any(
        item.get("basis") == "donor-render-replay" for item in captured["source_operations"]
    )
    assert any(
        item["kind"] == "donor-source-operation-unavailable" for item in captured["diagnostics"]
    )


def test_source_rows_remain_available_after_many_prior_short_rows() -> None:
    from reprobit.report_explorer_sources import source_rendering

    context = {"source_rendering_coverage": {"rows": 20_000, "characters": 300_000}}
    rendering = source_rendering(context, b"old\n", b"new\n")
    assert rendering["truncated"] is False
    assert rendering["rows"][0]["before"]["text"] == "old"
    assert rendering["rows"][0]["after"]["text"] == "new"


def test_donor_flat_header_projection_requires_a_unique_declared_basename() -> None:
    from reprobit.report_explorer_sources import donor_source_pairs

    declaration = {
        "id": "donor",
        "family": "donor_source_overlay",
        "parameters": [
            {"name": "renderings", "value": [{"path": "src/main.cpp"}, {"path": "inc/unit.h"}]},
        ],
    }
    statement = {
        "compiler_statement": {
            "request_receipt": {
                "intervention_id": "donor",
                "input_digests": {
                    "clean:src/main.cpp": "main-before",
                    "effective:src/main.cpp": "main-before",
                    "clean:inc/unit.h": "header-before",
                    "clean:other/unit.h": "other-before",
                },
                "output_digests": {"s.cpp": "main-after", "inc/unit.h": "header-after"},
            }
        }
    }
    assert donor_source_pairs(declaration, statement) == [
        ("src/main.cpp", "main-before", "main-after"),
        ("inc/unit.h", "header-before", "header-after"),
    ]
    declaration["parameters"][0]["value"].append({"path": "other/unit.h"})
    assert donor_source_pairs(declaration, statement) == [
        ("src/main.cpp", "main-before", "main-after")
    ]


@pytest.mark.parametrize("counts", [(10001, 0), (1, -1), (True, 1)])
def test_compiler_carrier_replay_has_explicit_bounded_counts(counts: tuple[object, object]) -> None:
    from reprobit.report_explorer_sources import _carrier_is_bounded

    assert not _carrier_is_bounded(
        {
            "kind": "extern_run_pair_v1",
            "header_count": counts[0],
            "seat_count": counts[1],
            "header_prefix": "A",
            "seat_prefix": "B",
            "width": 3,
        }
    )
    assert _carrier_is_bounded(
        {
            "kind": "extern_run_pair_v1",
            "header_count": 3,
            "seat_count": 2,
            "header_prefix": "A",
            "seat_prefix": "B",
            "width": 3,
        }
    )


def test_donor_receipt_attribution_joins_exact_paths_after_renderer_sorts_outputs(
    tmp_path: Path,
) -> None:
    report, pair = _donor_replay_fixture(tmp_path)
    header = _source(tmp_path, "header.h", "int header;\n")
    changed = _source(tmp_path, "changed.h", "int header;\nclass Header;\n")
    statement = report.proof.certificates[1].semantic_proofs[0].input_statement
    statement["intervention"]["parameters"][0]["value"].append(
        {
            "path": "inc/header.h",
            "operations": [
                {"op": "append", "id": "op_header", "gen": {"k": "fwd", "id": "Header"}}
            ],
        }
    )
    request = statement["compiler_statement"]["request_receipt"]
    request["input_digests"]["clean:inc/header.h"] = header.digest.value
    request["output_digests"]["inc/header.h"] = changed.digest.value
    report = report.model_copy(
        update={
            "proof": report.proof.model_copy(
                update={
                    "artifacts": (*report.proof.artifacts, header, changed),
                }
            )
        }
    )
    report = report.model_copy(
        update={"exploration": collect_source_diff_context(report, pairs=(pair,))}
    )
    context = collect_explorer_context(report)
    operations = context["source_operations"]

    assert [(item["path"], item["action_id"]) for item in operations] == [
        ("src/unit.cpp", "op_replace_original"),
        ("inc/header.h", "op_header"),
    ]
    assert operations[1]["before"] == ""
    assert operations[1]["after"] == "class Header;\n"
    assert not any(
        item["kind"] == "donor-source-operation-unavailable" for item in context["diagnostics"]
    )
