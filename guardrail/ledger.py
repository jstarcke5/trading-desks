#!/usr/bin/env python3
"""Book integrity: what we believe versus what the broker actually holds.

Every risk control reads local state — daily notional, exposure, position ages. That file was
written by our own bookkeeping and never checked against truth. A cache nobody verifies is not
a cache; it is a lie waiting to be believed.

Four defects this closes, all confirmed by red team on 2026-08-19:

  ref_id was minted per CALL, so a retry became a second position. The key protected nothing
  while the code claimed it did — worse than having no key at all.

  Daily counters never reset. They accumulate forever: the daily cap ratchets permanently shut
  and the loss cap eventually halts the system for good, for reasons nobody would think to look
  for months later.

  Nothing reconciled against the broker. A fill landing after a timeout is invisible to EVERY
  control simultaneously — no cap, no exposure limit, no flatten plan can see it.

  Full fills were assumed. A $20 order filling $12 corrupted exposure in the dangerous
  direction, and a later sell of the recorded size oversells.
"""
import hashlib, uuid

# ---------------------------------------------------------------- idempotency
def ref_id_for(order, session_id):
    """A deterministic key for a LOGICAL order. Same intent in the same session -> same key, so
    a retry is the same order to the broker rather than a second one. A different amount, side,
    symbol or session is a genuinely different order and gets its own key."""
    parts = [str(session_id), str(order.get("symbol", "")), str(order.get("side", "")),
             str(order.get("type", "")), str(order.get("dollar_amount", "")),
             str(order.get("quantity", "")), str(order.get("limit_price", ""))]
    digest = hashlib.sha256("|".join(parts).encode()).digest()
    return str(uuid.UUID(bytes=digest[:16]))

# ---------------------------------------------------------------- daily roll
DAILY_KEYS = ("notional_today", "realized_pnl_today")

def roll(state, today):
    """Reset per-day counters when the date changes. Positions survive; they are not daily.
    An absent or unreadable `as_of` is treated as a new day -- state of unknown vintage must
    never be trusted to hold a loss cap open."""
    out = dict(state or {})
    if out.get("as_of") != today:
        for k in DAILY_KEYS:
            out[k] = 0.0
    out["as_of"] = today
    out.setdefault("positions", {})
    out.setdefault("open_exposure", 0.0)
    return out

# ---------------------------------------------------------------- reconcile
def reconcile(state, broker_positions):
    """The broker is the source of truth. Returns (state, drift) where drift is a list of
    human-readable differences -- every one of which is a finding worth journalling, because a
    silent divergence is how an invisible position survives."""
    out = dict(state or {})
    local = dict(out.get("positions") or {})
    drift, merged, exposure = [], {}, 0.0

    for p in broker_positions or []:
        sym = p.get("symbol")
        if not sym:
            continue
        try:
            qty = float(p.get("quantity") or 0)
        except (TypeError, ValueError):
            continue
        if qty <= 0:
            continue
        try:
            exposure += float(p.get("market_value") or 0)
        except (TypeError, ValueError):
            pass
        known = local.pop(sym, None)
        if known is None:
            # Unknown open time. NOT "now" -- that would reset min_hold and let a hold rule be
            # evaded by losing track. NOT ancient either. Unknown means unknown, and callers
            # must treat a null open time as "cannot verify the hold."
            merged[sym] = {"quantity": qty, "opened_at": None}
            drift.append("%s: position unknown to us (%.4f) — adopted from broker" % (sym, qty))
        else:
            if abs(float(known.get("quantity") or 0) - qty) > 1e-9:
                drift.append("%s: quantity drift, ours %.4f vs broker %.4f — taking broker's"
                             % (sym, float(known.get("quantity") or 0), qty))
            merged[sym] = {"quantity": qty, "opened_at": known.get("opened_at")}

    for sym, known in local.items():
        drift.append("%s: we recorded %.4f but the broker shows it gone — dropped"
                     % (sym, float(known.get("quantity") or 0)))

    out["positions"] = merged
    out["open_exposure"] = round(exposure, 4)
    return out, drift

