from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError
from test_report import bundle, digest, proof_report, proof_report_with_debug_companion

from reprobit.costs import calculate_cost, intervention_cost_row_digest
from reprobit.model import (
    Artifact,
    ArtifactKind,
    ArtifactOrigin,
    Certificate,
    Digest,
    ProofObligation,
    ProvenanceKind,
    ProvenanceNode,
    Scope,
    SemanticProof,
    Verdict,
)
from reprobit.report import Report
from reprobit.report_explorer_data import (
    _file_locations,
    _intervention_locations,
    _present_previews,
    _source_pairs,
    _source_previews,
    build_explorer_data,
)
from reprobit.schema import (
    ClassicField,
    ClassicRecipeFamily,
    ClassicRecipeIntervention,
    ClassicRecipeRole,
    OracleFunction,
    StateCarrierIntervention,
    intervention_authority_digest,
)
from reprobit.strict_json import canonical_json


def sample_report() -> Report:
    proof = proof_report()
    return Report.from_bundle(
        bundle(),
        Verdict(cold=True, byte_exact=True, logic_certified=True, toolchain_origin=True),
        evidence=proof.summary,
        proof=proof,
        target_results={"program": True},
        target_artifacts={"program": (100, digest(b"oracle"))},
    )


def function_report(
    *,
    reference_span: dict[str, object] | None = None,
    parameters: dict[str, object] | None = None,
    constraints: dict[str, object] | None = None,
    auxiliary_ids: tuple[str, ...] = (),
) -> Report:
    scope = Scope(target="program", translation_unit="main", function="?work@@YAXXZ")
    donor = StateCarrierIntervention(
        id="carrier",
        scope=Scope(target="program", translation_unit="main"),
        rationale="Compiler state",
        carrier="declarations",
        beneficiaries=(scope,),
    )
    intervention = ClassicRecipeIntervention(
        id="select-body",
        family=ClassicRecipeFamily.EQUAL_BODY_STRICT,
        role=ClassicRecipeRole.FUNCTION,
        build_target="program",
        symbol=scope.function,
        scope=scope,
        rationale="Select the measured body",
        dependencies=(donor.id,),
        parameters=tuple(
            ClassicField(name=name, value=value)
            for name, value in sorted((parameters or {}).items())
        ),
    )
    auxiliary_donors = tuple(
        donor.model_copy(update={"id": identity}) for identity in auxiliary_ids
    )
    costs = calculate_cost((donor, intervention, *auxiliary_donors))
    row = next(row for row in costs.interventions if row.intervention_id == intervention.id)
    input_statement = {"intervention": intervention.model_dump(mode="json")}
    if constraints is not None:
        input_statement["candidate_constraints"] = constraints
    if reference_span is not None:
        input_statement["candidate_constraints"] = {"retail_oracle": reference_span}
    output_statement = {
        "validator_trace": {"body_length": 12, "body_changed_offsets": [1, 2, 7]},
    }
    semantic = SemanticProof(
        family=intervention.family.value,
        validator_id="test-validator",
        validator_digest=digest(b"validator"),
        input_statement=input_statement,
        output_statement=output_statement,
        input_statement_digest=Digest.from_bytes(canonical_json(input_statement)),
        output_statement_digest=Digest.from_bytes(canonical_json(output_statement)),
        obligations=("body.equal",),
        evidence_digest=digest(b"evidence"),
    )
    certificate = Certificate(
        id="certificate",
        intervention_id=intervention.id,
        intervention_authority_digest=intervention_authority_digest(intervention),
        intervention_cost_digest=intervention_cost_row_digest(row),
        obligations=(ProofObligation(name="body.equal", passed=True),),
        artifact_ids=("candidate",),
        semantic_proofs=(semantic,),
    )
    # The projector deliberately handles incomplete runs, including ledger rows
    # for which no certificate was produced.
    base = sample_report()
    return base.model_copy(
        update={
            "costs": costs,
            "proof": base.proof.model_copy(update={"certificates": (certificate,)}),
        }
    )


def test_explorer_preserves_every_cost_and_function_relative_coordinate() -> None:
    report = function_report()
    data: Any = build_explorer_data(report)
    assert data["summary"]["total_cost"] == 26
    assert data["summary"]["intervention_count"] == 2
    assert data["summary"]["unit_count"] == 2
    assert data["summary"]["mapped_interventions"] == 0
    assert data["summary"]["function_relative_interventions"] == 1
    rows = {item["id"]: item for item in data["interventions"]}
    assert rows["carrier"]["status"] == "missing"
    assert rows["select-body"]["changed_bytes"] == 3
    assert rows["select-body"]["body_size"] == 12
    assert {item["space"] for item in rows["select-body"]["locations"]} == {"function"}
    changed = [item for item in rows["select-body"]["locations"] if item["relation"] == "changed"]
    assert [(item["start"], item["end"]) for item in changed] == [(1, 3), (7, 8)]
    assert data["functions"][0]["total_cost"] == {"numerator": 26, "denominator": 1}


