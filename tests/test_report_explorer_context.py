from __future__ import annotations

import struct
from pathlib import Path

import pytest
from test_msvc42_pdb import _synthetic_pdb

from reprobit.model import (
    Artifact,
    ArtifactKind,
    ArtifactOrigin,
    Certificate,
    Digest,
    SemanticProof,
)
from reprobit.report import (
    BuildExecutionSummary,
    ExecutionFileReceipt,
    ProofReport,
    Report,
    RuntimeBindingPreimage,
    RuntimeProofBinding,
    SupplementalOutputFileSummary,
    SupplementalOutputSummary,
    TargetSummary,
)
from reprobit.report_explorer_context import collect_explorer_context


def _image(*, signature: int = 0x66778899) -> bytes:
    data = bytearray(0x640)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<HHIIIHH", data, 0x84, 0x14C, 2, 0, 0, 0, 224, 0)
    optional = 0x98
    struct.pack_into("<H", data, optional, 0x10B)
    struct.pack_into("<I", data, optional + 28, 0x400000)
    struct.pack_into("<I", data, optional + 92, 16)
    struct.pack_into("<II", data, optional + 96 + 6 * 8, 0x1000, 28)
    for index, name in enumerate((b".text", b".data")):
        header = optional + 224 + index * 40
        data[header : header + len(name)] = name
        struct.pack_into(
            "<IIII", data, header + 8, 0x200, (index + 1) * 0x1000, 0x200, (index + 1) * 0x200
        )
    payload = struct.pack("<4sIII", b"NB10", 0, signature, 7) + b"Z:\\build\\sample.pdb\0"
    struct.pack_into("<IIHHIIII", data, 0x200, 0, 0, 0, 0, 2, len(payload), 0, 0x600)
    data[0x600 : 0x600 + len(payload)] = payload
    data[0x500:0x510] = bytes(range(16))
    return bytes(data)


def _receipt(path: Path, data: bytes) -> ExecutionFileReceipt:
    path.write_bytes(data)
    info = path.stat()
    return ExecutionFileReceipt(
        path=str(path),
        size=len(data),
        digest=Digest.from_bytes(data),
        fresh=True,
        device=info.st_dev,
        inode=info.st_ino,
    )


def _supplement(receipt: ExecutionFileReceipt, role: str) -> SupplementalOutputFileSummary:
    return SupplementalOutputFileSummary(
        role=role,
        logical_path=f"build/{role}",
        path=receipt.path,
        digest=receipt.digest,
        size=receipt.size,
        raw_digest=receipt.digest,
        raw_size=receipt.size,
        outside_policy_digest=receipt.digest,
        changed_bytes=0,
    )


def _report(
    receipt: ExecutionFileReceipt,
    *,
    supplemental: tuple[SupplementalOutputSummary, ...] = (),
    sources: tuple[Artifact, ...] = (),
    requested_sources: tuple[Digest, ...] = (),
    exploration: dict[str, object] | None = None,
) -> Report:
    # Collector tests isolate receipt enrichment from the separately tested
    # authenticity model. Every file receipt and PE/PDB payload remains real.
    build = BuildExecutionSummary.model_construct(inputs=(), outputs=(receipt,), steps=())
    runtime = RuntimeProofBinding.model_construct(
        preimage=RuntimeBindingPreimage.model_construct(build=build)
    )
    statement = {"source_inputs": [{"digest": digest.model_dump()} for digest in requested_sources]}
    certificate = Certificate.model_construct(
        semantic_proofs=(SemanticProof.model_construct(input_statement=statement),)
    )
    proof = ProofReport.model_construct(
        runtime=runtime,
        supplemental_outputs=supplemental,
        artifacts=sources,
        certificates=(certificate,),
    )
    target = TargetSummary(
        id="sample",
        artifact="build/sample.exe",
        candidate_size=receipt.size,
        candidate_digest=receipt.digest,
        oracle_size=receipt.size,
        oracle_digest=receipt.digest,
        byte_exact=True,
    )
    return Report.model_construct(proof=proof, targets=(target,), exploration=exploration or {})


