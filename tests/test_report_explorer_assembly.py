from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest
import test_classic_register_bijection_reencoding_full as coff_fixture

from reprobit.costs import calculate_intervention_cost, intervention_cost_row_digest
from reprobit.intervention_metadata import ClassicRecipeFamily
from reprobit.model import Certificate, Digest, ProofObligation, Scope, SemanticProof
from reprobit.report_explorer_assembly import capture_assembly_diff, verified_assembly_diff
from reprobit.schema import ClassicField, ClassicRecipeIntervention, ClassicRecipeRole
from reprobit.strict_json import canonical_json


def _fixture(
    before: bytes = bytes.fromhex("558bec33c05dc3"),
    after: bytes = bytes.fromhex("558becb8010000005dc3"),
    *,
    ranges: list[dict[str, object]] | None = None,
    relocations: tuple[int, ...] = (),
    lines: tuple[tuple[int, int], ...] = (),
) -> tuple[ClassicRecipeIntervention, bytes, bytes, dict[str, Any], dict[str, Any], Certificate]:
    intervention = ClassicRecipeIntervention(
        id="changed-function",
        family=ClassicRecipeFamily.RETAIL_EXACT_INSTRUCTION_MOSAIC
        if ranges
        else ClassicRecipeFamily.SAME_SLOT_RESIZE,
        role=ClassicRecipeRole.FUNCTION,
        build_target="program",
        scope=Scope(target="program", translation_unit="main", function=coff_fixture.TARGET_SYMBOL),
        symbol=coff_fixture.TARGET_SYMBOL,
        rationale="Show the exact compiler-produced function change.",
        dependencies=("private-compile",),
        parameters=(ClassicField(name="instruction_ranges", value=ranges),) if ranges else (),
    )
    first = coff_fixture.make_coff(body=before, relocations=relocations, lines=lines)
    second = coff_fixture.make_coff(body=after, relocations=relocations, lines=lines)
    inputs = {
        "intervention": intervention.model_dump(mode="json"),
        "seed": {"digest": Digest.from_bytes(first).model_dump(mode="json"), "size": len(first)},
    }
    outputs = {
        "candidate": {
            "digest": Digest.from_bytes(second).model_dump(mode="json"),
            "size": len(second),
        },
        "validator_trace": {},
    }
    proof = SemanticProof(
        family=intervention.family.value,
        validator_id="fixture",
        validator_digest=Digest.from_bytes(b"validator"),
        input_statement_digest=Digest.from_bytes(canonical_json(inputs)),
        output_statement_digest=Digest.from_bytes(canonical_json(outputs)),
        input_statement=inputs,
        output_statement=outputs,
        obligations=("fixture",),
        evidence_digest=Digest.from_bytes(b"evidence"),
    )
    cost = calculate_intervention_cost(intervention)
    certificate = Certificate(
        id="certificate",
        intervention_id=intervention.id,
        intervention_authority_digest=cost.intervention_authority_digest,
        intervention_cost_digest=intervention_cost_row_digest(cost),
        obligations=(ProofObligation(name="fixture", passed=True),),
        artifact_ids=("object",),
        semantic_proofs=(proof,),
    )
    return intervention, first, second, inputs, outputs, certificate


def _capture(fixture: tuple[Any, ...]) -> dict[str, Any]:
    intervention, first, second, inputs, outputs, _ = fixture
    result = capture_assembly_diff(
        intervention, first, second, input_statement=inputs, output_statement=outputs
    )
    assert result is not None
    return result


def test_exact_function_change_is_aligned_with_unchanged_context_and_object_coordinates() -> None:
    fixture = _fixture()
    capture = _capture(fixture)
    cost = calculate_intervention_cost(fixture[0])
    assert verified_assembly_diff(cost, fixture[-1], capture) == capture
    assert capture["coordinate_space"] == "function"
    assert capture["changed_rows"] == 1
    changed = next(row for row in capture["rows"] if row["kind"] == "replace")
    assert changed["before"]["text"] == "xor eax, eax"
    assert changed["after"]["text"] == "mov eax, 1"
    assert changed["before"]["offset"] == changed["after"]["offset"] == 3
    assert capture["before"]["decoded_bytes"] == 7
    assert capture["after"]["decoded_bytes"] == 10
    assert capture["before"]["object_offset"] > 0
    assert any(row["kind"] == "equal" for row in capture["rows"])
    assert "final addresses" in capture["notes"][0]


def test_relocated_memory_operand_names_the_symbol_instead_of_zero_placeholder() -> None:
    fixture = _fixture(
        before=bytes.fromhex("8b1d00000000c3"),
        after=bytes.fromhex("8b0d00000000c3"),
        relocations=(2,),
    )
    capture = _capture(fixture)
    row = capture["rows"][0]
    assert row["before"]["text"] == f"mov ebx, dword ptr [<{coff_fixture.NIL_SYMBOL}>]"
    assert row["after"]["text"] == f"mov ecx, dword ptr [<{coff_fixture.NIL_SYMBOL}>]"
    assert row["after"]["raw_operands"] == "ecx, dword ptr [0]"
    assert row["after"]["relocations"][0]["offset"] == 2
    assert "linker" in capture["notes"][-1]


