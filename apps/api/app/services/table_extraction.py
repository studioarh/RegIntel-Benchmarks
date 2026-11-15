from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from bs4 import Tag

MAX_ROWS_PER_HEADER_BLOCK = 10


def _clean_cell(value: Any) -> str:
    if value is None:
        return ""
    raw = str(value).replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    cleaned = re.sub(r"\s+", " ", raw).strip()
    return cleaned.replace("|", "\\|")


@dataclass(frozen=True)
class ExtractedTable:
    page_number: int | None
    headers: list[str]
    rows: list[list[str]]
    is_continuation: bool = False

    @property
    def markdown(self) -> str:
        return format_self_contained_markdown_table(
            headers=self.headers,
            rows=self.rows,
            page_number=self.page_number,
            is_continuation=self.is_continuation,
        )

    def to_metadata(self) -> dict[str, Any]:
        return {
            "page_number": self.page_number,
            "headers": self.headers,
            "rows": self.rows,
            "row_count": len(self.rows),
            "column_count": len(self.headers),
            "is_continuation": self.is_continuation,
        }


def format_self_contained_markdown_table(
    headers: list[str],
    rows: list[list[str]],
    page_number: int | None = None,
    is_continuation: bool = False,
    max_rows_per_block: int = MAX_ROWS_PER_HEADER_BLOCK,
) -> str:
    if not headers or not rows:
        return ""

    col_count = len(headers)
    normalized_headers = [h if h else f"Col_{idx + 1}" for idx, h in enumerate(headers)]
    header_line = "| " + " | ".join(normalized_headers) + " |"
    separator_line = "| " + " | ".join(["---"] * col_count) + " |"

    blocks: list[str] = []
    total_rows = len(rows)

    for start_idx in range(0, total_rows, max_rows_per_block):
        row_slice = rows[start_idx : start_idx + max_rows_per_block]
        label_parts: list[str] = ["[REGULATORY TABLE"]
        if page_number is not None:
            label_parts.append(f"Page {page_number}")
        if is_continuation or start_idx > 0:
            label_parts.append("Continued")
        label = " - ".join(label_parts) + "]"

        lines = [label, header_line, separator_line]
        for row in row_slice:
            padded = (row + [""] * col_count)[:col_count]
            lines.append("| " + " | ".join(padded) + " |")
        blocks.append("\n".join(lines))

    return "\n\n".join(blocks)


def _looks_like_data_row(row: list[str], prior_headers: list[str]) -> bool:
    """Return True if `row` is likely a continuation data row rather than a new header row."""
    if [c.lower() for c in row] == [h.lower() for h in prior_headers]:
        return False
    numeric_or_code_cells = sum(
        1 for cell in row if re.search(r"(\d+(\.\d+)?%|£\d|\b\d+\s*(days|months|years)\b)", cell)
    )
    return numeric_or_code_cells > 0


