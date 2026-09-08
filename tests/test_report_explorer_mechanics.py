from __future__ import annotations

import json
from hashlib import sha256
from typing import cast

import pytest
from pydantic import TypeAdapter

from reprobit.classic_donors import (
    generate_declaration_shape,
    generate_extern_run,
    generate_forward_run,
    generate_pad_shape,
)
from reprobit.costs import (
    InterventionCost,
    calculate_intervention_cost,
    intervention_cost_row_digest,
)
from reprobit.intervention_metadata import CLASSIC_RECIPE_METADATA, ClassicRecipeFamily
from reprobit.model import ByteRange, Certificate, Digest, ProofObligation, Scope, SemanticProof
from reprobit.report_explorer_mechanics import (
    _CLASSIC,
    _GENERIC,
    describe_intervention,
    evidence_details,
)
from reprobit.schema import (
    ClassicField,
    ClassicRecipeIntervention,
    ClassicRecipeRole,
    Intervention,
    LegacyOracleInstallIntervention,
    OracleInstallRange,
)
from reprobit.strict_json import canonical_json


def _fixture(
    family: ClassicRecipeFamily,
    parameters: dict[str, object] | None = None,
    trace: dict[str, object] | None = None,
    input_extra: dict[str, object] | None = None,
    output_extra: dict[str, object] | None = None,
) -> tuple[InterventionCost, Certificate]:
    metadata = CLASSIC_RECIPE_METADATA[family]
    assert metadata.role is not None
    role = metadata.role
    scope = Scope(
        target="program",
        translation_unit="main" if role is not ClassicRecipeRole.PROJECT else None,
        function="work" if role is ClassicRecipeRole.FUNCTION else None,
    )
    intervention = ClassicRecipeIntervention(
        id="example",
        family=family,
        role=role,
        build_target="program",
        scope=scope,
        rationale="A recorded declaration for the mechanics preview fixture.",
        symbol=scope.function,
        dependencies=("donor",) if role is ClassicRecipeRole.FUNCTION else (),
        parameters=tuple(
            ClassicField(name=key, value=value) for key, value in sorted((parameters or {}).items())
        ),
    )
    cost = calculate_intervention_cost(intervention)
    statement = {"intervention": intervention.model_dump(mode="json"), **(input_extra or {})}
    output = {"validator_trace": trace or {}, **(output_extra or {})}
    digest = Digest.from_bytes(b"fixture")
    proof = SemanticProof(
        family=family.value,
        validator_id="fixture",
        validator_digest=digest,
        input_statement_digest=Digest.from_bytes(canonical_json(statement)),
        output_statement_digest=Digest.from_bytes(canonical_json(output)),
        obligations=("fixture",),
        evidence_digest=digest,
        input_statement=statement,
        output_statement=output,
    )
    certificate = Certificate(
        id="certificate",
        intervention_id=intervention.id,
        intervention_authority_digest=cost.intervention_authority_digest,
        intervention_cost_digest=intervention_cost_row_digest(cost),
        obligations=(ProofObligation(name="fixture", passed=True),),
        artifact_ids=("object",),
        semantic_proofs=(proof,),
    )
    return cost, certificate


def _previews(description: dict[str, object]) -> list[dict[str, str]]:
    return cast(list[dict[str, str]], description["previews"])


def test_every_family_and_generic_kind_has_plain_mechanics() -> None:
    assert set(_CLASSIC) == set(ClassicRecipeFamily)
    assert set(_GENERIC) == {
        "state_carrier",
        "generated_supplier",
        "metadata_normalization",
        "link_ordering",
        "equal_body_donor",
        "structural_donor",
        "cross_tu_donor",
        "semantic_rewrite",
        "binary_surgery",
        "legacy.oracle_install",
    }
    cost, _ = _fixture(ClassicRecipeFamily.IMAGE_METADATA)
    for family in ClassicRecipeFamily:
        description = describe_intervention(cost.model_copy(update={"family": family}), None)
        assert description["title"] != "Recorded build intervention"
        assert len(cast(list[str], description["steps"])) == 3
        assert description["stage"] in {"source", "compile", "object", "link", "image", "reference"}
        json.dumps(description)
    for kind in _GENERIC:
        description = describe_intervention(
            cost.model_copy(update={"family": None, "kind": kind}), None
        )
        assert description["title"] != "Recorded build intervention"


