#!/usr/bin/env python3
"""Per-symbol trading cost, measured rather than assumed.

A single fee constant is a guess applied uniformly. Measured live on 2026-08-19 within one
minute: SPY's half-spread was 0.0019%, AMD's was 0.0355% -- nineteen times wider. A constant
is wrong for both, and the direction of the error matters: too high kills good ideas silently
at the gate, too low lets expensive ones through.

The inherited 0.05%/side from the research ledger was NINE TIMES the measured median for this
broker, which charges no commission. That single wrong number was rejecting every intraday
idea before analysis began -- correct reasoning on a bad input, which is the hardest kind of
failure to notice.
"""
SAFETY_MULTIPLE = 5.0      # quoted spread is not the whole cost: fractional market orders can
                           # fill outside the NBBO, routing quality varies, and one snapshot is
                           # not a session average.
FALLBACK_FEE_PCT = 0.03    # used when a symbol cannot be measured -- conservative on purpose
MAX_PLAUSIBLE_HALF_SPREAD = 5.0    # above this the quote is broken, not expensive
GATE = 0.05                # fee-in-R ceiling

def parse(payload):
    """{symbol: half_spread_pct}. The broker nests quotes under 'quote'; a flat parser found
    nothing and looked like 'no data' rather than 'wrong shape'."""
    out = {}
    for row in ((payload or {}).get("data") or {}).get("results") or []:
        q = row.get("quote") if isinstance(row, dict) else None
        if not isinstance(q, dict):
            continue
        sym = q.get("symbol")
        try:
            bid = float(q["bid_price"]); ask = float(q["ask_price"])
        except (KeyError, TypeError, ValueError):
            continue
        if not sym or bid <= 0 or ask <= 0 or ask < bid:      # crossed book = unusable
            continue
        mid = (ask + bid) / 2.0
        if mid <= 0:
            continue
        out[sym] = (ask - bid) / mid * 100.0 / 2.0
    return out

def effective_fee(half_spread_pct):
    """The cost to plan against: the measured half-spread with a safety multiple, or the
    conservative constant when the symbol could not be measured."""
    if half_spread_pct is None:
        return FALLBACK_FEE_PCT
    try:
        h = float(half_spread_pct)
    except (TypeError, ValueError):
        return FALLBACK_FEE_PCT
    if h <= 0:
        return FALLBACK_FEE_PCT
    return h * SAFETY_MULTIPLE

def fee_in_r(stop_pct, fee_pct_per_side):
    if not stop_pct or float(stop_pct) <= 0:
        return float("inf")
    return (2.0 * float(fee_pct_per_side)) / float(stop_pct)

def cost_gate(half_spread_pct, stop_pct):
    """(ok, detail). The one equation, using this symbol's own measured cost."""
    if half_spread_pct is not None:
        try:
            if float(half_spread_pct) > MAX_PLAUSIBLE_HALF_SPREAD:
                return False, ("implausible half-spread %.4f%% — refusing to trade on a broken "
                               "quote" % float(half_spread_pct))
        except (TypeError, ValueError):
            return False, "implausible half-spread — unreadable quote"
    fee = effective_fee(half_spread_pct)
    r = fee_in_r(stop_pct, fee)
    if r >= GATE:
        return False, ("fee-in-R %.4f exceeds the %.2f ceiling (cost %.4f%%/side, stop %.2f%%)"
                       % (r, GATE, fee, float(stop_pct or 0)))
    return True, ("fee-in-R %.4f (cost %.4f%%/side, stop %.2f%%)"
                  % (r, fee, float(stop_pct or 0)))
