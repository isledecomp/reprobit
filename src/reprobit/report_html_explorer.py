"""The portable binary-explorer page and its no-script inventory."""

from __future__ import annotations

import base64
import gzip
import json

from reprobit.report import Report
from reprobit.report_explorer_data import build_explorer_data
from reprobit.report_html_components import code, escape, table


def render_explorer(
    report: Report,
    *,
    context: dict[str, object] | None = None,
    canonical_json_href: str | None = None,
) -> str:
    """Embed display data as inert escaped text, never executable JavaScript."""

    data = build_explorer_data(report, context=context)
    serialized = json.dumps(data, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    payload = base64.b64encode(gzip.compress(serialized, compresslevel=6, mtime=0)).decode("ascii")
    evidence_link = (
        f'<a class="ex-back" href="{escape(canonical_json_href)}">Full JSON evidence</a>'
        if canonical_json_href is not None
        else '<a class="ex-back" href="#advanced">Full report evidence</a>'
    )
    fallback = table(
        ("Intervention", "Target", "Function / source unit", "Cost (points)"),
        tuple(
            (
                code(item.intervention_id),
                code(item.scope.target),
                code(item.scope.function or item.scope.translation_unit or "Whole target"),
                f"{item.cost:,}",
            )
            for item in report.costs.interventions
        ),
        caption="Complete intervention inventory",
        empty_message="This build records no interventions.",
    )
    return f"""
<section id="binary-explorer" aria-labelledby="explorer-title">
  <div class="ex-heading">
    <div><p class="eyebrow">The build, made visible</p>
      <h1 id="explorer-title">Inside the binary</h1>
      <p class="lede">Find a change. See where it lands. Follow how it was made.</p></div>
    <div class="ex-heading-links"><a class="ex-back" href="#overview">← Build report</a>
      {evidence_link}</div>
  </div>
  <div id="explorer-data" data-compression="gzip-base64" hidden>{payload}</div>
  <div class="ex-app" hidden>
    <div class="ex-toolbar">
      <label>Binary<select id="ex-target"></select></label>
      <label class="ex-search">Find a function, source file, change, or address
        <input id="ex-search" type="search" placeholder="Search name, path, or 0x address"
          autocomplete="off" spellcheck="false"></label>
      <button id="ex-reset" type="button">Reset view</button>
    </div>
    <div id="ex-metrics" class="ex-metrics"></div>
    <div class="ex-stage-row" id="ex-stages" aria-label="Filter changes by build stage"></div>
    <div class="ex-mobile-view"><button id="ex-toggle-map" type="button"
      aria-expanded="false">Show binary map</button>
      <button id="ex-jump-detail" type="button">View selected change ↓</button></div>
    <div class="ex-workspace">
      <aside class="ex-map-panel" aria-labelledby="ex-map-title">
        <div class="ex-panel-head"><h2 id="ex-map-title">Binary map</h2>
          <label class="ex-small">Coordinates<select id="ex-space">
            <option value="va">Final binary address</option>
            <option value="file">File offset</option>
            <option value="reference-va">Reference address</option>
            <option value="debug-va">Debug companion address</option>
            <option value="linked-va">Address before image edits</option>
          </select></label></div>
        <p id="ex-map-caption" class="ex-small"></p>
        <div id="ex-sections" class="ex-sections" aria-label="Zoom to a binary section"></div>
        <div class="ex-map-key"><span>Address / section</span><span>Cost · changes</span></div>
        <div id="ex-map" class="ex-map"></div>
        <div class="ex-map-actions"><button type="button" id="ex-zoom-out">Whole binary</button>
          <button type="button" id="ex-zoom-range">Zoom to range</button>
          <button type="button" id="ex-clear-range">Clear range</button></div>
        <p class="ex-small">Select a band to filter changes.<br>Teal → gold: increasing cost.
          White dot: selected change.</p>
        <div id="ex-map-accounting" class="ex-map-accounting"></div>
      </aside>
      <section class="ex-list-panel" aria-labelledby="ex-list-title">
        <div class="ex-panel-head"><h2 id="ex-list-title">Changes</h2>
          <label class="ex-small">Sort<select id="ex-sort">
            <option value="cost">Highest cost</option><option value="address">Address order</option>
            <option value="name">Name</option></select></label></div>
        <div class="ex-list-tools"><label class="ex-small">Location<select id="ex-location">
          <option value="all">Every change</option><option value="mapped">On this map</option>
          <option value="unmapped">Outside this map</option></select></label>
          <output id="ex-result-count" class="ex-small" aria-live="polite"></output></div>
        <div id="ex-range-filter" class="ex-range-filter" hidden></div>
        <div id="ex-list" class="ex-list" role="region"
          aria-label="Matching changes" tabindex="0"></div>
      </section>
      <section id="ex-detail" class="ex-detail" aria-label="Selected change"
        tabindex="-1"></section>
    </div>
    <details class="ex-operations"><summary class="ex-panel-head">
      <span>Other recorded build adjustments</span><span id="ex-operation-count"></span></summary>
      <p class="ex-small">Object ordering and comparison-file normalization also affect the build.
        These records carry no separate intervention charge.</p>
      <div id="ex-operations"></div>
    </details>
    <details class="ex-coverage"><summary>Map coverage &amp; reading this view</summary>
      <div id="ex-coverage"></div>
      <p>Cost points rank the amount and kind of intervention. They are neither runtime overhead
        nor milliseconds. A shared change is charged once; its destinations show where
        it is used.</p>
      <p>Map density divides each change's cost equally across its recorded locations, then
        spreads each share over that location's extent. Zooming preserves that allocation.
        It does not measure the number of changed bytes. Empty bands mean no mapped
        intervention in this report, not proof that every byte there was untouched.</p>
      <p>Source previews show recorded edits or receipt-checked source text. Binary edits can happen
        after compilation and need not have a corresponding C++ source change.</p>
    </details>
  </div>
  <div class="ex-fallback"><p>The interactive map needs JavaScript. All recorded interventions
    are listed below; the build report and its evidence tables remain readable.</p>{fallback}</div>
</section>"""


__all__ = ["render_explorer"]