def test_shared_beneficiary_locations_do_not_duplicate_charges() -> None:
    context = {
        "targets": [
            {
                "id": "program",
                "symbols": [
                    {
                        "name": "?work@@YAXXZ",
                        "tu": "main",
                        "va": 0x401000,
                        "size": 12,
                        "space": "va",
                    },
                    {"name": "?work@@YAXXZ", "va": 0x402000, "size": None, "space": "debug-va"},
                ],
            }
        ]
    }
    data: Any = build_explorer_data(function_report(), context=context)
    rows = {item["id"]: item for item in data["interventions"]}
    assert data["summary"]["total_cost"] == sum(item["cost"] for item in rows.values()) == 26
    assert data["summary"]["mapped_interventions"] == 2
    assert rows["carrier"]["locations"][0]["relation"] == "beneficiary"
    assert rows["carrier"]["locations"][0]["start"] == 0x401000
    assert rows["select-body"]["locations"][0]["end"] == 0x40100C


def test_ambiguous_symbols_and_reference_coordinates_are_not_candidate_placements() -> None:
    context = {
        "targets": [
            {
                "id": "program",
                "symbols": [
                    {"name": "?work@@YAXXZ", "va": 0x401000},
                    {"name": "?work@@YAXXZ", "va": 0x402000},
                ],
            }
        ]
    }
    data: Any = build_explorer_data(function_report(), context=context)
    assert data["summary"]["mapped_interventions"] == 0
    context["targets"][0]["symbols"] = [
        {"name": "?work@@YAXXZ", "va": 0x401000, "space": "reference-va"},
    ]
    data = build_explorer_data(function_report(), context=context)
    assert data["summary"]["mapped_interventions"] == 0
    assert any(
        location["space"] == "reference-va"
        for row in data["interventions"]
        for location in row["locations"]
    )


def test_unbound_statement_cannot_supply_mechanics_or_locations() -> None:
    report = function_report()
    certificate = report.proof.certificates[0].model_copy(
        update={
            "intervention_authority_digest": digest(b"different authority"),
        }
    )
    report = report.model_copy(
        update={
            "proof": report.proof.model_copy(update={"certificates": (certificate,)}),
        }
    )
    data: Any = build_explorer_data(report)
    function = next(row for row in data["interventions"] if row["id"] == "select-body")
    assert function["locations"] == []
    assert function["body_size"] is None


def test_debug_normalization_stays_outside_candidate_coordinate_space_and_cost() -> None:
    base = sample_report()
    report = base.model_copy(update={"proof": proof_report_with_debug_companion()})
    data: Any = build_explorer_data(report)
    assert data["operations"]
    assert all(item["cost"] == 0 for item in data["operations"])
    assert all(
        location["space"] == "supplemental-file"
        for row in data["operations"]
        for location in row["locations"]
    )
    assert data["summary"]["total_cost"] == base.costs.project_total


def test_report_binds_exploration_and_detaches_mutable_caller_context() -> None:
    report = sample_report()
    context: dict[str, object] = {"targets": [{"id": "program", "image_base": 0x400000}]}
    enriched = report.with_exploration(context)
    assert enriched.run_id != report.run_id
    assert enriched.proof == report.proof
    context["targets"] = []
    assert enriched.exploration["targets"]
    wire = enriched.model_dump(mode="json", exclude_computed_fields=True, exclude_none=True)
    wire["exploration"] = {}
    with pytest.raises(ValidationError, match="run_id"):
        Report.model_validate_json(canonical_json(wire))
    with pytest.raises(ValueError, match="non-finite"):
        report.with_exploration({"bad": float("nan")})


def test_from_bundle_embeds_reference_functions_only_as_exact_candidate_coordinates() -> None:
    project = bundle()
    oracle = project.oracle_documents[0].model_copy(
        update={
            "functions": (
                OracleFunction(
                    translation_unit="main",
                    symbol="?work@@YAXXZ",
                    address=0x401000,
                    size=12,
                    digest=digest(b"function"),
                ),
            )
        }
    )
    project = project.model_copy(update={"oracle_documents": (oracle,)})
    proof = proof_report()
    report = Report.from_bundle(
        project,
        Verdict(cold=True, byte_exact=True, logic_certified=True, toolchain_origin=True),
        evidence=proof.summary,
        proof=proof,
        target_results={"program": True},
        target_artifacts={"program": (100, digest(b"oracle"))},
    )
    data: Any = build_explorer_data(report)
    symbol = data["targets"][0]["symbols"][0]
    assert symbol["space"] == "va"
    assert symbol["va"] == 0x401000
    assert symbol["size"] == 12
    assert symbol["tu"] == "main"


