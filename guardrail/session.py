#!/usr/bin/env python3
"""Timeboxed trading session: trade inside a window, be FLAT before it closes.

The mandate conflicts with itself unless handled deliberately. min_hold_minutes forbids
selling too soon after buying; "be flat by 11:30" requires selling. A position opened at 11:29
cannot legally be closed by 11:30, so the system would have to break one of its own rules to
obey the other -- and a system that must break a rule will break whichever one is cheapest.

Resolution: entries stop early enough that anything opened can still be closed legally.

    last_entry = end - min_hold_minutes

With a 09:30-11:30 window and a 60-minute minimum hold, entries run 09:30-10:30 and the second
hour is exit-only. That is not a limitation -- it is the only arrangement in which both rules
can hold at once.
"""
import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

def _at(now, hhmm):
    h, m = (int(x) for x in hhmm.split(":"))
    base = now.astimezone(ET) if now.tzinfo else now.replace(tzinfo=ET)
    return base.replace(hour=h, minute=m, second=0, microsecond=0)

def start_time(now, w):      return _at(now, w["start"])
def end_time(now, w):        return _at(now, w["end"])
def last_entry_time(now, w):
    return end_time(now, w) - datetime.timedelta(minutes=w["min_hold_minutes"])
def flatten_time(now, w):
    return end_time(now, w) - datetime.timedelta(minutes=w.get("flatten_buffer_minutes", 10))

def validate(w):
    """A window shorter than the minimum hold cannot be satisfied. Reject it at configuration
    time rather than discovering it with an open position and no legal way out."""
    probe = datetime.datetime(2026, 1, 1, 12, 0, tzinfo=ET)
    span = (end_time(probe, w) - start_time(probe, w)).total_seconds() / 60.0
    if span <= 0:
        raise ValueError("session end must be after session start")
    if span < w["min_hold_minutes"]:
        raise ValueError(
            "session window is %d min but min_hold_minutes is %d — nothing bought could ever "
            "be legally sold before the close. Widen the window or lower min_hold."
            % (span, w["min_hold_minutes"]))
    return True

def phase(now, w):
    n = now.astimezone(ET) if now.tzinfo else now.replace(tzinfo=ET)
    if n < start_time(n, w):        return "before"
    if n >= end_time(n, w):         return "over"
    if n >= flatten_time(n, w):     return "flatten"
    if n >= last_entry_time(n, w):  return "exit-only"
    return "open"

def may_trade(side, now, w):
    p = phase(now, w)
    if p == "over":
        return False, "session is over (ended %s ET) — no further orders" % w["end"]
    if p == "before":
        return False, "session has not started (opens %s ET)" % w["start"]
    if side == "sell":
        return True, ""                       # exits are always allowed inside the window
    if p in ("exit-only", "flatten"):
        return False, ("new positions could not be exited before the session closes "
                       "(last entry was %s ET)" % last_entry_time(now, w).strftime("%H:%M"))
    return True, ""

def flatten_plan(state, now, w):
    """What must be sold to end the session flat. Empty until the buffer opens, so nothing is
    unwound early on a whim."""
    if phase(now, w) != "flatten":
        return []
    out = []
    for symbol, pos in (state.get("positions") or {}).items():
        qty = float(pos.get("quantity") or 0)
        if qty > 0:
            out.append({"side": "sell", "symbol": symbol, "quantity": qty,
                        "reason": "session flatten — %s ET close" % w["end"]})
    return out
