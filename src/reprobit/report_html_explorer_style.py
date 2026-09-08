"""Local assets for the interactive binary-explorer page."""

# ruff: noqa: E501

EXPLORER_CSS = r"""
[hidden] { display: none !important; }
#binary-explorer { margin-top: 3rem; scroll-margin-top: 4rem; }
body.ex-mode main { width: min(1600px, calc(100% - 3rem)); padding-top: 1.2rem; }
body.ex-mode #binary-explorer { margin-top: 0; }
body.ex-mode .section-nav a[href="#binary-explorer"] { color: var(--accent); background: var(--accent-soft); box-shadow: inset 0 -3px var(--accent); }
.ex-heading { display: flex; justify-content: space-between; gap: 1rem; align-items: center; margin-bottom: 1rem; }
.ex-heading h1 { font-size: clamp(1.8rem, 3vw, 2.2rem); margin: .35rem 0; }
.ex-heading .lede { margin: .55rem 0 0; }
.ex-back { white-space: nowrap; font-size: .85rem; }
.ex-heading-links { display: flex; gap: 1rem; flex-wrap: wrap; }
.ex-app { --source: #7652ab; --compile: #3768a8; --object: #187a78; --link: #a26b19; --image: #aa5834; --reference: #b52c4d; }
.ex-app button, .ex-app select, .ex-app input { font: inherit; }
.ex-app button, .ex-app select { border: 1px solid var(--line); border-radius: .4rem; background: white; color: var(--ink); padding: .45rem .6rem; cursor: pointer; }
.ex-app button:hover { background: var(--accent-soft); border-color: var(--accent); }
.ex-app button:disabled { cursor: default; opacity: .45; }
.ex-app select { max-width: 100%; }
.ex-app label { display: grid; gap: .25rem; font-size: .78rem; color: var(--muted); font-weight: 600; }
.ex-toolbar { display: flex; gap: 1rem; align-items: end; padding: 1rem 1.2rem; background: white; border: 1px solid var(--line); border-radius: .6rem .6rem 0 0; }
.ex-toolbar > label:first-child { min-width: 11rem; }
.ex-toolbar select { min-height: 2.7rem; font-size: 1rem; font-weight: 650; }
.ex-search { flex: 1; }
.ex-search input { width: 100%; border: 1px solid var(--line); padding: .7rem .8rem; border-radius: .4rem; color: var(--ink); background: #f8fafb; }
.ex-toolbar button { min-height: 2.7rem; }
.ex-metrics { display: grid; grid-template-columns: repeat(4, 1fr); background: #e8eef1; gap: 1px; border: 1px solid var(--line); border-top: 0; border-radius: 0 0 .6rem .6rem; overflow: hidden; }
.ex-metric { background: #fbfcfd; padding: .7rem 1.2rem; }
.ex-metric strong { display: block; font-size: 1.7rem; letter-spacing: -.04em; font-variant-numeric: tabular-nums; }
.ex-metric span { display: block; color: var(--muted); font-size: .78rem; }
.ex-metric small { color: var(--muted); font-size: .73rem; }
.ex-stage-row { display: flex; flex-wrap: wrap; gap: .4rem; padding: 1.15rem 0; }
.ex-stage-row button { display: flex; align-items: center; gap: .45rem; font-size: .8rem; padding: .4rem .65rem; border-radius: 1.2rem; }
.ex-stage-row button[aria-pressed="true"] { background: #173e4b; color: white; border-color: #173e4b; }
.ex-dot { display: inline-block; width: .5rem; height: .5rem; background: var(--stage, var(--accent)); border-radius: 50%; flex-shrink: 0; }
.ex-workspace { display: grid; grid-template-columns: 220px minmax(235px, .6fr) minmax(430px, 1.6fr); gap: 1rem; align-items: start; }
.ex-map-panel, .ex-list-panel, .ex-detail, .ex-operations { background: white; border: 1px solid var(--line); border-radius: .6rem; min-width: 0; overflow: hidden; }
.ex-panel-head { display: flex; align-items: center; justify-content: space-between; gap: .5rem; padding: 1rem; border-bottom: 1px solid var(--line); }
.ex-panel-head h2 { font-size: .96rem; margin: 0; }
.ex-panel-head select { font-size: .72rem; padding: .3rem .4rem; }
.ex-small { font-size: .74rem; line-height: 1.5; color: var(--muted); }
.ex-map-panel { background: #172e3a; color: #e5eef3; border-color: #172e3a; }
.ex-map-panel .ex-panel-head { display: block; border-color: #36505c; }
.ex-map-panel .ex-panel-head label { margin: .6rem 0 0; min-width: 0; color: #b8cbd4; }
.ex-map-panel .ex-panel-head select { background: #213e4b; border-color: #416170; color: white; width: 100%; min-width: 0; }
.ex-map-panel .ex-small { margin: .7rem 1rem; color: #b8cbd4; }
.ex-app .ex-map-panel button:hover { background: #365562; color: white; border-color: #7898a6; }
.ex-map-key { display: flex; justify-content: space-between; font-size: .64rem; color: #a5bfcc; margin: 1rem 1rem .5rem; }
.ex-sections { display: flex; flex-wrap: wrap; gap: .3rem; padding: 0 1rem; }
.ex-sections button { padding: .2rem .3rem; font: .6rem ui-monospace, monospace; background: #213e4b; border-color: #416170; color: #c6dbe5; }
.ex-map { padding: 0 .8rem; max-height: 480px; overflow-y: auto; }
.ex-map .ex-band { display: grid; grid-template-columns: 82px 1fr 32px; width: 100%; align-items: center; gap: .3rem; height: 16px; padding: 0; border: 0; border-radius: 1px; color: #b8cbd4; background: transparent; text-align: left; position: relative; }
.ex-band .ex-address { font: 9px ui-monospace, monospace; white-space: nowrap; }
.ex-band .ex-band-fill { height: 12px; display: block; background: #294652; border-left: 2px solid #57747f; position: relative; }
.ex-band .ex-band-fill i { position: absolute; inset: 0 auto 0 0; width: var(--density); background: #5bbbc0; min-width: 0; }
.ex-band[data-hot="true"] .ex-band-fill i { background: #efb858; }
.ex-band[aria-pressed="true"] .ex-band-fill { outline: 2px solid white; z-index: 1; }
.ex-band[data-selected="true"] .ex-band-fill::after { content: ''; position: absolute; right: -5px; top: 3px; width: 6px; height: 6px; border-radius: 50%; background: white; }
.ex-band-count { font: 9px ui-monospace, monospace; text-align: right; }
.ex-map .ex-band:hover { background: #365562; }
.ex-map-actions { display: flex; gap: .4rem; padding: .8rem 1rem 0; }
.ex-map-actions { flex-wrap: wrap; }
.ex-mobile-view { display: none; }
.ex-mobile-diff-hint { display: none; }
.ex-map-actions button { font-size: .67rem; padding: .3rem .45rem; background: #244452; color: white; border-color: #476672; }
.ex-map-accounting { border-top: 1px solid #36505c; padding: .8rem 1rem; font-size: .72rem; color: #bdd0d8; }
.ex-map-accounting strong { color: white; }
.ex-list-tools { display: flex; gap: .5rem; justify-content: space-between; align-items: end; padding: .65rem .85rem; border-bottom: 1px solid var(--line); }
.ex-list-tools select { font-size: .72rem; }
.ex-list { max-height: 650px; overflow: auto; scrollbar-width: thin; }
.ex-list .ex-change { display: block; border: 0; border-bottom: 1px solid #e4eaee; padding: .85rem .9rem; border-radius: 0; width: 100%; text-align: left; background: white; border-left: 3px solid transparent; }
.ex-list .ex-change[aria-pressed="true"] { background: #eaf4f6; border-left-color: var(--accent); }
.ex-change-title { display: block; font-size: .82rem; font-weight: 700; overflow-wrap: anywhere; line-height: 1.45; }
.ex-change-sub { display: block; font-size: .71rem; color: var(--muted); margin-top: .2rem; overflow-wrap: anywhere; }
.ex-change-foot { display: flex; justify-content: space-between; align-items: center; gap: .4rem; margin-top: .45rem; font-size: .68rem; color: var(--muted); }
.ex-change-foot strong { color: var(--ink); white-space: nowrap; }
.ex-change-meter { height: 3px; width: 100%; background: #e3ebee; margin-top: .45rem; }
.ex-change-meter i { display: block; height: 3px; width: var(--share); min-width: 2px; background: var(--stage, var(--accent)); }
.ex-range-filter { padding: .5rem .8rem; background: #fff4de; color: #785215; font-size: .72rem; }
.ex-detail { min-height: 620px; padding-bottom: 1rem; scroll-margin-top: 4rem; }
.ex-detail-head { padding: 1.15rem 1.2rem; border-bottom: 1px solid var(--line); background: linear-gradient(135deg, #f7fafb, #fff); }
.ex-detail-head h2 { font-size: 1.2rem; line-height: 1.4; margin: .5rem 0; overflow-wrap: anywhere; }
.ex-detail-head p { font-size: .85rem; color: var(--muted); margin: .4rem 0; }
.ex-detail-head .ex-action-name { color: var(--ink); font-weight: 600; font-size: .78rem; }
.ex-cost-badge { margin-left: auto; font-size: .85rem; color: var(--ink); }
.ex-brief { display: flex; flex-wrap: wrap; gap: .35rem .8rem; padding-top: .55rem; font-size: .72rem; color: var(--muted); }
.ex-brief code { font-size: .75rem; }
.ex-brief-path { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; max-width: 100%; }
.ex-badges { display: flex; flex-wrap: wrap; gap: .5rem; align-items: center; }
.ex-badge { display: inline-flex; align-items: center; gap: .35rem; padding: .18rem .45rem; border: 1px solid var(--line); border-radius: .3rem; font-size: .67rem; background: white; }
.ex-badge.passed { color: var(--ok); background: var(--ok-soft); border-color: #b5dcca; }
.ex-badge.failed, .ex-badge.reference { color: var(--bad); background: var(--bad-soft); }
.ex-detail-section { padding: 1rem 1.2rem 0; }
.ex-detail-section h3 { font-size: .83rem; margin-bottom: .6rem; }
.ex-flow { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); list-style: none; padding: 0; margin: .2rem 0; gap: .6rem; counter-reset: step; }
.ex-flow li { counter-increment: step; padding: .6rem; background: #f3f7f8; border: 1px solid #dce6e9; border-radius: .4rem; font-size: .72rem; line-height: 1.5; position: relative; }
.ex-flow li::before { content: counter(step, decimal-leading-zero); display: block; font: 700 .65rem ui-monospace, monospace; color: var(--accent); margin-bottom: .35rem; }
.ex-location { border-left: 2px solid #9dbcc5; padding: .3rem .6rem; margin: .4rem 0; font-size: .75rem; overflow-wrap: anywhere; }
.ex-location small { display: block; margin-top: .15rem; color: var(--muted); font-size: .67rem; }
.ex-location code { font-size: .82rem; }
.ex-facts { display: grid; grid-template-columns: 1fr 1fr; gap: .35rem .8rem; margin: 0; }
.ex-facts div { border-bottom: 1px solid #e7ecef; padding: .4rem 0; min-width: 0; }
.ex-facts dt { color: var(--muted); font-size: .68rem; }
.ex-facts dd { font-size: .8rem; margin: .2rem 0 0; overflow-wrap: anywhere; }
.ex-preview { border: 1px solid var(--line); border-radius: .4rem; margin-top: .65rem; overflow: hidden; }
.ex-preview > h4 { font-size: .78rem; margin: 0; padding: .55rem .7rem; background: #f4f7f9; border-bottom: 1px solid var(--line); }
.ex-diff { display: grid; grid-template-columns: 1fr 1fr; }
.ex-diff > div { min-width: 0; }
.ex-diff > div + div { border-left: 1px solid var(--line); }
.ex-diff-label { display: block; font-size: .65rem; padding: .4rem .7rem; background: #fff3ed; color: #86513d; }
.ex-diff > div:last-child .ex-diff-label { background: #eaf5ef; color: #326e51; }
.ex-diff pre { border: 0; border-radius: 0; margin: 0; padding: .55rem .7rem; font-size: .68rem; background: white; max-height: 270px; white-space: pre; tab-size: 2; }
.ex-preview > p { margin: 0; padding: .5rem .7rem; border-top: 1px solid var(--line); font-size: .67rem; color: var(--muted); }
.ex-fold { border-top: 1px solid var(--line); margin-top: .6rem; padding: .3rem 0; }
.ex-fold > :not(summary) { margin: .5rem 0; }
.ex-preview > .ex-fold { margin: 0; padding: .15rem .7rem; }
.ex-preview > .ex-fold summary { font-size: .68rem; color: var(--muted); }
.ex-file-label { display: block; padding: .4rem .7rem; background: #eaf5ef; color: #326e51; font-size: .7rem; }
.ex-preview .ex-file-source { margin: 0; border: 0; border-radius: 0; padding: .8rem; max-height: 420px; font-size: .73rem; background: #fbfdfc; white-space: pre; overflow: auto; }
.ex-assembly { min-width: 0; }
.ex-asm-controls { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: .5rem; font-size: .76rem; }
.ex-asm-controls button { font-size: .7rem; }
.ex-asm-scroll { overflow: auto; max-height: 500px; border: 1px solid var(--line); border-radius: .35rem; margin-top: .65rem; }
.ex-asm-row { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); min-width: 560px; }
.ex-asm-header { background: #edf3f5; position: sticky; top: 0; z-index: 1; font-size: .7rem; font-weight: 650; }
.ex-asm-header > div { padding: .5rem .75rem; }
.ex-asm-cell { display: grid; grid-template-columns: 55px minmax(0,1fr); gap: .3rem; min-width: 0; padding: .3rem .4rem; font: .69rem/1.5 ui-monospace, monospace; background: #fcfdfd; }
.ex-asm-cell + .ex-asm-cell { border-left: 1px solid var(--line); }
.ex-asm-cell.ex-asm-removed { background: #fff0eb; }
.ex-asm-cell.ex-asm-added { background: #eaf7ee; }
.ex-asm-offset { color: #687e89; font-size: .64rem; white-space: nowrap; padding-top: .1rem; }
.ex-asm-code { font: inherit; white-space: pre-wrap; overflow-wrap: anywhere; background: transparent; padding: 0; border: 0; border-radius: 0; box-shadow: none; }
.ex-source-diff .ex-asm-cell { grid-template-columns: 44px minmax(0,1fr); }
.ex-diff-mark { display: inline-block; width: 1.2em; font-weight: 700; }
.ex-encoding-change { grid-column: 1 / -1; padding: .2rem .6rem; color: #765319; background: #fff5df; font-size: .65rem; }
.ex-preview-tabs { display: flex; flex-wrap: wrap; gap: .35rem; }
.ex-preview-tabs button { font-size: .72rem; }
.ex-preview-tabs button[aria-pressed="true"] { background: #173e4b; color: white; }
.ex-preview-count { margin: .4rem 0; font-size: .7rem; color: var(--muted); }
.ex-asm-selected { box-shadow: inset 3px 0 #5b8cbb; }
.ex-asm-gap { text-align: center; padding: .4rem; background: #f1f5f7; color: var(--muted); font-size: .65rem; min-width: 560px; }
.ex-preview-tools { display: grid; gap: .5rem; }
.ex-preview-tools input { width: 100%; padding: .5rem; border: 1px solid var(--line); border-radius: .3rem; font-size: .75rem; }
.ex-preview-tools select { width: 100%; font-size: .73rem; text-overflow: ellipsis; }
.ex-source-paths { max-height: 180px; overflow: auto; overflow-wrap: anywhere; }
.ex-detail details { font-size: .78rem; }
.ex-detail details summary { cursor: pointer; font-weight: 650; padding: .5rem 0; }
.ex-detail details pre { max-height: 350px; font-size: .67rem; }
.ex-related { display: flex; gap: .4rem; flex-wrap: wrap; }
.ex-related button { font-size: .7rem; max-width: 100%; overflow-wrap: anywhere; text-align: left; }
.ex-byte-track { display: flex; gap: 1px; height: 25px; margin: .5rem 0; background: #e6edef; }
.ex-byte-track span { flex: 1; background: #e6edef; }
.ex-byte-track span.changed { background: #328e94; }
.ex-empty { padding: 2rem 1rem; color: var(--muted); font-size: .85rem; }
.ex-operations { margin-top: 1.2rem; }
.ex-operations > summary { cursor: pointer; font-weight: 650; font-size: .9rem; }
.ex-operations > summary::before { content: '▸'; }
.ex-operations[open] > summary::before { content: '▾'; }
.ex-operations > summary > span:first-of-type { flex: 1; }
.ex-operations > p { margin: .8rem 1rem; }
#ex-operations { padding: 0 1rem 1rem; }
#ex-operations details { border-bottom: 1px solid var(--line); padding: .5rem 0; font-size: .8rem; }
#ex-operations summary { cursor: pointer; }
#ex-operations pre { max-height: 220px; font-size: .7rem; }
.ex-coverage { font-size: .78rem; color: var(--muted); margin-top: 1.3rem; padding: 1rem; border: 1px solid var(--line); border-radius: .4rem; }
.ex-coverage summary { color: var(--ink); font-weight: 650; cursor: pointer; }
.ex-coverage p { max-width: 100ch; }
.ex-coverage li { margin: .4rem 0; }
.ex-fallback { margin-top: 1rem; }
@media (min-width: 1250px) { .ex-map-panel, .ex-list-panel { position: sticky; top: 4rem; } }
@media (max-width: 1150px) { .ex-workspace { grid-template-columns: 220px minmax(240px, 1fr); } .ex-detail { grid-column: 1 / -1; } .ex-map { max-height: 360px; } .ex-list { max-height: 570px; } }
@media (max-width: 650px) {
  body.ex-mode main { width: calc(100% - 1.2rem); }
  body.ex-mode .section-nav { overflow-x: auto; }
  body.ex-mode .section-nav ul { flex-wrap: nowrap; }
  .ex-heading { display: block; } .ex-back { display: inline-block; margin-top: .7rem; }
  .ex-toolbar { flex-wrap: wrap; padding: .8rem; } .ex-toolbar > label:first-child { min-width: 0; flex: 1; }
  .ex-search { flex-basis: 100%; order: 3; } .ex-metrics { grid-template-columns: 1fr 1fr; }
  .ex-metric { padding: .7rem .8rem; } .ex-workspace { display: block; }
  .ex-map-panel, .ex-list-panel { margin-bottom: .8rem; } .ex-map { max-height: 180px; }
  .ex-map .ex-band { grid-template-columns: 95px 1fr 50px; height: 28px; }
  .ex-mobile-view { display: flex; gap: .5rem; margin-bottom: .8rem; }
  .ex-mobile-view button { flex: 1; font-size: .75rem; }
  .ex-mobile-diff-hint { display: block; font-size: .7rem; color: var(--muted); margin: .4rem .7rem; }
  .ex-app:not(.ex-mobile-map-open) .ex-map-panel { display: none; }
  .ex-list { max-height: 350px; } .ex-diff { grid-template-columns: 1fr; }
  .ex-diff > div + div { border-left: 0; border-top: 1px solid var(--line); }
  .ex-flow { grid-template-columns: 1fr; } .ex-flow li::before { display: inline; margin-right: .5rem; }
}
@media print {
  .ex-toolbar, .ex-map-actions, .ex-stage-row, .ex-list-tools, .ex-back { display: none; }
  .ex-workspace { display: block; } .ex-map-panel { display: none; }
  .ex-list { max-height: none; } .ex-detail { break-before: page; }
  .ex-diff pre { max-height: none; white-space: pre-wrap; }
}
""".strip()