def test_source_pairs_use_explicit_receipts_and_donor_effective_preimage() -> None:
    declaration = {
        "parameters": [
            {
                "name": "outputs",
                "value": [
                    {"path": "main.cpp", "clean": "clean-main", "effective": "effective-main"},
                ],
            }
        ]
    }
    statement = {
        "compiler_statement": {
            "request_receipt": {
                "input_digests": {
                    "clean:main.cpp": "clean-main",
                    "effective:main.cpp": "effective-main",
                    "clean:header.h": "clean-header",
                },
                "output_digests": {
                    "s.cpp": "private-main",
                    "inc/source/header.h": "private-header",
                },
            }
        }
    }
    assert _source_pairs(declaration, statement) == [
        ("main.cpp", "clean-main", "effective-main"),
        ("main.cpp", "effective-main", "private-main"),
        ("header.h", "clean-header", "private-header"),
    ]


def test_source_diff_preserves_context_and_rejects_truncation_as_an_edit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    declaration = {
        "parameters": [
            {
                "name": "outputs",
                "value": [
                    {"path": "main.cpp", "clean": "before", "effective": "after"},
                ],
            }
        ]
    }
    monkeypatch.setattr(
        "reprobit.report_explorer_data.evidence_details", lambda *_, **__: (declaration, {}, {})
    )
    cost = sample_report().costs.interventions[0]
    before = "\n".join(f"line {number}" for number in range(30))
    after = before.replace("line 15", "changed line 15")
    previews = _source_previews(
        cost,
        None,
        {
            "before": {"text": before},
            "after": {"text": after},
        },
    )
    assert len(previews) == 1
    assert "- line 15" in previews[0]["before"]
    assert "+ changed line 15" in previews[0]["after"]
    assert "line 29" not in previews[0]["after"]
    assert (
        _source_previews(
            cost,
            None,
            {
                "before": {"text": before, "truncated": True},
                "after": {"text": before + "\npartial line", "truncated": True},
            },
        )
        == []
    )
    assert _source_previews(cost, None, {"after": {"text": after}}) == []


def test_proof_declared_reference_span_maps_function_and_shared_donor() -> None:
    report = function_report(
        reference_span={
            "image": "PROGRAM.EXE",
            "address": "0x401000",
            "length": 12,
            "verdict": "MATCH",
        }
    )
    data: Any = build_explorer_data(report)
    assert data["summary"]["mapped_interventions"] == 2
    assert data["targets"][0]["symbols"][0]["va"] == 0x401000
    assert data["targets"][0]["symbols"][0]["size"] == 12
    assert "Proof-declared" in data["targets"][0]["symbols"][0]["basis"]
    donor = next(row for row in data["interventions"] if row["id"] == "carrier")
    assert donor["locations"][0]["relation"] == "beneficiary"


@pytest.mark.parametrize("image,verdict", [("other.exe", "MATCH"), ("program.exe", "DIFFERENT")])
def test_unrelated_or_nonmatching_reference_span_does_not_map(image: str, verdict: str) -> None:
    report = function_report(
        reference_span={
            "image": image,
            "address": "0x401000",
            "length": 12,
            "verdict": verdict,
        }
    )
    data: Any = build_explorer_data(report)
    assert data["summary"]["mapped_interventions"] == 0


def test_reference_span_in_a_nonexact_candidate_keeps_reference_coordinates() -> None:
    report = function_report(
        reference_span={
            "image": "program.exe",
            "address": "0x401000",
            "length": 12,
            "verdict": "MATCH",
        }
    )
    report = report.model_copy(
        update={
            "targets": (report.targets[0].model_copy(update={"byte_exact": False}),),
        }
    )
    data: Any = build_explorer_data(report)
    assert data["summary"]["mapped_interventions"] == 0
    assert data["targets"][0]["symbols"][0]["space"] == "reference-va"


def test_report_carries_all_declarations_and_refuses_changed_authority() -> None:
    report = sample_report()
    declarations: Any = report.exploration["declarations"]
    assert set(declarations) == {row.intervention_id for row in report.costs.interventions}
    row = next(iter(declarations.values()))
    assert row["kind"] == "state_carrier"
    assert row["carrier"]
    bad = {**row, "carrier": "different carrier"}
    with pytest.raises(ValidationError, match="cost authority"):
        report.with_exploration({"declarations": {row["id"]: bad}})