@pytest.mark.parametrize("mutation", ["declaration", "authority", "cost", "identity"])
def test_unbound_receipt_cannot_supply_previews_or_dependencies(mutation: str) -> None:
    cost, certificate = _fixture(
        ClassicRecipeFamily.RETAIL_EXACT_REGISTER_BIJECTION,
        {"register_bijection": {"mapping": {"eax": "ecx"}}},
    )
    if mutation == "declaration":
        proof = certificate.semantic_proofs[0]
        statement = cast(dict[str, object], proof.input_statement)
        declaration = cast(dict[str, object], statement["intervention"])
        changed = {**statement, "intervention": {**declaration, "dependencies": ["unrelated"]}}
        # This alternate statement is internally self-consistent, but it is not
        # the intervention authority to which the cost row was committed.
        changed_proof = proof.model_copy(
            update={
                "input_statement": changed,
                "input_statement_digest": Digest.from_bytes(canonical_json(changed)),
            }
        )
        certificate = certificate.model_copy(update={"semantic_proofs": (changed_proof,)})
    elif mutation == "identity":
        certificate = certificate.model_copy(update={"intervention_id": "other"})
    else:
        field = (
            "intervention_authority_digest"
            if mutation == "authority"
            else "intervention_cost_digest"
        )
        certificate = certificate.model_copy(update={field: Digest.from_bytes(b"other")})
    description = describe_intervention(cost, certificate)
    assert description["previews"] == []
    assert description["dependencies"] == []
    assert evidence_details(cost, certificate) == ({}, {}, {})


@pytest.mark.parametrize(
    ("family", "parameters", "expected"),
    [
        (
            ClassicRecipeFamily.DECLARATION_SHAPE,
            {"classes": 1, "functions": 2},
            generate_declaration_shape(1, 2),
        ),
        (
            ClassicRecipeFamily.PAD_SHAPE,
            {"classes": 1, "functions_per_class": 2},
            generate_pad_shape(1, 2),
        ),
        (
            ClassicRecipeFamily.FORWARD_DECLARATION_RUN,
            {"prefix": "Names", "count": 2, "width": 2, "placement": "suffix"},
            generate_forward_run("Names", 2, 2),
        ),
        (
            ClassicRecipeFamily.FORWARD_RUN_WITH_SHAPE,
            {"prefix": "Names", "count": 2, "width": 2, "classes": 1, "functions": 2},
            generate_forward_run("Names", 2, 2) + generate_declaration_shape(1, 2),
        ),
        (
            ClassicRecipeFamily.EXTERN_RUN_PAIR,
            {
                "header_prefix": "header",
                "header_count": 0,
                "seat_prefix": "seat",
                "seat_count": 2,
                "width": 2,
            },
            generate_extern_run("seat", 2, 2),
        ),
        (
            ClassicRecipeFamily.DECLARATION_RUN_TRIPLE,
            {
                "pre_prefix": "A",
                "pre_count": 1,
                "post_prefix": "B",
                "post_count": 0,
                "eof_prefix": "C",
                "eof_count": 2,
                "width": 2,
            },
            generate_forward_run("A", 1, 2) + generate_forward_run("C", 2, 2),
        ),
        (
            ClassicRecipeFamily.PREFIX_FORWARD_AFTER_INCLUDES_EXTERN,
            {
                "forward_prefix": "Names",
                "forward_count": 2,
                "forward_width": 2,
                "extern_prefix": "names",
                "extern_count": 1,
                "extern_width": 2,
            },
            generate_forward_run("Names", 2, 2) + generate_extern_run("names", 1, 2),
        ),
    ],
)
def test_declaration_preview_reuses_build_renderer_and_checks_digest(
    family: ClassicRecipeFamily,
    parameters: dict[str, object],
    expected: bytes,
) -> None:
    parameters = {**parameters, "generated_header_sha256": sha256(expected).hexdigest()}
    cost, certificate = _fixture(family, parameters)
    preview = _previews(describe_intervention(cost, certificate))[0]
    assert preview["after"] == expected.decode("ascii")
    assert "SHA-256 matches" in preview["note"]
    parameters["generated_header_sha256"] = "0" * 64
    cost, certificate = _fixture(family, parameters)
    assert not _previews(describe_intervention(cost, certificate))


