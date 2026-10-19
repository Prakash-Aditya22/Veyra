"""Download official source files with completeness checks and a provenance manifest.

A collision-table download once stopped at 1.4 GB of 1.5 GB and still parsed
as valid CSV. So nothing here trusts a file because it opens: every download is
streamed to a temporary file, its byte count is compared with Content-Length,
an MD5 is checked when the publisher supplies one, CSVs must end on a complete
record, and zips must pass a CRC test. Only then is the file moved into place
and recorded in RAW/manifest.json with its URL, size and SHA-256.

Usage (from the repo root):
    .venv/Scripts/python ml/blackspot/download.py stats19 aadf os_open_roads
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import io
import json
import logging
import sys
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from blackspot.config import RAW
    from blackspot.io_utils import setup_logging, write_json
else:
    from .config import RAW
    from .io_utils import setup_logging, write_json

log = logging.getLogger("blackspot.download")

DFT = "https://data.dft.gov.uk/road-accidents-safety-data/"
MANIFEST = RAW / "manifest.json"


@dataclass(frozen=True)
class Source:
    key: str
    url: str
    dest: Path
    kind: str                      # "csv" | "zip"
    md5: str | None = None


def stats19_sources() -> list[Source]:
    out = []
    for table in ("collision", "casualty", "vehicle"):
        for year in range(2021, 2026):
            name = f"dft-road-casualty-statistics-{table}-{year}.csv"
            out.append(Source(f"stats19_{table}_{year}", DFT + name, RAW / "stats19" / name, "csv"))
    name = "dft-road-casualty-statistics-casualty-1979-latest-published-year.csv"
    out.append(Source("stats19_casualty_all", DFT + name, RAW / "stats19" / name, "csv"))
    return out


SOURCES: dict[str, list[Source]] = {
    "stats19": stats19_sources(),
    "aadf": [Source("dft_aadf",
                    "https://storage.googleapis.com/dft-statistics/road-traffic/downloads/"
                    "data-gov-uk/dft_traffic_counts_aadf.zip",
                    RAW / "aadf" / "dft_traffic_counts_aadf.zip", "zip")],
    "guide": [Source("stats19_data_guide_2025",
                     "https://assets.publishing.service.gov.uk/media/6ab2a71d997a4b2950cced58/"
                     "dft-road-casualty-statistics-road-safety-open-dataset-data-guide-2025.xlsx",
                     RAW / "stats19" / "dft-road-casualty-statistics-road-safety-open-dataset-data-guide-2025.xlsx",
                     "zip")],                              # xlsx is a zip container
    "os_open_roads": [Source("os_open_roads",
                             "https://api.os.uk/downloads/v1/products/OpenRoads/downloads"
                             "?area=GB&format=ESRI%C2%AE+Shapefile&redirect",
                             RAW / "os_open_roads" / "oproad_essh_gb.zip", "zip",
                             md5=None)],   # filled at run time from the OS Data Hub listing
}


# ------------------------------------------------------------------ validation
def csv_is_complete(path: Path) -> tuple[bool, str]:
    """True if the last record has as many fields as the header.

    A truncated download almost always ends mid-record, which shows up as a
    short final row. Quoted fields are handled by the csv module.
    """
    with open(path, "rb") as fh:
        header = fh.readline().decode("utf-8-sig")
        fh.seek(0, 2)
        size = fh.tell()
        fh.seek(max(0, size - 65536))
        tail = fh.read().decode("utf-8", errors="replace")
    n_header = len(next(csv.reader(io.StringIO(header))))
    lines = [ln for ln in tail.splitlines() if ln.strip()]
    if not lines:
        return False, "empty file"
    n_last = len(next(csv.reader(io.StringIO(lines[-1]))))
    if n_last != n_header:
        return False, f"last record has {n_last} fields, header has {n_header}"
    return True, f"{n_header} fields, last record complete"


def zip_is_complete(path: Path) -> tuple[bool, str]:
    try:
        with zipfile.ZipFile(path) as z:
            bad = z.testzip()
            n = len(z.namelist())
    except zipfile.BadZipFile as e:
        return False, f"bad zip: {e}"
    if bad is not None:
        return False, f"CRC failure in {bad}"
    return True, f"{n} members, CRC ok"


# ------------------------------------------------------------------ download
def _load_manifest() -> dict:
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {}


def _os_md5() -> str | None:
    """OS publishes an MD5 for each product download; use it when reachable."""
    try:
        with urllib.request.urlopen(
                "https://api.os.uk/downloads/v1/products/OpenRoads/downloads", timeout=60) as r:
            for item in json.loads(r.read()):
                if item.get("fileName") == "oproad_essh_gb.zip":
                    return item.get("md5")
    except Exception as e:                              # noqa: BLE001 -- best effort
        log.warning("could not read OS md5 listing: %s", e)
    return None


def fetch(src: Source, retries: int = 3, force: bool = False) -> dict:
    manifest = _load_manifest()
    rec = manifest.get(src.key)
    if (not force and rec and src.dest.exists()
            and src.dest.stat().st_size == rec.get("bytes") and rec.get("valid")):
        log.info("%s: already present and validated (%s bytes)", src.key, rec["bytes"])
        return rec

    src.dest.parent.mkdir(parents=True, exist_ok=True)
    part = src.dest.with_name(src.dest.name + ".part")
    expected_md5 = src.md5 or (_os_md5() if src.key == "os_open_roads" else None)
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            sha, md5, n = hashlib.sha256(), hashlib.md5(), 0
            req = urllib.request.Request(src.url, headers={"User-Agent": "blackspot-research/2.0"})
            with urllib.request.urlopen(req, timeout=120) as r, open(part, "wb") as fh:
                length = r.headers.get("Content-Length")
                length = int(length) if length else None
                t0 = time.time()
                while True:
                    block = r.read(1 << 20)
                    if not block:
                        break
                    fh.write(block); sha.update(block); md5.update(block); n += len(block)
                    if n % (100 << 20) < (1 << 20):
                        log.info("%s: %.0f MB", src.key, n / 1e6)
            if length is not None and n != length:
                raise IOError(f"truncated: received {n} of {length} bytes")
            if expected_md5 and md5.hexdigest() != expected_md5:
                raise IOError(f"md5 mismatch: {md5.hexdigest()} != {expected_md5}")
            ok, why = (csv_is_complete if src.kind == "csv" else zip_is_complete)(part)
            if not ok:
                raise IOError(f"incomplete {src.kind}: {why}")
            part.replace(src.dest)
            rec = {"url": src.url, "file": str(src.dest.relative_to(RAW)), "bytes": n,
                   "content_length": length, "sha256": sha.hexdigest(), "md5": md5.hexdigest(),
                   "md5_expected": expected_md5, "validation": why, "valid": True,
                   "downloaded_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                   "seconds": round(time.time() - t0, 1)}
            manifest = _load_manifest()
            manifest[src.key] = rec
            write_json(manifest, MANIFEST)
            log.info("%s: ok %.1f MB (%s)", src.key, n / 1e6, why)
            return rec
        except Exception as e:                          # noqa: BLE001 -- retried, then raised
            last_err = e
            log.warning("%s: attempt %d/%d failed: %s", src.key, attempt, retries, e)
            if part.exists():
                part.unlink()
            time.sleep(5 * attempt)
    raise RuntimeError(f"{src.key}: download failed after {retries} attempts: {last_err}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("groups", nargs="+", choices=sorted(SOURCES))
    ap.add_argument("--force", action="store_true", help="re-download even if validated")
    ap.add_argument("--skip", nargs="*", default=[], help="source keys to skip")
    args = ap.parse_args(argv)
    setup_logging()
    failed = []
    for g in args.groups:
        for src in SOURCES[g]:
            if src.key in args.skip:
                continue
            try:
                fetch(src, force=args.force)
            except RuntimeError as e:
                log.error("%s", e)
                failed.append(src.key)
    if failed:
        log.error("FAILED: %s", ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
