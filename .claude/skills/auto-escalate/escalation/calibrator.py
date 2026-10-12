"""Learn the cheapest escalation rung that reliably succeeds, per signal.

Pipeline:  log_decision() -> JSONL  ->  calibrate()  ->  learned floors.

A *decision* records which difficulty signals fired, which (model, effort)
rung was chosen, and the outcome once known ("pass" on first try,
"reescalated" if a higher rung was needed, "failed" if it never succeeded).
:func:`calibrate` mines the log for each signal and recommends the lowest rung
whose empirical first-try success rate clears a target — raising the floor
where the policy under-powers, lowering it where it over-pays. Stdlib only.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

# The escalation ladder, cheapest -> most powerful. Index = cost/capability rank.
RUNGS: tuple[tuple[str, str], ...] = (
    ("haiku", "low"),
    ("haiku", "medium"),
    ("sonnet", "medium"),
    ("sonnet", "high"),
    ("sonnet", "xhigh"),
    ("opus", "high"),
    ("opus", "xhigh"),
    ("opus", "max"),
    ("fable", "max"),
)
_RUNG_POS = {rung: i for i, rung in enumerate(RUNGS)}

PASS = "pass"
REESCALATED = "reescalated"
FAILED = "failed"


def rung_index(model: str, effort: str) -> int:
    """Position of a (model, effort) rung on the ladder; -1 if unknown."""
    return _RUNG_POS.get((model, effort), -1)


@dataclass
class Decision:
    """One escalation decision and its (eventual) outcome."""

    signals: tuple[str, ...]
    model: str
    effort: str
    outcome: str  # PASS | REESCALATED | FAILED
    task: str = ""
    ts: str = ""

    def as_dict(self) -> dict:
        return {
            "signals": list(self.signals),
            "model": self.model,
            "effort": self.effort,
            "outcome": self.outcome,
            "task": self.task,
            "ts": self.ts,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Decision":
        return cls(
            signals=tuple(d.get("signals", [])),
            model=d.get("model", ""),
            effort=d.get("effort", ""),
            outcome=d.get("outcome", ""),
            task=d.get("task", ""),
            ts=d.get("ts", ""),
        )


def log_decision(decision: Decision, path: Path | str) -> None:
    """Append one decision to the JSONL log (created if absent)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(decision.as_dict()) + "\n")


def load_decisions(path: Path | str) -> list[Decision]:
    """Read every decision from a JSONL log (empty list if the file is absent)."""
    p = Path(path)
    if not p.exists():
        return []
    out: list[Decision] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(Decision.from_dict(json.loads(line)))
    return out


@dataclass
class SignalCalibration:
    """What the log has learned about one difficulty signal."""

    signal: str
    samples: int
    learned_floor: tuple[str, str] | None  # cheapest rung meeting the target
    confident: bool                          # enough samples to trust it
    per_rung: dict[tuple[str, str], tuple[int, int]] = field(default_factory=dict)
    # per_rung[rung] = (passes, total)


def _wilson_lower_bound(passes: int, total: int, z: float = 1.96) -> float:
    """Lower bound of a Wilson score interval — a sample-size-aware success
    rate. Five-for-five is trusted less than fifty-for-fifty; this stops a
    lucky small sample from prematurely lowering a floor."""
    if total == 0:
        return 0.0
    phat = passes / total
    denom = 1 + z * z / total
    centre = phat + z * z / (2 * total)
    margin = z * math.sqrt((phat * (1 - phat) + z * z / (4 * total)) / total)
    return (centre - margin) / denom


def calibrate(
    decisions: Iterable[Decision],
    *,
    target: float = 0.75,
    min_samples: int = 5,
) -> dict[str, SignalCalibration]:
    """For each signal, recommend the cheapest rung whose *lower-bound* success
    rate clears ``target``. A rung "succeeds" when the outcome is PASS (solved
    on the first try — REESCALATED and FAILED both count against it).

    Returns a calibration per signal. ``learned_floor`` is None (and
    ``confident`` False) until at least one rung has ``min_samples`` decisions,
    so the policy falls back to the hand-written rubric while evidence is thin.
    """
    # signal -> rung -> [passes, total]
    tally: dict[str, dict[tuple[str, str], list[int]]] = {}
    for d in decisions:
        rung = (d.model, d.effort)
        if rung_index(*rung) < 0:
            continue
        for sig in d.signals:
            slot = tally.setdefault(sig, {}).setdefault(rung, [0, 0])
            slot[1] += 1
            if d.outcome == PASS:
                slot[0] += 1

    result: dict[str, SignalCalibration] = {}
    for sig, rungs in tally.items():
        per_rung = {r: (p, t) for r, (p, t) in rungs.items()}
        samples = sum(t for _, t in per_rung.values())
        # Candidate floors: rungs with enough samples clearing the target's
        # lower bound. Pick the cheapest by ladder position.
        eligible = [
            r
            for r, (p, t) in per_rung.items()
            if t >= min_samples and _wilson_lower_bound(p, t) >= target
        ]
        floor = min(eligible, key=lambda r: rung_index(*r)) if eligible else None
        confident = floor is not None
        result[sig] = SignalCalibration(
            signal=sig,
            samples=samples,
            learned_floor=floor,
            confident=confident,
            per_rung=per_rung,
        )
    return result


def render_report(calib: dict[str, SignalCalibration]) -> str:
    """Human- and skill-readable Markdown table of learned floors."""
    lines = [
        "# Learned escalation floors (auto-generated)",
        "",
        "<!-- Generated by `python -m escalation report`. Do not edit by hand. -->",
        "",
        "Cheapest rung whose observed first-try success clears the target, per",
        "difficulty signal. Signals below the sample threshold keep the",
        "hand-written rubric default (shown as `insufficient data`).",
        "",
        "| Signal | Samples | Learned floor | Confident |",
        "|---|---|---|---|",
    ]
    for sig in sorted(calib):
        c = calib[sig]
        floor = (
            f"`{c.learned_floor[0]} + {c.learned_floor[1]}`"
            if c.learned_floor
            else "_insufficient data_"
        )
        lines.append(
            f"| {sig} | {c.samples} | {floor} | {'yes' if c.confident else 'no'} |"
        )
    return "\n".join(lines).rstrip() + "\n"
