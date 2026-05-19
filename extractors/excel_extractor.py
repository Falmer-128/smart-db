"""
Excel (.xlsx / .xls) extraction using pandas.

Tables are converted to **Markdown** format so that an LLM can
consume them naturally inside a RAG context window.
"""

from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)


def extract(file_path: str) -> str:
    """
    Read every sheet in an Excel workbook and convert each to a
    Markdown table.

    Returns
    -------
    str
        Markdown-formatted representation of all sheets.

    Raises
    ------
    RuntimeError
        When pandas / openpyxl cannot open or parse the file.
    """
    logger.info("Extracting tables from Excel: '%s'.", file_path)

    try:
        sheets: dict[str, pd.DataFrame] = pd.read_excel(
            file_path, sheet_name=None, dtype=str
        )
    except Exception as exc:
        raise RuntimeError(
            f"pandas failed to read Excel file '{file_path}': {exc}"
        ) from exc

    sections: list[str] = []

    for sheet_name, df in sheets.items():
        if df.empty:
            logger.debug("Sheet '%s' is empty — skipping.", sheet_name)
            continue

        # Fill NaN with empty string for clean Markdown output
        df = df.fillna("")
        md_table = df.to_markdown(index=False)
        sections.append(f"## Sheet: {sheet_name}\n\n{md_table}")

    result = "\n\n---\n\n".join(sections)
    logger.info(
        "Excel extraction complete — %d non-empty sheet(s).", len(sections)
    )
    return result
