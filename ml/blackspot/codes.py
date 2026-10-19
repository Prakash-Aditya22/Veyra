"""STATS19 code -> label maps, read from DfT's own data guide (2025 edition).

v1 hard-coded historic code lists while the data used the 2024 format, so
revised junction levels (13, 16-19) appeared as bare numbers. Labels now come
from the official guide's `2024_code_list` sheet, and `UNKNOWN` marks the
codes the guide defines as missing, out of range or unknown, so analyses can
flag rather than interpret them.
"""
from __future__ import annotations

from functools import lru_cache

import pandas as pd

from .config import RAW

GUIDE = RAW / "stats19" / "dft-road-casualty-statistics-road-safety-open-dataset-data-guide-2025.xlsx"


@lru_cache(maxsize=1)
def code_list() -> pd.DataFrame:
    if not GUIDE.exists():
        raise FileNotFoundError(f"{GUIDE} missing -- run ml/blackspot/download.py guide")
    c = pd.read_excel(GUIDE, sheet_name="2024_code_list")
    c["table"] = c["table"].ffill()
    c["field name"] = c["field name"].ffill()
    return c


def labels(field: str, table: str = "collision") -> dict:
    c = code_list()
    d = c[(c.table == table) & (c["field name"] == field)].dropna(subset=["code/format"])
    out = {}
    for code, lab in zip(d["code/format"], d["label"]):
        try:
            code = int(code)
        except (TypeError, ValueError):
            continue
        out[code] = "None" if pd.isna(lab) else str(lab).strip()
    return out


def is_unknown_label(label: str) -> bool:
    s = str(label).lower()
    return ("unknown" in s) or ("missing" in s) or ("out of range" in s) or ("unallocated" in s)


def unknown_codes(field: str, table: str = "collision") -> set:
    return {k for k, v in labels(field, table).items() if is_unknown_label(v)}
