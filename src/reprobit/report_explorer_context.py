"""Optional, receipt-checked local evidence for the binary explorer.

This is display context, never a new authenticity claim. Only files explicitly
named by the report are opened, and their complete size and SHA-256 identity
must match before any contents are displayed or interpreted. Missing build
directories therefore reduce detail without preventing report generation.
"""

from __future__ import annotations

import copy
import os
import stat
import struct
from collections import Counter, defaultdict
from hashlib import sha256
from pathlib import Path
from typing import Any

from reprobit.binary import ByteIdentityError, require
from reprobit.model import ArtifactKind, Digest
from reprobit.msvc42_pdb import Msvc42PdbLinkMap, read_msvc42_pdb_link_map
from reprobit.pe32 import (
    Pe32Headers,
    Pe32Section,
    parse_pe32_headers,
    pe32_highlow_relocation_offsets,
)
from reprobit.report import Report
from reprobit.report_explorer_sources import (
    _excerpts,
    collect_donor_source_operations,
    source_pairs,
    source_rendering,
)
from reprobit.secure_path_contracts import is_redirected_metadata, no_follow_file_flags

_MAX_FILE_BYTES = 128 * 1024 * 1024
_MAX_TOTAL_BYTES = 256 * 1024 * 1024
_MAX_SOURCE_BYTES = 1024 * 1024
_MAX_SOURCE_CHARACTERS = 256_000
_MAX_SOURCE_TOTAL_CHARACTERS = 2_000_000
_MAX_SOURCE_FILES = 1024
_MAX_SOURCE_PATHS = 4096
_MAX_DIAGNOSTICS = 128
_MAX_SYMBOLS = 100_000