def _debug_pair(
    tmp_path: Path, *, signature: int = 0x66778899, image_data: bytes | None = None
) -> SupplementalOutputSummary:
    image = _receipt(tmp_path / "debug.exe", image_data or _image(signature=signature))
    pdb = _receipt(tmp_path / "debug.pdb", _synthetic_pdb(with_link_map=True))
    return SupplementalOutputSummary(
        id="debug.sample",
        target_id="sample",
        policy="test-debug-pair",
        source_step_id="link",
        publish_step_id="publish",
        files=(_supplement(image, "image"), _supplement(pdb, "pdb")),
    )


def test_verified_images_have_sections_and_exact_public_starts(tmp_path: Path) -> None:
    receipt = _receipt(tmp_path / "sample.exe", _image())
    report = _report(receipt, supplemental=(_debug_pair(tmp_path),))
    context = collect_explorer_context(report)
    target = context["targets"][0]

    assert target["image_base"] == 0x400000
    assert target["sections"][1] == {
        "name": ".data",
        "va": 0x402000,
        "size": 512,
        "file_offset": 1024,
        "file_size": 512,
    }
    first, second = target["symbols"]
    assert first["name"] == "?first@@"
    assert first["va"] == 0x402100
    assert first["size"] is None
    assert first["space"] == second["space"] == "va"
    assert first["source"] == "object.obj"
    assert context["diagnostics"] == []


def test_changed_contribution_keeps_debug_coordinates_separate(tmp_path: Path) -> None:
    candidate = bytearray(_image())
    candidate[0x500] ^= 0xFF
    receipt = _receipt(tmp_path / "sample.exe", bytes(candidate))
    context = collect_explorer_context(_report(receipt, supplemental=(_debug_pair(tmp_path),)))
    first, second = context["targets"][0]["symbols"]

    assert first["space"] == "debug-va"
    assert "before final image changes" in first["basis"]
    assert second["space"] == "va"


def test_receipt_matching_pdb_still_must_bind_to_debug_image(tmp_path: Path) -> None:
    receipt = _receipt(tmp_path / "sample.exe", _image())
    context = collect_explorer_context(
        _report(receipt, supplemental=(_debug_pair(tmp_path, signature=0xDEADBEEF),))
    )

    assert context["targets"][0]["symbols"] == []
    assert any(item["kind"] == "unsupported-debug-pair" for item in context["diagnostics"])


@pytest.mark.parametrize("change", ("remove", "same-size", "grow", "symlink"))
def test_missing_or_stale_candidate_never_supplies_geometry(tmp_path: Path, change: str) -> None:
    path = tmp_path / "sample.exe"
    receipt = _receipt(path, _image())
    if change == "remove":
        path.unlink()
    elif change == "same-size":
        path.write_bytes(b"x" * receipt.size)
    elif change == "grow":
        path.write_bytes(_image() + b"x")
    else:
        other = tmp_path / "other.exe"
        path.rename(other)
        path.symlink_to(other)
    context = collect_explorer_context(_report(receipt))

    assert context["targets"][0]["sections"] == []
    assert any(item["kind"] == "candidate-unavailable" for item in context["diagnostics"])


def test_embedded_reference_extents_survive_local_enrichment(tmp_path: Path) -> None:
    receipt = _receipt(tmp_path / "sample.exe", _image())
    symbol = {"name": "?first@@", "va": 0x402100, "size": 8, "space": "va", "tu": "one"}
    original: dict[str, object] = {"targets": [{"id": "sample", "symbols": [symbol]}]}
    report = _report(receipt, supplemental=(_debug_pair(tmp_path),), exploration=original)
    context = collect_explorer_context(report)

    assert context["targets"][0]["symbols"][0] == symbol
    assert len(context["targets"][0]["symbols"]) == 2
    assert report.exploration == original