def test_large_header_is_digest_checked_before_explicit_preview_truncation() -> None:
    generated = generate_forward_run("Names", 999, 3)
    cost, certificate = _fixture(
        ClassicRecipeFamily.FORWARD_DECLARATION_RUN,
        {
            "prefix": "Names",
            "count": 999,
            "width": 3,
            "generated_header_sha256": sha256(generated).hexdigest(),
        },
    )
    preview = _previews(describe_intervention(cost, certificate))[0]
    assert "class Names000;" in preview["after"]
    assert "class Names998;" not in preview["after"]
    assert "truncated" in preview["after"]
    assert "SHA-256 matches" in preview["note"]


@pytest.mark.parametrize(
    ("kind", "placement", "fields", "expected", "location"),
    [
        (
            "force_included_shape_v1",
            "force_include_v1",
            {"classes": 1, "functions": 2},
            generate_declaration_shape(1, 2),
            "header is included before",
        ),
        (
            "force_included_pad_shape_v1",
            "force_include_v1",
            {"classes": 1, "functions_per_class": 2},
            generate_pad_shape(1, 2),
            "header is included before",
        ),
        (
            "extern_run_pair_v1",
            "after_includes_and_eof_v1",
            {
                "header_prefix": "Head",
                "header_count": 1,
                "seat_prefix": "Tail",
                "seat_count": 2,
                "width": 2,
            },
            generate_extern_run("Head", 1, 2) + generate_extern_run("Tail", 2, 2),
            "after the includes and at the end",
        ),
        (
            "declaration_run_triple_v1",
            "start_after_includes_and_eof_v1",
            {
                "pre_prefix": "A",
                "pre_count": 1,
                "post_prefix": "B",
                "post_count": 1,
                "eof_prefix": "C",
                "eof_count": 2,
                "width": 2,
            },
            generate_forward_run("A", 1, 2)
            + generate_forward_run("B", 1, 2)
            + generate_forward_run("C", 2, 2),
            "at the start, after the includes, and at the end",
        ),
    ],
)
def test_nested_overlay_carriers_render_exact_bytes_with_placement_and_existing_charge(
    kind: str,
    placement: str,
    fields: dict[str, object],
    expected: bytes,
    location: str,
) -> None:
    carrier = {
        "kind": kind,
        "placement": placement,
        **fields,
        "generated_declarations_sha256": sha256(expected).hexdigest(),
    }
    cost, certificate = _fixture(
        ClassicRecipeFamily.DONOR_SOURCE_OVERLAY, {"compiler_state_carrier": carrier}
    )
    description = describe_intervention(cost, certificate)
    preview = _previews(description)[0]
    assert preview["title"] == "Generated declarations for the private compile"
    assert preview["after"] == expected.decode("ascii")
    assert "SHA-256 matches" in preview["note"]
    assert location in preview["note"]
    assert "existing donor charge; there is no extra charge" in preview["note"]
    assert "action_id" not in preview
    # Changing a pin changes the authority digest too, so use a newly bound
    # declaration and prove that rendering still refuses a mismatching payload.
    for update in (
        {"generated_declarations_sha256": "0" * 64},
        {"placement": "unknown"},
        {"kind": "unknown"},
    ):
        changed_cost, changed_certificate = _fixture(
            ClassicRecipeFamily.DONOR_SOURCE_OVERLAY,
            {"compiler_state_carrier": {**carrier, **update}},
        )
        assert _previews(describe_intervention(changed_cost, changed_certificate)) == []


