"""Generation-time display coordinates from captured terminal linker maps."""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from hashlib import sha256
from itertools import pairwise
from typing import Any

from reprobit.report import Report
from reprobit.report_explorer_context import _body_sizes

_MAX_MAP_BYTES = 16 * 1024 * 1024
_MAX_PUBLICS = 100_000
_ROW = re.compile(
    r"^\s*([0-9a-fA-F]{4}):([0-9a-fA-F]{8})\s+(\S+)\s+"
    r"([0-9a-fA-F]{8})\s+(.*?)\s*$"
)


def parse_link_map(payload: bytes) -> list[dict[str, Any]]:
    """Read exact VA/public/provider facts; reject incomplete or ambiguous tables."""
    if len(payload) > _MAX_MAP_BYTES:
        raise ValueError("Captured linker map exceeds the display size limit")
    text = payload.decode("ascii")
    rows: list[dict[str, Any]] = []
    started = finished = False
    seen: set[str] = set()
    for line in text.splitlines():
        if "Publics by Value" in line and "Lib:Object" in line:
            if started:
                raise ValueError("Captured linker map repeats its public table")
            started = True
            continue
        if not started:
            continue
        if line.strip().casefold().startswith("entry point at"):
            finished = True
            break
        if not line.strip():
            continue
        match = _ROW.fullmatch(line)
        if match is None:
            raise ValueError("Captured linker map has an unsupported public row")
        section, offset, name, va, tail = match.groups()
        fields = tail.split(None, 1)
        function = bool(fields and fields[0] == "f")
        provider = fields[1] if function and len(fields) == 2 else tail
        provider = re.sub(r"^i\s+", "", provider)
        if not provider or (function and len(fields) != 2):
            raise ValueError("Captured linker map has a public without a provider")
        if name in seen:
            raise ValueError("Captured linker map has an ambiguous repeated public name")
        seen.add(name)
        rows.append(
            {
                "name": name,
                "va": int(va, 16),
                "section": int(section, 16),
                "section_offset": int(offset, 16),
                "provider": provider,
                "function": function,
            }
        )
        if len(rows) > _MAX_PUBLICS:
            raise ValueError("Captured linker map exceeds the public count limit")
    if not started or not finished:
        raise ValueError("Captured linker map has no complete public table")
    return rows


def _digest(value: object) -> str | None:
    if isinstance(value, dict):
        digest = value.get("digest")
        if isinstance(digest, dict) and isinstance(digest.get("value"), str):
            return str(digest["value"])
    return None


def _repack_pieces(value: object) -> list[tuple[int, int, int]]:
    if not isinstance(value, dict) or value.get("schema") != "comdat_tail_thunk_repack_v1":
        raise ValueError("Unsupported postlink text packing schema")
    rows = value.get("pieces")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 4:
        raise ValueError("Invalid postlink text packing pieces")
    pieces = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Invalid postlink text packing piece")
        lo, hi, shift = row.get("src_lo"), row.get("src_hi"), row.get("shift")
        if (
            not isinstance(lo, str)
            or not re.fullmatch(r"0x[0-9a-f]{1,8}", lo)
            or not isinstance(hi, str)
            or not re.fullmatch(r"0x[0-9a-f]{1,8}", hi)
            or type(shift) is not int
            or not 1 <= shift <= 63
        ):
            raise ValueError("Invalid postlink text packing coordinates")
        start, end = int(lo, 16), int(hi, 16)
        if not shift <= start < end:
            raise ValueError("Invalid postlink text packing bounds")
        pieces.append((start, end, shift))
    sources = sorted((lo, hi) for lo, hi, _ in pieces)
    destinations = sorted((lo - shift, hi - shift) for lo, hi, shift in pieces)
    if any(a[1] > b[0] for spans in (sources, destinations) for a, b in pairwise(spans)):
        raise ValueError("Overlapping postlink text packing pieces")
    return pieces