def _source(tmp_path: Path, name: str, text: str) -> Artifact:
    path = tmp_path / name
    data = text.encode()
    path.write_bytes(data)
    return Artifact(
        id=name,
        kind=ArtifactKind.SOURCE,
        logical_path=f"source/{name}",
        receipt_path=str(path),
        digest=Digest.from_bytes(data),
        size=len(data),
        origin=ArtifactOrigin.FRESH_DONOR,
    )


def test_source_previews_read_only_requested_digest_bound_artifacts(tmp_path: Path) -> None:
    receipt = _receipt(tmp_path / "sample.exe", _image())
    source = _source(tmp_path, "donor.cpp", "int sample() { return 42; }\n" * 12000)
    unrelated = _source(tmp_path, "unrelated.cpp", "unrelated local text")
    report = _report(receipt, sources=(source, unrelated), requested_sources=(source.digest,))
    context = collect_explorer_context(report)
    preview = context["sources"][source.digest.value]

    assert set(context["sources"]) == {source.digest.value}
    assert preview["text"].startswith("int sample() { return 42; }")
    assert len(preview["text"]) == 256_000
    assert preview["truncated"] is True
    assert preview["path"] == "source/donor.cpp"
    assert preview["size"] == source.size


def test_changed_source_is_not_exposed_even_if_a_matching_filename_exists(tmp_path: Path) -> None:
    receipt = _receipt(tmp_path / "sample.exe", _image())
    source = _source(tmp_path, "donor.cpp", "int value = 1;")
    Path(source.receipt_path or "").write_text("int value = 2;")
    context = collect_explorer_context(
        _report(receipt, sources=(source,), requested_sources=(source.digest,))
    )

    assert context["sources"] == {}
    diagnostic = next(
        item for item in context["diagnostics"] if item["kind"] == "source-snapshot-unavailable"
    )
    assert diagnostic["reasons"] == {"stale-file": 1}


@pytest.mark.parametrize("statement_kind", ("overlay", "compiler"))
def test_before_and_after_sources_are_collected_from_rendering_receipts(
    tmp_path: Path, statement_kind: str
) -> None:
    receipt = _receipt(tmp_path / "sample.exe", _image())
    before = _source(tmp_path, "before.cpp", "int value = 1;")
    after = _source(tmp_path, "after.cpp", "int value = 2;")
    report = _report(receipt, sources=(before, after))
    if statement_kind == "overlay":
        statement = {
            "intervention": {
                "parameters": [
                    {
                        "name": "outputs",
                        "value": [
                            {
                                "path": "input.cpp",
                                "clean": before.digest.value,
                                "effective": after.digest.value,
                            }
                        ],
                    }
                ]
            }
        }
    else:
        statement = {
            "compiler_statement": {
                "request_receipt": {
                    "input_digests": {"effective:input.cpp": before.digest.value},
                    "output_digests": {"s.cpp": after.digest.value},
                }
            }
        }
    proof = SemanticProof.model_construct(input_statement=statement)
    certificate = Certificate.model_construct(semantic_proofs=(proof,))
    report = report.model_copy(
        update={"proof": report.proof.model_copy(update={"certificates": (certificate,)})}
    )
    context = collect_explorer_context(report)

    assert context["sources"] == {}
    change = context["source_diffs"][0]
    assert change["before"] == "@@ lines 1-1 @@\nint value = 1;"
    assert change["after"] == "@@ lines 1-1 @@\nint value = 2;"
    assert change["before_digest"] == before.digest.value
    assert change["after_digest"] == after.digest.value
    assert context["source_coverage"]["captured_changes"] == 1


def _with_source_pair(report: Report, before: Artifact, after: Artifact) -> Report:
    proof = SemanticProof.model_construct(
        input_statement={
            "compiler_statement": {
                "request_receipt": {
                    "input_digests": {"effective:input.cpp": before.digest.value},
                    "output_digests": {"s.cpp": after.digest.value},
                }
            }
        }
    )
    certificate = Certificate.model_construct(semantic_proofs=(proof,))
    return report.model_copy(
        update={"proof": report.proof.model_copy(update={"certificates": (certificate,)})}
    )


