"""Guardrail enforcement — pure logic, no I/O. Stdlib only (python3.9).

Robinhood Agentic ships no spending caps, no order-size limits and no kill switch;
the funded balance is the only hard limit that exists. This module is the replacement.

Design rule: FAIL CLOSED. Anything unrecognised, missing, mistyped or out of range is a
refusal. There is no permissive default anywhere in this file.
"""
import collections
import datetime

Decision = collections.namedtuple("Decision", "ok reason")

def _no(reason):
    return Decision(False, reason)

OK = Decision(True, "")

ORDER_FIELDS = {"symbol", "side", "quantity", "limit_price", "order_type", "asset_class"}
LIMIT_FIELDS = {"max_order_notional", "max_daily_notional", "max_open_exposure",
                "daily_loss_cap", "allowlist", "allow_options", "allow_market_orders",
                "opening_blackout_minutes", "min_hold_minutes"}
SIDES = {"buy", "sell"}
ORDER_TYPES = {"limit", "market"}

TOOLS_BY_MODE = {
    "read-market":    ["get_quote", "get_bars", "market_clock"],
    "read-portfolio": ["get_positions", "get_account"],
    "orders":         ["place_order", "cancel_order", "get_order_status"],
}

def tools_for_mode(mode):
    """Unknown mode exposes nothing — a typo must not widen the tool surface."""
    return list(TOOLS_BY_MODE.get(mode, []))

def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)

def evaluate(order, limits, state, now, market_open):
    # --- schema: exact field set, fail closed on extra or missing -------------
    if not isinstance(order, dict):
        return _no("order is not an object")
    extra = set(order) - ORDER_FIELDS
    if extra:
        return _no("unknown order field(s): %s" % ", ".join(sorted(extra)))
    missing = ORDER_FIELDS - set(order)
    if missing:
        return _no("missing order field(s): %s" % ", ".join(sorted(missing)))
    if not isinstance(limits, dict) or (LIMIT_FIELDS - set(limits)):
        return _no("limits config incomplete: %s" % ", ".join(sorted(LIMIT_FIELDS - set(limits or {}))))

    qty = _number(order["quantity"])
    price = _number(order["limit_price"])
    if qty is None or price is None:
        return _no("quantity and limit_price must be numbers")
    if qty <= 0 or price <= 0:
        return _no("quantity and limit_price must be positive")
    if order["side"] not in SIDES:
        return _no("unknown side %r" % (order["side"],))
    if order["order_type"] not in ORDER_TYPES:
        return _no("unknown order_type %r" % (order["order_type"],))

    notional = qty * price
    side = order["side"]

    # --- halt: the daily loss cap outranks every other consideration ----------
    pnl = _number(state.get("realized_pnl_today", 0.0))
    cap = _number(limits["daily_loss_cap"])
    if pnl is None or cap is None:
        return _no("daily_loss_cap state unreadable")
    if pnl <= -abs(cap):
        return _no("HALTED: daily_loss_cap reached (%.2f of %.2f)" % (pnl, -abs(cap)))

    # --- instrument -----------------------------------------------------------
    if order["symbol"] not in limits["allowlist"]:
        return _no("%s is not on the allowlist" % order["symbol"])
    if order["asset_class"] != "equity":
        if order["asset_class"] == "option" and not limits["allow_options"]:
            return _no("options are disabled")
        return _no("asset_class %r is not permitted" % (order["asset_class"],))
    if order["order_type"] == "market" and not limits["allow_market_orders"]:
        return _no("market orders are disabled")

    # --- timing ---------------------------------------------------------------
    blackout_end = datetime.datetime.combine(now.date(), market_open) + \
        datetime.timedelta(minutes=limits["opening_blackout_minutes"])
    if order["order_type"] == "market" and now < blackout_end:
        return _no("market orders are in the opening blackout until %s" % blackout_end.strftime("%H:%M"))

    if side == "sell":
        pos = (state.get("positions") or {}).get(order["symbol"])
        if not pos:
            return _no("no recorded position in %s to sell" % order["symbol"])
        try:
            opened = datetime.datetime.fromisoformat(pos["opened_at"])
        except (KeyError, TypeError, ValueError):
            return _no("position open time for %s is unreadable" % order["symbol"])
        held = (now - opened).total_seconds() / 60.0
        if held < limits["min_hold_minutes"]:
            return _no("min_hold_minutes not met (held %.0fm of %sm)" % (held, limits["min_hold_minutes"]))

    # --- size -----------------------------------------------------------------
    if notional > limits["max_order_notional"]:
        return _no("order notional %.2f exceeds max_order_notional %.2f"
                   % (notional, limits["max_order_notional"]))
    used = _number(state.get("notional_today", 0.0)) or 0.0
    if used + notional > limits["max_daily_notional"]:
        return _no("would exceed max_daily_notional (%.2f used + %.2f > %.2f)"
                   % (used, notional, limits["max_daily_notional"]))
    if side == "buy":
        exposure = _number(state.get("open_exposure", 0.0)) or 0.0
        if exposure + notional > limits["max_open_exposure"]:
            return _no("would exceed max_open_exposure (%.2f + %.2f > %.2f)"
                       % (exposure, notional, limits["max_open_exposure"]))

    return OK