def test_final_virtual_addresses_map_only_through_unambiguous_raw_sections() -> None:
    location = {
        "space": "va",
        "start": 0x401010,
        "end": 0x401020,
        "label": "function",
        "relation": "beneficiary",
    }
    section = {"va": 0x401000, "size": 64, "file_offset": 512, "file_size": 64}
    result = _file_locations([location], {"sections": [section]})
    assert [(row["start"], row["end"], row["relation"]) for row in result] == [
        (528, 544, "beneficiary"),
    ]
    assert _file_locations([{**location, "space": "reference-va"}], {"sections": [section]}) == []
    assert _file_locations([location], {"sections": [{**section, "file_size": 16}]}) == []
    # Even a partially overlapping second virtual section makes the region ambiguous.
    assert (
        _file_locations(
            [location],
            {
                "sections": [
                    section,
                    {"va": 0x401018, "size": 16, "file_offset": 700, "file_size": 16},
                ]
            },
        )
        == []
    )
    assert (
        _file_locations(
            [location],
            {
                "sections": [
                    section,
                    {"va": 0x402000, "size": 64, "file_offset": 520, "file_size": 64},
                ]
            },
        )
        == []
    )


def test_repack_source_and_destination_use_distinct_coordinate_spaces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    declaration = {
        "parameters": [
            {
                "name": "text_repack",
                "value": {
                    "pieces": [{"src_lo": "0x401020", "src_hi": "0x401030", "shift": 16}],
                },
            }
        ]
    }
    monkeypatch.setattr(
        "reprobit.report_explorer_data.evidence_details", lambda *_, **__: (declaration, {}, {})
    )
    report = sample_report()
    locations, _, _ = _intervention_locations(report.costs.interventions[0], None, report, {})
    assert [(row["space"], row["start"], row["end"]) for row in locations] == [
        ("linked-va", 0x401020, 0x401030),
        ("va", 0x401010, 0x401020),
    ]


def test_object_order_specification_is_shown_only_for_its_observed_transform() -> None:
    base = sample_report()
    transformed_digest = digest(b"reordered object")
    transformed_id = (
        "artifact."
        + Digest.from_bytes(
            canonical_json(
                (
                    "object-transform",
                    "main",
                    transformed_digest,
                    20,
                )
            )
        ).value[:24]
    )
    artifact = Artifact(
        id=transformed_id,
        kind=ArtifactKind.OBJECT,
        logical_path="build/main.obj",
        digest=transformed_digest,
        size=20,
        origin=ArtifactOrigin.COMPOSED,
    )
    node = ProvenanceNode(
        id="observed-order",
        kind=ProvenanceKind.OBJECT_TRANSFORM,
        operation="restore_comdat_group_order",
        origin=ArtifactOrigin.COMPOSED,
        artifact_id=artifact.id,
        parents=("seed-origin",),
    )
    report = base.model_copy(
        update={
            "proof": base.proof.model_copy(
                update={
                    "artifacts": (*base.proof.artifacts, artifact),
                    "provenance": (*base.proof.provenance, node),
                }
            )
        }
    )
    data: Any = build_explorer_data(
        report,
        context={
            "object_transforms": [
                {"tu": "main", "operation": node.operation, "orders": [["first", "second"]]},
                {"tu": "unused", "operation": node.operation, "orders": [["x", "y"]]},
            ]
        },
    )
    assert len(data["operations"]) == 1
    assert data["operations"][0]["title"] == "Restore object section order"
    assert data["operations"][0]["detail"]["orders"] == [["first", "second"]]
    assert data["operations"][0]["cost"] == 0


def test_secondary_donors_are_navigable_without_changing_cost_or_guessing_ids() -> None:
    report = function_report(
        parameters={
            "instruction_donor": "instruction-carrier",
            "target_donor": "carrier",
            "rationale_hint": "unrelated-carrier",
            "unrecognized_reference": "unrelated-carrier",
        },
        constraints={
            "complete_donor": "complete-carrier",
            "donor_variants": [{"donor": "variant-carrier"}],
        },
        auxiliary_ids=(
            "instruction-carrier",
            "complete-carrier",
            "variant-carrier",
            "unrelated-carrier",
        ),
    )
    data: Any = build_explorer_data(report)
    consumer = next(row for row in data["interventions"] if row["id"] == "select-body")
    assert consumer["dependencies"] == [
        "carrier",
        "complete-carrier",
        "instruction-carrier",
        "variant-carrier",
    ]
    # The same dependency list powers the inspector's reverse "Used by" links.
    assert [
        row["id"] for row in data["interventions"] if "instruction-carrier" in row["dependencies"]
    ] == ["select-body"]
    assert data["summary"]["total_cost"] == report.costs.project_total == 30
    assert len(data["interventions"]) == len(report.costs.interventions)