def test_compact_donor_changes_preserve_existing_capture_and_skip_unchanged_lines(
    tmp_path: Path,
) -> None:
    receipt = _receipt(tmp_path / "sample.exe", _image())
    before = _source(tmp_path, "before.cpp", "unchanged\n" * 1000 + "int value = 1;\n")
    after = _source(tmp_path, "after.cpp", "unchanged\n" * 1000 + "int value = 2;\n")
    existing = {
        "path": "other.cpp",
        "before_digest": None,
        "after_digest": "a" * 64,
        "before": "",
        "after": "new generated source",
        "truncated": False,
    }
    report = _with_source_pair(
        _report(receipt, sources=(before, after), exploration={"source_diffs": [existing]}),
        before,
        after,
    )
    context = collect_explorer_context(report)

    assert context["source_diffs"][0] == existing
    change = context["source_diffs"][1]
    assert change["before"].count("unchanged\n") == 3
    assert change["after"].endswith("int value = 2;\n")
    assert change["truncated"] is False
    assert context["diagnostics"] == []


def test_existing_exact_change_covers_versions_without_recorded_paths(tmp_path: Path) -> None:
    receipt = _receipt(tmp_path / "sample.exe", _image())
    before = _source(tmp_path, "before.cpp", "int value = 1;")
    after = _source(tmp_path, "after.cpp", "int value = 2;")
    report = _with_source_pair(_report(receipt, sources=(before, after)), before, after)
    context = collect_explorer_context(report)
    # Clean paths can be overwritten by an overlay, while some generated
    # effective versions never have a physical source path at all.
    Path(before.receipt_path or "").write_text("later content")
    after = after.model_copy(update={"receipt_path": None})
    report = report.model_copy(
        update={
            "proof": report.proof.model_copy(update={"artifacts": (before, after)}),
            "exploration": {**context, "diagnostics": [{"kind": "source-unavailable"}]},
        }
    )
    captured = collect_explorer_context(report)

    assert captured["source_diffs"] == context["source_diffs"]
    assert captured["sources"] == {}
    assert captured["diagnostics"] == []
    assert captured["source_coverage"]["unavailable_changes"] == 0


def test_missing_change_is_distinct_from_optional_snapshot_and_budget(tmp_path: Path) -> None:
    receipt = _receipt(tmp_path / "sample.exe", _image())
    before = _source(tmp_path, "before.cpp", "int value = 1;").model_copy(
        update={"receipt_path": None}
    )
    after = _source(tmp_path, "after.cpp", "int value = 2;")
    report = _with_source_pair(_report(receipt, sources=(before, after)), before, after)
    context = collect_explorer_context(report)

    assert context["source_coverage"]["unavailable_changes"] == 1
    assert context["source_coverage"]["limited_changes"] == 0
    diagnostic = next(
        item for item in context["diagnostics"] if item["kind"] == "source-change-unavailable"
    )
    assert diagnostic["details"] == [{"path": "input.cpp", "reasons": ["no-recorded-path"]}]
    assert before.digest.value not in context["sources"]


def test_exhausted_budget_never_inserts_empty_nonempty_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("reprobit.report_explorer_context._MAX_SOURCE_TOTAL_CHARACTERS", 3)
    receipt = _receipt(tmp_path / "sample.exe", _image())
    first = _source(tmp_path, "first.cpp", "abcdefgh")
    second = _source(tmp_path, "second.cpp", "zyxwvuts")
    context = collect_explorer_context(
        _report(receipt, sources=(first, second), requested_sources=(first.digest, second.digest))
    )

    assert len(context["sources"]) == 1
    assert len(next(iter(context["sources"].values()))["text"]) == 3
    assert context["source_coverage"]["limited_optional_snapshots"] == 1
    assert context["source_coverage"]["unavailable_optional_snapshots"] == {}