def test_source_overlay_renders_real_fragment_and_discloses_missing_original_text() -> None:
    cost, certificate = _fixture(
        ClassicRecipeFamily.SOURCE_OVERLAY_GRAPH,
        {
            "graph": {"generated_tus": [], "link_admissions": []},
            "outputs": [
                {
                    "path": "src/main.cpp",
                    "ops": [
                        {"op": "insert", "gen": {"k": "fwd", "id": "PreviewClass", "lines": 1}},
                        {"op": "delete", "removed": {"size": 17}},
                    ],
                }
            ],
        },
    )
    description = describe_intervention(cost, certificate)
    previews = _previews(description)
    assert description["source_paths"] == ["src/main.cpp"]
    assert description["stage"] == "source"
    assert previews[0]["after"] == "class PreviewClass;\n"
    assert previews[1]["before"] == "17 original bytes (text not stored in this receipt)."
    assert previews[1]["after"] == "Fragment removed."
    assert "Fragment rendered" in previews[0]["note"]


def test_overlay_preview_preserves_every_operation_in_stable_order() -> None:
    operations = [
        {"op": "insert", "gen": {"k": "fwd", "id": f"Class{i}", "lines": 1}} for i in range(30)
    ] + [{"op": "delete", "removed": {"size": 4}}]
    cost, certificate = _fixture(
        ClassicRecipeFamily.SOURCE_OVERLAY_GRAPH,
        {
            "graph": {"generated_tus": [], "link_admissions": []},
            "outputs": [{"path": "src/main.cpp", "ops": operations}],
        },
    )
    previews = _previews(describe_intervention(cost, certificate))
    assert any(p["after"] == "Fragment removed." for p in previews)
    assert len(previews) == 31
    assert previews[0]["action_id"] == "src/main.cpp#0"
    assert previews[-1]["action_id"] == "src/main.cpp#30"
    assert previews[-1]["action_index"] == "31"
    assert previews[-1]["source_path"] == "src/main.cpp"


def test_overlay_positions_come_from_actual_render_receipt() -> None:
    cost, certificate = _fixture(
        ClassicRecipeFamily.SOURCE_OVERLAY_GRAPH,
        {
            "graph": {"generated_tus": [], "link_admissions": []},
            "outputs": [
                {
                    "path": "src/main.cpp",
                    "ops": [
                        {
                            "op": "insert",
                            "id": "add-name",
                            "gen": {"k": "fwd", "id": "Name", "lines": 1},
                        },
                    ],
                }
            ],
        },
        output_extra={
            "project_overlay_epoch": {
                "source_validation": {
                    "render_receipts": [
                        {
                            "path": "src/main.cpp",
                            "operations": [
                                {
                                    "operation_id": "add-name",
                                    "anchors": [
                                        {
                                            "role": "start",
                                            "byte_offset": 790,
                                            "token_boundary": 114,
                                        },
                                    ],
                                }
                            ],
                        },
                    ]
                }
            }
        },
    )
    preview = _previews(describe_intervention(cost, certificate))[0]
    assert "start byte +0x316 (token boundary 114)" in preview["note"]


def test_each_generated_unit_and_link_admission_remains_browsable() -> None:
    generated = [{"path": f"src/generated{i}.cpp", "ordinal": i} for i in range(24)]
    admissions = [{"path": f"obj/generated{i}.obj", "ordinal": i} for i in range(24)]
    cost, certificate = _fixture(
        ClassicRecipeFamily.SOURCE_OVERLAY_GRAPH,
        {
            "graph": {"generated_tus": generated, "link_admissions": admissions},
            "outputs": [{"path": "src/main.cpp", "ops": [{"op": "insert"}]}],
        },
    )
    previews = _previews(describe_intervention(cost, certificate))
    assert sum(p.get("operation") == "generated_tus" for p in previews) == 24
    assert sum(p.get("operation") == "link_admissions" for p in previews) == 24


def test_overlay_fragment_digest_mismatch_is_disclosed() -> None:
    cost, certificate = _fixture(
        ClassicRecipeFamily.SOURCE_OVERLAY_GRAPH,
        {
            "graph": {"generated_tus": [], "link_admissions": []},
            "outputs": [
                {
                    "path": "src/main.cpp",
                    "ops": [
                        {"op": "insert", "gen": {"k": "fwd", "id": "Name", "lines": 1}},
                    ],
                }
            ],
        },
        output_extra={
            "project_overlay_epoch": {
                "source_validation": {
                    "render_receipts": [
                        {
                            "path": "src/main.cpp",
                            "operations": [
                                {"operation_id": "src/main.cpp#0", "fragment_digest": "0" * 64},
                            ],
                        },
                    ]
                }
            }
        },
    )
    preview = _previews(describe_intervention(cost, certificate))[0]
    assert "differs from the recorded fragment digest" in preview["note"]
    assert '"id": "Name"' in preview["after"]


