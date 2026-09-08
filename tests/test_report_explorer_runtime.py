from __future__ import annotations

from types import SimpleNamespace

from test_classic_mosaic_repair import _action, _donor, _receipt

from reprobit import classic_orchestration as orchestration
from reprobit.classic_orchestration import ClassicPreparedDonor, ClassicPreparedUnit
from reprobit.model import Digest
from reprobit.schema import ClassicTranslationUnitPlan


def test_display_capture_receives_each_immediate_preimage_without_changing_composition(
    monkeypatch,
) -> None:
    donor = _donor("donor.primary")
    first = _action({}).model_copy(update={"id": "first"})
    second = _action({}).model_copy(update={"id": "second"})
    prepared = ClassicPreparedDonor(
        donor, SimpleNamespace(logical_outputs={}, carrier_identifiers=frozenset())
    )
    unit = ClassicPreparedUnit(
        ClassicTranslationUnitPlan(
            id="unit.fixture",
            target_id="program",
            build_target="program",
            source="src/unit.cpp",
            source_digest=Digest.from_bytes(b"source"),
        ),
        (prepared,),
        (first, second),
        (),
        (first, second),
        (_receipt(first, b"body"), _receipt(second, b"body")),
    )
    monkeypatch.setattr(orchestration, "_require_classic_donor_semantic_material", lambda *_: None)
    monkeypatch.setattr(
        orchestration, "issue_classic_donor_semantics", lambda *_, **__: SimpleNamespace(proof=None)
    )

    def dispatch(_dispatcher, action, materials, *_args):
        output = materials.seed_object + action.id.encode()
        candidate = SimpleNamespace(
            output=output,
            evidence_digest=Digest.from_bytes(output),
            semantic_proof=None,
            semantic_input_statement={"action": action.id},
            semantic_output_statement={"bytes": len(output)},
        )
        return SimpleNamespace(candidate=candidate, provisional_repair=False)

    monkeypatch.setattr(orchestration.repair_dispatch, "dispatch_classic_action", dispatch)
    captures = []

    def capture(action, before, candidate):
        captures.append((action.id, before, candidate.output, candidate.semantic_input_statement))

    materials = {donor.id: SimpleNamespace(intervention=donor, donor_object=b"donor")}
    baseline = orchestration.compose_classic_unit(
        unit, seed_object=b"seed", donor_materials=materials, seed_source=b"source"
    )
    observed = orchestration.compose_classic_unit(
        unit,
        seed_object=b"seed",
        donor_materials=materials,
        seed_source=b"source",
        capture_function_change=capture,
    )
    assert captures == [
        ("first", b"seed", b"seedfirst", {"action": "first"}),
        ("second", b"seedfirst", b"seedfirstsecond", {"action": "second"}),
    ]
    assert observed == baseline