def test_sparse_donor_pin_resolves_but_unknown_and_conflicting_choices_do_not() -> None:
    report = function_report(
        parameters={"donor_variants": [{}], "instruction_donor": "not-in-report"},
        constraints={"donor_variants[0].donor": "variant-carrier"},
        auxiliary_ids=("variant-carrier",),
    )
    data: Any = build_explorer_data(report)
    consumer = next(row for row in data["interventions"] if row["id"] == "select-body")
    assert consumer["dependencies"] == ["carrier", "variant-carrier"]
    conflicting = function_report(
        parameters={"instruction_donor": "first-carrier"},
        constraints={"instruction_donor": "second-carrier"},
        auxiliary_ids=("first-carrier", "second-carrier"),
    )
    data = build_explorer_data(conflicting)
    consumer = next(row for row in data["interventions"] if row["id"] == "select-body")
    assert consumer["dependencies"] == ["carrier"]


def test_measured_mosaic_variant_records_preserve_declared_donor_navigation() -> None:
    report = function_report(
        parameters={
            "donor_variants": [{"donor": "variant-carrier"}],
            "instruction_ranges": [{"donor": "variant-carrier"}],
        },
        constraints={
            "donor_variants": [
                {"donor": "variant-carrier", "expected_body_length": 1494},
            ]
        },
        auxiliary_ids=("variant-carrier",),
    )
    data: Any = build_explorer_data(report)
    consumer = next(row for row in data["interventions"] if row["id"] == "select-body")
    assert consumer["dependencies"] == ["carrier", "variant-carrier"]


def test_runtime_source_pair_excerpts_are_preferred_and_require_exact_receipt_pair() -> None:
    report = function_report(
        parameters={
            "outputs": [
                {"path": "main.cpp", "clean": "original-digest", "effective": "effective-digest"},
            ]
        }
    )
    captured = {
        "path": "main.cpp",
        "before_digest": "original-digest",
        "after_digest": "effective-digest",
        "before_size": 2000,
        "after_size": 2010,
        "before": "@@ lines 17-19 @@\nif (old_form) {",
        "after": "@@ lines 17-19 @@\nif (new_form) {",
        "note": "Captured from the verified clean/effective source pair.",
        "truncated": False,
        "source_rendering": {"rows": [{"kind": "replace"}], "truncated": False},
    }
    context: dict[str, object] = {"source_diffs": [captured]}
    data: Any = build_explorer_data(report, context=context)
    consumer = next(row for row in data["interventions"] if row["id"] == "select-body")
    assert consumer["previews"][0]["before"] == captured["before"]
    assert consumer["previews"][0]["after"] == captured["after"]
    assert consumer["previews"][0]["source_path"] == "main.cpp"
    assert consumer["previews"][0]["preview_kind"] == "file"
    assert consumer["previews"][0]["source_rendering"] == captured["source_rendering"]
    context["sources"] = {
        "original-digest": {"text": "different rendering"},
        "effective-digest": {"text": "snapshot fallback"},
    }
    data = build_explorer_data(report, context=context)
    consumer = next(row for row in data["interventions"] if row["id"] == "select-body")
    assert consumer["previews"][0]["before"] == captured["before"]
    assert sum(preview["title"] == "main.cpp" for preview in consumer["previews"]) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"path": "other.cpp"},
        {"before_digest": "wrong-before"},
        {"after_digest": "wrong-after"},
    ],
)
def test_runtime_source_diff_never_attaches_to_a_similar_but_different_pair(
    change: dict[str, object],
) -> None:
    report = function_report(
        parameters={
            "outputs": [
                {"path": "main.cpp", "clean": "before", "effective": "after"},
            ]
        }
    )
    captured = {
        "path": "main.cpp",
        "before_digest": "before",
        "after_digest": "after",
        "before": "captured original",
        "after": "captured changed",
        **change,
    }
    data: Any = build_explorer_data(report, context={"source_diffs": [captured]})
    consumer = next(row for row in data["interventions"] if row["id"] == "select-body")
    assert not any(preview["before"] == "captured original" for preview in consumer["previews"])


def test_truncated_source_capture_is_disclosed_and_duplicate_pair_is_ambiguous() -> None:
    report = function_report(
        parameters={
            "outputs": [
                {"path": "main.cpp", "clean": "before", "effective": "after"},
            ]
        }
    )
    captured = {
        "path": "main.cpp",
        "before_digest": "before",
        "after_digest": "after",
        "before": "captured original",
        "after": "captured changed",
        "truncated": True,
    }
    data: Any = build_explorer_data(report, context={"source_diffs": [captured]})
    consumer = next(row for row in data["interventions"] if row["id"] == "select-body")
    assert "bounded excerpt" in consumer["previews"][0]["note"]
    data = build_explorer_data(
        report,
        context={
            "source_diffs": [
                captured,
                {**captured, "after": "conflicting rendering"},
            ]
        },
    )
    consumer = next(row for row in data["interventions"] if row["id"] == "select-body")
    assert not any(preview["before"] == "captured original" for preview in consumer["previews"])