def test_metadata_preview_uses_real_old_and_new_values_at_file_offsets() -> None:
    cost, certificate = _fixture(
        ClassicRecipeFamily.IMAGE_METADATA,
        {"link_time": 123},
        {
            "schema": "pe32_timestamp_normalization_v1",
            "writes": [{"file_offset": 136, "before": 987, "after": 123}],
        },
    )
    description = describe_intervention(cost, certificate)
    primary, preview = _previews(description)
    assert description["summary"] == "1 timestamp field updated."
    assert primary["title"] == "Link timestamp · 1 field"
    assert primary["before"] == "1970-01-01 00:16:27 UTC"
    assert primary["after"] == "1970-01-01 00:02:03 UTC"
    assert primary["presentation"] == "primary"
    assert preview["title"] == "Metadata writes"
    assert preview["before"] == "file +0x88  987"
    assert preview["after"] == "file +0x88  123"
    assert "File offsets" in preview["note"]
    assert preview["presentation"] == "technical"


def test_timestamp_fields_group_identical_transitions_and_count_actual_changes() -> None:
    cost, certificate = _fixture(
        ClassicRecipeFamily.IMAGE_METADATA,
        {"link_time": 123, "resource_time": 100},
        {
            "schema": "pe32_timestamp_normalization_v1",
            "writes": [
                {"file_offset": 136, "before": 987, "after": 123},
                {"file_offset": 200, "before": 987, "after": 123},
                {"file_offset": 300, "before": 987, "after": 100},
                {"file_offset": 400, "before": 100, "after": 100},
            ],
        },
    )
    description = describe_intervention(cost, certificate)
    previews = _previews(description)
    assert (
        description["summary"] == "3 timestamp fields updated. 1 already held the declared values."
    )
    assert previews[0]["title"] == "Link timestamp · 2 fields"
    assert previews[1]["title"] == "Resource timestamp · 1 field"
    assert previews[2]["before"] == previews[2]["after"] == "1970-01-01 00:01:40 UTC"
    assert {"label": "Timestamp fields", "value": "4"} in description["facts"]


def test_missing_timestamp_input_is_never_guessed_from_the_declared_target() -> None:
    cost, certificate = _fixture(
        ClassicRecipeFamily.IMAGE_METADATA,
        {"link_time": 123},
        {
            "schema": "pe32_timestamp_normalization_v1",
            "writes": [{"file_offset": 136, "after": 123}],
        },
    )
    description = describe_intervention(cost, certificate)
    preview = _previews(description)[0]
    assert preview["before"] == "Timestamp not recorded."
    assert preview["after"] == "1970-01-01 00:02:03 UTC"
    assert "updated" not in str(description["summary"])


@pytest.mark.parametrize("before", [0, 0xFFFFFFFF])
def test_reserved_pe_timestamps_are_not_presented_as_dates(before: int) -> None:
    cost, certificate = _fixture(
        ClassicRecipeFamily.IMAGE_METADATA,
        {"link_time": 123},
        {
            "schema": "pe32_timestamp_normalization_v1",
            "writes": [{"file_offset": 136, "before": before, "after": 123}],
        },
    )
    preview = _previews(describe_intervention(cost, certificate))[0]
    assert preview["before"] == f"No meaningful timestamp ({before:#x})."


def test_unknown_metadata_trace_is_not_assumed_to_contain_unix_times() -> None:
    cost, certificate = _fixture(
        ClassicRecipeFamily.IMAGE_METADATA,
        {"link_time": 123},
        {"schema": "other_metadata", "writes": [{"file_offset": 136, "before": 987, "after": 123}]},
    )
    previews = _previews(describe_intervention(cost, certificate))
    assert [preview["title"] for preview in previews] == ["Metadata writes"]
    assert "UTC" not in previews[0]["before"]


