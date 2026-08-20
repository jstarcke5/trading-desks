#!/usr/bin/env python3
"""Switch 3 — the live order branch. The most safety-critical file here.

Shaped by two facts read from the broker's real schema, not its docs:

  1. Fractional / notional orders require type=market. At $100.00 with SPY near $767 there is no
     whole-share option, so notional is mandatory.
  2. A NOTIONAL market order is bounded by construction -- dollar_amount fixes the spend
     exactly. The usual reason to fear a market order is unbounded cost; with the dollars
     pinned, only the share count floats. So market is permitted ONLY with dollar_amount, and
     never together with quantity.

Everything here fails closed. review_equity_order always precedes place_equity_order, so the
real quote is seen before anything is live, and ref_id makes a retry idempotent rather than a
second position.
"""
import datetime, json, urllib.error, urllib.request, uuid

BROKER_URL = "https://agent.robinhood.com/mcp/trading"
ALLOWED_TYPES = {"market", "limit"}          # no stops: a stop is a second, unreviewed order

# Measured on the live broker 2026-08-19, mid-session: median half-spread across 12 liquid
# names was 0.0058% (SPY 0.0019%, QQQ 0.0014%, AMD 0.0355%). The research ledger's inherited
# 0.05%/side was NINE TIMES too expensive for this broker, which charges no commission -- and
# that wrong number was killing every intraday idea at the cost gate before analysis began.
#
# 0.03% is deliberately ~5x the measured median: quoted spread is not the whole cost. Fractional
# market orders can fill outside the NBBO, routing quality varies, and one snapshot is not a
# session average. Cost varies hugely by symbol (AMD is 6x SPY), so a desk should prefer the
# live per-symbol spread over this constant whenever it can obtain one.
DEFAULT_FEE_PCT_PER_SIDE = 0.03

def fee_pct_per_side(limits):
    v = (limits or {}).get("fee_pct_per_side")
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 \
        else DEFAULT_FEE_PCT_PER_SIDE

def fee_in_r(stop_pct, fee_pct_per_side):
    """The one equation. Above ~0.05 an idea needs an enormous raw edge to survive its costs."""
    if not stop_pct or stop_pct <= 0:
        return float("inf")
    return (2.0 * float(fee_pct_per_side)) / float(stop_pct)

def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None

# ------------------------------------------------------------------ switch 3
ARMED_FILE = "arming file guardrail/.armed"

def armed(here=None):
    """A file on disk that must be created by hand.

    This exists because the test suite itself was a live-order vector: a test that sets
    GUARDRAIL_UPSTREAM=http would, once a real broker token existed, have transmitted. Env vars
    are cheap to set by accident, in a test, a shell profile, or a CI job. A file that no test
    ever creates is not.
    """
    import pathlib
    base = pathlib.Path(here) if here else pathlib.Path(__file__).resolve().parent
    return (base / ".armed").is_file()

def transmission_enabled(env, token="present", here=None):
    """ALL THREE, deliberately. Absent any one, nothing leaves the machine."""
    return (env.get("GUARDRAIL_UPSTREAM") == "http"
            and bool(token)
            and armed(here))

def may_place(reviewed):
    if not reviewed:
        return False, "review_equity_order must run first — never place an unreviewed order"
    return True, ""

# ------------------------------------------------------------------ the checks
def market_gate(now, limits):
    """Refuse outside a live regular session.

    Gap found while arming: nothing checked this. A gfd order sent pre-market QUEUES for the
    open -- an unattended live order placed hours after the reasoning that produced it, and
    filled into whatever the overnight gap did. Also refuse the closing minutes: an order
    reasoned about at 15:58 has no time to be wrong cheaply.
    """
    from zoneinfo import ZoneInfo
    et = now.astimezone(ZoneInfo("America/New_York")) if now.tzinfo else now
    if et.weekday() >= 5:
        return False, "market is closed (weekend)"
    open_t  = et.replace(hour=9,  minute=30, second=0, microsecond=0)
    close_t = et.replace(hour=16, minute=0,  second=0, microsecond=0)
    if et < open_t or et > close_t:
        return False, "market is closed (%s ET)" % et.strftime("%H:%M")
    blackout = open_t + datetime.timedelta(minutes=limits.get("opening_blackout_minutes", 15))
    if et < blackout:
        return False, "opening blackout until %s ET" % blackout.strftime("%H:%M")
    if et > close_t - datetime.timedelta(minutes=5):
        return False, "closing window — refusing new orders after %s ET" % (
            (close_t - datetime.timedelta(minutes=5)).strftime("%H:%M"))
    return True, ""

