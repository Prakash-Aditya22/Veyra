"""v2 blackspot pipeline entry point.

Run from anywhere; every path is anchored on the repository:

    .venv/Scripts/python ml/blackspot/download.py stats19 aadf os_open_roads   # once, ~1.6 GB
    .venv/Scripts/python ml/pipeline.py data        # canonical collisions 2015-2025      (~2 min)
    .venv/Scripts/python ml/pipeline.py network     # OS Open Roads -> 500 m segments    (~15 min)
    .venv/Scripts/python ml/pipeline.py snap        # collisions -> segments               (~5 min)
    .venv/Scripts/python ml/pipeline.py coverage    # national KSI coverage of the scored network  (~1 min)
    .venv/Scripts/python ml/pipeline.py develop     # rolling-origin development folds, ablations
    .venv/Scripts/python ml/pipeline.py holdout     # frozen final holdout (2024-25), spatial CV
    .venv/Scripts/python ml/pipeline.py forecast    # production forecast 2026-27 + v2 outputs
    .venv/Scripts/python ml/pipeline.py severity    # deployable severity model, temporal + spatial tests
    .venv/Scripts/python ml/pipeline.py all

`holdout` refuses to run unless `develop` has written and frozen the model
specification, so the final holdout can never steer a modelling choice.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from blackspot.config import ensure_dirs  # noqa: E402
from blackspot.io_utils import setup_logging  # noqa: E402

log = logging.getLogger("blackspot.pipeline")
STEPS = ["data", "network", "snap", "coverage", "develop", "holdout", "forecast", "severity"]


def run(step: str) -> None:
    t0 = time.time()
    log.info("=== step %s", step)
    if step == "data":
        from blackspot.steps import step_data; step_data()
    elif step == "network":
        from blackspot.steps import step_network; step_network()
    elif step == "snap":
        from blackspot.steps import step_snap; step_snap()
    elif step == "coverage":
        from blackspot.steps import step_coverage; step_coverage()
    elif step == "develop":
        from blackspot.steps import step_develop; step_develop()
    elif step == "holdout":
        from blackspot.steps import step_holdout; step_holdout()
    elif step == "forecast":
        from blackspot.steps import step_forecast; step_forecast()
    elif step == "severity":
        from blackspot.steps import step_severity; step_severity()
    log.info("=== step %s done in %.1f min", step, (time.time() - t0) / 60)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=STEPS + ["all"])
    args = ap.parse_args(argv)
    setup_logging()
    ensure_dirs()
    for s in (STEPS if args.step == "all" else [args.step]):
        run(s)
    return 0


if __name__ == "__main__":
    sys.exit(main())
