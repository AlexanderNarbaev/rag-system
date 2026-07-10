# etl/chunker/table_extractor.py
"""Extract and parse HTML tables from Confluence/Jira documents."""

import logging
from dataclasses import dataclass

try:
    from bs4 import BeautifulSoup as _BS4  # noqa: F401, N814

    BS4_AVAILABLE = True
except ImportError:
    _BS4 = None  # type: ignore
    BS4_AVAILABLE = False

logger = logging.getLogger(__name__)

TABLE_EXTRACTION_ENABLED = True


@dataclass
class TableData:
    headers: list[str]
    rows: list[list[str]]
    caption: str = ""


def extract_tables_from_html(html: str) -> list[TableData]:
    """Extract all <table> elements from HTML and parse into TableData objects.

    Handles <th> in both <thead> and <tr>, <td> in <tbody> and <tr>.
    """
    if not html or not BS4_AVAILABLE or _BS4 is None:
        return []

    try:
        soup = _BS4(html, "html.parser")
    except Exception:
        logger.warning("Failed to parse HTML with BeautifulSoup")
        return []

    tables = []
    for table_elem in soup.find_all("table"):
        caption = ""
        caption_elem = table_elem.find("caption")
        if caption_elem:
            caption = caption_elem.get_text(strip=True)

        headers = []
        rows = []

        thead = table_elem.find("thead")
        if thead:
            tr = thead.find("tr")
            if tr:
                headers = [th.get_text(strip=True) for th in tr.find_all(["th", "td"])]

        tbody = table_elem.find("tbody") or table_elem
        for tr in tbody.find_all("tr"):
            cells = tr.find_all(["th", "td"])
            if not cells:
                continue
            if any(cell.name == "th" and not headers for cell in cells):
                headers = [cell.get_text(strip=True) for cell in cells]
                continue
            row = [cell.get_text(strip=True) for cell in cells]
            if row:
                rows.append(row)

        if not headers and not rows:
            continue

        tables.append(TableData(headers=headers, rows=rows, caption=caption))

    return tables


def table_to_markdown(table: TableData) -> str:
    """Convert TableData to a Markdown-formatted table string."""
    if not table.rows and not table.headers:
        return ""

    has_headers = bool(table.headers)
    max_cols = len(table.headers) if has_headers else max((len(r) for r in table.rows), default=0)

    if max_cols == 0:
        return ""

    lines = []
    if table.caption:
        lines.append(f"**{table.caption}**\n")

    def _clean_cell(text: str) -> str:
        return text.replace("\n", " ").replace("|", "\\|")

    if has_headers:
        padded_headers = table.headers + [""] * (max_cols - len(table.headers))
        lines.append("| " + " | ".join(_clean_cell(h) for h in padded_headers) + " |")
    else:
        lines.append("| " + " | ".join(" " for _ in range(max_cols)) + " |")

    lines.append("|" + "|".join(" --- " for _ in range(max_cols)) + "|")

    for row in table.rows:
        padded = row + [""] * (max_cols - len(row))
        lines.append("| " + " | ".join(_clean_cell(c) for c in padded) + " |")

    return "\n".join(lines)


def table_to_json(table: TableData) -> dict:
    """Convert TableData to a structured dict representation.

    Includes headers, rows, caption, row_count, and records (dict format).
    """
    result = {
        "headers": table.headers,
        "rows": table.rows,
        "caption": table.caption,
        "row_count": len(table.rows),
    }

    if table.headers:
        records = []
        for row in table.rows:
            record = {}
            for i, val in enumerate(row):
                if i < len(table.headers):
                    record[table.headers[i]] = val
            records.append(record)
        result["records"] = records

    return result
