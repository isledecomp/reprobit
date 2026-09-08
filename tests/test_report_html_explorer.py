from __future__ import annotations

import base64
import gzip
import json
from html.parser import HTMLParser
from pathlib import Path

from test_report import failure_report

from reprobit.report import Report
from reprobit.report_html_explorer_style import EXPLORER_SCRIPT
from reprobit.report_io import render_report_html
from reprobit.strict_json import canonical_json


class ExplorerDocument(HTMLParser):
    def __init__(self, html: str) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: list[str] = []
        self.scripts = 0
        self.payload: list[str] = []
        self.in_payload = False
        self.feed(html)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if attributes.get("id"):
            self.ids.append(str(attributes["id"]))
        if tag == "script":
            self.scripts += 1
        if attributes.get("id") == "explorer-data":
            self.in_payload = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "div" and self.in_payload:
            self.in_payload = False

    def handle_data(self, data: str) -> None:
        if self.in_payload:
            self.payload.append(data)

    def explorer_data(self) -> dict[str, object]:
        decoded = gzip.decompress(base64.b64decode("".join(self.payload)))
        return json.loads(decoded)  # type: ignore[no-any-return]


def test_explorer_is_a_portable_page_with_complete_escaped_inventory() -> None:
    attack = '</div><script>alert("source")</script><img src=x onerror=alert(1)>'
    report = failure_report().with_exploration(
        {"diagnostics": [{"kind": "sample", "message": attack}]}
    )
    rendered = render_report_html(report)
    document = ExplorerDocument(rendered)
    payload = document.explorer_data()

    assert document.scripts == 1
    assert len(document.ids) == len(set(document.ids))
    assert attack not in rendered
    assert payload["diagnostics"][0]["message"] == attack
    assert {item["id"] for item in payload["interventions"]} == {
        item.intervention_id for item in report.costs.interventions
    }
    assert sum(item["cost"] for item in payload["interventions"]) == report.costs.project_total
    assert 'href="#binary-explorer"' in rendered
    assert "Complete intervention inventory" in rendered
    assert "Map coverage &amp; reading this view" in rendered
    assert "innerHTML" not in EXPLORER_SCRIPT
    assert "fetch(" not in EXPLORER_SCRIPT


def test_captured_explorer_renders_identically_after_json_roundtrip_without_files() -> None:
    report = failure_report().with_exploration(
        {
            "targets": [
                {
                    "id": "program",
                    "image_base": 0x400000,
                    "sections": [
                        {
                            "name": ".text",
                            "va": 0x401000,
                            "size": 100,
                            "file_offset": 0,
                            "file_size": 100,
                        }
                    ],
                    "symbols": [],
                }
            ]
        }
    )
    reread = Report.model_validate_json(canonical_json(report))
    # Rendering has no dependency on a surviving build directory or network.
    from unittest.mock import patch

    with patch.object(Path, "read_bytes", side_effect=AssertionError("unexpected file read")):
        assert render_report_html(reread) == render_report_html(report)
    payload = ExplorerDocument(render_report_html(reread)).explorer_data()
    assert payload["targets"][0]["sections"][0]["va"] == 0x401000