def test_genuine_empty_file_is_a_valid_snapshot(tmp_path: Path) -> None:
    receipt = _receipt(tmp_path / "sample.exe", _image())
    source = _source(tmp_path, "empty.cpp", "")
    report = _report(receipt, sources=(source,), requested_sources=(source.digest,))
    context = collect_explorer_context(report)

    assert context["sources"][source.digest.value]["size"] == 0
    assert context["sources"][source.digest.value]["text"] == ""
    assert context["sources"][source.digest.value]["truncated"] is False


def test_change_budget_exhaustion_is_reported_as_a_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("reprobit.report_explorer_context._MAX_SOURCE_TOTAL_CHARACTERS", 0)
    receipt = _receipt(tmp_path / "sample.exe", _image())
    before = _source(tmp_path, "before.cpp", "old")
    after = _source(tmp_path, "after.cpp", "new")
    report = _with_source_pair(_report(receipt, sources=(before, after)), before, after)
    context = collect_explorer_context(report)

    assert context["source_diffs"] == []
    assert context["source_coverage"]["limited_changes"] == 1
    assert context["source_coverage"]["unavailable_changes"] == 0
    assert context["sources"] == {}


def test_receipt_size_limit_prevents_opening_an_oversized_file(tmp_path: Path) -> None:
    receipt = _receipt(tmp_path / "sample.exe", _image()).model_copy(
        update={"size": 129 * 1024 * 1024}
    )
    context = collect_explorer_context(_report(receipt))

    assert context["targets"][0]["sections"] == []
    assert context["diagnostics"][0]["kind"] == "read-limit"


def _with_body_size(report: Report, size: int, *, name: str = "?first@@") -> Report:
    semantic = SemanticProof.model_construct(
        input_statement={
            "intervention": {
                "scope": {
                    "target": "sample",
                    "function": name,
                    "translation_unit": "first-tu",
                }
            }
        },
        output_statement={"validator_trace": {"mangled": name, "body_length": size}},
    )
    certificate = Certificate.model_construct(semantic_proofs=(semantic,))
    return report.model_copy(
        update={"proof": report.proof.model_copy(update={"certificates": (certificate,)})}
    )


def test_validator_body_size_maps_a_function_inside_a_changed_contribution(tmp_path: Path) -> None:
    image = bytearray(_image())
    image[0x506] ^= 1
    receipt = _receipt(tmp_path / "sample.exe", bytes(image))
    report = _with_body_size(_report(receipt, supplemental=(_debug_pair(tmp_path),)), 4)
    first = collect_explorer_context(report)["targets"][0]["symbols"][0]

    assert first["space"] == "va"
    assert first["size"] == 4
    assert first["tu"] == "first-tu"


@pytest.mark.parametrize("change", ("none", "pointed-data", "instruction", "relocation-site"))
def test_relocated_pointer_requires_exact_pointed_contribution(tmp_path: Path, change: str) -> None:
    debug = bytearray(_image())
    struct.pack_into("<II", debug, 0x98 + 96 + 5 * 8, 0x1040, 12)
    struct.pack_into("<IIHH", debug, 0x240, 0x2000, 12, 0x3100, 0)
    struct.pack_into("<I", debug, 0x500, 0x402108)
    final = bytearray(debug)
    struct.pack_into("<I", final, 0x500, 0x402118)
    final[0x518:0x520] = debug[0x508:0x510]
    if change == "pointed-data":
        final[0x51F] ^= 1
    elif change == "instruction":
        final[0x507] ^= 1
    elif change == "relocation-site":
        struct.pack_into("<H", final, 0x248, 0x3101)
    receipt = _receipt(tmp_path / "sample.exe", bytes(final))
    report = _with_body_size(
        _report(receipt, supplemental=(_debug_pair(tmp_path, image_data=bytes(debug)),)), 8
    )
    first = collect_explorer_context(report)["targets"][0]["symbols"][0]

    assert first["space"] == ("va" if change == "none" else "debug-va")
    if change == "none":
        assert first["size"] == 8
        assert "recorded relocation operands" in first["basis"]
