"""Validate a v2 release directory against the integration contract.

    .venv/Scripts/python ml/audit/validate_contract.py                       # data/v2 (the real release)
    .venv/Scripts/python ml/audit/validate_contract.py ml/tests/fixtures/integration

Checks required fields, types, nullability, allowed values, the exposure and history rules,
ID format, GeoJSON geometry and coordinate order, and that every optional extension joins to
the base CSV on segment_id with the same rank. Optional files are checked only when present.
Exits 1 on any problem. Needs pandas and numpy only, not the national pipeline.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from blackspot.config import BACKEND_DATA  # noqa: E402
from blackspot.contract import FILES, validate_release  # noqa: E402


def main(argv) -> int:
    root = Path(argv[1]) if len(argv) > 1 else BACKEND_DATA / "v2"
    res = validate_release(root)
    bad = 0
    for k in FILES.values():
        if k in res:
            print(f"{'PASS' if not res[k] else 'FAIL'}  {k}")
            for e in res[k]:
                print("      ", e)
            bad += bool(res[k])
        else:
            print(f"absent {k} (optional)")
    print(f"{root}: {'all present files conform' if not bad else f'{bad} file(s) with problems'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
