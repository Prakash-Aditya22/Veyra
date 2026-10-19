"""Safe file writes, hashing and logging shared by every pipeline step."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

log = logging.getLogger("blackspot")


def setup_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                        datefmt="%H:%M:%S")


def file_hash(path: Path, algo: str = "sha256", chunk: int = 1 << 20) -> str:
    h = hashlib.new(algo)
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


@contextmanager
def atomic_path(dest: Path) -> Iterator[Path]:
    """Yield a temporary path beside `dest`; move it over `dest` only on success.

    A crash mid-write leaves the previous `dest` intact instead of a truncated
    file that later parses as valid.
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{dest.name}.", suffix=".tmp", dir=dest.parent)
    os.close(fd)
    tmp = Path(tmp)
    try:
        yield tmp
        os.replace(tmp, dest)
    finally:
        if tmp.exists():
            tmp.unlink()


def write_json(obj: Any, dest: Path) -> None:
    with atomic_path(dest) as tmp:
        tmp.write_text(json.dumps(obj, indent=2, default=_json_default), encoding="utf-8")


def write_text(text: str, dest: Path) -> None:
    with atomic_path(dest) as tmp:
        tmp.write_text(text, encoding="utf-8")


def write_csv(df, dest: Path, **kw) -> None:
    with atomic_path(dest) as tmp:
        df.to_csv(tmp, index=False, **kw)


def write_parquet(df, dest: Path) -> None:
    with atomic_path(dest) as tmp:
        df.to_parquet(tmp, index=False)


def _json_default(o):
    import numpy as np
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, Path):
        return str(o)
    raise TypeError(f"not JSON serialisable: {type(o)}")
