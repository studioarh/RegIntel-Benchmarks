from __future__ import annotations

from apps.api.app.services.table_extraction import (
    extract_html_table,
    extract_pdf_page_tables,
    parse_table_metadata_from_chunk_text,
)
from bs4 import BeautifulSoup, Tag


def test_html_table_extraction_preserves_markdown_and_structured_metadata() -> None:
    html = """
    <table>
        <thead>
            <tr>
                <th>Rule Code</th>
                <th>Governance Category</th>
                <th>Mandatory Window</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td>SYSC 15A.2.1R</td>
                <td>Operational Resilience Mapping</td>
                <td>12 months</td>
            </tr>
            <tr>
                <td>DISP 1.6.2R</td>
                <td>Final Complaint Resolution</td>
                <td>8 weeks</td>
            </tr>
        </tbody>
    </table>
    """
    soup = BeautifulSoup(html, "html.parser")
    table_tag = soup.find("table")
    assert isinstance(table_tag, Tag)

    extracted = extract_html_table(table_tag)
    assert extracted is not None
    assert "[REGULATORY TABLE]" in extracted.markdown
    assert "| Rule Code | Governance Category | Mandatory Window |" in extracted.markdown
    assert "| SYSC 15A.2.1R | Operational Resilience Mapping | 12 months |" in extracted.markdown

    meta = extracted.to_metadata()
    assert meta["headers"] == ["Rule Code", "Governance Category", "Mandatory Window"]
    assert meta["row_count"] == 2

    parsed_meta = parse_table_metadata_from_chunk_text(extracted.markdown)
    assert parsed_meta is not None
    assert parsed_meta["headers"] == ["Rule Code", "Governance Category", "Mandatory Window"]
    assert len(parsed_meta["rows"]) == 2


def test_pdf_multi_page_table_continuation_stitches_headers() -> None:
    class FakeTable:
        def __init__(self, grid: list[list[str]], bbox: tuple[float, float, float, float]) -> None:
            self._grid = grid
            self.bbox = bbox

        def extract(self) -> list[list[str]]:
            return self._grid

    class FakePage:
        def __init__(self, tables: list[FakeTable]) -> None:
            self._tables = tables

        def find_tables(self) -> list[FakeTable]:
            return self._tables

    page1 = FakePage(
        [
            FakeTable(
                grid=[
                    ["FCA Rule", "Complaint Category", "Resolution Window"],
                    ["DISP 1.6.2R", "Standard Dispute Resolution", "8 weeks"],
                ],
                bbox=(50.0, 300.0, 550.0, 740.0),
            )
        ]
    )
    page2 = FakePage(
        [
            FakeTable(
                grid=[
                    ["DISP 1.6.2AR", "Complex Statutory Review", "28 days"],
                ],
                bbox=(50.0, 65.0, 550.0, 200.0),
            )
        ]
    )

    p1_tables, prev_headers = extract_pdf_page_tables(page1, page_number=1, prev_table_headers=None)
    assert len(p1_tables) == 1
    assert p1_tables[0].is_continuation is False
    assert prev_headers == ["FCA Rule", "Complaint Category", "Resolution Window"]

    p2_tables, _ = extract_pdf_page_tables(page2, page_number=2, prev_table_headers=prev_headers)
    assert len(p2_tables) == 1
    assert p2_tables[0].is_continuation is True
    assert p2_tables[0].headers == ["FCA Rule", "Complaint Category", "Resolution Window"]
    assert "[REGULATORY TABLE - Page 2 - Continued]" in p2_tables[0].markdown