def test_instruction_mechanics_keep_offsets_distinct_from_bytes_and_addresses() -> None:
    cost, certificate = _fixture(
        ClassicRecipeFamily.RETAIL_EXACT_REGISTER_BIJECTION,
        {},
        {
            "register_bijection": {"eax": "ecx", "ecx": "eax"},
            "body_changed_offsets": [3, 10],
            "body_length": 40,
            "instruction_schedule": [{"start": 12, "end": 20, "target_order": [1, 0]}],
            "relocation_moves": [[8, 12]],
        },
    )
    description = describe_intervention(cost, certificate)
    previews = {p["title"]: p for p in _previews(description)}
    assert description["dependencies"] == ["donor"]
    assert previews["Register roles"]["before"] == "eax\necx"
    assert previews["Register roles"]["after"] == "ecx\neax"
    assert previews["Instruction order · +0xc to +0x14"]["after"] == "1 → 0"
    assert previews["Reference positions"]["before"] == "+0x8"
    assert previews["Reference positions"]["after"] == "+0xc"
    assert previews["Changed byte positions"]["after"] == "+0x3  +0xa"
    assert "not a byte diff" in previews["Changed byte positions"]["note"]


def test_instruction_ranges_name_the_declared_secondary_donor() -> None:
    cost, certificate = _fixture(
        ClassicRecipeFamily.RETAIL_EXACT_SAME_TU_INSTRUCTION_HYBRID_RESIZE,
        {"instruction_donor": "secondary.donor"},
        {
            "instruction_ranges": [
                {
                    "target_start": 10,
                    "target_end": 13,
                    "instruction_donor_start": 2,
                    "instruction_donor_end": 5,
                },
                {
                    "target_start": 20,
                    "target_end": 23,
                    "donor": "range.donor",
                    "instruction_donor_start": 7,
                    "instruction_donor_end": 10,
                },
            ]
        },
    )
    preview = _previews(describe_intervention(cost, certificate))[0]
    assert preview["title"] == "Selected instruction ranges"
    assert preview["after"] == "secondary.donor: +0x2 to +0x5\nrange.donor: +0x7 to +0xa"


def test_pool_layout_is_object_stage_and_uses_section_relative_offsets() -> None:
    cost, certificate = _fixture(
        ClassicRecipeFamily.IMAGE_BINARY_REPACK,
        {
            "rdata_pool_repack": {
                "translation_unit": "src/main.cpp",
                "permutation": [{"symbol": "$T1", "size": 8, "old_offset": 48, "new_offset": 40}],
            }
        },
    )
    description = describe_intervention(cost, certificate)
    preview = _previews(description)[0]
    assert description["stage"] == "object"
    assert description["source_paths"] == ["src/main.cpp"]
    assert preview["before"] == "$T1  +0x30  (8 bytes)"
    assert preview["after"] == "$T1  +0x28  (8 bytes)"
    assert "object's data section" in preview["note"]


def test_executable_repack_shows_declared_virtual_address_movement() -> None:
    cost, certificate = _fixture(
        ClassicRecipeFamily.IMAGE_BINARY_REPACK,
        {
            "text_repack": {"pieces": [{"src_lo": "0x401030", "src_hi": "0x401050", "shift": 14}]},
        },
    )
    description = describe_intervention(cost, certificate)
    preview = _previews(description)[0]
    assert description["stage"] == "image"
    assert description["title"] == "Move executable code ranges"
    assert preview["before"] == "0x401030 to 0x401050"
    assert preview["after"] == "0x401022 to 0x401042"
    assert "Virtual addresses, end excluded" in preview["note"]


def test_compound_rewrites_show_register_stack_and_sum_changes() -> None:
    cost, certificate = _fixture(
        ClassicRecipeFamily.RETAIL_EXACT_DONOR_REWRITING,
        {},
        {
            "register_bijections": [{"mapping": {"eax": "edi", "edi": "eax"}, "region": [12, 20]}],
            "slot_bijections": [{"mapping": {"-20": -24, "-24": -20}}],
            "fp_sum_reassociation": [{"chain_start": 24, "order": [2, 0, 1]}],
            "growth": [[32, 34, 2, 3]],
        },
    )
    previews = {p["title"]: p for p in _previews(describe_intervention(cost, certificate))}
    assert previews["Register roles · +0xc to +0x14"]["after"] == "edi\neax"
    assert previews["Stack locations"]["after"] == "-24\n-20"
    assert previews["Floating-point sum order · +0x18"]["after"] == "2 → 0 → 1"
    assert previews["Instruction size changes"]["after"] == "+0x22: 3 bytes"


