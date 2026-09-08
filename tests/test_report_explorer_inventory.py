from __future__ import annotations

import pytest
from pydantic import ValidationError
from test_report import bundle, digest, proof_report

from reprobit.model import Verdict
from reprobit.report import Report
from reprobit.schema import (
    BuildPlanDocument,
    ClassicGroupOrderPlan,
    ClassicTargetGate,
    ClassicTranslationUnitPlan,
    InterventionDocument,
    ProjectBundle,
    SourceManifestDocument,
    SourceManifestEntry,
    source_manifest_digest,
)
from reprobit.strict_json import canonical_json


def _planned_bundle(*, reverse: bool = False) -> ProjectBundle:
    base = bundle()
    sources = {"src/first.cpp": b"void first() {}\n", "src/last.cpp": b"void last() {}\n"}
    manifest = SourceManifestDocument(
        schema_version=3,
        complete=True,
        entries=tuple(
            SourceManifestEntry(path=path, size=len(contents), digest=digest(contents))
            for path, contents in sources.items()
        ),
    )
    units: tuple[ClassicTranslationUnitPlan, ...] = (
        ClassicTranslationUnitPlan(
            id="first",
            target_id="program",
            build_target="support_library",
            source="src/first.cpp",
            source_digest=digest(sources["src/first.cpp"]),
        ),
        ClassicTranslationUnitPlan(
            id="last",
            target_id="program",
            build_target="program",
            source="src/last.cpp",
            source_digest=digest(sources["src/last.cpp"]),
            group_order=ClassicGroupOrderPlan(
                operation="restore_comdat_group_order", orders=(("one", "two"),)
            ),
        ),
    )
    if reverse:
        units = tuple(reversed(units))
    plan = BuildPlanDocument(
        schema_version=3,
        source_manifest_digest=source_manifest_digest(manifest),
        translation_units=units,
        source_overlay_digest=digest(b"no source overlay"),
        source_overlay_interventions=(),
        archives=(),
        target_gates=(ClassicTargetGate(target_id="program", build_target="program"),),
    )
    return ProjectBundle.model_validate(
        {
            **base.model_dump(),
            "root": base.root,
            "source_manifest": manifest,
            "build_plan": plan,
            "intervention_documents": (
                *base.intervention_documents,
                *(
                    InterventionDocument(
                        schema_version=3,
                        target_id=unit.target_id,
                        translation_unit_id=unit.id,
                        source=unit.source,
                        source_digest=unit.source_digest,
                        build_target=unit.build_target,
                    )
                    for unit in units
                ),
            ),
        }
    )


def _report(project: ProjectBundle) -> Report:
    proof = proof_report()
    return Report.from_bundle(
        project,
        Verdict(cold=True, byte_exact=True, logic_certified=True, toolchain_origin=True),
        evidence=proof.summary,
        proof=proof,
        target_results={"program": True},
        target_artifacts={"program": (100, digest(b"oracle"))},
    )


def test_source_inventory_includes_units_without_object_adjustments() -> None:
    report = _report(_planned_bundle())
    assert report.exploration["translation_units"] == [
        {
            "tu": "first",
            "target": "program",
            "source_path": "src/first.cpp",
            "source_digest": digest(b"void first() {}\n").model_dump(mode="json"),
            "build_target": "support_library",
        },
        {
            "tu": "last",
            "target": "program",
            "source_path": "src/last.cpp",
            "source_digest": digest(b"void last() {}\n").model_dump(mode="json"),
            "build_target": "program",
        },
    ]
    transforms = report.exploration["object_transforms"]
    assert isinstance(transforms, list) and len(transforms) == 1
    assert _report(_planned_bundle(reverse=True)).run_id == report.run_id
    assert Report.model_validate_json(canonical_json(report)) == report


def test_source_inventory_is_bound_to_the_saved_report() -> None:
    report = _report(_planned_bundle())
    payload = report.model_dump(exclude_computed_fields=True)
    payload["exploration"]["translation_units"][0]["source_path"] = "src/another.cpp"
    with pytest.raises(ValidationError, match="complete public payload"):
        Report.model_validate(payload)


def test_source_inventory_is_empty_without_a_reviewed_build_plan() -> None:
    assert _report(bundle()).exploration["translation_units"] == []