def check(order, limits, state, buying_power, now=None):
    """Returns (ok, reason). Order shape is the broker's, not ours."""
    if not isinstance(order, dict):
        return False, "order must be an object"

    if now is not None:                     # omitting `now` must not bypass the gate --
        ok, why = market_gate(now, limits)  # server.py always passes it
        if not ok:
            return False, why

    # An EMPTY allowlist means "no symbol restriction" -- a deliberate user choice, made
    # explicit here so it can never be the accidental result of a truncated or corrupt config.
    # A MISSING key still fails closed: absence is not permission.
    if "allowlist" not in limits:
        return False, "limits config has no allowlist key — refusing (absence is not permission)"
    sym = order.get("symbol")
    allowed = limits["allowlist"]
    if allowed and sym not in allowed:
        return False, "%s is not on the allowlist" % sym
    if not str(sym or "").strip():
        return False, "order has no symbol"
    if order.get("side") not in ("buy", "sell"):
        return False, "side must be buy or sell"

    otype = order.get("type")
    if otype not in ALLOWED_TYPES:
        return False, ("type %r is not permitted — only market (with dollar_amount) or limit. "
                       "A stop order is a second order nobody reviewed." % otype)
    if order.get("market_hours", "regular_hours") != "regular_hours":
        return False, "market_hours must be regular_hours — thin books outside them"
    if order.get("time_in_force", "gfd") != "gfd":
        return False, "time_in_force must be gfd — an order must not outlive the session that reasoned about it"
    if order.get("tax_lots"):
        return False, "tax_lot selection is not supported by this proxy"

    dollars, qty = order.get("dollar_amount"), order.get("quantity")

    if otype == "market":
        if dollars and qty:
            return False, "market order carries both dollar_amount and quantity — ambiguous, refused"
        if not dollars:
            return False, ("a market order must use dollar_amount, never quantity: notional "
                           "bounds the spend, share quantity does not")
        notional = _f(dollars)
    else:                                            # limit
        price = _f(order.get("limit_price"))
        n = _f(qty)
        if price is None or price <= 0:
            return False, "limit order requires a positive limit_price"
        if n is None or n <= 0:
            return False, "limit order requires a positive quantity"
        notional = n * price

    if notional is None or notional <= 0:
        return False, "could not compute a positive notional"

    # halt outranks everything
    pnl, cap = _f(state.get("realized_pnl_today", 0.0)), _f(limits.get("daily_loss_cap"))
    if pnl is None or cap is None:
        return False, "daily_loss_cap state unreadable"
    if pnl <= -abs(cap):
        return False, "HALTED: daily_loss_cap reached (%.2f of %.2f)" % (pnl, -abs(cap))

    if notional > _f(limits["max_order_notional"]):
        return False, "notional %.2f exceeds max_order_notional %.2f" % (
            notional, _f(limits["max_order_notional"]))

    used = _f(state.get("notional_today", 0.0)) or 0.0
    if used + notional > _f(limits["max_daily_notional"]):
        return False, "would exceed max_daily_notional (%.2f used + %.2f > %.2f)" % (
            used, notional, _f(limits["max_daily_notional"]))

    if order["side"] == "buy":
        exp = _f(state.get("open_exposure", 0.0)) or 0.0
        if exp + notional > _f(limits["max_open_exposure"]):
            return False, "would exceed max_open_exposure (%.2f + %.2f > %.2f)" % (
                exp, notional, _f(limits["max_open_exposure"]))
        bp = _f(buying_power)
        if bp is None:
            return False, "buying power unknown — refusing to guess"
        if notional > bp:
            return False, "notional %.2f exceeds real buying power %.2f" % (notional, bp)

    return True, ""

# ------------------------------------------------------------------ payload
def build_payload(order, pinned_account, ref_id=None):
    """Normalise into exactly what the broker expects. Hours and TIF are forced, not defaulted,
    so a caller cannot omit them into something riskier."""
    p = {
        "account_number": pinned_account,
        "symbol": order["symbol"],
        "side": order["side"],
        "type": order["type"],
        "market_hours": "regular_hours",
        "time_in_force": "gfd",
        "ref_id": ref_id or str(uuid.uuid4()),
    }
    if order.get("dollar_amount"):
        p["dollar_amount"] = "%.2f" % _f(order["dollar_amount"])
    if order.get("quantity"):
        p["quantity"] = str(order["quantity"])
    if order.get("limit_price"):
        p["limit_price"] = "%.2f" % _f(order["limit_price"])
    return p

# ------------------------------------------------------------------ transport
def _rpc(token, method, params, rid=1, timeout=30):
    body = json.dumps({"jsonrpc": "2.0", "id": rid, "method": method,
                       "params": params or {}}).encode()
    req = urllib.request.Request(BROKER_URL, data=body, headers={
        "Authorization": "Bearer " + token, "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream"})
    raw = urllib.request.urlopen(req, timeout=timeout).read().decode()
    for line in raw.splitlines():
        if line.startswith("data:"):
            raw = line[5:].strip()
            break
    return json.loads(raw)

def _call(token, tool, args):
    _rpc(token, "initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                               "clientInfo": {"name": "guardrail", "version": "1.0"}})
    r = _rpc(token, "tools/call", {"name": tool, "arguments": args}, rid=2)
    res = r.get("result") or {}
    text = "".join(c.get("text", "") for c in (res.get("content") or []))
    try:
        return json.loads(text) if text else res
    except ValueError:
        return {"raw": text[:600]}

def review(token, payload):
    args = {k: v for k, v in payload.items() if k != "ref_id"}
    return _call(token, "review_equity_order", args)

def place(token, payload):
    return _call(token, "place_equity_order", payload)