def test_import_order_does_not_invent_original_order() -> None:
    cost, certificate = _fixture(
        ClassicRecipeFamily.IMAGE_LINK_ORDER,
        {
            "import_order": {
                "imports": [
                    {
                        "dll": "API.dll",
                        "order": [
                            {"kind": "name", "value": "Open"},
                            {"kind": "ordinal", "value": 3},
                        ],
                    }
                ]
            }
        },
    )
    preview = _previews(describe_intervention(cost, certificate))[0]
    assert preview["after"] == "API.dll\nOpen → #3"
    assert "not stored" in preview["before"]


def test_only_own_source_receipts_and_trace_are_exposed() -> None:
    cost, certificate = _fixture(
        ClassicRecipeFamily.DECLARATION_SHAPE,
        {},
        {},
        {
            "compiler_statement": {
                "request_receipt": {
                    "input_digests": {"clean:src/main.cpp": "abc", "effective:src/main.cpp": "def"}
                }
            },
            "clean_manifest": [{"path": "unrelated.h"}],
        },
        {"downstream_uses": [{"proof": {"input_statement": {"SECRET_NESTED_PROOF": "x"}}}]},
    )
    description = describe_intervention(cost, certificate)
    assert description["source_paths"] == ["src/main.cpp"]
    assert "SECRET_NESTED_PROOF" not in json.dumps(description)
    assert "unrelated.h" not in json.dumps(description)


def test_oversized_generator_is_described_without_allocating_its_rendering() -> None:
    cost, certificate = _fixture(
        ClassicRecipeFamily.DONOR_SOURCE_OVERLAY,
        {
            "renderings": [
                {
                    "path": "src/main.cpp",
                    "operations": [
                        {"op": "insert", "gen": {"k": "fwd", "id": "Names", "lines": 2_000_000}},
                    ],
                }
            ]
        },
    )
    preview = _previews(describe_intervention(cost, certificate))[0]
    assert "exceeds the preview limit" in preview["note"]
    assert len(preview["after"]) < 1000


@pytest.mark.parametrize(
    ("kind", "fields", "visible"),
    [
        ("state_carrier", {"carrier": "carrier.record"}, "carrier.record"),
        ("generated_supplier", {"supplier": "supplier.record"}, "supplier.record"),
        ("metadata_normalization", {"field": "timestamp", "value": 12345}, "12345"),
        ("link_ordering", {"item_ids": ["object.z", "object.a"]}, "1. object.z\n2. object.a"),
        (
            "equal_body_donor",
            {"donor_artifact": "compiled.a", "donor_symbol": "helper", "expected_size": 17},
            "Expected body: 17 bytes",
        ),
        (
            "structural_donor",
            {"donor_artifact": "compiled.a", "donor_symbol": "helper", "mode": "resize"},
            "Supporting operation: resize",
        ),
        (
            "cross_tu_donor",
            {
                "donor_artifact": "compiled.a",
                "donor_symbol": "helper",
                "donor_translation_unit": "other.unit",
            },
            "Source unit: other.unit",
        ),
        (
            "semantic_rewrite",
            {
                "method": "register_bijection",
                "source_artifact": "compiled.a",
                "rewrite_digest": {"value": "0" * 64},
            },
            "register bijection",
        ),
        (
            "binary_surgery",
            {
                "method": "instruction_mosaic",
                "source_artifacts": ["compiled.a", "compiled.b"],
                "output_digest": {"value": "0" * 64},
            },
            "instruction mosaic",
        ),
    ],
)
def test_native_declaration_fallback_exposes_actual_fields_without_fabricated_trace(
    kind: str,
    fields: dict[str, object],
    visible: str,
) -> None:
    intervention = TypeAdapter(Intervention).validate_json(
        canonical_json(
            {
                "id": "native",
                "scope": {"target": "program"},
                "rationale": "Native declaration fixture",
                "kind": kind,
                "dependencies": ["setup"],
                **fields,
            }
        )
    )
    cost = calculate_intervention_cost(intervention)
    raw = intervention.model_dump(mode="json")
    description = describe_intervention(cost, None, declaration=raw)
    assert visible in "\n".join(p["after"] for p in _previews(description))
    assert description["dependencies"] == ["setup"]
    assert cast(dict[str, object], description["detail"])["trace"] == {}
    assert evidence_details(cost, None, declaration=raw) == (raw, {}, {})
    assert "detailed trace is not recorded" in json.dumps(description["facts"])


