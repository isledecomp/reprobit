"""Receipt-backed explanations and bounded previews for the build explorer.

This is a read-only view of report evidence. It never opens project files, replays
an intervention, or treats a digest as if it contained source or machine code.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256

from reprobit.classic.overlay_generator import render_classic_overlay_generator
from reprobit.classic_donors import (
    generate_declaration_shape,
    generate_extern_run,
    generate_forward_run,
    generate_pad_shape,
)
from reprobit.costs import InterventionCost, intervention_cost_row_digest
from reprobit.intervention_metadata import ClassicRecipeFamily
from reprobit.model import Certificate, Digest
from reprobit.strict_json import canonical_json

_TEXT_LIMIT = 2400
_TEXT_LINES = 48
_OMITTED = "Full evidence is available in the canonical JSON report."


@dataclass(frozen=True)
class _Mechanic:
    title: str
    stage: str
    summary: str
    steps: tuple[str, str, str]


_CARRIER_STEPS = (
    "Add unused declarations to a private copy of the source.",
    "Compile that copy; the extra names can change the compiler's choices.",
    "Make the compiled result available to the recorded dependent interventions.",
)
_BODY_STEPS = (
    "Compile a private source copy to obtain an alternative function body.",
    "Place the selected body in the original object file.",
    "Check its references and supporting records before linking.",
)
_REWRITE_STEPS = (
    "Start with the recorded compiler-produced function.",
    "Apply the listed instruction changes and check their meaning.",
    "Update affected references and records, then check the result.",
)

# Every family has an explicit description, including historical fallback names.
_CLASSIC: dict[ClassicRecipeFamily, _Mechanic] = {
    ClassicRecipeFamily.DECLARATION_SHAPE: _Mechanic(
        "Add unused class declarations",
        "compile",
        "Unused classes and inline members steer compiler choices without emitting code or data.",
        _CARRIER_STEPS,
    ),
    ClassicRecipeFamily.FORWARD_DECLARATION_RUN: _Mechanic(
        "Add a run of class names",
        "compile",
        "A numbered run of forward declarations changes the compiler's internal name order.",
        _CARRIER_STEPS,
    ),
    ClassicRecipeFamily.PAD_SHAPE: _Mechanic(
        "Add a grid of unused declarations",
        "compile",
        "A regular grid of unused classes and members steers the private compile.",
        _CARRIER_STEPS,
    ),
    ClassicRecipeFamily.EXTERN_RUN_PAIR: _Mechanic(
        "Add unused names at two source positions",
        "compile",
        "Unused extern declarations are inserted after the includes and at the source end.",
        _CARRIER_STEPS,
    ),
    ClassicRecipeFamily.FORWARD_RUN_WITH_SHAPE: _Mechanic(
        "Combine class names with unused members",
        "compile",
        "A class-name run and a generated declaration header steer the same private compile.",
        _CARRIER_STEPS,
    ),
    ClassicRecipeFamily.DECLARATION_RUN_TRIPLE: _Mechanic(
        "Add unused names at three source positions",
        "compile",
        "Class declarations are placed at the start, after includes, and at the end of the source.",
        _CARRIER_STEPS,
    ),
    ClassicRecipeFamily.PREFIX_FORWARD_AFTER_INCLUDES_EXTERN: _Mechanic(
        "Place declarations around the includes",
        "compile",
        "Class names at the source start and extern names after includes steer compilation.",
        _CARRIER_STEPS,
    ),
    ClassicRecipeFamily.DONOR_SOURCE_OVERLAY: _Mechanic(
        "Edit a private source copy",
        "source",
        "Recorded source edits create an alternative compile used by dependent interventions.",
        (
            "Locate each recorded edit in a private source copy.",
            "Render the declared additions, replacements, moves, or deletions.",
            "Compile the private copy for the recorded consumers.",
        ),
    ),
    ClassicRecipeFamily.SOURCE_OVERLAY_GRAPH: _Mechanic(
        "Apply source edits before the main build",
        "source",
        "Checked edits and generated files become inputs to the project's main compilation.",
        (
            "Match each edit to the recorded original source.",
            "Render the source changes and any generated compilation units.",
            "Check the resulting source and its declared compiler and linker uses.",
        ),
    ),
    ClassicRecipeFamily.EQUAL_BODY_STRICT: _Mechanic(
        "Select an alternative function body",
        "object",
        "A same-size function body from a private compile replaces the original selection.",
        _BODY_STEPS,
    ),
    ClassicRecipeFamily.EQUAL_BODY_EH_STRUCTURAL_LOCAL: _Mechanic(
        "Select a body with exception records",
        "object",
        "The alternative function is installed with matching exception-handling records.",
        _BODY_STEPS,
    ),
    ClassicRecipeFamily.SAME_SLOT_RESIZE: _Mechanic(
        "Resize a function within its reserved space",
        "object",
        "A different-size compiled function fits the same linked space; local offsets are updated.",
        _BODY_STEPS,
    ),
    ClassicRecipeFamily.EQUAL_BODY_EH_RELOC_LAYOUT: _Mechanic(
        "Move references with an alternative body",
        "object",
        "The selected function's references and exception records follow its instruction layout.",
        _BODY_STEPS,
    ),
    ClassicRecipeFamily.RETAIL_EXACT_RELOC_DIVERGENT: _Mechanic(
        "Rebuild the function's reference layout",
        "object",
        "A compiled replacement body uses a different arrangement of references to other symbols.",
        _BODY_STEPS,
    ),
    ClassicRecipeFamily.RETAIL_EXACT_DONOR_REWRITING: _Mechanic(
        "Rewrite instructions from a private compile",
        "object",
        "Checked changes to registers, instruction order, or operand forms reshape the function.",
        _REWRITE_STEPS,
    ),
    ClassicRecipeFamily.RETAIL_EXACT_INSTRUCTION_MOSAIC: _Mechanic(
        "Combine compiled instruction ranges",
        "object",
        "Selected complete instruction ranges from a private compile replace the recorded ranges.",
        (
            "Locate the original and privately compiled instruction ranges.",
            "Copy only the declared complete instructions into the function.",
            "Carry their references and supporting records, then check the assembled result.",
        ),
    ),
    ClassicRecipeFamily.RETAIL_EXACT_REGISTER_BIJECTION: _Mechanic(
        "Swap registers in a function region",
        "object",
        "Registers exchange roles in a bounded region while preserving the values the code uses.",
        _REWRITE_STEPS,
    ),
    ClassicRecipeFamily.RETAIL_EXACT_SOURCE_EQUAL_BODY: _Mechanic(
        "Select a body from a checked source refactor",
        "object",
        "A checked source refactor supplies the function together with its matching debug records.",
        _BODY_STEPS,
    ),
    ClassicRecipeFamily.RETAIL_EXACT_COMPOSED_REWRITING: _Mechanic(
        "Combine checked instruction rewrites",
        "object",
        "A recorded sequence of scheduling, register, and operand changes reshapes the function.",
        _REWRITE_STEPS,
    ),
    ClassicRecipeFamily.RETAIL_EXACT_SOURCE_TARGET_CLOSURE: _Mechanic(
        "Select a function and its required companions",
        "object",
        "A source-matched replacement carries the additional compiled records it requires.",
        _BODY_STEPS,
    ),
    ClassicRecipeFamily.RETAIL_EXACT_WEB_RECOLOUR: _Mechanic(
        "Change registers for selected values",
        "object",
        "Selected value lifetimes move between registers, with recorded instruction reorderings.",
        _REWRITE_STEPS,
    ),
    ClassicRecipeFamily.RETAIL_EXACT_CROSS_TU_COMPLETE_TARGET_RESIZE: _Mechanic(
        "Select a function from another source unit",
        "object",
        "A function compiled in another source unit supplies the replacement and required records.",
        _BODY_STEPS,
    ),
    ClassicRecipeFamily.RETAIL_EXACT_REGISTER_BIJECTION_REENCODING: _Mechanic(
        "Swap registers and resize their encodings",
        "object",
        "Register changes alter instruction lengths, so branches and references move with them.",
        _REWRITE_STEPS,
    ),
    ClassicRecipeFamily.RETAIL_EXACT_SAME_TU_INSTRUCTION_HYBRID_RESIZE: _Mechanic(
        "Combine instruction donors and resize",
        "object",
        "Complete instructions from another compile of the same source join a replacement body.",
        (
            "Compile the recorded source with each declared private setup.",
            "Combine the selected body with the listed donor instruction ranges.",
            "Resize the function and update its references and supporting records.",
        ),
    ),
    ClassicRecipeFamily.RETAIL_EXACT_SIMULATED_ELISION: _Mechanic(
        "Install recorded reference bytes",
        "reference",
        "This historical family is represented by an explicit reference-byte installation.",
        (
            "Identify the declared reference ranges.",
            "Install the allowlisted bytes.",
            "Disclose their reference origin and affected output ranges.",
        ),
    ),
    ClassicRecipeFamily.ARCHIVE_ADMISSION: _Mechanic(
        "Admit a compiled object to the link",
        "link",
        "The recorded object or archive member becomes available to the linker.",
        (
            "Identify the compiled object and its permitted symbols.",
            "Add it at the declared link position.",
            "Check which definitions the link selects.",
        ),
    ),
    ClassicRecipeFamily.IMAGE_METADATA: _Mechanic(
        "Set image timestamps",
        "image",
        "Recorded timestamp fields in the executable image are set to their declared values.",
        (
            "Locate the declared image metadata fields.",
            "Write the recorded timestamp values.",
            "Check the changed fields and the remaining image bytes.",
        ),
    ),
    ClassicRecipeFamily.IMAGE_LINK_ORDER: _Mechanic(
        "Reorder imported functions",
        "image",
        "Import slots are reordered and code references are updated to their new locations.",
        (
            "Locate the image's imported functions.",
            "Place them in the recorded order.",
            "Update affected call operands and check the resulting image.",
        ),
    ),
    ClassicRecipeFamily.IMAGE_BINARY_REPACK: _Mechanic(
        "Repack binary data",
        "image",
        "Existing binary data moves to the recorded layout, with its references updated.",
        (
            "Locate the declared data and padding.",
            "Move the existing bytes into the new layout.",
            "Update symbols or references and check the result.",
        ),
    ),
}

_GENERIC: dict[str, _Mechanic] = {
    "state_carrier": _Mechanic(
        "Adjust compiler state",
        "compile",
        "The recorded carrier influences compiler choices.",
        _CARRIER_STEPS,
    ),
    "generated_supplier": _Mechanic(
        "Compile a generated supplier",
        "compile",
        "Generated source supplies declared definitions to the build.",
        (
            "Render the recorded supplier.",
            "Compile its definitions.",
            "Use the permitted definitions in the build.",
        ),
    ),
    "metadata_normalization": _Mechanic(
        "Set a metadata field",
        "image",
        "A declared metadata field is set to a stable recorded value.",
        (
            "Locate the declared field.",
            "Write its recorded value.",
            "Check the field and the surrounding bytes.",
        ),
    ),
    "link_ordering": _Mechanic(
        "Set linker input order",
        "link",
        "The linker receives inputs in the declared order.",
        (
            "Identify the selected link inputs.",
            "Arrange them in the recorded order.",
            "Link and check the resulting selections and layout.",
        ),
    ),
    "equal_body_donor": _Mechanic(
        "Select an alternative function body",
        "object",
        "A same-size compiled donor supplies the selected function.",
        _BODY_STEPS,
    ),
    "structural_donor": _Mechanic(
        "Select a body and supporting records",
        "object",
        "A compiled donor replaces the function and its required structural records.",
        _BODY_STEPS,
    ),
    "cross_tu_donor": _Mechanic(
        "Select a body from another source unit",
        "object",
        "Another compilation unit supplies the selected function.",
        _BODY_STEPS,
    ),
    "semantic_rewrite": _Mechanic(
        "Apply checked instruction changes",
        "object",
        "The declared rewrite changes machine instructions with a check of their meaning.",
        _REWRITE_STEPS,
    ),
    "binary_surgery": _Mechanic(
        "Assemble or repack binary ranges",
        "object",
        "The declared binary operation selects or rearranges recorded compiled material.",
        (
            "Locate the recorded input artifacts.",
            "Apply the declared range operation.",
            "Check the resulting bytes and their origin.",
        ),
    ),
    "legacy.oracle_install": _Mechanic(
        "Install reference bytes",
        "reference",
        "Allowlisted bytes are copied from the reference binary and disclosed in the report.",
        (
            "Locate the declared reference and output ranges.",
            "Copy the allowed reference bytes.",
            "Record their reference origin and quarantine the affected output.",
        ),
    ),
}

_OVERLAY_CARRIERS: dict[str, tuple[ClassicRecipeFamily, str, str]] = {
    "force_included_shape_v1": (
        ClassicRecipeFamily.DECLARATION_SHAPE,
        "force_include_v1",
        "A generated header is included before compiling the private source.",
    ),
    "force_included_pad_shape_v1": (
        ClassicRecipeFamily.PAD_SHAPE,
        "force_include_v1",
        "A generated header is included before compiling the private source.",
    ),
    "extern_run_pair_v1": (
        ClassicRecipeFamily.EXTERN_RUN_PAIR,
        "after_includes_and_eof_v1",
        "Fragments go after the includes and at the end of the private source, in that order.",
    ),
    "declaration_run_triple_v1": (
        ClassicRecipeFamily.DECLARATION_RUN_TRIPLE,
        "start_after_includes_and_eof_v1",
        "Fragments go at the start, after the includes, and at the end of the private source.",
    ),
}


def _mapping(value: object) -> dict[str, object]:
    return {str(k): v for k, v in value.items()} if isinstance(value, dict) else {}


def _rows(value: object) -> list[dict[str, object]]:
    return (
        [_mapping(row) for row in value if isinstance(row, dict)] if isinstance(value, list) else []
    )


def evidence_details(
    cost: InterventionCost,
    certificate: Certificate | None,
    *,
    declaration: object | None = None,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    """Return bound declarations, keeping declaration-only context separate from proofs.

    A captured declaration may fill a report's missing operation parameters. It
    must match the complete authority digest in the cost ledger, and it cannot
    supply or borrow a semantic execution trace.
    """
    if certificate is not None and (
        certificate.intervention_id == cost.intervention_id
        and certificate.intervention_authority_digest == cost.intervention_authority_digest
        and certificate.intervention_cost_digest == intervention_cost_row_digest(cost)
    ):
        for proof in certificate.semantic_proofs:
            statement = _mapping(proof.input_statement)
            recorded = _bound_declaration(cost, statement.get("intervention"))
            if recorded:
                return recorded, statement, _mapping(proof.output_statement)
    return _bound_declaration(cost, declaration), {}, {}


def _bound_declaration(cost: InterventionCost, value: object) -> dict[str, object]:
    if not isinstance(value, dict) or value.get("id") != cost.intervention_id:
        return {}
    if value.get("kind") != cost.kind or value.get("family") != cost.family:
        return {}
    try:
        binding = Digest.from_bytes(
            canonical_json(
                {
                    "schema": "reprobit-intervention-authority-v1",
                    "intervention": value,
                }
            )
        )
    except (ValueError, TypeError, RecursionError):
        return {}
    return _mapping(value) if binding == cost.intervention_authority_digest else {}


def _bounded_text(value: str) -> str:
    lines = value.splitlines(keepends=True)
    shortened = "".join(lines[:_TEXT_LINES])[:_TEXT_LIMIT]
    if len(shortened) < len(value):
        return shortened.rstrip() + f"\n… preview truncated ({len(value):,} characters total)."
    return value


def _compact(value: object, *, depth: int = 0, budget: list[int] | None = None) -> object:
    """Keep a useful evidence excerpt without recursively duplicating consumer proofs."""
    if budget is None:
        budget = [1200]
    budget[0] -= 1
    if depth > 8 or budget[0] < 0:
        return "… evidence excerpt truncated; see the canonical JSON report"
    if isinstance(value, dict):
        result: dict[str, object] = {}
        omitted = 0
        for key, item in value.items():
            if key in {
                "proof",
                "downstream_uses",
                "primary_source_seal",
                "clean_manifest",
                "compiler_identity",
                "overlay_intervention",
            }:
                omitted += 1
                continue
            if len(result) >= 40 or budget[0] < 0:
                omitted += 1
                continue
            result[str(key)] = _compact(item, depth=depth + 1, budget=budget)
        if omitted:
            result["_omitted_fields"] = f"{omitted} fields; see the canonical JSON report"
        return result
    if isinstance(value, list):
        values = [_compact(item, depth=depth + 1, budget=budget) for item in value[:24]]
        if len(value) > 24:
            values.append(f"… {len(value) - 24} more entries; see the canonical JSON report")
        return values
    if isinstance(value, str):
        return _bounded_text(value)
    return value


def _display(value: object) -> str:
    if isinstance(value, str):
        return _bounded_text(value)
    return _bounded_text(json.dumps(_compact(value), ensure_ascii=False, indent=2))


def _preview(title: str, before: str, after: str, note: str = "") -> dict[str, str]:
    return {
        "title": title,
        "before": _bounded_text(before),
        "after": _bounded_text(after),
        "note": note,
    }


def _integer(parameters: dict[str, object], key: str) -> int:
    value = parameters[key]
    if type(value) is not int:
        raise ValueError(f"{key} is not an integer")
    return value


def _declarations(family: ClassicRecipeFamily | None, p: dict[str, object]) -> bytes | None:
    """Use the compiler's pure renderers; reproduce their declared concatenation order."""
    if family is ClassicRecipeFamily.DONOR_SOURCE_OVERLAY:
        carrier = _mapping(p.get("compiler_state_carrier"))
        specification = _OVERLAY_CARRIERS.get(str(carrier.get("kind")))
        if specification is None or carrier.get("placement") != specification[1]:
            return None
        return _declarations(specification[0], carrier)
    if family is ClassicRecipeFamily.DECLARATION_SHAPE:
        return generate_declaration_shape(_integer(p, "classes"), _integer(p, "functions"))
    if family is ClassicRecipeFamily.PAD_SHAPE:
        return generate_pad_shape(_integer(p, "classes"), _integer(p, "functions_per_class"))
    if family in {
        ClassicRecipeFamily.FORWARD_DECLARATION_RUN,
        ClassicRecipeFamily.FORWARD_RUN_WITH_SHAPE,
    }:
        result = generate_forward_run(str(p["prefix"]), _integer(p, "count"), _integer(p, "width"))
        if family is ClassicRecipeFamily.FORWARD_RUN_WITH_SHAPE:
            result += generate_declaration_shape(_integer(p, "classes"), _integer(p, "functions"))
        return result
    if family in {ClassicRecipeFamily.EXTERN_RUN_PAIR, ClassicRecipeFamily.DECLARATION_RUN_TRIPLE}:
        extern = family is ClassicRecipeFamily.EXTERN_RUN_PAIR
        seats = ("header", "seat") if extern else ("pre", "post", "eof")
        generate = generate_extern_run if extern else generate_forward_run
        return b"".join(
            generate(str(p[f"{seat}_prefix"]), _integer(p, f"{seat}_count"), _integer(p, "width"))
            for seat in seats
            if _integer(p, f"{seat}_count")
        )
    if family is ClassicRecipeFamily.PREFIX_FORWARD_AFTER_INCLUDES_EXTERN:
        return generate_forward_run(
            str(p["forward_prefix"]), _integer(p, "forward_count"), _integer(p, "forward_width")
        ) + generate_extern_run(
            str(p["extern_prefix"]), _integer(p, "extern_count"), _integer(p, "extern_width")
        )
    return None