@pytest.mark.parametrize(
    ("before_digest", "size", "expected_before", "expected_after"),
    [
        (None, 0, "(new file)", "(empty file)"),
        ("before", 0, "(empty file)", "(empty file)"),
        ("before", 1200, "(no text in this excerpt)", "(no text in this excerpt)"),
    ],
)
def test_empty_source_excerpts_do_not_imply_file_creation_or_removal(
    before_digest: str | None, size: int, expected_before: str, expected_after: str
) -> None:
    report = function_report(
        parameters={"outputs": [{"path": "main.cpp", "clean": before_digest, "effective": "after"}]}
    )
    captured = {
        "path": "main.cpp",
        "before_digest": before_digest,
        "after_digest": "after",
        "before": "",
        "after": "",
        "before_size": size,
        "after_size": size,
    }
    data: Any = build_explorer_data(report, context={"source_diffs": [captured]})
    consumer = next(row for row in data["interventions"] if row["id"] == "select-body")
    preview = consumer["previews"][0]
    assert preview["before"] == expected_before
    assert preview["after"] == expected_after


def generated_unit_report(payload: bytes) -> tuple[Report, dict[str, object]]:
    unit = {
        "path": "generated.cpp",
        "ordinal": 13,
        "after": "previous.cpp",
        "before": "following.cpp",
    }
    return (
        function_report(
            parameters={
                "graph": {"generated_tus": [unit]},
                "outputs": [
                    {
                        "path": unit["path"],
                        "clean": None,
                        "effective": Digest.from_bytes(payload).value,
                        "size": len(payload),
                    }
                ],
            }
        ),
        unit,
    )


@pytest.mark.parametrize("encoding", ["utf-8", "cp1252"])
def test_generated_action_shows_complete_source_with_build_placement_preserved(
    encoding: str,
) -> None:
    source = '// generated café\n#include "body.h"\nvoid generated() {}\n'
    payload = source.encode(encoding)
    report, unit = generated_unit_report(payload)
    captured = {
        "path": unit["path"],
        "before_digest": None,
        "after_digest": Digest.from_bytes(payload).value,
        "before": "",
        "after": "@@ lines 1-3 @@\n" + source,
        "truncated": False,
    }
    data: Any = build_explorer_data(report, context={"source_diffs": [captured]})
    consumer = next(row for row in data["interventions"] if row["id"] == "select-body")
    preview = next(p for p in consumer["previews"] if p.get("operation") == "generated_tus")
    assert preview["after"] == source
    assert preview["content_complete"] is True
    assert preview["content_available"] is True
    assert preview["build_context"] == unit
    assert preview["action_id"] == "generated_tus#1"
    assert preview["action_index"] == "1"
    assert preview["source_path"] == unit["path"]
    assert data["summary"]["total_cost"] == report.costs.project_total


@pytest.mark.parametrize(
    "change",
    [
        {"path": "unrelated.cpp"},
        {"before_digest": "unrelated-original"},
        {"after_digest": "unrelated-output"},
    ],
)
def test_generated_action_does_not_reuse_an_unrelated_source_pair(
    change: dict[str, object],
) -> None:
    source = b"void generated() {}\n"
    report, unit = generated_unit_report(source)
    captured = {
        "path": unit["path"],
        "before_digest": None,
        "after_digest": Digest.from_bytes(source).value,
        "before": "",
        "after": "@@ lines 1-1 @@\n" + source.decode(),
        **change,
    }
    data: Any = build_explorer_data(report, context={"source_diffs": [captured]})
    consumer = next(row for row in data["interventions"] if row["id"] == "select-body")
    preview = next(p for p in consumer["previews"] if p.get("operation") == "generated_tus")
    assert "void generated" not in preview["after"]
    assert preview["content_complete"] is False
    assert preview["content_available"] is False
    assert preview["build_context"] == unit


@pytest.mark.parametrize(
    ("text", "truncated"),
    [
        ("void generated() {}\n", True),
        ("void gener", False),
    ],
)
def test_generated_source_capture_never_labels_partial_contents_complete(
    text: str, truncated: bool
) -> None:
    report, unit = generated_unit_report(b"void generated() {}\n")
    captured = {
        "path": unit["path"],
        "before_digest": None,
        "after_digest": Digest.from_bytes(b"void generated() {}\n").value,
        "before": "",
        "after": "@@ lines 1-1 @@\n" + text,
        "truncated": truncated,
    }
    data: Any = build_explorer_data(report, context={"source_diffs": [captured]})
    consumer = next(row for row in data["interventions"] if row["id"] == "select-body")
    preview = next(p for p in consumer["previews"] if p.get("operation") == "generated_tus")
    assert preview["after"] == text
    assert preview["content_complete"] is False
    assert preview["content_available"] is True
    assert "excerpt" in preview["note"]


