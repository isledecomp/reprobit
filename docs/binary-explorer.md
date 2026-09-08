# Binary explorer

Open **Binary explorer** in any generated HTML report. The explorer is a second
page inside the same portable HTML file. It needs no server, installed tools,
or network connection. Explorer data is compressed inside the file and opened
locally with the browser's built-in decompressor. The ordinary build report remains available from the
navigation bar; without JavaScript, a complete intervention inventory is shown.

Choose a binary, then select a change from the list or an address band on the
map. The list supports address order, highest cost, build-stage filters, and
search by function, source path, intervention ID, or hexadecimal address.
Use **Zoom to range**, select the band again, or choose a section such as `.text`. Clear the
range to return to the other changes. Each change has a link that can be
bookmarked within the saved report.

The detail panel connects three things:

- **Location:** the function, recorded byte ranges, source files, and destinations
  of shared work, with the origin of each address.
- **Mechanics:** a short sequence showing where the operation enters the build,
  concrete source or instruction changes, and links to its dependencies and users.
- **Cost:** the existing cost-model charge, its units, and its share of the target.
  Points describe intervention complexity, not execution time or runtime overhead.

Large source recipes separate file comparisons, generated files, and individual
edits, with a searchable selector in each group. Generated compilation units show
their complete source when captured, with build placement available separately.
Every recorded overlay edit, generated compilation unit, and link admission is included. Declaration
previews use the built-in generator and must match their recorded digest before
being presented as regenerated source. When both source receipts are available,
the panel shows aligned changed lines. Individual edits recover their removed
and inserted text from exact source bytes and signed operation receipts.

Function transformations show a side-by-side x86 assembly comparison captured
immediately before and after the operation. Changed regions appear first, with
the complete captured listing available on demand. Operands use relocation
symbols where recorded. These offsets are within the function before linking;
the location above the comparison places it in the binary. Data bytes and gaps
that cannot be safely decoded are reported separately. Source comparisons and
supporting byte measurements remain available below the assembly.

Other transformations show metadata values, data-pool moves, or their applicable
recorded mechanics; they do not imply a corresponding C++ edit. Technical
measurements, receipt identifiers, and verification checks are folded away.

## Address and cost semantics

Coordinate spaces remain separate:

| View | Meaning |
| --- | --- |
| Final binary address | An address in the final image, supported by a byte-exact reference inventory or receipt-checked linked symbols and matching bytes. |
| File offset | A position in the final artifact file. |
| Reference address | A reference-inventory address when the rebuilt target is not byte-exact. |
| Debug companion address | A linked debug-image address that could not be established in the final image. |
| Address before image edits | An actual linker-map address before declared image moves. |
| Function offset | An offset within the object function body, shown in the detail panel. |

Symbol records with no measured extent are shown as **start only**. The explorer
does not infer function lengths from neighboring symbols or addresses from names.
Intermediate object offsets and supplemental-file offsets appear in details and
never become final-image addresses by assumption.

Each intervention is charged once. Shared interventions can have several mapped
destinations. Map bands divide their charge equally among recorded locations
and spread each share over its extent. Zooming preserves that allocation.
This is a visual allocation, not the
function-cost ledger or a count of changed bytes. The map footer totals the visible
range; the metric above counts locations across the selected coordinate space.
Filters dim unrelated map bands; they do
not change the total charged cost. Whole-target source recipes and other changes
without an exact byte location remain visible through **Outside this map**.

Empty bands mean that no intervention is mapped there in the report. They do not
prove those bytes were untouched. **Other recorded build adjustments** includes
object-order transformations and named debug-companion normalization categories
that carry no separate intervention charge.

## Captured report data

Report generation captures an `exploration` object while the build workspace is
still available. It carries intervention declarations, the reference function
inventory, translation-unit source paths, PE sections, actual terminal-link map
addresses, receipt-checked symbol locations, source comparisons, assembly changes,
and coverage diagnostics. Linker addresses
are shown as final only when the recorded image transformations form a complete
chain to the reported output; declared code moves adjust those addresses.
Source overlays also preserve compact before/after excerpts from the original
and edited bytes retained during the build. Their full hashes and output size
must match the declared source pair, so replacing a working source file later
does not lose its original text. Excerpts are capped per file and across the
report, with any clipping stated beside the preview.
Private source variants retain the clean inputs needed to replay their recorded
edits. Replayed text is displayed only after matching the entire recorded output,
the action declaration, and its removed and inserted fragment hashes.
This presentation context is included in the report's public-payload digest;
it does not change the proof certificates or authenticity verdict.

Only files named in report receipts are read. Complete size and SHA-256 checks
precede parsing or source display. Linked PDBs must also match the debug image's
recorded identity. Read and preview limits keep report generation bounded;
missing, stale, unsupported, or truncated material is disclosed. Source text
and all strings remain inert, escaped content in the HTML.

HTML rendering consumes the captured JSON and performs no local file reads.
This preserves its behavior after temporary build files are removed or the
report is copied to another computer. Reports created before exploration data
was captured should be regenerated with `rbit verify`; no inferred migration of
old report identities is performed.