def test_call_relocation_does_not_display_local_fake_address() -> None:
    fixture = _fixture(
        before=bytes.fromhex("e80000000033c0c3"),
        after=bytes.fromhex("e80000000033c9c3"),
        relocations=(1,),
    )
    capture = _capture(fixture)
    assert capture["rows"][0]["before"]["text"] == f"call <{coff_fixture.NIL_SYMBOL}>"
    assert capture["rows"][0]["before"]["raw_operands"] == "5"


def test_unreachable_table_bytes_are_not_rendered_as_assembly() -> None:
    capture = _capture(_fixture(before=b"\xc3\x00\x00\x00\x00", after=b"\xc3\x01\x00\x00\x00"))
    assert len(capture["rows"]) == 1
    assert capture["before"]["decoded_bytes"] == 1
    assert capture["before"]["undecoded_ranges"] == [{"start": 1, "end": 5}]
    assert capture["undecoded_byte_changes"] == 1
    assert capture["before"]["undecoded_previews"][0]["bytes"] == "00000000"
    assert capture["after"]["undecoded_previews"][0]["bytes"] == "01000000"
    assert "1 changed bytes are outside decoded instructions" in capture["notes"][-1]


def test_invalid_encoding_is_not_skipped_and_does_not_invent_instructions() -> None:
    capture = _capture(_fixture(before=b"\x55\x0f", after=b"\x55\x0f"))
    assert len(capture["rows"]) == 1
    assert capture["before"]["undecoded_ranges"] == [{"start": 1, "end": 2}]


def test_selected_mosaic_ranges_are_marked_including_unchanged_selected_instructions() -> None:
    capture = _capture(
        _fixture(
            before=bytes.fromhex("c3cc33c0c3"),
            after=bytes.fromhex("c3cc33c9c3"),
            ranges=[{"start": 2, "end": 5, "donor": "other-compile"}],
        )
    )
    selected = [row for row in capture["rows"] if row["selected"]]
    assert len(selected) == 2
    assert selected[0]["before"]["text"] == "xor eax, eax"
    assert selected[0]["after"]["text"] == "xor ecx, ecx"
    assert selected[-1]["kind"] == "equal"
    assert capture["before"]["selected_ranges_complete"]
    assert capture["selected_ranges"][0]["donor"] == "other-compile"
    assert capture["before"]["undecoded_ranges"] == [{"start": 1, "end": 2}]


def test_compiler_line_anchors_reach_separate_case_blocks() -> None:
    capture = _capture(
        _fixture(before=b"\xc3\xcc\x33\xc0\xc3", after=b"\xc3\xcc\x33\xc9\xc3", lines=((2, 10),))
    )
    assert any(row["kind"] == "replace" for row in capture["rows"])
    assert capture["before"]["decoded_bytes"] == 4


@pytest.mark.parametrize("field", ["intervention", "seed", "candidate"])
def test_capture_refuses_objects_or_declaration_that_do_not_match_receipt(field: str) -> None:
    intervention, first, second, inputs, outputs, _ = _fixture()
    if field == "intervention":
        inputs["intervention"]["rationale"] = "different declaration"
    elif field == "seed":
        first = second
    else:
        second = first
    assert (
        capture_assembly_diff(
            intervention, first, second, input_statement=inputs, output_statement=outputs
        )
        is None
    )


@pytest.mark.parametrize(
    "field", ["rows", "authority_digest", "input_statement_digest", "intervention_id"]
)
def test_display_refuses_mutated_or_unbound_capture(field: str) -> None:
    fixture = _fixture()
    capture = deepcopy(_capture(fixture))
    capture[field] = "wrong"
    assert (
        verified_assembly_diff(calculate_intervention_cost(fixture[0]), fixture[-1], capture)
        is None
    )


def test_display_refuses_other_certificate_or_cost_and_missing_proof() -> None:
    fixture = _fixture()
    capture = _capture(fixture)
    cost = calculate_intervention_cost(fixture[0])
    certificate = fixture[-1]
    assert verified_assembly_diff(cost, None, capture) is None
    assert (
        verified_assembly_diff(
            cost.model_copy(update={"intervention_id": "other"}), certificate, capture
        )
        is None
    )
    assert (
        verified_assembly_diff(
            cost, certificate.model_copy(update={"semantic_proofs": ()}), capture
        )
        is None
    )


def test_instruction_limit_is_explicit_and_keeps_undecoded_extent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("reprobit.report_explorer_assembly._MAX_INSTRUCTIONS", 2)
    capture = _capture(_fixture(before=b"\x90\x90\x90\xc3", after=b"\x90\x90\x90\xc3"))
    assert capture["truncated"] is True
    assert capture["before"]["undecoded_ranges"] == [{"start": 2, "end": 4}]


def test_oversized_body_capture_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("reprobit.report_explorer_assembly._MAX_BODY", 4)
    intervention, first, second, inputs, outputs, _ = _fixture()
    assert (
        capture_assembly_diff(
            intervention, first, second, input_statement=inputs, output_statement=outputs
        )
        is None
    )