def test_generated_unit_can_use_a_complete_verified_snapshot() -> None:
    source = b"void generated() {}\n"
    report, _unit = generated_unit_report(source)
    data: Any = build_explorer_data(
        report,
        context={
            "sources": {
                Digest.from_bytes(source).value: {"text": source.decode(), "truncated": False}
            }
        },
    )
    consumer = next(row for row in data["interventions"] if row["id"] == "select-body")
    preview = next(p for p in consumer["previews"] if p.get("operation") == "generated_tus")
    assert preview["after"] == source.decode()
    assert preview["content_complete"] is True


def test_low_level_records_are_preserved_under_technical_details() -> None:
    previews = [
        {"title": "Changed byte positions", "after": "0x1 0x3"},
        {"title": "Selected instruction ranges", "after": "0x0 to 0x4"},
        {"title": "Generated compilation units · 1. unit.cpp", "after": "void unit() {}"},
    ]
    without_assembly = _present_previews(previews, assembly_available=False)
    with_assembly = _present_previews(previews, assembly_available=True)
    assert [p["presentation"] for p in without_assembly] == ["technical", "primary", "primary"]
    assert [p["presentation"] for p in with_assembly] == ["technical", "technical", "primary"]
    assert [p["after"] for p in with_assembly] == [p["after"] for p in previews]
    assert all("presentation" not in preview for preview in previews)


def _source_action_fixture() -> tuple[Report, dict[str, Any]]:
    before, after = Digest.from_bytes(b"old").value, Digest.from_bytes(b"new").value
    report = function_report(
        parameters={
            "outputs": [
                {
                    "path": "main.cpp",
                    "clean": before,
                    "effective": after,
                    "size": 3,
                    "ops": [
                        {
                            "id": "replace-original",
                            "op": "replace",
                            "removed": {"sha256": before, "size": 3},
                        }
                    ],
                }
            ]
        }
    )
    certificate = report.proof.certificates[0]
    semantic = certificate.semantic_proofs[0]
    output = {
        **semantic.output_statement,
        "project_overlay_epoch": {
            "source_validation": {
                "render_receipts": [
                    {
                        "path": "main.cpp",
                        "input_digest": before,
                        "output_digest": after,
                        "input_size": 3,
                        "output_size": 3,
                        "operations": [
                            {
                                "operation_id": "replace-original",
                                "action": "replace",
                                "removed_digest": before,
                                "removed_size": 3,
                                "fragment_digest": after,
                                "fragment_size": 3,
                                "anchors": [
                                    {"role": "start", "byte_offset": 0},
                                    {"role": "end", "byte_offset": 3},
                                ],
                            }
                        ],
                    }
                ],
            }
        },
    }
    semantic = semantic.model_copy(
        update={
            "output_statement": output,
            "output_statement_digest": Digest.from_bytes(canonical_json(output)),
        }
    )
    certificate = certificate.model_copy(update={"semantic_proofs": (semantic,)})
    report = report.model_copy(
        update={
            "proof": report.proof.model_copy(
                update={
                    "certificates": (certificate,),
                }
            )
        }
    )
    return report, {
        "intervention_id": "select-body",
        "path": "main.cpp",
        "action_id": "replace-original",
        "operation": "replace",
        "before_digest": before,
        "after_digest": after,
        "removed_digest": before,
        "removed_size": 3,
        "fragment_digest": after,
        "fragment_size": 3,
        "before": "old",
        "after": "new",
        "truncated": False,
        "source_rendering": {"rows": [{"kind": "replace"}], "truncated": False},
    }


def test_action_source_text_replaces_placeholder_and_preserves_identity_and_cost() -> None:
    report, capture = _source_action_fixture()
    data: Any = build_explorer_data(report, context={"source_operations": [capture]})
    row = next(item for item in data["interventions"] if item["id"] == "select-body")
    preview = next(item for item in row["previews"] if item.get("action_id") == "replace-original")

    assert preview["before"] == "old"
    assert preview["after"] == "new"
    assert preview["source_captured"] is True
    assert preview["action_index"] == "1"
    assert preview["preview_kind"] == "action"
    assert preview["source_rendering"] == capture["source_rendering"]
    assert row["source_paths"] == ["main.cpp"]
    assert row["cost"] == next(
        c.cost for c in report.costs.interventions if c.intervention_id == row["id"]
    )