class _Reader:
    def __init__(self, diagnostics: list[dict[str, Any]]) -> None:
        self.diagnostics = diagnostics
        self.bytes_read = 0
        self.omitted_diagnostics = 0
        self.last_issue: dict[str, Any] | None = None

    def issue(self, kind: str, message: str, **details: Any) -> None:
        self.last_issue = {"kind": kind, "message": message, **details}
        if len(self.diagnostics) >= _MAX_DIAGNOSTICS:
            self.omitted_diagnostics += 1
            return
        self.diagnostics.append({"kind": kind, "message": message, **details})

    def read(
        self,
        path: str,
        size: int,
        digest: Digest,
        *,
        limit: int = _MAX_FILE_BYTES,
        target_id: str | None = None,
        diagnose: bool = True,
    ) -> bytes | None:
        count, omitted = len(self.diagnostics), self.omitted_diagnostics
        self.last_issue = None
        result = self._read(path, size, digest, limit=limit, target_id=target_id)
        if not diagnose:
            del self.diagnostics[count:]
            self.omitted_diagnostics = omitted
        return result

    def _read(
        self, path: str, size: int, digest: Digest, *, limit: int, target_id: str | None
    ) -> bytes | None:
        details = {"path": path, **({"target_id": target_id} if target_id else {})}
        if not Path(path).is_absolute():
            self.issue("relative-path", "A recorded file path is not absolute.", **details)
            return None
        if size > limit or self.bytes_read + size > _MAX_TOTAL_BYTES:
            self.issue("read-limit", "A recorded file exceeds the explorer read limit.", **details)
            return None
        try:
            named = Path(path).lstat()
            if is_redirected_metadata(named) or not stat.S_ISREG(named.st_mode):
                self.issue("not-regular", "A recorded file is not a regular file.", **details)
                return None
            flags = no_follow_file_flags(os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
            with os.fdopen(os.open(path, flags), "rb") as stream:
                info = os.fstat(stream.fileno())
                if is_redirected_metadata(info) or not stat.S_ISREG(info.st_mode):
                    self.issue("not-regular", "A recorded file is not a regular file.", **details)
                    return None
                if (info.st_dev, info.st_ino) != (named.st_dev, named.st_ino):
                    self.issue("stale-file", "A recorded file changed while opening.", **details)
                    return None
                if info.st_size != size:
                    self.issue("stale-file", "A recorded file has changed size.", **details)
                    return None
                data = stream.read(size + 1)
                self.bytes_read += len(data)
                after = Path(path).lstat()
                if (
                    is_redirected_metadata(after)
                    or not stat.S_ISREG(after.st_mode)
                    or (after.st_dev, after.st_ino) != (info.st_dev, info.st_ino)
                ):
                    self.issue("stale-file", "A recorded file changed while reading.", **details)
                    return None
        except OSError:
            self.issue("missing-file", "A recorded file is missing or cannot be read.", **details)
            return None
        if len(data) != size or sha256(data).hexdigest() != digest.value:
            self.issue("stale-file", "A recorded file no longer matches its receipt.", **details)
            return None
        return data


def _sections(headers: Pe32Headers) -> list[dict[str, Any]]:
    return [
        {
            "name": section.raw_name.rstrip(b"\0").decode("ascii", errors="replace"),
            "va": headers.image_base + section.virtual_address,
            "size": section.virtual_size or section.raw_size,
            "file_offset": section.raw_offset,
            "file_size": section.raw_size,
        }
        for section in headers.sections
    ]


def _check_pdb_binding(image: Pe32Headers, link_map: Msvc42PdbLinkMap) -> None:
    """Bind symbol records to this exact debug image, without following its path."""
    rva, size = image.data_directory(6, "debug directory")
    require(rva > 0 and 0 < size <= 28 * 96 and size % 28 == 0, "invalid debug directory")
    offset = image.rva_to_offset(rva, size, context="debug directory")
    identities = []
    for at in range(offset, offset + size, 28):
        kind, length, _address, pointer = struct.unpack_from("<IIII", image.data, at + 12)
        if kind != 2:
            continue
        require(length >= 17 and pointer <= len(image.data) - length, "invalid CodeView payload")
        magic, stream_offset, signature, age = struct.unpack_from("<4sIII", image.data, pointer)
        require(magic == b"NB10" and stream_offset == 0, "unsupported CodeView identity")
        require(image.data[pointer + length - 1] == 0, "unterminated CodeView path")
        identities.append((signature, age))
    require(
        identities == [(link_map.identity.signature, link_map.identity.age)],
        "debug image and PDB identities differ",
    )


def _matching_section(
    candidate: Pe32Headers | None, debug: Pe32Headers, section: Pe32Section
) -> Pe32Section | None:
    if candidate is None or candidate.image_base != debug.image_base:
        return None
    matches = [
        item
        for item in candidate.sections
        if item.raw_name == section.raw_name and item.virtual_address == section.virtual_address
    ]
    return matches[0] if len(matches) == 1 else None


def _same_range(
    candidate: Pe32Headers,
    final_section: Pe32Section,
    debug: Pe32Headers,
    debug_section: Pe32Section,
    offset: int,
    size: int,
) -> bool:
    if (
        size <= 0
        or offset < 0
        or offset + size > min(final_section.raw_size, debug_section.raw_size)
    ):
        return False
    final_start = final_section.raw_offset + offset
    debug_start = debug_section.raw_offset + offset
    return (
        candidate.data[final_start : final_start + size]
        == debug.data[debug_start : debug_start + size]
    )


def _symbols(
    candidate: Pe32Headers | None,
    debug: Pe32Headers,
    link_map: Msvc42PdbLinkMap,
    body_sizes: dict[str, tuple[int, str]],
) -> list[dict[str, Any]]:
    """Public symbols are points; neither names nor neighbor gaps supply lengths."""
    result: list[dict[str, Any]] = []
    try:
        final_relocs = pe32_highlow_relocation_offsets(candidate.data) if candidate else frozenset()
        debug_relocs = pe32_highlow_relocation_offsets(debug.data)
    except ByteIdentityError:
        # Unsupported relocation data cannot strengthen a location claim.
        final_relocs = debug_relocs = frozenset()
    starts: dict[str, set[tuple[int, int]]] = {}
    for symbol in link_map.publics:
        starts.setdefault(symbol.name, set()).add((symbol.section, symbol.offset))
    for symbol in link_map.publics[:_MAX_SYMBOLS]:
        if not 1 <= symbol.section <= len(debug.sections):
            continue
        section = debug.sections[symbol.section - 1]
        if symbol.offset >= (section.virtual_size or section.raw_size):
            continue
        contributions = [
            item
            for item in link_map.contributions
            if item.section == symbol.section
            and item.offset <= symbol.offset < item.offset + item.size
        ]
        final_section = _matching_section(candidate, debug, section)
        mapped = False
        body_matched = False
        relocated_body = False
        body = body_sizes.get(symbol.name) if len(starts[symbol.name]) == 1 else None
        if candidate is not None and final_section is not None:
            mapped = final_section.raw_size == section.raw_size and _same_range(
                candidate, final_section, debug, section, 0, section.raw_size
            )
            if not mapped and len(contributions) == 1:
                contribution = contributions[0]
                mapped = _same_range(
                    candidate,
                    final_section,
                    debug,
                    section,
                    contribution.offset,
                    contribution.size,
                )
            if body is not None:
                body_matched = _same_range(
                    candidate, final_section, debug, section, symbol.offset, body[0]
                )
                if not body_matched:
                    relocated_body = _same_relocated_body(
                        candidate,
                        final_section,
                        debug,
                        section,
                        symbol.offset,
                        body[0],
                        final_relocs,
                        debug_relocs,
                        link_map,
                    )
                    body_matched = relocated_body
                mapped = mapped or body_matched
        row: dict[str, Any] = {
            "name": symbol.name,
            "va": debug.image_base + section.virtual_address + symbol.offset,
            "size": body[0] if body is not None and body_matched else None,
            "space": "va" if mapped else "debug-va",
            "basis": (
                "Receipt-checked linked PDB; containing bytes unchanged at this final address"
                if mapped
                else "Receipt-checked linked PDB; debug companion before final image changes"
            ),
        }
        if body is not None and body_matched:
            row["tu"] = body[1]
            row["basis"] = "Receipt-checked linked PDB and validator-recorded body length; " + (
                "function layout matches at this final address; "
                "only recorded relocation operands differ"
                if relocated_body
                else "function bytes unchanged at this final address"
            )
        owners = {item.module_index for item in contributions}
        if len(owners) == 1:
            owner = next(iter(owners))
            if 0 <= owner < len(link_map.modules):
                row["source"] = link_map.modules[owner].object_name
        result.append(row)
    return result


def _same_relocated_body(
    candidate: Pe32Headers,
    final_section: Pe32Section,
    debug: Pe32Headers,
    debug_section: Pe32Section,
    offset: int,
    size: int,
    final_relocs: frozenset[int],
    debug_relocs: frozenset[int],
    link_map: Msvc42PdbLinkMap,
) -> bool:
    """Match fixed body layout while allowing only PE-declared address operands.

    Debug linking can insert a directory before read-only data. The function
    stays put but pointers to that data move. Both images must declare the same
    complete HIGHLOW sites, all other bytes must match, and each changed pointer
    must address byte-identical complete PDB contributions in the same uniquely
    named PE section. Matching instruction shape alone is insufficient.
    """
    if (
        size <= 0
        or offset < 0
        or offset + size > min(final_section.raw_size, debug_section.raw_size)
    ):
        return False
    final_start, debug_start = final_section.raw_offset + offset, debug_section.raw_offset + offset
    final_sites = {
        site - final_start for site in final_relocs if final_start - 3 <= site < final_start + size
    }
    debug_sites = {
        site - debug_start for site in debug_relocs if debug_start - 3 <= site < debug_start + size
    }
    if (
        not final_sites
        or final_sites != debug_sites
        or any(site < 0 or site + 4 > size for site in final_sites)
    ):
        return False
    final_body = candidate.data[final_start : final_start + size]
    debug_body = debug.data[debug_start : debug_start + size]
    cursor = 0
    for site in sorted(final_sites):
        if site < cursor or final_body[cursor:site] != debug_body[cursor:site]:
            return False
        final_pointer = struct.unpack_from("<I", final_body, site)[0]
        debug_pointer = struct.unpack_from("<I", debug_body, site)[0]
        if final_pointer != debug_pointer and not _same_pointed_contribution(
            candidate, debug, link_map, final_pointer, debug_pointer
        ):
            return False
        cursor = site + 4
    return final_body[cursor:] == debug_body[cursor:]


def _same_pointed_contribution(
    candidate: Pe32Headers,
    debug: Pe32Headers,
    link_map: Msvc42PdbLinkMap,
    final_pointer: int,
    debug_pointer: int,
) -> bool:
    debug_targets = [
        (index, section)
        for index, section in enumerate(debug.sections, 1)
        if section.backs_rva(debug_pointer - debug.image_base, 1)
    ]
    final_targets = [
        section
        for section in candidate.sections
        if section.backs_rva(final_pointer - candidate.image_base, 1)
    ]
    if len(debug_targets) != 1 or len(final_targets) != 1:
        return False
    index, debug_section = debug_targets[0]
    final_section = final_targets[0]
    if final_section.raw_name != debug_section.raw_name:
        return False
    debug_offset = debug_pointer - debug.image_base - debug_section.virtual_address
    final_offset = final_pointer - candidate.image_base - final_section.virtual_address
    contributions = [
        contribution
        for contribution in link_map.contributions
        if contribution.section == index
        and contribution.offset <= debug_offset < contribution.offset + contribution.size
    ]
    if len(contributions) != 1:
        return False
    contribution = contributions[0]
    candidate_offset = contribution.offset + final_offset - debug_offset
    if (
        candidate_offset < 0
        or candidate_offset + contribution.size > final_section.raw_size
        or contribution.offset + contribution.size > debug_section.raw_size
    ):
        return False
    start = final_section.raw_offset + candidate_offset
    debug_start = debug_section.raw_offset + contribution.offset
    return (
        candidate.data[start : start + contribution.size]
        == debug.data[debug_start : debug_start + contribution.size]
    )


def _body_sizes(report: Report, target_id: str) -> dict[str, tuple[int, str]]:
    """Use only unambiguous function lengths from named semantic output traces."""
    candidates: dict[str, set[tuple[int, str]]] = {}
    for certificate in report.proof.certificates:
        for proof in certificate.semantic_proofs:
            before, after = proof.input_statement, proof.output_statement
            if not isinstance(before, dict) or not isinstance(after, dict):
                continue
            intervention = before.get("intervention", {})
            scope = intervention.get("scope", {}) if isinstance(intervention, dict) else {}
            trace = after.get("validator_trace", {})
            if not isinstance(scope, dict) or not isinstance(trace, dict):
                continue
            name, tu = scope.get("function"), scope.get("translation_unit")
            size = trace.get("body_length", trace.get("donor_length"))
            if (
                scope.get("target") == target_id
                and isinstance(name, str)
                and trace.get("mangled") == name
                and isinstance(tu, str)
                and type(size) is int
                and 0 < size <= _MAX_FILE_BYTES
            ):
                candidates.setdefault(name, set()).add((size, tu))
    return {name: next(iter(values)) for name, values in candidates.items() if len(values) == 1}


def _source_digests(report: Report) -> set[str]:
    result: set[str] = set()
    for certificate in report.proof.certificates:
        for proof in certificate.semantic_proofs:
            statement = proof.input_statement
            if not isinstance(statement, dict):
                continue
            inputs = statement.get("source_inputs", [])
            for item in inputs if isinstance(inputs, list) else []:
                if isinstance(item, dict) and isinstance(item.get("digest"), dict):
                    value = item["digest"].get("value")
                    if isinstance(value, str):
                        result.add(value)
            compiler = statement.get("compiler_statement", {})
            request = compiler.get("request_receipt", {}) if isinstance(compiler, dict) else {}
            if isinstance(request, dict):
                for name in ("input_digests", "output_digests"):
                    digests = request.get(name, {})
                    if isinstance(digests, dict):
                        result.update(value for value in digests.values() if isinstance(value, str))
            intervention = statement.get("intervention", {})
            parameters = (
                intervention.get("parameters", []) if isinstance(intervention, dict) else []
            )
            for parameter in parameters if isinstance(parameters, list) else []:
                if not isinstance(parameter, dict) or parameter.get("name") != "outputs":
                    continue
                declarations = parameter.get("value", [])
                for declaration in declarations if isinstance(declarations, list) else []:
                    if isinstance(declaration, dict):
                        result.update(
                            declaration[name]
                            for name in ("clean", "effective")
                            if isinstance(declaration.get(name), str)
                        )
    return result


def _collect_sources(report: Report, reader: _Reader, context: dict[str, Any]) -> None:
    sources = context["sources"]
    # A budget-exhausted empty string is not a captured nonempty source file.
    for key in list(sources):
        if not isinstance(sources[key], dict) or (
            not sources[key].get("text") and sources[key].get("size") != 0
        ):
            del sources[key]
    requested: set[tuple[str, str | None, str]] = set()
    for certificate in report.proof.certificates:
        for proof in certificate.semantic_proofs:
            statement = proof.input_statement
            if not isinstance(statement, dict):
                continue
            declaration = statement.get("intervention", {})
            if not isinstance(declaration, dict):
                continue
            requested.update(
                (path, before, after)
                for path, before, after in source_pairs(declaration, statement)
                if (before is None or isinstance(before, str))
                and isinstance(after, str)
                and before != after
            )
    diffs = context.get("source_diffs", [])
    diffs = [item for item in diffs if isinstance(item, dict)] if isinstance(diffs, list) else []
    context["source_diffs"] = diffs
    covered = {
        (item.get("path"), item.get("before_digest"), item.get("after_digest"))
        for item in diffs
        if isinstance(item.get("path"), str)
        and (item.get("before_digest") is None or isinstance(item.get("before_digest"), str))
        and isinstance(item.get("after_digest"), str)
        and isinstance(item.get("before"), str)
        and isinstance(item.get("after"), str)
    }
    records: dict[str, list[Any]] = defaultdict(list)
    for artifact in report.proof.artifacts:
        if artifact.kind in {ArtifactKind.SOURCE, ArtifactKind.GENERATED}:
            records[artifact.digest.value].append(artifact)
    for values in records.values():
        values.sort(key=lambda item: (len(item.receipt_path or ""), item.receipt_path or ""))
    verified: dict[str, bytes] = {}
    failures: dict[str, str] = {}
    reads = 0

    def load(key: str) -> bytes | None:
        nonlocal reads
        if key in verified:
            return verified[key]
        if key in failures:
            return None
        # Runtime capture can retain an original source version whose physical
        # path has since been overwritten. Recheck complete embedded bytes just
        # as strictly as a file before using them in another source change.
        snapshot = sources.get(key)
        text_value = snapshot.get("text") if isinstance(snapshot, dict) else None
        if (
            isinstance(snapshot, dict)
            and snapshot.get("truncated") is False
            and isinstance(text_value, str)
        ):
            try:
                embedded = text_value.encode(snapshot.get("encoding", "utf-8"))
            except (AttributeError, KeyError, LookupError, UnicodeEncodeError):
                embedded = b""
            if len(embedded) == snapshot.get("size") and sha256(embedded).hexdigest() == key:
                verified[key] = embedded
                return embedded
        if len(verified) + len(failures) >= _MAX_SOURCE_FILES:
            failures[key] = "file-count-limit"
            return None
        candidates = [item for item in records[key] if item.receipt_path is not None]
        reason = "no-recorded-path"
        for artifact in candidates:
            if reads >= _MAX_SOURCE_PATHS:
                reason = "read-count-limit"
                break
            reads += 1
            data = reader.read(
                artifact.receipt_path,
                artifact.size,
                artifact.digest,
                limit=_MAX_SOURCE_BYTES,
                diagnose=False,
            )
            if data is not None:
                verified[key] = data
                return data
            reason = str((reader.last_issue or {}).get("kind", "unreadable-file"))
        failures[key] = reason
        return None

    diff_characters = sum(
        len(str(item.get("before", ""))) + len(str(item.get("after", "")))
        for item in diffs
        if isinstance(item, dict)
    )
    missing_changes: list[dict[str, Any]] = []
    limited_changes = 0
    for path, before, after in sorted(
        requested, key=lambda item: (item[0], item[1] or "", item[2])
    ):
        if (path, before, after) in covered:
            continue
        remaining = _MAX_SOURCE_TOTAL_CHARACTERS - diff_characters
        if remaining < 2:
            limited_changes += 1
            continue
        old = load(before) if before is not None else b""
        new = load(after)
        if old is None or new is None:
            reasons = sorted({failures[key] for key in (before, after) if key in failures})
            if reasons and all("limit" in reason for reason in reasons):
                limited_changes += 1
            else:
                missing_changes.append({"path": path, "reasons": reasons})
            continue
        old_text, new_text, clipped = _excerpts(old, new, min(32_000, remaining // 2))
        diff_characters += len(old_text) + len(new_text)
        diffs.append(
            {
                "path": path,
                "before_digest": before,
                "after_digest": after,
                "before_size": len(old),
                "after_size": len(new),
                "before": old_text,
                "after": new_text,
                "truncated": clipped,
                "source_rendering": source_rendering(context, old, new),
                "note": (
                    "Exact before and after source; "
                    "complete files match the recorded hashes and size."
                    + (" Excerpts are clipped to the report display limit." if clipped else "")
                ),
            }
        )
        covered.add((path, before, after))

    collect_donor_source_operations(report, context, load)

    # Whole-file snapshots are optional once every requested use of a version
    # has an exact change excerpt. This avoids notices about intentionally
    # overwritten clean paths and versions that never had a physical path.
    uses: dict[str, set[tuple[str, str | None, str]]] = defaultdict(set)
    for pair in requested:
        for key in pair[1:]:
            if key is not None:
                uses[key].add(pair)
    clipped_pairs = {
        (item.get("path"), item.get("before_digest"), item.get("after_digest"))
        for item in diffs
        if item.get("truncated") is True
        and isinstance(item.get("path"), str)
        and (item.get("before_digest") is None or isinstance(item.get("before_digest"), str))
        and isinstance(item.get("after_digest"), str)
    }
    # Generated units need complete source to show their whole contents. Keep
    # their snapshot fallback when a new-file excerpt was clipped.
    clipped_generated = {pair[2] for pair in clipped_pairs if pair[1] is None}
    covered_versions = {
        key for key, pairs in uses.items() if pairs <= covered and key not in clipped_generated
    }
    wanted = _source_digests(report) - covered_versions - sources.keys()
    characters = sum(len(str(item.get("text", ""))) for item in sources.values())
    limited_snapshots = 0
    missing_snapshots: Counter[str] = Counter()
    for key in sorted(wanted):
        remaining = _MAX_SOURCE_TOTAL_CHARACTERS - characters
        if remaining <= 0:
            limited_snapshots += 1
            continue
        data = load(key)
        if data is None:
            reason = failures[key]
            if "limit" in reason:
                limited_snapshots += 1
            else:
                missing_snapshots[reason] += 1
            continue
        try:
            text = data.decode("utf-8")
            encoding = "utf-8"
        except UnicodeDecodeError:
            text = data.decode("cp1252", errors="replace")
            encoding = "cp1252"
        shown = text[: min(_MAX_SOURCE_CHARACTERS, remaining)]
        characters += len(shown)
        sources[key] = {
            "text": shown,
            "path": records[key][0].logical_path,
            "size": len(data),
            "truncated": len(shown) < len(text),
            "encoding": encoding,
            "basis": "Source bytes checked against the recorded SHA-256 digest and size",
        }
    context["source_coverage"] = {
        "requested_changes": len(requested),
        "captured_changes": len(requested & covered),
        "truncated_changes": len(requested & clipped_pairs),
        "unavailable_changes": len(missing_changes),
        "limited_changes": limited_changes,
        "snapshots": len(sources),
        "snapshot_characters": characters,
        "limited_optional_snapshots": limited_snapshots,
        "unavailable_optional_snapshots": dict(missing_snapshots),
    }
    if missing_changes:
        reader.diagnostics.append(
            {
                "kind": "source-change-unavailable",
                "count": len(missing_changes),
                "message": (
                    f"{len(missing_changes)} source changes lack readable "
                    "recorded before/after files."
                ),
                "details": missing_changes[:16],
            }
        )
    if limited_changes:
        reader.diagnostics.append(
            {
                "kind": "source-change-limit",
                "count": limited_changes,
                "message": (
                    f"{limited_changes} source-change excerpts exceed the report display budget."
                ),
            }
        )
    if limited_snapshots:
        reader.diagnostics.append(
            {
                "kind": "source-snapshot-limit",
                "count": limited_snapshots,
                "message": (
                    f"{limited_snapshots} optional full-file source previews "
                    "exceed the display budget."
                ),
            }
        )
    if missing_snapshots:
        reader.diagnostics.append(
            {
                "kind": "source-snapshot-unavailable",
                "count": sum(missing_snapshots.values()),
                "message": (
                    f"{sum(missing_snapshots.values())} optional full-file source "
                    "previews are unavailable."
                ),
                "reasons": dict(missing_snapshots),
            }
        )


def collect_explorer_context(report: Report) -> dict[str, Any]:
    """Collect bounded display details while preserving embedded report context.

    Linked PDB addresses stay in a separate coordinate space unless an exact
    containing byte range is unchanged at the same final image address. PDB
    public records do not establish function lengths. Source text is a bounded
    preview of digest-checked files explicitly named by semantic input receipts.
    """
    context: dict[str, Any] = copy.deepcopy(getattr(report, "exploration", {}) or {})
    targets = context.get("targets", [])
    sources = context.get("sources", {})
    diagnostics = context.get("diagnostics", [])
    targets = (
        [item for item in targets if isinstance(item, dict)] if isinstance(targets, list) else []
    )
    sources = sources if isinstance(sources, dict) else {}
    diagnostics = diagnostics if isinstance(diagnostics, list) else []
    source_summary_kinds = {
        "source-unavailable",
        "source-change-unavailable",
        "source-change-limit",
        "source-snapshot-unavailable",
        "source-snapshot-limit",
    }
    diagnostics = [
        item
        for item in diagnostics
        if not isinstance(item, dict) or item.get("kind") not in source_summary_kinds
    ]
    context.update(targets=targets, sources=sources, diagnostics=diagnostics)
    reader = _Reader(diagnostics)
    outputs = report.proof.runtime.preimage.build.outputs
    for target in report.targets:
        row = next((item for item in targets if item.get("id") == target.id), None)
        if row is None:
            row = {"id": target.id, "sections": [], "symbols": []}
            targets.append(row)
        symbols = row.get("symbols", [])
        row["symbols"] = (
            [
                item
                for item in symbols
                if isinstance(item, dict) and isinstance(item.get("name"), str)
            ]
            if isinstance(symbols, list)
            else []
        )
        candidate = None
        receipts = sorted(
            (
                item
                for item in outputs
                if item.size == target.candidate_size and item.digest == target.candidate_digest
            ),
            key=lambda item: (len(item.path), item.path),
        )
        for receipt in receipts:
            data = reader.read(receipt.path, receipt.size, receipt.digest, target_id=target.id)
            if data is None:
                continue
            try:
                candidate = parse_pe32_headers(data)
                row.update(
                    image_base=candidate.image_base,
                    sections=_sections(candidate),
                    space="va",
                    basis="Candidate image checked against its recorded SHA-256 digest and size",
                )
            except ByteIdentityError as error:
                reader.issue("unsupported-image", str(error), target_id=target.id)
            break
        if candidate is None:
            reader.issue(
                "candidate-unavailable",
                "The recorded candidate image is unavailable; final section addresses are omitted.",
                target_id=target.id,
            )
        for supplemental in report.proof.supplemental_outputs:
            if supplemental.target_id != target.id:
                continue
            files = {item.role: item for item in supplemental.files}
            if "image" not in files or "pdb" not in files:
                continue
            image_file, pdb_file = files["image"], files["pdb"]
            image_data = reader.read(
                image_file.path, image_file.size, image_file.digest, target_id=target.id
            )
            pdb_data = reader.read(
                pdb_file.path, pdb_file.size, pdb_file.digest, target_id=target.id
            )
            if image_data is None or pdb_data is None:
                continue
            try:
                debug = parse_pe32_headers(image_data)
                link_map = read_msvc42_pdb_link_map(pdb_data)
                _check_pdb_binding(debug, link_map)
                row["debug_image_base"] = debug.image_base
                row["debug_sections"] = _sections(debug)
                symbols = _symbols(candidate, debug, link_map, _body_sizes(report, target.id))
                existing = {
                    (item["name"], item.get("va"), item.get("space", "va"))
                    for item in row["symbols"]
                }
                row["symbols"].extend(
                    item
                    for item in symbols
                    if (item["name"], item["va"], item["space"]) not in existing
                )
                if len(link_map.publics) > _MAX_SYMBOLS:
                    reader.issue("symbol-limit", "The linked symbol preview was limited.")
            except (ByteIdentityError, ValueError, struct.error) as error:
                reader.issue("unsupported-debug-pair", str(error), target_id=target.id)
    _collect_sources(report, reader, context)
    if reader.omitted_diagnostics:
        diagnostics.append(
            {
                "kind": "diagnostic-limit",
                "message": f"{reader.omitted_diagnostics} further file diagnostics omitted.",
                "count": reader.omitted_diagnostics,
            }
        )
    return context


__all__ = ["collect_explorer_context"]