def test_native_reference_installation_declares_actual_ranges_and_origin() -> None:
    digest = Digest.from_bytes(b"native")
    span = ByteRange(offset=4, length=3)
    intervention = LegacyOracleInstallIntervention.freeze(
        id="reference",
        scope=Scope(target="program", translation_unit="main", function="work"),
        rationale="Reference installation fixture",
        proof_receipt_digest=digest,
        preimage_digest=digest,
        oracle_body_digest=digest,
        oracle_target="reference",
        oracle_address=0x401000,
        byte_count=3,
        maximum_oracle_payload_bytes=3,
        ranges=(OracleInstallRange(preimage_range=span, output_range=span, oracle_range=span),),
    )
    description = describe_intervention(
        calculate_intervention_cost(intervention),
        None,
        declaration=intervention.model_dump(mode="json"),
    )
    preview = _previews(description)[0]
    assert description["stage"] == "reference"
    assert preview["before"] == "Candidate +0x4: 3 bytes"
    assert "Copied from reference +0x4: 3 bytes" in preview["after"]
    assert "disclosed reference origin" in preview["note"]


@pytest.mark.parametrize("mutation", ["identity", "parameter", "missing", "malformed", "cycle"])
def test_declaration_fallback_refuses_unbound_or_malformed_values(mutation: str) -> None:
    intervention = TypeAdapter(Intervention).validate_json(
        canonical_json(
            {
                "id": "native",
                "scope": {"target": "program"},
                "rationale": "Native declaration fixture",
                "kind": "state_carrier",
                "carrier": "recorded",
            }
        )
    )
    raw = intervention.model_dump(mode="json")
    if mutation == "identity":
        raw["id"] = "other"
    elif mutation == "parameter":
        raw["carrier"] = "other"
    elif mutation == "missing":
        del raw["version"]
    elif mutation == "malformed":
        raw["carrier"] = object()
    else:
        raw["cycle"] = raw
    cost = calculate_intervention_cost(intervention)
    assert evidence_details(cost, None, declaration=raw) == ({}, {}, {})
    assert describe_intervention(cost, None, declaration=raw)["previews"] == []


def test_declaration_fallback_never_borrows_an_unbound_certificate_trace() -> None:
    cost, certificate = _fixture(
        ClassicRecipeFamily.IMAGE_METADATA,
        {"link_time": 123},
        {
            "writes": [{"file_offset": 136, "before": 999, "after": 123}],
        },
    )
    raw, _, _ = evidence_details(cost, certificate)
    bad_certificate = certificate.model_copy(update={"intervention_id": "other"})
    assert evidence_details(cost, bad_certificate, declaration=raw) == (raw, {}, {})
    description = describe_intervention(cost, bad_certificate, declaration=raw)
    assert all(preview["title"] != "Metadata writes" for preview in _previews(description))


def test_native_fallback_previews_are_bounded_without_mutating_captured_declaration() -> None:
    intervention = TypeAdapter(Intervention).validate_json(
        canonical_json(
            {
                "id": "native",
                "scope": {"target": "program"},
                "rationale": "Native declaration fixture",
                "kind": "link_ordering",
                "item_ids": [f"object.{i}" for i in range(300)],
            }
        )
    )
    raw = intervention.model_dump(mode="json")
    description = describe_intervention(
        calculate_intervention_cost(intervention), None, declaration=raw
    )
    assert "truncated" in _previews(description)[0]["after"]
    assert len(_previews(description)[0]["after"]) < 2500
    assert len(raw["item_ids"]) == 300
    assert "the canonical JSON report" in json.dumps(description["detail"])
    assert "report.json" not in json.dumps(description)