@pytest.mark.parametrize(
    "change",
    [
        {"intervention_id": "other"},
        {"path": "other.cpp"},
        {"action_id": "other"},
        {"operation": "delete"},
        {"before_digest": "wrong"},
        {"after_digest": "wrong"},
        {"removed_digest": "wrong"},
        {"fragment_digest": "wrong"},
        {"before": "bad"},
        {"after": "bad"},
        {"removed_size": 4},
    ],
)
def test_action_source_requires_exact_receipt_identity_pins_and_full_text(
    change: dict[str, object],
) -> None:
    report, capture = _source_action_fixture()
    data: Any = build_explorer_data(report, context={"source_operations": [{**capture, **change}]})
    row = next(item for item in data["interventions"] if item["id"] == "select-body")
    preview = next(item for item in row["previews"] if item.get("action_id") == "replace-original")

    assert not preview.get("source_captured")
    assert "text not stored" in preview["before"]


def test_ambiguous_duplicate_action_capture_is_not_attached() -> None:
    report, capture = _source_action_fixture()
    data: Any = build_explorer_data(report, context={"source_operations": [capture, capture]})
    row = next(item for item in data["interventions"] if item["id"] == "select-body")
    assert not any(item.get("source_captured") for item in row["previews"])


def test_function_source_path_uses_exact_target_and_translation_unit() -> None:
    report = function_report()
    data: Any = build_explorer_data(
        report,
        context={
            "translation_units": [
                {"target": "other", "tu": "main", "source_path": "wrong.cpp"},
                {"target": "program", "tu": "main", "source_path": "src/main.cpp"},
            ]
        },
    )
    row = next(item for item in data["interventions"] if item["id"] == "select-body")
    assert row["source_paths"] == ["src/main.cpp"]

    data = build_explorer_data(
        report,
        context={
            "translation_units": [
                {"target": "program", "tu": "main", "source_path": "one.cpp"},
                {"target": "program", "tu": "main", "source_path": "two.cpp"},
            ]
        },
    )
    row = next(item for item in data["interventions"] if item["id"] == "select-body")
    assert row["source_paths"] == []


@pytest.mark.parametrize("change", [None, "declaration", "before", "after", "fragment", "identity"])
def test_donor_action_projection_checks_declaration_and_source_receipts(
    monkeypatch: pytest.MonkeyPatch,
    change: str | None,
) -> None:
    from reprobit.report_explorer_data import _source_action_previews

    cost = function_report().costs.interventions[1]
    before, after = "old", "class Donor;\n"
    old_digest, new_digest = (
        Digest.from_bytes(before.encode()).value,
        Digest.from_bytes(after.encode()).value,
    )
    operation = {
        "id": "op_edit",
        "op": "replace",
        "gen": {"k": "fwd", "id": "Donor"},
        "removed": {"sha256": old_digest, "size": len(before)},
    }
    declaration = {
        "id": cost.intervention_id,
        "family": "donor_source_overlay",
        "parameters": [
            {"name": "renderings", "value": [{"path": "main.cpp", "operations": [operation]}]},
        ],
    }
    statement = {
        "compiler_statement": {
            "request_receipt": {
                "intervention_id": cost.intervention_id,
                "input_digests": {"clean:main.cpp": old_digest, "effective:main.cpp": old_digest},
                "output_digests": {"s.cpp": new_digest},
            }
        }
    }
    monkeypatch.setattr(
        "reprobit.report_explorer_data.evidence_details",
        lambda *args, **kwargs: (declaration, statement, {}),
    )
    capture = {
        "intervention_id": cost.intervention_id,
        "path": "main.cpp",
        "action_id": "op_edit",
        "operation": "replace",
        "before_digest": old_digest,
        "after_digest": new_digest,
        "removed_digest": old_digest,
        "removed_size": len(before),
        "fragment_digest": new_digest,
        "fragment_size": len(after),
        "before": before,
        "after": after,
        "truncated": False,
        "basis": "donor-render-replay",
        "operation_declaration_digest": Digest.from_bytes(canonical_json(operation)).value,
        "source_rendering": {"rows": [{"kind": "replace"}]},
    }
    if change == "declaration":
        operation["gen"]["id"] = "Other"
    elif change == "identity":
        capture["intervention_id"] = "other"
    elif change == "fragment":
        capture["fragment_digest"] = "wrong"
    elif change is not None:
        capture[change] = "wrong"
    preview = {
        "source_path": "main.cpp",
        "action_id": "op_edit",
        "operation": "replace",
        "before": "original bytes not stored",
        "after": "generated",
    }
    result = _source_action_previews(cost, None, [preview], [capture])[0]
    if change is None:
        assert result["before"] == before
        assert result["after"] == after
        assert result["source_captured"] is True
        assert result["source_rendering"] == capture["source_rendering"]
    else:
        assert result == preview