def _source_paths(parameters: dict[str, object], statement: dict[str, object]) -> list[str]:
    paths: set[str] = set()

    # Only declared source fields and compiler input receipts; avoid toolchain headers
    # and every file in the project's otherwise unrelated clean-source manifest.
    def visit(value: object, depth: int = 0) -> None:
        if depth > 10:
            return
        if isinstance(value, dict):
            for key, item in value.items():
                if (
                    key in {"path", "donor_source", "translation_unit", "source_path"}
                    and isinstance(item, str)
                    and item.lower().endswith(
                        (".c", ".cpp", ".cxx", ".cc", ".h", ".hpp", ".inl", ".inc")
                    )
                ):
                    paths.add(item)
                visit(item, depth + 1)
        elif isinstance(value, list):
            for item in value:
                visit(item, depth + 1)

    visit(parameters)
    compiler = _mapping(statement.get("compiler_statement"))
    receipt = _mapping(compiler.get("request_receipt"))
    for key in _mapping(receipt.get("input_digests")):
        if key.startswith(("clean:", "effective:")):
            paths.add(key.split(":", 1)[1])
    return sorted(paths)


def _generator_is_bounded(value: object, depth: int = 0) -> bool:
    if depth > 16:
        return False
    if isinstance(value, dict):
        for key, item in value.items():
            if (
                key in {"lines", "count", "width", "extent"}
                and isinstance(item, int)
                and item > 10000
            ):
                return False
            if not _generator_is_bounded(item, depth + 1):
                return False
    elif isinstance(value, list):
        return len(value) <= 1000 and all(_generator_is_bounded(v, depth + 1) for v in value)
    elif isinstance(value, str):
        return len(value) <= 100000
    return True