def extract_pdf_page_tables(
    page: Any,
    page_number: int,
    prev_table_headers: list[str] | None = None,
) -> tuple[list[ExtractedTable], list[str] | None]:
    """Extract tables from a PyMuPDF page and stitch multi-page continuation headers."""
    find_tables_fn = getattr(page, "find_tables", None)
    if not callable(find_tables_fn):
        return [], prev_table_headers

    try:
        finder = find_tables_fn()
        raw_tables = getattr(finder, "tables", None) or list(finder)
    except Exception:
        return [], prev_table_headers

    extracted_tables: list[ExtractedTable] = []
    last_headers: list[str] | None = prev_table_headers

    for tbl_idx, tbl in enumerate(raw_tables):
        try:
            grid = tbl.extract()
        except Exception:
            continue

        if not grid or len(grid) < 1:
            continue

        cleaned_grid: list[list[str]] = []
        for raw_row in grid:
            if not raw_row:
                continue
            cleaned_row = [_clean_cell(c) for c in raw_row]
            if any(cleaned_row):
                cleaned_grid.append(cleaned_row)

        if not cleaned_grid:
            continue

        first_row = cleaned_grid[0]
        if len(first_row) < 2:
            continue

        is_cont = False
        bbox = getattr(tbl, "bbox", None)
        near_page_top = bool(bbox and len(bbox) >= 2 and float(bbox[1]) < 140.0)

        if (
            tbl_idx == 0
            and last_headers is not None
            and len(first_row) == len(last_headers)
            and (near_page_top or _looks_like_data_row(first_row, last_headers))
        ):
            is_cont = True
            headers = list(last_headers)
            if [c.lower() for c in first_row] == [h.lower() for h in headers]:
                data_rows = cleaned_grid[1:]
            else:
                data_rows = cleaned_grid
        else:
            if len(cleaned_grid) < 2:
                continue
            headers = first_row
            data_rows = cleaned_grid[1:]

        if not data_rows:
            continue

        table_obj = ExtractedTable(
            page_number=page_number,
            headers=headers,
            rows=data_rows,
            is_continuation=is_cont,
        )
        extracted_tables.append(table_obj)
        last_headers = headers

    return extracted_tables, last_headers


def extract_html_table(table_tag: Tag) -> ExtractedTable | None:
    """Extract a BeautifulSoup <table> into a structured ExtractedTable."""
    rows_raw: list[list[str]] = []
    header_cells: list[str] = []

    thead = table_tag.find("thead")
    if isinstance(thead, Tag):
        header_tr = thead.find("tr")
        if isinstance(header_tr, Tag):
            header_cells = [
                _clean_cell(cell.get_text(" ", strip=True))
                for cell in header_tr.find_all(["th", "td"])
            ]

    for tr in table_tag.find_all("tr"):
        if not isinstance(tr, Tag):
            continue
        if thead is not None and tr.find_parent("thead") is not None:
            continue

        ths = tr.find_all("th")
        tds = tr.find_all("td")

        if ths and not tds and not header_cells:
            header_cells = [_clean_cell(th.get_text(" ", strip=True)) for th in ths]
            continue

        cells = [_clean_cell(c.get_text(" ", strip=True)) for c in tr.find_all(["th", "td"])]
        if any(cells):
            rows_raw.append(cells)

    if not header_cells and len(rows_raw) >= 2:
        header_cells = rows_raw[0]
        rows_raw = rows_raw[1:]

    if len(header_cells) < 2 or not rows_raw:
        return None

    return ExtractedTable(
        page_number=None,
        headers=header_cells,
        rows=rows_raw,
        is_continuation=False,
    )


def parse_table_metadata_from_chunk_text(chunk_text: str | None) -> dict[str, Any] | None:
    """Detect and parse Markdown regulatory tables inside a chunk into structured JSONB."""
    if not chunk_text or "|" not in chunk_text:
        return None

    lines = [line.strip() for line in chunk_text.splitlines() if line.strip()]
    table_lines = [line for line in lines if line.startswith("|") and line.endswith("|")]
    if len(table_lines) < 3:
        return None

    def _split_md_row(line: str) -> list[str]:
        inner = line.strip("|")
        return [c.strip() for c in re.split(r"(?<!\\)\|", inner)]

    headers = _split_md_row(table_lines[0])
    separator = _split_md_row(table_lines[1])
    if not all(re.match(r"^:?-{2,}:?$", cell) for cell in separator if cell):
        return None

    rows: list[list[str]] = []
    for row_line in table_lines[2:]:
        cells = _split_md_row(row_line)
        if all(re.match(r"^:?-{2,}:?$", c) for c in cells if c):
            continue
        if [c.lower() for c in cells] == [h.lower() for h in headers]:
            continue
        rows.append(cells)

    if not rows:
        return None

    return {
        "headers": headers,
        "rows": rows,
        "row_count": len(rows),
        "column_count": len(headers),
    }
