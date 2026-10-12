"""Self-calibrating escalation policy.

A data flywheel for /auto-escalate: log every (signals -> chosen rung ->
outcome) decision, then learn the cheapest rung that reliably succeeds for
each difficulty signal. The policy improves as evidence accrues — approaching,
never reaching, optimal.
"""
from .calibrator import (
    RUNGS,
    Decision,
    calibrate,
    load_decisions,
    log_decision,
    render_report,
    rung_index,
)

__all__ = [
    "RUNGS",
    "Decision",
    "calibrate",
    "load_decisions",
    "log_decision",
    "render_report",
    "rung_index",
]
__version__ = "1.0.0"