EXPLORER_SCRIPT = r"""
(async () => {
  const root = document.getElementById('binary-explorer');
  if (!root) return;
  const $ = id => document.getElementById('ex-' + id);
  const payload = document.getElementById('explorer-data');
  let data;
  try {
    const bytes=Uint8Array.from(atob(payload.textContent.trim()),c=>c.charCodeAt(0));
    const stream=new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'));
    data=JSON.parse(await new Response(stream).text());
    payload.textContent='';
  } catch (_) {
    root.querySelector('.ex-fallback > p').textContent='The interactive explorer could not be loaded in this browser. The complete inventory below and the build report remain available.';
    return;
  }
  const items = data.interventions || [];
  const targets = data.targets || [];
  const stages = {source:'Source edits',compile:'Compiler setup',object:'Compiled code',link:'Link layout',image:'Image details',reference:'Reference bytes'};
  const spaces = {va:'Binary address',file:'File offset','reference-va':'Reference address','debug-va':'Debug address','linked-va':'Before image edits',function:'Function offset',artifact:'Object offset','supplemental-file':'Comparison-file offset'};
  const nf = new Intl.NumberFormat('en', {maximumFractionDigits: 1});
  const num = n => nf.format(n || 0);
  const hex = n => '0x' + Number(n).toString(16).padStart(8, '0');
  const txt = value => typeof value === 'string' ? value : JSON.stringify(value, null, 2);
  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; };
  const button = (label, action, cls) => { const b = el('button', cls, label); b.type = 'button'; b.addEventListener('click', action); return b; };
  const stageColor = (node, stage) => node.style.setProperty('--stage', 'var(--' + (Object.hasOwn(stages, stage) ? stage : 'object') + ')');
  const byId = new Map(items.map(i => [i.id, i]));
  const state = {target: [...targets].sort((a,b) => b.cost-a.cost)[0]?.id || '', stage:'all', selected:null, range:null, zoom:null};
  const target = () => targets.find(t => t.id === state.target) || {};
  const targetItems = () => items.filter(i => i.target === state.target);
  // A public symbol can establish a start without an extent. Use a one-address
  // marker for picking; never present that marker width as the function size.
  const locs = item => (item.locations || []).filter(l => l.space === $('space').value && Number.isFinite(l.start)).map(l=>({...l,end:Number.isFinite(l.end)?l.end:l.start+1}));
  const overlaps = (l,r) => l.start < r[1] && l.end > r[0];
  const firstAddress = item => Math.min(...locs(item).map(l => l.start));
  const compactName = i => i.display_function || i.function || i.title || i.id;
  const primarySource = i => (i.source_paths||[]).find(p=>/\.(?:c|cc|cpp|cxx)$/i.test(p))||i.source_paths?.[0];
  const mapped = i => locs(i).length > 0;
  const preferredLocation = i => (i.locations||[]).find(l=>l.space===$('space').value&&l.relation!=='changed')||(i.locations||[]).find(l=>l.space===$('space').value)||(i.locations||[]).find(l=>l.space==='va')||(i.locations||[]).find(l=>l.space==='file')||(i.locations||[])[0];
  function showOnMap(location) {
    if(!['va','file','reference-va','debug-va','linked-va'].includes(location.space))return;
    $('space').value=location.space;state.range=null;state.zoom=null;
    $('location').value='all';if(/^0x[0-9a-f]+$/i.test($('search').value.trim()))$('search').value='';
    root.querySelector('.ex-app').classList.add('ex-mobile-map-open');$('toggle-map').textContent='Hide binary map';$('toggle-map').setAttribute('aria-expanded','true');
    render();root.querySelector('.ex-map-panel').scrollIntoView({block:'start'});
  }
  const sections = () => $('space').value === 'debug-va' ? (target().debug_sections||[]) : ['reference-va','linked-va'].includes($('space').value) ? [] : (target().sections||[]);
  function sectionRange(s) {
    return $('space').value === 'file' ? [s.file_offset, s.file_offset + s.file_size] : [s.va, s.va + s.size];
  }
  function fullRange() {
    if ($('space').value === 'file') return [0, target().size || 1];
    const ss = sections().map(sectionRange).filter(s => s.every(Number.isFinite));
    const ls = targetItems().flatMap(locs);
    const base=$('space').value==='va'?target().image_base:$('space').value==='debug-va'?target().debug_image_base:undefined;
    return [Math.min(...ss.map(s=>s[0]), ...ls.map(l=>l.start), base ?? Infinity) || 0, Math.max(...ss.map(s=>s[1]), ...ls.map(l=>l.end), 1)];
  }
  function route() {
    const path = location.hash.slice(1).split('/');
    const active = path[0] === 'binary-explorer';
    document.getElementById('report-summary').hidden = active;
    root.hidden = !active;
    document.body.classList.toggle('ex-mode', active);
    if (!active) {
      const destination=document.getElementById(path[0]);
      if(destination)requestAnimationFrame(()=>destination.scrollIntoView({block:'start'}));
      return;
    }
    let id = null;
    try { id = path[1] ? decodeURIComponent(path[1]) : null; } catch (_) { /* Invalid URL fragment. */ }
    if (id && byId.has(id)) {
      const item = byId.get(id);
      if (state.target !== item.target) { state.target = item.target; $('target').value = state.target; state.zoom = null; state.range = null; }
      state.selected = id;
      state.stage = 'all'; $('search').value = ''; $('location').value = 'all';
      state.range = null;
    }
    render();
    requestAnimationFrame(()=>{if(id&&byId.has(id)&&innerWidth<1150){$('detail').focus({preventScroll:true});$('detail').scrollIntoView({block:'start'});}else root.scrollIntoView({block:'start'});});
  }
  function select(item, focus = false) {
    state.selected = item.id;
    history.replaceState(null, '', '#binary-explorer/' + encodeURIComponent(item.id));
    renderList(); renderMap(); renderDetail();
    if (focus) { $('detail').focus({preventScroll:true}); if (innerWidth < 1150) $('detail').scrollIntoView({block:'start', behavior:'auto'}); }
  }
  function matching() {
    const q = $('search').value.trim().toLowerCase();
    const address = /^0x[0-9a-f]+$/i.test(q) ? Number.parseInt(q.slice(2),16) : null;
    const result = targetItems().filter(i => {
      if (state.stage !== 'all' && i.stage !== state.stage) return false;
      if ($('location').value === 'mapped' && !mapped(i)) return false;
      if ($('location').value === 'unmapped' && mapped(i)) return false;
      if (state.range && !locs(i).some(l=>overlaps(l,state.range))) return false;
      if (address !== null) return locs(i).some(l=>l.start <= address && l.end > address);
      return !q || [i.id,i.function,i.display_function,i.tu,i.title,i.family,i.cost_class,...(i.source_paths||[])].filter(Boolean).join(' ').toLowerCase().includes(q);
    });
    const sort = $('sort').value;
    result.sort((a,b) => (sort === 'address' ? firstAddress(a)-firstAddress(b) : sort === 'name' ? compactName(a).localeCompare(compactName(b)) : b.cost-a.cost) || a.id.localeCompare(b.id));
    return result;
  }
  function renderMetrics() {
    const all = targetItems();
    const total = all.reduce((s,i)=>s+i.cost,0);
    const located = all.filter(mapped);
    const locatedCost = located.reduce((s,i)=>s+i.cost,0);
    const values = [['Recorded changes',num(all.length), 'All interventions included'],['Intervention cost',num(total)+' pts','Effort score · not runtime overhead'],['Located in these coordinates',num(located.length)+' / '+num(all.length),num(locatedCost)+' pts across the whole binary'],['Build result',target().byte_exact?'Exact match':'Not byte-identical','Compared with the reference binary']];
    $('metrics').replaceChildren(...values.map(([label,value,note]) => {const n=el('div','ex-metric');n.append(el('span','',label),el('strong','',value),el('small','',note));return n;}));
  }
  function renderStages() {
    const all = targetItems();
    $('stages').replaceChildren(...Object.entries({all:'All changes',...stages}).filter(([s])=>s==='all'||all.some(i=>i.stage===s)).map(([s,label])=>{
      const count = s==='all'?all.length:all.filter(i=>i.stage===s).length;
      const b=button(label+' · '+num(count),()=>{state.stage=s; render();});
      if(s!=='all') {const dot=el('i','ex-dot');stageColor(dot,s); b.prepend(dot);}
      b.setAttribute('aria-pressed',String(state.stage===s));return b;
    }));
  }
  function renderMap() {
    const all=targetItems();
    const extent=state.zoom || fullRange();
    if (!extent.every(Number.isFinite) || extent[1] <= extent[0]) {
      $('map').replaceChildren(el('p','ex-small','No locations recorded in this coordinate space.'));
      $('map-caption').textContent=(spaces[$('space').value]||'Address')+' · no recorded extent';
      $('sections').replaceChildren();
      $('map-accounting').replaceChildren(el('div','','0 pts located on map'),el('div','',num(all.reduce((sum,i)=>sum+i.cost,0))+' pts outside map'));
      $('zoom-out').disabled=!state.zoom;$('clear-range').disabled=!state.range;$('zoom-range').disabled=!state.range;
      return;
    }
    const bins=32, step=Math.max(1,2**Math.ceil(Math.log2((extent[1]-extent[0])/bins)));
    const bands=Array.from({length:bins},(_,j)=>({start:extent[0]+j*step,end:Math.min(extent[1],extent[0]+(j+1)*step),cost:0,items:[]})).filter(b=>b.start<b.end);
    const visible=new Set(matching().map(i=>i.id));
    for(const i of all) {
      const locations=locs(i);
      for(const b of bands) {
        const hits=locations.filter(l=>overlaps(l,[b.start,b.end]));
        if(!hits.length)continue;
        b.items.push(i);
        for(const l of hits)b.cost+=i.cost/locations.length*(Math.min(l.end,b.end)-Math.max(l.start,b.start))/(l.end-l.start);
      }
    }
    const max=Math.max(...bands.map(b=>b.cost),1);
    $('map').replaceChildren(...bands.map((b,j)=>{
      const selected=byId.get(state.selected);
      const section=sections().find(s=>overlaps({start:sectionRange(s)[0],end:sectionRange(s)[1]},[b.start,b.end]));
      const label=hex(b.start)+'\u2013'+hex(b.end)+' · '+(section?.name||'')+' · '+num(b.items.length)+' changes · '+num(b.cost)+' allocated points';
      const n=button('',()=>{ if(state.range && state.range[0]===b.start && state.range[1]===b.end) {state.zoom=[b.start,b.end]; state.range=null;} else {state.range=[b.start,b.end];} render(); },'ex-band');
      n.title=label;n.setAttribute('aria-label',label);n.setAttribute('aria-pressed',String(Boolean(state.range&&overlaps({start:b.start,end:b.end},state.range))));
      n.dataset.hot=String(b.cost>max*.66);n.dataset.selected=String(Boolean(selected&&locs(selected).some(l=>overlaps(l,[b.start,b.end]))));
      const address=el('span','ex-address',j%4===0?hex(b.start):section&&sectionRange(section)[0]>=b.start?section.name:'');
      const fill=el('span','ex-band-fill');fill.style.setProperty('--density',(b.cost/max*100)+'%');fill.append(el('i'));
      if(b.items.length && !b.items.some(i=>visible.has(i.id))) fill.style.opacity='.35';
      n.append(address,fill,el('span','ex-band-count',b.items.length?String(b.items.length):''));return n;
    }));
    $('map-caption').textContent=(spaces[$('space').value]||'Address')+' · '+hex(extent[0])+'\u2013'+hex(extent[1]);
    $('sections').replaceChildren(...sections().map(s=>button(s.name,()=>{state.zoom=sectionRange(s);state.range=null;render();})));
    const off=all.filter(i=>!mapped(i));
    $('map-accounting').replaceChildren(el('div','',num(bands.reduce((s,b)=>s+b.cost,0))+' pts allocated to the visible range'),el('div','',num(off.reduce((s,i)=>s+i.cost,0))+' pts without locations in these coordinates'));
    $('zoom-out').disabled=!state.zoom;$('clear-range').disabled=!state.range;$('zoom-range').disabled=!state.range;
  }
  function renderList() {
    const rows=matching();
    $('result-count').textContent=num(rows.length)+' / '+num(targetItems().length)+' changes';
    $('range-filter').hidden=!state.range;
    if(state.range) $('range-filter').textContent='Range: '+hex(state.range[0])+'\u2013'+hex(state.range[1]);
    const max=Math.max(...targetItems().map(i=>i.cost),1);
    const scroll=$('list').scrollTop;
    $('list').replaceChildren(...rows.map(i=>{
      const b=button('',()=>select(i,true),'ex-change');b.setAttribute('aria-pressed',String(i.id===state.selected));stageColor(b,i.stage);
      b.append(el('span','ex-change-title',compactName(i)),el('span','ex-change-sub',i.function?i.title:i.family==='source_overlay_graph'?num(i.source_paths?.length)+' source files':(primarySource(i)||i.tu||'Whole target')));
      const foot=el('span','ex-change-foot');const a=firstAddress(i);
      const other=preferredLocation(i);
      foot.append(el('span','',Number.isFinite(a)?(spaces[$('space').value]||'')+' '+hex(a):other?(spaces[other.space]||other.space)+' '+hex(other.start):i.function?'Address unavailable':'Whole-build change'),el('strong','',num(i.cost)+' pts'));
      const meter=el('div','ex-change-meter');const bar=el('i');meter.style.setProperty('--share',(i.cost/max*100)+'%');meter.append(bar);b.append(foot,meter);return b;
    }));
    if(!rows.length) $('list').append(el('p','ex-empty','No changes match this view. Clear the range or reset the filters.'));
    $('list').scrollTop=scroll;
  }
  function locationsBlock(locations) {
    const block=el('div');
    const primary=locations.filter(l=>l.relation!=='changed'), changes=locations.filter(l=>l.relation==='changed');
    const ordered=[...primary,...changes];
    const more=el('details');more.append(el('summary','',num(Math.max(0,ordered.length-3))+' more recorded ranges'));
    for(const [index,l] of ordered.entries()) {
      const row=el('div','ex-location');row.append(el('code','',(spaces[l.space]||l.space)+' '+hex(l.start)+(Number.isFinite(l.end)?'\u2013'+hex(l.end):' · start only')),el('small','',[l.label,l.basis,l.relation==='beneficiary'?'Shared destination; no additional charge':''].filter(Boolean).join(' · ')));block.append(row);
      if(index>=3) more.append(row);
    }
    if(ordered.length>3)block.append(more);
    if(!locations.length) block.append(el('p','ex-small','No exact address was recorded. This change remains in the inventory and cost total.'));
    return block;
  }
  function factsBlock(pairs) {
    const dl=el('dl','ex-facts');
    for(const [label,value] of pairs){const d=el('div');d.append(el('dt','',label),el('dd','',value));dl.append(d);}
    return dl;
  }
  function fold(label, ...children) {
    const d=el('details','ex-fold');d.append(el('summary','',label),...children);return d;
  }
  function sourceBlock(rendering) {
    const scroll=el('div','ex-asm-scroll ex-source-diff'),header=el('div','ex-asm-row ex-asm-header');header.append(el('div','','Before'),el('div','','After'));scroll.append(header);
    for(const r of rendering.rows||[]) {
      if(r.kind==='gap'){scroll.append(el('div','ex-asm-gap',num(r.count)+(r.reason==='limit'?' rows omitted by the preview limit':' unchanged lines hidden')));continue;}
      const row=el('div','ex-asm-row');
      for(const side of ['before','after']) {
        const value=r[side],changed=r.kind!=='equal',cell=el('div','ex-asm-cell '+(changed&&value?(side==='before'?'ex-asm-removed':'ex-asm-added'):''));
        const code=el('code','ex-asm-code');if(value){code.append(el('span','ex-diff-mark',changed?(side==='before'?'\u2212':'+'):' '),document.createTextNode(value.text+(value.text_truncated?' …':'')));}
        cell.append(el('span','ex-asm-offset',value?(value.line??'·'+value.local_line):''),code);row.append(cell);
      }
      if(r.kind==='replace'&&r.before?.text===r.after?.text&&r.before?.line_ending!==r.after?.line_ending)row.append(el('span','ex-encoding-change','Line ending: '+r.before.line_ending+' → '+r.after.line_ending));
      scroll.append(row);
    }
    const box=el('div');box.append(el('p','ex-mobile-diff-hint','Swipe sideways to compare both sides ↔'),scroll);
    if(rendering.truncated)box.append(el('p','ex-small','Source preview limited; omitted content is marked in the comparison.'));
    if(rendering.undecodable_bytes_escaped)box.append(el('p','ex-small','Unrecognized text bytes are shown as escaped values.'));
    return box;
  }
  function previewBox(p, i) {
    const box=el('div','ex-preview');box.append(el('h4','',p.title));
    if(i.family==='source_overlay_graph'&&p.action_id) {
      const kind=p.operation==='generated_tus'?'generated_translation_unit':p.operation==='link_admissions'?'link_admission':'source_overlay_edit';
      const unit=i.units.find(u=>u.kind===kind);
      if(unit)box.append(el('p','',num(unit.unit_cost)+' points · included in this recipe\u2019s '+num(i.cost)+' points'));
    }
    if(p.operation==='generated_tus' && p.build_context) {
      const available=p.content_available===true;
      const lines=String(p.after||'').split('\n').length-(String(p.after||'').endsWith('\n')?1:0);
      const label=p.content_complete?'Complete source · '+num(lines)+' lines':available?'Source excerpt':'Source content';
      box.append(el('span','ex-file-label',label),el('pre','ex-file-source',p.after||'Source contents were not captured.'));
      const placement=Object.entries(p.build_context).filter(([key])=>['after','before','ordinal'].includes(key)).map(([key,value])=>[key==='after'?'Compiled after':key==='before'?'Compiled before':'Build position',txt(value)]);
      if(placement.length)box.append(fold('Position in the build',factsBlock(placement)));
    } else if(p.source_rendering?.rows?.some(r=>r.kind!=='gap')) {
      box.append(sourceBlock(p.source_rendering));
    } else {
      const diff=el('div','ex-diff');
      for(const [label,value] of [['Before',p.before],['After',p.after]]) {const col=el('div');col.append(el('span','ex-diff-label',label),el('pre','',value||'—'));diff.append(col);}
      box.append(diff);
    }
    if(p.note)box.append(fold('About this preview',el('p','ex-small',p.note)));
    return box;
  }
  function previewGallery(parent, previews, i) {
    if(previews.length<=2){for(const p of previews)parent.append(previewBox(p,i));return;}
    const category=p=>p.operation==='generated_tus'?'generated':p.action_id?'operations':p.preview_kind==='file'||p.source_rendering?'files':'other';
    const groups=[['files','File comparisons'],['generated','Generated files'],['operations','Individual edits'],['other','Other changes']].filter(([key])=>previews.some(p=>category(p)===key));
    let active=groups[0][0];
    const controls=el('div','ex-preview-tools'),tabs=el('div','ex-preview-tabs'),search=el('input'),label=el('label','','Choose a file or edit'),picker=el('select'),holder=el('div');
    search.type='search';search.placeholder='Find a source file or operation';search.setAttribute('aria-label','Filter source renderings');picker.setAttribute('aria-label','Choose a rendering');label.append(picker);controls.append(search,label);parent.append(controls,holder);
    const show=()=>{holder.replaceChildren();if(picker.value!=='')holder.append(previewBox(previews[Number(picker.value)],i));else holder.append(el('p','ex-small','No source files or operations match this filter.'));};
    const fill=()=>{tabs.replaceChildren(...groups.map(([key,title])=>{const b=button(title+' · '+num(previews.filter(p=>category(p)===key).length),()=>{active=key;fill();});b.setAttribute('aria-pressed',String(active===key));return b;}));picker.replaceChildren(...previews.flatMap((p,index)=>{if(category(p)!==active||!(p.title+' '+(p.source_path||'')).toLowerCase().includes(search.value.toLowerCase()))return [];const option=el('option','',p.title);option.value=String(index);return [option];}));show();};
    if(groups.length>1)controls.prepend(tabs);
    if(i.family==='source_overlay_graph'&&groups.some(([key])=>key==='files'))controls.append(el('p','ex-preview-count','File comparisons collect the edits below. They do not add another charge.'));
    search.addEventListener('input',fill);picker.addEventListener('change',show);fill();
  }
  function assemblyBlock(assembly) {
    const box=el('div','ex-assembly'),rows=assembly.rows||[],controls=el('div','ex-asm-controls'),scroll=el('div','ex-asm-scroll');
    const changed=rows.filter(r=>r.kind!=='equal').length;
    controls.append(el('strong','',changed?num(changed)+' changed instruction rows':'No decoded instruction changes'));
    let expanded=false;
    const toggle=button('Show full captured listing',()=>{expanded=!expanded;toggle.textContent=expanded?'Show changed regions':'Show full captured listing';draw();});
    controls.append(toggle);box.append(controls,el('p','ex-small','32-bit x86 · offsets within this function · before linking'),el('p','ex-mobile-diff-hint','Swipe sideways to compare both sides ↔'),scroll);
    if(!changed)box.append(el('p','ex-small','The decoded instructions are unchanged. This operation can still select a different source for those bytes or change data within the function.'));
    const undecoded=[['Before',assembly.before],['After',assembly.after]].filter(([,side])=>side?.undecoded_ranges?.length);
    if(undecoded.length) {
      const count=assembly.undecoded_byte_changes;
      box.append(el('p','ex-small',typeof count==='number'?(count?num(count)+' additional byte changes outside decoded instructions.':'Bytes outside decoded instructions are unchanged.'):'Some function bytes are data or could not be decoded; their offsets cannot be aligned after this size change.'));
      const ranges=fold('Data and undecoded bytes');
      for(const [name,side] of undecoded){ranges.append(el('h4','',name+' · '+num(side.decoded_bytes)+' / '+num(side.body_size)+' bytes decoded'));for(const p of side.undecoded_previews||[])ranges.append(el('pre','',hex(p.start)+'\u2013'+hex(p.end)+'\n'+p.bytes+(p.truncated?'\n… byte preview limited':'')));}
      box.append(ranges);
    }
    if(assembly.truncated)box.append(el('p','ex-small','This is a partial instruction listing. See technical details for capture limits.'));
    function cell(inst,kind,side) {
      const node=el('div','ex-asm-cell '+(kind==='equal'||!inst?'':side==='before'?'ex-asm-removed':'ex-asm-added'));
      if(!inst){node.append(el('span','ex-asm-offset',''),el('code','ex-asm-code',''));return node;}
      const offset=Number.isFinite(inst.offset)?'+0x'+Number(inst.offset).toString(16).padStart(4,'0'):'';
      const code=el('code','ex-asm-code');code.append(el('span','ex-diff-mark',kind==='equal'?' ':side==='before'?'\u2212':'+'),document.createTextNode(inst.text||[inst.mnemonic,inst.operands].filter(Boolean).join(' ')));
      node.append(el('span','ex-asm-offset',offset),code);
      if(inst.bytes)node.title='Instruction bytes: '+inst.bytes;
      return node;
    }
    function draw() {
      const header=el('div','ex-asm-row ex-asm-header');header.append(el('div','','Before'),el('div','','After'));scroll.replaceChildren(header);
      const shown=new Set();
      if(expanded)rows.forEach((_,index)=>shown.add(index));
      else {rows.forEach((r,index)=>{if(r.kind!=='equal')for(let j=Math.max(0,index-2);j<=Math.min(rows.length-1,index+2);j++)shown.add(j);});if(!shown.size)for(let j=0;j<Math.min(rows.length,8);j++)shown.add(j);}
      let previous=-1;
      for(const index of [...shown].sort((a,b)=>a-b)) {
        if(index>previous+1)scroll.append(el('div','ex-asm-gap',num(index-previous-1)+' unchanged rows hidden'));
        const r=rows[index],line=el('div','ex-asm-row');if(r.selected){line.classList.add('ex-asm-selected');line.title='Within a selected instruction range';}line.append(cell(r.before,r.kind,'before'),cell(r.after,r.kind,'after'));
        if(r.kind==='replace'&&r.before?.text===r.after?.text&&r.before?.bytes!==r.after?.bytes)line.append(el('span','ex-encoding-change','Same instruction text · encoding changed: '+r.before.bytes+' → '+r.after.bytes));
        scroll.append(line);previous=index;
      }
      if(previous<rows.length-1)scroll.append(el('div','ex-asm-gap',num(rows.length-previous-1)+' unchanged rows hidden'));
    }
    draw();return box;
  }
  function renderDetail() {
    const i=byId.get(state.selected),panel=$('detail');panel.replaceChildren();
    if(!i || i.target!==state.target){panel.append(el('p','ex-empty','Select a change to see what it does.'));return;}
    const head=el('div','ex-detail-head'),badges=el('div','ex-badges'),stage=el('span','ex-badge',stages[i.stage]||i.stage);
    stageColor(stage,i.stage);stage.prepend(el('i','ex-dot'));badges.append(stage,el('strong','ex-cost-badge',num(i.cost)+' pts'));
    if(i.status==='failed')badges.append(el('span','ex-badge failed','Checks failed'));
    if(i.status==='missing')badges.append(el('span','ex-badge failed','Evidence missing'));
    if(i.kind==='legacy.oracle_install')badges.append(el('span','ex-badge reference','Reference bytes · authenticity exception'));
    head.append(badges,el('h2','',compactName(i)));
    if(i.function)head.append(el('p','ex-action-name',i.title));
    head.append(el('p','',i.summary));
    const locations=i.locations||[],preferred=preferredLocation(i);
    const brief=el('div','ex-brief');
    if(preferred){brief.append(el('code','',(spaces[preferred.space]||preferred.space)+' '+hex(preferred.start)+(Number.isFinite(preferred.end)?'\u2013'+hex(preferred.end):' · start only')));if(['va','file','reference-va','debug-va','linked-va'].includes(preferred.space))brief.append(button('Show on map',()=>showOnMap(preferred),'ex-small'));}
    else brief.append(el('span','',i.function?'Final address not captured':'Shared change · no single binary address'));
    if(i.source_paths?.length){const path=el('span','ex-brief-path',i.source_paths.length===1?i.source_paths[0]:num(i.source_paths.length)+' source files');path.title=i.source_paths.join('\n');brief.append(path);}
    head.append(brief);panel.append(head);
    const section=title=>{const s=el('div','ex-detail-section');s.append(el('h3','',title));panel.append(s);return s;};
    const change=section('What changed'),primary=(i.previews||[]).filter(p=>p.presentation!=='technical'),technical=(i.previews||[]).filter(p=>p.presentation==='technical');
    if(i.assembly) {
      change.append(assemblyBlock(i.assembly));
      if(primary.length){const extra=fold('Source and other changes');previewGallery(extra,primary,i);change.append(extra);}
    } else if(primary.length)previewGallery(change,primary,i);
    else change.append(el('p','ex-small','No code or source comparison was captured for this operation. Its recorded details are available below.'));
    const cost=fold('Cost breakdown',factsBlock([['This change',num(i.cost)+' points'],['Share of this binary',num(i.cost/Math.max(1,target().cost)*100)+'%'],...i.units.map(u=>[u.kind.replaceAll('_',' '),num(u.count)+' \u00d7 '+num(u.unit_cost)+' = '+num(u.cost)+' pts'])]));
    const flow=el('ol','ex-flow');for(const step of i.steps||[])flow.append(el('li','',txt(step)));
    const explain=el('div','ex-detail-section');explain.append(cost,fold('How it reaches the binary',flow));panel.append(explain);
    const relatedIds=[...(i.dependencies||[]),...items.filter(other=>(other.dependencies||[]).includes(i.id)).map(other=>other.id)];
    if(relatedIds.length){const s=section('Connected changes'),buttons=el('div','ex-related');for(const id of new Set(relatedIds)){const other=byId.get(id);if(!other)continue;const name=other.display_function||primarySource(other)?.split('/').pop()||other.title;const b=button(((i.dependencies||[]).includes(id)?'Uses: ':'Used by: ')+name,()=>{state.target=other.target;$('target').value=state.target;state.stage='all';state.range=null;state.zoom=null;$('search').value='';$('location').value='all';select(other);render();});b.title=other.title+' · '+other.id;buttons.append(b);}s.append(buttons);}
    const details=fold('Technical details'),detailsWrap=el('div','ex-detail-section');detailsWrap.append(details);panel.append(detailsWrap);
    details.append(el('h4','','Recorded locations'),locationsBlock(locations));
    if(i.source_paths?.length){const paths=el('div','ex-source-paths');for(const path of i.source_paths)paths.append(el('p','ex-small',path));details.append(fold('Source files',paths));}
    if(i.body_size)details.append(el('p','ex-small',num(i.body_size)+' bytes in the recorded function body'+(i.changed_bytes!==null&&i.changed_bytes!==undefined?' · '+num(i.changed_bytes)+' changed bytes':'')));
    if(i.facts?.length)details.append(fold('Measurements and inputs',factsBlock(i.facts.map(f=>[f.label,txt(f.value)]))));
    if(technical.length){const traces=fold('Byte positions and supporting records');previewGallery(traces,technical,i);details.append(traces);}
    if(i.assembly?.notes?.length)details.append(fold('Assembly capture notes',...i.assembly.notes.map(n=>el('p','ex-small',txt(n)))));
    const checks=fold(num(i.checks?.length)+' verification checks');for(const check of i.checks||[])checks.append(el('p','ex-small',(check.passed?'✓ ':'\u00d7 ')+check.name+(check.detail?' — '+check.detail:'')));details.append(checks,fold(i.family||i.kind,el('pre','',txt(i.detail||{}))),el('p','ex-small','Intervention: '+i.id));
    if(i.tu)details.append(el('p','ex-small','Source unit: '+i.tu));
    const link=button('Link to this change',()=>{const input=el('input');input.value=location.href;input.setAttribute('aria-label','Link to selected change');input.readOnly=true;link.replaceWith(input);input.select();});link.className='ex-small';details.append(link);
  }
  function renderOperations() {
    const ops=(data.operations||[]).filter(o=>o.target===state.target || o.targets?.includes(state.target));
    $('operation-count').textContent=num(ops.length)+' records';
    $('operations').replaceChildren(...ops.map(o=>{const path=o.detail?.source_path||o.artifact||'',d=el('details');d.append(el('summary','',o.title+(path?' · '+path.split('/').pop():'')),el('p','ex-small',o.summary));if(o.locations?.length)d.append(locationsBlock(o.locations));if(o.detail?.orders?.length){const groups=el('div');for(const order of o.detail.orders)groups.append(el('pre','',order.join('\n↓\n')));d.append(fold('Resulting section order',groups));}if(o.detail)d.append(fold('Recorded details',el('pre','',txt(o.detail))));return d;}));
    if(!ops.length)$('operations').append(el('p','ex-small','No additional build adjustments were recorded for this binary.'));
  }
  function render() {
    for(const option of $('space').options){const available=['va','file'].includes(option.value)||targetItems().some(i=>(i.locations||[]).some(l=>l.space===option.value));option.hidden=!available;option.disabled=!available;}
    if($('space').selectedOptions[0]?.disabled){$('space').value='va';state.range=null;state.zoom=null;}
    const rows=matching();
    if(!rows.some(i=>i.id===state.selected)) state.selected=rows[0]?.id||null;
    if(state.selected)history.replaceState(null,'','#binary-explorer/'+encodeURIComponent(state.selected));
    renderMetrics();renderStages();renderList();renderMap();renderDetail();renderOperations();
  }
  for(const t of targets){const option=el('option','',t.id+' · '+num(t.size)+' B');option.value=t.id;$('target').append(option);}
  $('target').value=state.target;
  $('target').addEventListener('change',()=>{state.target=$('target').value;state.range=null;state.zoom=null;state.selected=null;history.replaceState(null,'','#binary-explorer');render();});
  $('space').addEventListener('change',()=>{state.range=null;state.zoom=null;render();});
  for(const id of ['search','sort','location']) $(id).addEventListener(id==='search'?'input':'change',render);
  $('reset').addEventListener('click',()=>{state.stage='all';state.range=null;state.zoom=null;$('search').value='';$('location').value='all';$('sort').value='cost';render();});
  $('zoom-out').addEventListener('click',()=>{state.zoom=null;state.range=null;render();});
  $('clear-range').addEventListener('click',()=>{state.range=null;render();});
  $('zoom-range').addEventListener('click',()=>{if(state.range){state.zoom=state.range;state.range=null;render();}});
  $('toggle-map').addEventListener('click',()=>{const open=root.querySelector('.ex-app').classList.toggle('ex-mobile-map-open');$('toggle-map').textContent=open?'Hide binary map':'Show binary map';$('toggle-map').setAttribute('aria-expanded',String(open));});
  $('jump-detail').addEventListener('click',()=>{$('detail').focus({preventScroll:true});$('detail').scrollIntoView({block:'start'});});
  const coverage=el('ul');
  const notices=new Map();
  for(const message of data.diagnostics||[]) {
    const label=typeof message==='string'?message:[message.message,message.target_id].filter(Boolean).join(' · ');
    notices.set(label,(notices.get(label)||0)+1);
  }
  for(const [label,count] of notices)coverage.append(el('li','',label+(count>1?' · '+num(count)+' records':'')));
  coverage.append(el('li','',num(items.length)+' interventions / '+num(items.reduce((s,i)=>s+i.cost,0))+' points in the complete build.'));
  $('coverage').append(coverage);
  root.querySelector('.ex-app').hidden=false;
  root.querySelector('.ex-fallback').hidden=true;
  window.addEventListener('hashchange',route);route();
})();
""".strip()


__all__ = ["EXPLORER_CSS", "EXPLORER_SCRIPT"]