def _transform_chain(
    report: Report, target: str, raw_digest: str, final_digest: str
) -> list[list[tuple[int, int, int]]] | None:
    """Close exact linked-image -> final-image receipts before moving any point."""
    edges: dict[str, list[tuple[str, str, dict[str, Any]]]] = {}
    for certificate in report.proof.certificates:
        for proof in certificate.semantic_proofs:
            before, after = proof.input_statement, proof.output_statement
            if not isinstance(before, dict) or not isinstance(after, dict):
                continue
            intervention = before.get("intervention", {})
            if not isinstance(intervention, dict):
                continue
            scope = intervention.get("scope", {})
            if not isinstance(scope, dict) or scope.get("target") != target:
                continue
            seed, result = _digest(before.get("seed")), _digest(after.get("candidate"))
            constraints = before.get("candidate_constraints", {})
            if seed and result and seed != result and isinstance(constraints, dict):
                edges.setdefault(seed, []).append((result, str(proof.family), constraints))
    current = raw_digest
    visited: set[str] = set()
    transforms: list[list[tuple[int, int, int]]] = []
    while current != final_digest:
        if current in visited or len(visited) >= 64 or len(edges.get(current, [])) != 1:
            return None
        visited.add(current)
        result, family, constraints = edges[current][0]
        if family == "image_binary_repack":
            try:
                transforms.append(_repack_pieces(constraints.get("text_repack")))
            except ValueError:
                return None
        elif family not in {"image_metadata", "image_link_order"}:
            return None
        current = result
    return transforms


def _move(va: int, transforms: list[list[tuple[int, int, int]]]) -> int:
    for pieces in transforms:
        for start, end, shift in pieces:
            if start <= va < end:
                va -= shift
                break
    return va


def collect_link_map_context(
    report: Report, *, captures: Mapping[str, tuple[str, str, bytes]]
) -> dict[str, object]:
    """Merge current runtime maps keyed by target into already collected context.

    Each capture is (terminal linker step, recorded raw image path, immutable
    map bytes). The raw image must have a fresh output receipt from that step.
    Map identity is embedded in the report; no local paths are searched.
    """
    context: dict[str, Any] = copy.deepcopy(report.exploration)
    targets = context.setdefault("targets", [])
    diagnostics = context.setdefault("diagnostics", [])
    outputs = report.proof.runtime.preimage.build.outputs
    steps = {step.id for step in report.proof.runtime.preimage.build.steps if step.returncode == 0}
    for target in report.targets:
        capture = captures.get(target.id)
        if capture is None:
            continue
        step, raw_path, payload = capture
        receipts = [
            item
            for item in outputs
            if item.path == raw_path and item.producer_step == step and item.fresh
        ]
        try:
            if step not in steps or len(receipts) != 1:
                raise ValueError("Captured map lacks its exact terminal-link image receipt")
            publics = parse_link_map(payload)
        except (ValueError, UnicodeDecodeError) as error:
            diagnostics.append(
                {"kind": "native-map-unavailable", "target_id": target.id, "message": str(error)}
            )
            continue
        row = next((item for item in targets if item.get("id") == target.id), None)
        if row is None:
            row = {"id": target.id, "symbols": [], "sections": []}
            targets.append(row)
        transforms = _transform_chain(
            report,
            target.id,
            receipts[0].digest.value,
            target.candidate_digest.value if target.candidate_digest else "",
        )
        sections = row.get("sections", [])
        sizes = _body_sizes(report, target.id)
        symbols = []
        for public in publics:
            index = public["section"] - 1
            section = sections[index] if 0 <= index < len(sections) else {}
            final = bool(
                transforms is not None
                and public["function"]
                and section.get("name") == ".text"
                and section.get("va", -1) + public["section_offset"] == public["va"]
            )
            va = _move(public["va"], transforms or []) if final else public["va"]
            size = sizes.get(public["name"], (None, ""))[0] if final else None
            if size and _move(public["va"] + size - 1, transforms or []) != va + size - 1:
                size = None
            symbols.append(
                {
                    "name": public["name"],
                    "va": va,
                    "size": size,
                    "provider": public["provider"],
                    "origin": "terminal-link-map",
                    "linked_va": public["va"],
                    "space": "va" if final else "linked-va",
                    "basis": (
                        "Captured terminal linker map; final coordinates follow "
                        "the complete recorded image pipeline"
                        if final
                        else "Captured terminal linker map; coordinates before final image changes"
                    ),
                }
            )
        names = {symbol["name"] for symbol in symbols}
        # The real terminal map supersedes the separate debug relink's addresses.
        row["symbols"] = symbols + [
            item for item in row.get("symbols", []) if item.get("name") not in names
        ]
        row["link_map"] = {
            "digest": sha256(payload).hexdigest(),
            "size": len(payload),
            "step_id": step,
            "linked_image_digest": receipts[0].digest.value,
            "final_pipeline_closed": transforms is not None,
            "public_count": len(publics),
        }
    return context


__all__ = ["collect_link_map_context", "parse_link_map"]
