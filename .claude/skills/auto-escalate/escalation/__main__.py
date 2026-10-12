"""CLI:  python -m escalation report [--log PATH] [--out PATH]
        python -m escalation stats  [--log PATH]"""
from __future__ import annotations

import argparse
from pathlib import Path

from .calibrator import calibrate, load_decisions, render_report

DEFAULT_LOG = Path.home() / ".claude" / "escalation-log.jsonl"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="escalation")
    ap.add_argument("cmd", choices=["report", "stats"])
    ap.add_argument("--log", default=str(DEFAULT_LOG))
    ap.add_argument("--out", default="")
    ap.add_argument("--target", type=float, default=0.75)
    ap.add_argument("--min-samples", type=int, default=5)
    a = ap.parse_args(argv)

    decisions = load_decisions(a.log)
    calib = calibrate(decisions, target=a.target, min_samples=a.min_samples)

    if a.cmd == "stats":
        print(f"{len(decisions)} decisions across {len(calib)} signals")
        for sig in sorted(calib):
            c = calib[sig]
            floor = f"{c.learned_floor}" if c.learned_floor else "insufficient data"
            print(f"  {sig:24} n={c.samples:<4} floor={floor}")
        return 0

    report = render_report(calib)
    if a.out:
        Path(a.out).write_text(report, encoding="utf-8")
        print(f"Wrote {a.out}")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