def _overlay_previews(
    p: dict[str, object],
    output_statement: dict[str, object],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    previews: list[dict[str, str]] = []
    facts: list[dict[str, str]] = []
    outputs = _rows(p.get("outputs")) + _rows(p.get("renderings"))
    operations = [
        (str(output.get("path", "source")), ordinal, operation)
        for output in outputs
        for ordinal, operation in enumerate(_rows(output.get("ops", output.get("operations"))))
    ]
    if not operations:
        return previews, facts
    counts = Counter(str(op.get("op", "edit")) for _, _, op in operations)
    facts.append(
        {
            "label": "Source operations",
            "value": ", ".join(f"{count} {name}" for name, count in sorted(counts.items())),
        }
    )
    facts.append({"label": "Edited files", "value": str(len(outputs))})
    generators = Counter(
        str(_mapping(op.get("gen")).get("k", "source range")) for _, _, op in operations
    )
    facts.append(
        {
            "label": "Rendered forms",
            "value": ", ".join(f"{count} {name}" for name, count in sorted(generators.items())),
        }
    )
    epoch = _mapping(output_statement.get("project_overlay_epoch"))
    validation = _mapping(epoch.get("source_validation"))
    receipts = {
        (str(receipt.get("path")), str(operation.get("operation_id"))): operation
        for receipt in _rows(validation.get("render_receipts"))
        for operation in _rows(receipt.get("operations"))
    }
    # Preserve the complete action inventory and declaration order. The browser
    # paginates it; only individual text excerpts are bounded here.
    for index, (path, ordinal, op) in enumerate(operations, 1):
        operation = str(op.get("op", "edit"))
        operation_id = str(op.get("id", f"{path}#{ordinal}"))
        receipt = receipts.get((path, operation_id), {})
        generator = _mapping(op.get("gen"))
        before = "Original source text is not stored in this receipt."
        after = ""
        note = "Recorded operation; this preview is a fragment, not a complete source diff."
        if operation in {"insert", "append", "prepend"}:
            before = "No inserted fragment."
        if generator and _generator_is_bounded(generator):
            try:
                rendered = render_classic_overlay_generator(generator)
                after = rendered.decode("utf-8", errors="replace")
                note = "Fragment rendered by the built-in generator from recorded parameters."
                recorded_digest = receipt.get("fragment_digest")
                if isinstance(recorded_digest, str):
                    if sha256(rendered).hexdigest() == recorded_digest:
                        note += " SHA-256 matches the recorded fragment bytes."
                    else:
                        after = _display(generator)
                        note = (
                            "Current generator output differs from the recorded fragment digest; "
                            "recorded parameters are shown."
                        )
            except (ValueError, KeyError, TypeError, OverflowError):
                after = _display(generator)
                note = "Recorded generator parameters; the source fragment could not be rendered."
        elif generator:
            after = _display(generator)
            note = "Generator exceeds the preview limit; recorded parameters shown."
        elif operation == "delete":
            after = "Fragment removed."
        else:
            after = _display({key: value for key, value in op.items() if key != "id"})
        removed = _mapping(op.get("removed"))
        if removed.get("size") is not None:
            before = f"{removed['size']} original bytes (text not stored in this receipt)."
        if operation == "delete":
            after = "Fragment removed."
            note = (
                "The original fragment is removed; its source text is not stored in this receipt."
            )
        elif operation == "replace":
            note += " The original fragment's text is not stored in this receipt."
        anchor = _mapping(op.get("anchor", op.get("from")))
        anchors = _rows(receipt.get("anchors"))
        if anchors:
            note += (
                " Recorded source positions: "
                + "; ".join(
                    f"{item.get('role')} byte {_offset(item.get('byte_offset'))} "
                    f"(token boundary {item.get('token_boundary')})"
                    for item in anchors
                )
                + "."
            )
        elif anchor:
            position = str(anchor.get("at", "after_newline")).replace("_", " ")
            note += f" Position: {position}, matched by recorded source context."
        elif operation == "append":
            note += " Position: end of the file."
        preview = _preview(f"{index}. {operation.capitalize()} · {path}", before, after, note)
        preview.update(
            {
                "source_path": path,
                "action_index": str(index),
                "action_id": operation_id,
                "operation": operation,
            }
        )
        previews.append(preview)
    return previews, facts


def _offset(value: object) -> str:
    return f"+0x{value:x}" if isinstance(value, int) else str(value)


def _timestamp(value: int | None) -> str:
    if value is None:
        return "Timestamp not recorded."
    # PE reserves both values: neither is a meaningful date (PE/COFF specification).
    if value in {0, 0xFFFFFFFF}:
        return f"No meaningful timestamp ({value:#x})."
    return datetime.fromtimestamp(value, tz=UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def _timestamp_changes(
    parameters: dict[str, object], trace: dict[str, object]
) -> tuple[str | None, list[dict[str, str]], list[dict[str, str]]]:
    """Interpret only the closed PE timestamp trace, grouping equal transitions."""
    if trace.get("schema") != "pe32_timestamp_normalization_v1":
        return None, [], []
    writes = _rows(trace.get("writes"))
    positions = [row.get("file_offset") for row in writes]
    if not writes or any(type(offset) is not int or offset < 0 for offset in positions):
        return None, [], []
    if len(set(positions)) != len(positions):
        return None, [], []

    def value(raw: object) -> int | None:
        return raw if type(raw) is int and 0 <= raw <= 0xFFFFFFFF else None

    transitions = Counter((value(row.get("before")), value(row.get("after"))) for row in writes)
    changed = sum(
        count
        for (before, after), count in transitions.items()
        if before is not None and after is not None and before != after
    )
    unknown = sum(
        count for (before, after), count in transitions.items() if before is None or after is None
    )
    unchanged = len(writes) - changed - unknown
    noun = "field" if len(writes) == 1 else "fields"
    if unknown:
        summary = (
            f"{len(writes)} timestamp {noun} written; "
            "some original or resulting values are not recorded."
        )
    elif not changed:
        summary = f"{len(writes)} timestamp {noun} already held the declared values."
    else:
        changed_noun = "field" if changed == 1 else "fields"
        summary = f"{changed} timestamp {changed_noun} updated."
        if unchanged:
            summary += f" {unchanged} already held the declared values."
    previews = []
    for (before, after), count in transitions.items():
        label = "Timestamp"
        link, resource = value(parameters.get("link_time")), value(parameters.get("resource_time"))
        if link != resource:
            if after is not None and after == link:
                label = "Link timestamp"
            elif after is not None and after == resource:
                label = "Resource timestamp"
        preview = _preview(
            f"{label} · {count} {'field' if count == 1 else 'fields'}",
            _timestamp(before),
            _timestamp(after),
            "Dates show the recorded field values in UTC. "
            "Exact file positions and numeric values are in the metadata write details.",
        )
        preview["presentation"] = "primary"
        previews.append(preview)
    facts = [{"label": "Timestamp fields", "value": str(len(writes))}]
    if not unknown:
        facts.append({"label": "Timestamp fields updated", "value": str(changed)})
    return summary, previews, facts


def _trace_previews(
    p: dict[str, object],
    trace: dict[str, object],
) -> list[dict[str, str]]:
    previews: list[dict[str, str]] = []
    writes = _rows(trace.get("writes"))
    if writes:

        def write_side(key: str) -> str:
            return "\n".join(
                f"file {_offset(row.get('file_offset'))}  {row.get(key)}" for row in writes[:32]
            )

        preview = _preview(
            "Metadata writes",
            write_side("before"),
            write_side("after"),
            f"File offsets; {len(writes)} writes recorded. "
            + (f"Showing 32. {_OMITTED}" if len(writes) > 32 else ""),
        )
        preview["presentation"] = "technical"
        previews.append(preview)
    if "seed_length" in trace and "donor_length" in trace:
        previews.append(
            _preview(
                "Function size",
                f"{trace['seed_length']} bytes",
                f"{trace['donor_length']} bytes",
                "Function body sizes; linked space may include padding.",
            )
        )
    mapping = _mapping(trace.get("register_bijection"))
    if not mapping:
        mapping = _mapping(_mapping(p.get("register_bijection")).get("mapping"))
    if mapping:
        previews.append(
            _preview(
                "Register roles",
                "\n".join(mapping),
                "\n".join(str(v) for v in mapping.values()),
                "Corresponding rows show the recorded register substitution.",
            )
        )
    for region in _rows(trace.get("register_bijections")):
        mapping = _mapping(region.get("mapping"))
        bounds = region.get("region")
        location = ""
        if isinstance(bounds, list) and len(bounds) == 2:
            location = f" · {_offset(bounds[0])} to {_offset(bounds[1])}"
        previews.append(
            _preview(
                "Register roles" + location,
                "\n".join(mapping),
                "\n".join(str(value) for value in mapping.values()),
                "Corresponding rows show register substitutions within the function region.",
            )
        )
    for mapping_row in _rows(trace.get("slot_bijections")):
        mapping = _mapping(mapping_row.get("mapping"))
        previews.append(
            _preview(
                "Stack locations",
                "\n".join(mapping),
                "\n".join(str(value) for value in mapping.values()),
                "Corresponding stack offsets exchange roles; these are not image addresses.",
            )
        )
    regions = _rows(trace.get("register_bijection_reencoding"))
    if not regions:
        regions = _rows(_mapping(p.get("register_bijection_reencoding")).get("regions"))
    for region in regions:
        mapping = _mapping(region.get("mapping"))
        previews.append(
            _preview(
                f"Register roles · {_offset(region.get('start'))} to {_offset(region.get('end'))}",
                "\n".join(mapping),
                "\n".join(str(v) for v in mapping.values()),
                "Function-relative range; instruction lengths may change.",
            )
        )
    webs = _rows(_mapping(p.get("web_recolour")).get("webs"))
    if webs:
        previews.append(
            _preview(
                "Registers for selected values",
                "\n".join(
                    f"{row.get('source_register')} at {_display(row.get('definitions'))}"
                    for row in webs[:16]
                ),
                "\n".join(
                    f"{row.get('image_register')} at {_display(row.get('definitions'))}"
                    for row in webs[:16]
                ),
                f"Function-relative definition offsets; {len(webs)} substitutions recorded.",
            )
        )
    schedules = _rows(trace.get("instruction_schedule")) + _rows(
        trace.get("simulated_region_rewrites")
    )
    for region in schedules:
        order = region.get("target_order")
        if not isinstance(order, list):
            continue
        start = region.get("start", region.get("region_start"))
        end = region.get("end", region.get("region_end"))
        previews.append(
            _preview(
                f"Instruction order · {_offset(start)} to {_offset(end)}",
                " → ".join(str(i) for i in range(len(order))),
                " → ".join(str(i) for i in order),
                "Numbers identify original instruction positions, starting at 0. "
                "Offsets are within the function.",
            )
        )
    for region in _rows(trace.get("fp_sum_reassociation")):
        order = region.get("order")
        if isinstance(order, list):
            previews.append(
                _preview(
                    f"Floating-point sum order · {_offset(region.get('chain_start'))}",
                    " → ".join(str(index) for index in range(len(order))),
                    " → ".join(str(index) for index in order),
                    "Numbers identify the original addend pairs, starting at 0. "
                    "The receipt records the checks for this particular rearrangement.",
                )
            )
    for key, label in (
        ("fp_pointer_exchanges", "Floating-point pointer exchanges"),
        ("x87_squared_addend_exchanges", "Squared addend exchanges"),
        ("commutative_operand_forms", "Operand order changes"),
        ("esp_argument_exchanges", "Stack argument exchanges"),
    ):
        for index, row in enumerate(_rows(trace.get(key)), 1):
            previews.append(
                _preview(
                    f"{label} · {index}",
                    "",
                    _display(row),
                    "Recorded operand changes and their function-relative instruction positions.",
                )
            )
    growth = trace.get("growth")
    if isinstance(growth, list) and growth:
        size_rows = [row for row in growth if isinstance(row, list) and len(row) == 4]
        previews.append(
            _preview(
                "Instruction size changes",
                "\n".join(f"{_offset(row[0])}: {row[2]} bytes" for row in size_rows),
                "\n".join(f"{_offset(row[1])}: {row[3]} bytes" for row in size_rows),
                "Original and resulting instruction positions and sizes, within the function.",
            )
        )
    relational = _rows(trace.get("relational_form"))
    if relational:
        previews.append(
            _preview(
                "Comparison encodings",
                "\n".join(
                    f"{_offset(r.get('compare_offset'))}: opcode {r.get('seed_compare_opcode')}, "
                    f"branch {r.get('seed_condition')}"
                    for r in relational
                ),
                "\n".join(
                    f"{_offset(r.get('compare_offset'))}: opcode {r.get('image_compare_opcode')}, "
                    f"branch {r.get('image_condition')}"
                    for r in relational
                ),
                "Recorded opcode values and branch conditions; offsets are within the function.",
            )
        )
    ranges = _rows(trace.get("instruction_ranges", p.get("instruction_ranges")))
    if ranges:
        instruction_donor = p.get("instruction_donor")
        if not isinstance(instruction_donor, str):
            instruction_donor = "compiled donor"
        previews.append(
            _preview(
                "Selected instruction ranges",
                "\n".join(
                    f"{_offset(r.get('start', r.get('target_start')))} to "
                    f"{_offset(r.get('end', r.get('target_end')))}"
                    for r in ranges
                ),
                "\n".join(
                    f"{r.get('donor', instruction_donor)}: "
                    f"{_offset(r.get('instruction_donor_start', r.get('start')))} to "
                    f"{_offset(r.get('instruction_donor_end', r.get('end')))}"
                    for r in ranges
                ),
                "Whole instruction selections at function-relative offsets. "
                "Machine-code bytes are not stored here.",
            )
        )
    for key in ("relocation_moves", "relocation_reseat"):
        moves = trace.get(key)
        if isinstance(moves, list) and moves:
            pairs = [r for r in moves if isinstance(r, list) and len(r) >= 2]
            previews.append(
                _preview(
                    "Reference positions",
                    "\n".join(_offset(r[0]) for r in pairs),
                    "\n".join(_offset(r[1]) for r in pairs),
                    "Old and new function-relative offsets of references to other symbols.",
                )
            )
    pool = _mapping(p.get("rdata_pool_repack"))
    permutation = _rows(pool.get("permutation"))
    if permutation:

        def pool_side(key: str) -> str:
            return "\n".join(
                f"{r.get('symbol')}  {_offset(r.get(key))}  ({r.get('size')} bytes)"
                for r in permutation
            )

        previews.append(
            _preview(
                "Constant pool layout",
                pool_side("old_offset"),
                pool_side("new_offset"),
                "Offsets within the object's data section; existing constants are moved.",
            )
        )
    text_repack = _mapping(p.get("text_repack"))
    for index, piece in enumerate(_rows(text_repack.get("pieces")), 1):
        try:
            low = int(str(piece.get("src_lo")), 0)
            high = int(str(piece.get("src_hi")), 0)
            shift = _integer(piece, "shift")
        except (ValueError, KeyError, TypeError):
            continue
        previews.append(
            _preview(
                f"Executable code range · {index}",
                f"0x{low:x} to 0x{high:x}",
                f"0x{low - shift:x} to 0x{high - shift:x}",
                f"Virtual addresses, end excluded; existing code moves {shift} bytes earlier. "
                "References are updated to follow it.",
            )
        )
    imports = _rows(_mapping(p.get("import_order")).get("imports"))
    if imports:
        names = []
        for item in imports:
            order = _rows(item.get("order"))
            names.append(
                str(item.get("dll"))
                + "\n"
                + " → ".join(
                    ("#" if r.get("kind") == "ordinal" else "") + str(r.get("value")) for r in order
                )
            )
        previews.append(
            _preview(
                "Declared import order",
                "Original import order is not stored in this receipt.",
                "\n\n".join(names),
                "Each library lists the target order of its named or numbered imports.",
            )
        )
    return previews


def _generic_previews(
    kind: str,
    declaration: dict[str, object],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Expose native operation parameters without implying an absent semantic trace."""
    previews: list[dict[str, str]] = []
    facts: list[dict[str, str]] = []
    for key, label in (
        ("carrier", "Compiler carrier"),
        ("supplier", "Generated supplier"),
        ("donor_artifact", "Compiled donor"),
        ("donor_symbol", "Selected donor function"),
        ("donor_translation_unit", "Donor source unit"),
        ("source_artifact", "Rewrite input"),
        ("expected_size", "Expected function bytes"),
        ("oracle_target", "Reference target"),
        ("byte_count", "Reference bytes installed"),
        ("maximum_oracle_payload_bytes", "Maximum allowed reference bytes"),
    ):
        if key in declaration:
            facts.append({"label": label, "value": _display(declaration[key])})
    method = declaration.get("method", declaration.get("mode"))
    if isinstance(method, str):
        facts.append({"label": "Operation", "value": method.replace("_", " ")})
    if kind in {"state_carrier", "generated_supplier"}:
        key = "carrier" if kind == "state_carrier" else "supplier"
        previews.append(
            _preview(
                "Compiler carrier" if key == "carrier" else "Generated supplier",
                "",
                _display(declaration.get(key)),
                "Recorded build input identifier. "
                "Its generated source text is not in this declaration.",
            )
        )
    elif kind == "metadata_normalization":
        previews.append(
            _preview(
                f"Metadata field · {declaration.get('field')}",
                "The original field value is not stored in this declaration.",
                _display(declaration.get("value")),
                "The recorded value to write to this field.",
            )
        )
    elif kind == "link_ordering":
        items = declaration.get("item_ids")
        if isinstance(items, list):
            previews.append(
                _preview(
                    "Linker input order",
                    "The original input order is not stored in this declaration.",
                    "\n".join(f"{index}. {item}" for index, item in enumerate(items, 1)),
                    "The linker receives these build inputs in the recorded sequence.",
                )
            )
    elif kind in {"equal_body_donor", "structural_donor", "cross_tu_donor"}:
        selections = [
            f"Function: {declaration.get('donor_symbol')}",
            f"Compiled input: {declaration.get('donor_artifact')}",
        ]
        if kind == "cross_tu_donor":
            selections.append(f"Source unit: {declaration.get('donor_translation_unit')}")
        if "expected_size" in declaration:
            selections.append(f"Expected body: {declaration['expected_size']} bytes")
        if isinstance(method, str):
            selections.append(f"Supporting operation: {method.replace('_', ' ')}")
        previews.append(
            _preview(
                "Function selection",
                "The original function bytes are not stored in this declaration.",
                "\n".join(selections),
                "Recorded donor selection. "
                "The compiled function bytes are held in the donor artifact.",
            )
        )
    elif kind == "semantic_rewrite":
        previews.append(
            _preview(
                "Instruction rewrite",
                f"Compiled input: {declaration.get('source_artifact')}",
                str(method).replace("_", " "),
                "Recorded rewrite method. Instruction substitutions require the execution trace; "
                "the declaration carries a digest of the rewrite.",
            )
        )
    elif kind == "binary_surgery":
        inputs = declaration.get("source_artifacts")
        if isinstance(inputs, list):
            previews.append(
                _preview(
                    "Binary operation inputs",
                    "\n".join(str(v) for v in inputs),
                    str(method).replace("_", " "),
                    "Recorded compiled inputs and operation. "
                    "Exact edited ranges require the execution trace.",
                )
            )
    elif kind == "legacy.oracle_install":
        address = declaration.get("oracle_address")
        if isinstance(address, int):
            facts.append({"label": "Reference function address", "value": f"0x{address:x}"})
        for index, row in enumerate(_rows(declaration.get("ranges")), 1):
            preimage = _mapping(row.get("preimage_range"))
            installed = _mapping(row.get("output_range"))
            reference = _mapping(row.get("oracle_range"))
            previews.append(
                _preview(
                    f"Reference-byte installation · {index}",
                    f"Candidate {_offset(preimage.get('offset'))}: {preimage.get('length')} bytes",
                    f"Output {_offset(installed.get('offset'))}: {installed.get('length')} bytes\n"
                    f"Copied from reference {_offset(reference.get('offset'))}: "
                    f"{reference.get('length')} bytes",
                    "Recorded offsets in the candidate, output, and reference function bodies. "
                    "These copied bytes retain their disclosed reference origin.",
                )
            )
    return previews, facts


def describe_intervention(
    cost: InterventionCost,
    certificate: Certificate | None,
    *,
    declaration: object | None = None,
) -> dict[str, object]:
    """Explain an intervention using only its bound, recorded semantic evidence."""
    fallback = _Mechanic(
        "Recorded build intervention",
        "object",
        "The cost ledger records this build operation; its family has no specialized preview.",
        ("Identify the recorded inputs.", "Apply the declared operation.", "Check the output."),
    )
    mechanic = (
        _CLASSIC.get(cost.family, fallback) if cost.family else _GENERIC.get(cost.kind, fallback)
    )
    declaration, statement, output = evidence_details(cost, certificate, declaration=declaration)
    parameters = {
        str(row["name"]): row.get("value")
        for row in _rows(declaration.get("parameters"))
        if "name" in row
    }
    trace = _mapping(output.get("validator_trace"))
    previews: list[dict[str, str]] = []
    facts: list[dict[str, str]] = []
    if not declaration:
        facts.append(
            {"label": "Evidence", "value": "Detailed mechanics are not recorded in this report."}
        )
    else:
        facts.append(
            {"label": "Evidence", "value": "Recorded declaration matches this cost entry."}
        )
        if not statement:
            facts.append(
                {
                    "label": "Execution trace",
                    "value": "The declaration is available; a detailed trace is not recorded.",
                }
            )
    dependencies = declaration.get("dependencies", [])
    stage = mechanic.stage
    title = mechanic.title
    summary = mechanic.summary
    if parameters.get("rdata_pool_repack"):
        stage = "object"
        title = "Reorder compiled constants"
        summary = "Constants are reordered inside a compiled object's data section before linking."
    elif parameters.get("text_repack"):
        title = "Move executable code ranges"
        summary = "Existing code moves to earlier image addresses and its references follow it."
    for key, label in (
        ("placement", "Declaration placement"),
        ("classes", "Generated classes"),
        ("functions", "Unused members"),
        ("count", "Generated declarations"),
        ("functions_per_class", "Unused members per class"),
    ):
        if key in parameters:
            facts.append({"label": label, "value": str(parameters[key]).replace("_", " ")})
    try:
        generated = _declarations(cost.family, parameters)
    except (ValueError, KeyError, TypeError, OverflowError):
        generated = None
    if generated is not None:
        carrier = (
            _mapping(parameters.get("compiler_state_carrier"))
            if cost.family is ClassicRecipeFamily.DONOR_SOURCE_OVERLAY
            else {}
        )
        expected = (
            carrier.get("generated_declarations_sha256")
            if carrier
            else parameters.get("generated_header_sha256")
        )
        if expected == sha256(generated).hexdigest():
            placement = (
                _OVERLAY_CARRIERS[str(carrier["kind"])][2]
                + " Included in the existing donor charge; there is no extra charge."
                if carrier
                else "Fragments at separate source positions are concatenated in declaration order."
            )
            previews.append(
                _preview(
                    "Generated declarations for the private compile"
                    if carrier
                    else "Generated declaration fragment",
                    "No generated declarations.",
                    generated.decode("ascii"),
                    "Rendered with the build's generator; SHA-256 matches the recorded bytes. "
                    + placement,
                )
            )
            facts.append(
                {
                    "label": "Generated fragment",
                    "value": f"{len(generated):,} bytes · digest matches",
                }
            )
        else:
            facts.append(
                {
                    "label": "Generated fragment",
                    "value": "Preview unavailable: generated bytes lack a matching digest.",
                }
            )
    overlay, overlay_facts = _overlay_previews(parameters, output)
    previews.extend(overlay)
    facts.extend(overlay_facts)
    if cost.family is ClassicRecipeFamily.IMAGE_METADATA:
        timestamp_summary, timestamp_previews, timestamp_facts = _timestamp_changes(
            parameters, trace
        )
        if timestamp_summary is not None:
            summary = timestamp_summary
        previews.extend(timestamp_previews)
        facts.extend(timestamp_facts)
    previews.extend(_trace_previews(parameters, trace))
    for key, label in (
        ("body_length", "Function bytes"),
        ("linked_span", "Linked space in bytes"),
        ("instruction_count", "Instructions"),
        ("semantic_relocation_count", "Symbol references"),
        ("section_number", "Object section number"),
        ("removed_padding_bytes", "Padding bytes removed"),
        ("literal_count", "Constants"),
        ("moved_slots", "Import slots moved"),
        ("rewritten_operands", "Import references updated"),
        ("file_size_delta", "Object size change"),
        ("oracle_payload_bytes_read", "Reference payload bytes read"),
        ("rel32_fixups", "Relative references updated"),
        ("absolute_fixups", "Absolute references updated"),
        ("relocation_entry_moves", "Relocation entries moved"),
        ("changed_byte_count", "Image bytes changed"),
    ):
        if key in trace:
            facts.append({"label": label, "value": str(trace[key])})
    offsets = trace.get(
        "body_changed_offsets", trace.get("changed_offsets", trace.get("rewritten_offsets"))
    )
    if isinstance(offsets, list) and offsets:
        facts.append({"label": "Changed function offsets", "value": str(len(offsets))})
        previews.append(
            _preview(
                "Changed byte positions",
                "Byte values are not stored in this receipt.",
                "  ".join(_offset(offset) for offset in offsets),
                "Offsets relative to the function start; this is a location list, not a byte diff.",
            )
        )
    graph = _mapping(parameters.get("graph"))
    for key, label in (
        ("generated_tus", "Generated compilation units"),
        ("link_admissions", "Link admissions"),
    ):
        rows = _rows(graph.get(key))
        if rows:
            facts.append({"label": label, "value": str(len(rows))})
            for index, row in enumerate(rows, 1):
                path = str(row.get("path", row.get("id", "build input")))
                preview = _preview(
                    f"{label} · {index}. {path}",
                    "",
                    _display(row),
                    "Recorded build addition and its position among compiler or linker inputs.",
                )
                preview.update(
                    {
                        "source_path": path,
                        "action_index": str(index),
                        "operation": key,
                        "action_id": f"{key}#{index}",
                    }
                )
                previews.append(preview)
    if declaration and cost.kind != "classic_recipe":
        generic = {
            key: value
            for key, value in declaration.items()
            if key
            not in {"id", "kind", "scope", "rationale", "version", "dependencies", "beneficiaries"}
        }
        native_previews, native_facts = _generic_previews(cost.kind, declaration)
        previews.extend(native_previews)
        facts.extend(native_facts)
        parameters.update(generic)
    return {
        "title": title,
        "stage": stage,
        "summary": summary,
        "steps": list(mechanic.steps),
        "previews": previews,
        "facts": facts,
        "dependencies": [value for value in dependencies if isinstance(value, str)]
        if isinstance(dependencies, list)
        else [],
        "source_paths": _source_paths(parameters, statement),
        "detail": _compact(
            {
                "parameters": parameters,
                "trace": trace,
                "rationale": declaration.get("rationale"),
                "candidate_constraints": statement.get("candidate_constraints"),
                "output": {
                    key: value
                    for key, value in output.items()
                    if key
                    in {
                        "disposition",
                        "direct_link_admissions",
                        "effective_outputs",
                        "discarded_outputs",
                        "private_artifact",
                    }
                },
            }
        ),
    }
