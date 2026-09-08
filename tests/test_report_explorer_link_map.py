from __future__ import annotations

from pathlib import Path

import pytest
from test_report_explorer_context import _image, _receipt, _report

from reprobit.model import Certificate, Digest, SemanticProof
from reprobit.report import ExecutionStepReceipt, Report
from reprobit.report_explorer_link_map import collect_link_map_context, parse_link_map


def _map(*rows: str) -> bytes:
    return (
        " Address Publics by Value Rva+Base Lib:Object\n"
        + "\n".join(rows)
        + "\n entry point at 0001:00000000\n"
    ).encode("ascii")


def _native_report(tmp_path: Path) -> Report:
    receipt = _receipt(tmp_path / "raw.exe", _image()).model_copy(
        update={"producer_step": "link.sample"}
    )
    report = _report(
        receipt,
        exploration={
            "targets": [
                {
                    "id": "sample",
                    "sections": [{"name": ".text", "va": 0x401000, "size": 512}],
                    "symbols": [
                        {"name": "_first", "va": 0x401088, "space": "debug-va", "tu": "old"}
                    ],
                }
            ]
        },
    )
    step = ExecutionStepReceipt(
        id="link.sample",
        returncode=0,
        attempts=1,
        duration_seconds=0,
        output_digest=Digest.from_bytes(b"output"),
        command_digest=Digest.from_bytes(b"command"),
    )
    build = report.proof.runtime.preimage.build.model_copy(update={"steps": (step,)})
    preimage = report.proof.runtime.preimage.model_copy(update={"build": build})
    runtime = report.proof.runtime.model_copy(update={"preimage": preimage})
    return report.model_copy(update={"proof": report.proof.model_copy(update={"runtime": runtime})})


def _collect(report: Report, payload: bytes) -> dict[str, object]:
    return collect_link_map_context(
        report,
        captures={
            "sample": ("link.sample", report.proof.runtime.preimage.build.outputs[0].path, payload)
        },
    )


def _transformed(
    report: Report, *, target: str = "sample", shift: int = 16, family: str = "image_binary_repack"
) -> Report:
    original = report.targets[0]
    final = Digest.from_bytes(b"transformed image")
    transformed = original.model_copy(update={"candidate_digest": final, "oracle_digest": final})
    semantic = SemanticProof.model_construct(
        family=family,
        input_statement={
            "seed": {"digest": original.candidate_digest.model_dump()},
            "intervention": {"scope": {"target": target}},
            "candidate_constraints": {
                "text_repack": {
                    "schema": "comdat_tail_thunk_repack_v1",
                    "pieces": [{"src_lo": "0x401030", "src_hi": "0x401050", "shift": shift}],
                }
            },
        },
        output_statement={"candidate": {"digest": final.model_dump()}},
    )
    certificate = Certificate.model_construct(semantic_proofs=(semantic,))
    return report.model_copy(
        update={
            "targets": (transformed,),
            "proof": report.proof.model_copy(update={"certificates": (certificate,)}),
        }
    )


def test_map_parser_keeps_exact_addresses_and_provider_identity() -> None:
    rows = parse_link_map(
        _map(
            " 0001:00000030 _first 00401030 f core:member.obj",
            " 0002:00000010 _data 00402010 unit.obj",
        )
    )
    assert rows[0] == {
        "name": "_first",
        "va": 0x401030,
        "section": 1,
        "section_offset": 0x30,
        "provider": "core:member.obj",
        "function": True,
    }
    assert rows[1]["function"] is False


@pytest.mark.parametrize(
    "payload",
    (
        b"no map",
        b"Address Publics by Value Lib:Object\n",
        _map("nonsense"),
        _map(" 0001:00000030 _first 00401030 f"),
        _map(
            " 0001:00000030 _first 00401030 f one.obj", " 0001:00000040 _first 00401040 f two.obj"
        ),
    ),
)
def test_parser_refuses_malformed_or_ambiguous_publics(payload: bytes) -> None:
    with pytest.raises(ValueError):
        parse_link_map(payload)


def test_captured_map_supersedes_debug_relink_and_embeds_receipt_identity(tmp_path: Path) -> None:
    report = _native_report(tmp_path)
    payload = _map(" 0001:00000030 _first 00401030 f unit.obj")
    result = _collect(report, payload)
    target = result["targets"][0]
    assert len(target["symbols"]) == 1
    assert target["symbols"][0]["space"] == "va"
    assert target["symbols"][0]["va"] == 0x401030
    assert target["symbols"][0]["size"] is None
    assert target["link_map"]["digest"] == Digest.from_bytes(payload).value
    assert target["link_map"]["size"] == len(payload)
    assert target["link_map"]["public_count"] == 1
    assert target["link_map"]["final_pipeline_closed"] is True
    assert report.exploration["targets"][0]["symbols"][0]["space"] == "debug-va"


def test_closed_repack_moves_only_symbols_inside_its_source_range(tmp_path: Path) -> None:
    report = _transformed(_native_report(tmp_path))
    result = _collect(
        report,
        _map(
            " 0001:00000010 _before 00401010 f unit.obj",
            " 0001:00000030 _first 00401030 f unit.obj",
            " 0001:00000050 _after 00401050 f unit.obj",
        ),
    )
    symbols = result["targets"][0]["symbols"]
    assert [row["va"] for row in symbols] == [0x401010, 0x401020, 0x401050]
    assert symbols[1]["linked_va"] == 0x401030
    assert all(row["space"] == "va" for row in symbols)


@pytest.mark.parametrize("change", ("target", "shift", "family"))
def test_uncertain_pipeline_preserves_linked_coordinates(tmp_path: Path, change: str) -> None:
    options = (
        {"target": "other"}
        if change == "target"
        else ({"shift": -16} if change == "shift" else {"family": "unknown_transform"})
    )
    report = _transformed(_native_report(tmp_path), **options)
    result = _collect(report, _map(" 0001:00000030 _first 00401030 f unit.obj"))
    symbol = result["targets"][0]["symbols"][0]
    assert symbol["va"] == 0x401030
    assert symbol["space"] == "linked-va"


def test_capture_requires_exact_target_terminal_image_receipt(tmp_path: Path) -> None:
    report = _native_report(tmp_path)
    result = collect_link_map_context(
        report,
        captures={
            "sample": (
                "wrong.step",
                report.proof.runtime.preimage.build.outputs[0].path,
                _map(" 0001:00000030 _first 00401030 f unit.obj"),
            ),
            "unrelated": (
                "link.sample",
                report.proof.runtime.preimage.build.outputs[0].path,
                _map(" 0001:00000030 _other 00401030 f unit.obj"),
            ),
        },
    )
    assert len(result["targets"]) == 1
    assert result["targets"][0]["symbols"][0]["space"] == "debug-va"
    assert result["diagnostics"][0]["kind"] == "native-map-unavailable"


def test_map_geometry_must_match_the_recorded_image_section(tmp_path: Path) -> None:
    report = _native_report(tmp_path)
    result = _collect(report, _map(" 0001:00000030 _first 00501030 f unit.obj"))
    assert result["targets"][0]["symbols"][0]["space"] == "linked-va"
