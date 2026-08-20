#!/usr/bin/env python3
"""The learning loop. Arithmetic, not an agent -- a loop that needs a model call gets skipped,
and a skipped learning loop is worse than none because it is still believed.

Two ideas carry this file:

1. LEARN FROM REJECTIONS. Executed trades will number a handful per year because the gates
   correctly kill almost everything; n=6 teaches nothing. Rejections are numerous, accumulate
   on quiet days, and their counterfactual outcome is computable from price alone with no
   capital at risk. That is where the sample size lives.

2. THE TRAP IN IDEA 1. A rejected idea never paid costs and never respected its stop, so
   scoring it naively ALWAYS concludes "the gates are too strict" -- turning this into a
   machine for rationalising away discipline. So costs and the stated stop are applied
   identically to what a real trade would have suffered, and neither is optional.

Learning updates the MAP (priors, thresholds, track records). It never touches the GUARDRAILS.
"""
import json, os, pathlib

MIN_SAMPLE = 20            # below this we report UNDERPOWERED rather than a verdict
WRONG_KILL_ALARM = 0.60    # share of wrong kills that flags a gate for human review

# --------------------------------------------------------------- calibration
def brier(rows):
    """rows: [(stated_confidence 0..1, was_right bool)]. Lower is better. 0.25 = coin flip.
    Returns None on no data -- an empty sample must never look like perfect calibration."""
    if not rows:
        return None
    return sum((p - (1.0 if hit else 0.0)) ** 2 for p, hit in rows) / len(rows)

def calibration_verdict(rows):
    b = brier(rows)
    if b is None:
        return "NO DATA"
    if len(rows) < MIN_SAMPLE:
        return "UNDERPOWERED (n=%d, need %d) — brier %.3f, not yet a verdict" % (
            len(rows), MIN_SAMPLE, b)
    stated = sum(p for p, _ in rows) / len(rows)
    actual = sum(1 for _, hit in rows if hit) / len(rows)
    gap = stated - actual
    if gap > 0.15:
        return "OVERCONFIDENT (said %.0f%%, right %.0f%%, n=%d, brier %.3f)" % (
            stated * 100, actual * 100, len(rows), b)
    if gap < -0.15:
        return "UNDERCONFIDENT (said %.0f%%, right %.0f%%, n=%d, brier %.3f)" % (
            stated * 100, actual * 100, len(rows), b)
    return "CALIBRATED (said %.0f%%, right %.0f%%, n=%d, brier %.3f)" % (
        stated * 100, actual * 100, len(rows), b)

# --------------------------------------------------------------- rejections
def score_rejection(entry, exit, stop_pct, side, fee_bps, worst_pct=None):
    """Would this killed idea actually have made money -- net of costs, honouring its own stop?

    worst_pct: the worst excursion against the position before the exit. If it breaches the
    stated stop, the trade would have been stopped out, and the later favourable outcome is
    unavailable. Omitting it flatters every rejection, which is the failure mode this guards.
    """
    if fee_bps is None:
        raise ValueError("costs are never optional — a backtest without costs is not evidence")
    if entry <= 0:
        raise ValueError("entry must be positive")

    direction = 1.0 if side == "buy" else -1.0
    gross_pct = direction * (exit - entry) / entry * 100.0

    stopped = worst_pct is not None and worst_pct <= -abs(stop_pct)
    if stopped:
        gross_pct = -abs(stop_pct)

    round_trip_pct = 2.0 * (fee_bps / 100.0)          # bps per side -> percent round trip
    net_pct = gross_pct - round_trip_pct

    return {
        "gross_pct": round(gross_pct, 4),
        "cost_pct": round(round_trip_pct, 4),
        "net_pct": round(net_pct, 4),
        "stopped_out": stopped,
        "verdict": "WRONGLY KILLED" if net_pct > 0 else "CORRECTLY KILLED",
    }

# --------------------------------------------------------------- gate efficacy
def gate_report(rows):
    """rows: [{"gate": name, "verdict": "WRONGLY KILLED"|"CORRECTLY KILLED"}]

    A gate that kills mostly winners is destroying value invisibly -- nothing else in this
    system could ever detect that. It is flagged for a HUMAN to review, never auto-adjusted.
    """
    out = {}
    for r in rows:
        g = out.setdefault(r["gate"], {"n": 0, "wrongly_killed": 0})
        g["n"] += 1
        if r["verdict"] == "WRONGLY KILLED":
            g["wrongly_killed"] += 1
    for name, g in out.items():
        share = g["wrongly_killed"] / g["n"] if g["n"] else 0.0
        g["wrong_kill_share"] = round(share, 3)
        if g["n"] < MIN_SAMPLE:
            g["assessment"] = "UNDERPOWERED (n=%d, need %d)" % (g["n"], MIN_SAMPLE)
        elif share >= WRONG_KILL_ALARM:
            g["assessment"] = ("REVIEW — killed %.0f%% winners over n=%d; a human must decide, "
                               "this is never auto-adjusted" % (share * 100, g["n"]))
        else:
            g["assessment"] = "EARNING its place (%.0f%% wrong kills, n=%d)" % (share * 100, g["n"])
    return out

# --------------------------------------------------------------- write sandbox
ALLOWED_DIR = "learning"

def may_write(path):
    """A system that can edit its own constraints has none. This is the whole safety model of
    the learning loop, and it is a path check rather than an instruction."""
    p = os.path.normpath(str(path))
    if os.path.isabs(p) or p.startswith(".."):
        return False
    parts = pathlib.PurePosixPath(p).parts
    return len(parts) >= 2 and parts[0] == ALLOWED_DIR and ".." not in parts

def write(path, obj):
    if not may_write(path):
        raise PermissionError("learning may write only inside %s/ — refused: %s"
                              % (ALLOWED_DIR, path))
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2) + "\n")
    return str(p)