# ---------------------------------------------------------------- fills
def apply_fill(state, symbol, side, filled_qty, filled_notional, now):
    """Record what ACTUALLY filled, never what was requested."""
    out = dict(state or {})
    positions = dict(out.get("positions") or {})
    try:
        qty = float(filled_qty or 0); notional = float(filled_notional or 0)
    except (TypeError, ValueError):
        return out
    if qty <= 0:
        return out

    out["notional_today"] = float(out.get("notional_today") or 0) + max(0.0, notional)
    # Exposure must be maintained here too, not only by reconcile(). Reconciliation needs a
    # reachable broker; if it is the ONLY writer, then a broker outage means open_exposure
    # never grows and the exposure cap silently stops binding — the failure mode being to
    # permit more risk, which is the wrong direction to fail in.
    exposure = float(out.get("open_exposure") or 0)
    out["open_exposure"] = round(max(0.0, exposure + (notional if side == "buy" else -notional)), 6)
    if side == "buy":
        pos = positions.get(symbol) or {"quantity": 0.0, "opened_at": now, "cost_basis": 0.0}
        pos["quantity"] = float(pos.get("quantity") or 0) + qty
        pos["cost_basis"] = float(pos.get("cost_basis") or 0) + max(0.0, notional)
        pos.setdefault("opened_at", now)
        positions[symbol] = pos
    else:
        pos = positions.get(symbol)
        if pos:
            remaining = float(pos.get("quantity") or 0) - qty
            if remaining > 1e-9:
                had = float(pos.get("quantity") or 0)
                if had > 0:                        # reduce basis proportionally
                    pos["cost_basis"] = float(pos.get("cost_basis") or 0) * (remaining / had)
                pos["quantity"] = remaining
                positions[symbol] = pos
            else:
                positions.pop(symbol, None)      # never negative: we do not short here
    out["positions"] = positions
    return out


# ---------------------------------------------------------------- open risk
# An auditor found three rules that combined into a trap nobody wrote down: min_hold refused
# every sell inside the window, stop orders are forbidden, and the loss cap read realized P&L
# only. A losing position could therefore run to any drawdown for a full hour with no automatic
# exit and nothing reacting. These close it.

def unrealized(state, marks):
    """Open P&L against cost basis. A position with no mark or no basis is SKIPPED, never
    guessed -- an invented mark is worse than an absent one."""
    total = 0.0
    for sym, pos in (state.get("positions") or {}).items():
        mark, basis = marks.get(sym), pos.get("cost_basis")
        if mark is None or basis is None:
            continue
        try:
            total += float(mark) * float(pos.get("quantity") or 0) - float(basis)
        except (TypeError, ValueError):
            continue
    return round(total, 6)

def total_pnl(state, marks):
    """What the loss cap must actually see: closed AND open."""
    try:
        realized = float(state.get("realized_pnl_today") or 0)
    except (TypeError, ValueError):
        realized = 0.0
    return round(realized + unrealized(state, marks), 6)

def halted(total_pnl_value, daily_loss_cap):
    """True when losses breach the cap. A GAIN never halts, however large."""
    try:
        return float(total_pnl_value) <= -abs(float(daily_loss_cap))
    except (TypeError, ValueError):
        return True                        # unreadable -> fail closed

def may_exit(side, held_minutes, min_hold_minutes, unrealized_pct):
    """A hold rule that traps a loser is not a risk control.

    An exit is permitted regardless of min_hold whenever the position is losing. min_hold
    exists to stop churn, not to prevent a stop-out -- and an unknown hold age (a position
    adopted during reconciliation) permits the exit, because refusing to close is the dangerous
    direction to fail in.
    """
    if side != "sell":
        return True, ""
    if held_minutes is None:
        return True, "hold age unknown — exit permitted rather than trapping the position"
    try:
        if float(unrealized_pct) < 0:
            return True, "exit permitted: position is losing, min_hold does not trap a loser"
        if float(held_minutes) >= float(min_hold_minutes):
            return True, ""
    except (TypeError, ValueError):
        return True, "unreadable P&L — exit permitted rather than trapping the position"
    return False, ("min_hold_minutes not met (held %s of %s) and the position is not losing"
                   % (held_minutes, min_hold_minutes))
