#!/usr/bin/env python3
"""Guardrail MCP proxy — sits between the Executor desk and Robinhood.

Re-exposes only the tools a mode needs, and hard-rejects anything over the configured
limits BEFORE it reaches the broker. Every decision is appended to audit.log.

Upstream defaults to `mock`. Live mode requires GUARDRAIL_UPSTREAM=http AND a token in
the environment; absent either, the server refuses to place orders. Fail closed.
"""
import argparse, datetime, json, os, sys, pathlib

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import guard, account, live, rhauth, reads, ledger  # noqa: E402
# NOTE: session.py and spread.py are deliberately NOT imported. They are written
# and tested but not enforced by this server, and an unused import would imply a
# wiring that does not exist. See README §10.

MARKET_OPEN = datetime.time(9, 30)
STATE_PATH  = HERE / "state.json"
AUDIT_PATH  = HERE / "audit.log"
LIMITS_PATH = HERE / "limits.json"

DESCRIPTIONS = {
    "get_quote":        "Latest quote for one allowlisted symbol.",
    "get_bars":         "Historical bars for one allowlisted symbol.",
    "market_clock":     "Whether the market is open, and the next open/close.",
    "get_positions":    "Current positions, read-only.",
    "get_account":      "Account balances and buying power, read-only.",
    "place_order":      "Submit an order. Rejected unless it clears every configured limit.",
    "cancel_order":     "Cancel a resting order by id.",
    "get_order_status": "Status of one previously submitted order.",
}

def audit(event, payload):
    line = json.dumps({"ts": datetime.datetime.now().isoformat(), "event": event, **payload})
    with open(AUDIT_PATH, "a") as fh:
        fh.write(line + "\n")

def load_json(path, default):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default

def order_schema():
    return {"type": "object", "additionalProperties": False,
            "required": sorted(guard.ORDER_FIELDS),
            "properties": {
                "symbol":      {"type": "string"},
                "side":        {"enum": ["buy", "sell"]},
                "quantity":    {"type": "number", "exclusiveMinimum": 0},
                "limit_price": {"type": "number", "exclusiveMinimum": 0},
                "order_type":  {"enum": ["limit", "market"]},
                "asset_class": {"enum": ["equity"]}}}

def commit(order, state, result=None):
    """Record what ACTUALLY filled, then reconcile against the broker.

    This previously booked quantity x limit_price as though every order filled in full at the
    limit price. A partial fill corrupted exposure in the dangerous direction, and a fill that
    landed after a timeout was recorded nowhere at all -- invisible to every control at once.
    """
    filled_qty, filled_notional = _filled_from(result, order)
    state = ledger.apply_fill(state, order.get("symbol"), order.get("side"),
                              filled_qty, filled_notional,
                              datetime.datetime.now().isoformat())
    # The broker is the truth; our file is a cache. Any divergence is a finding.
    # CRITICAL: only reconcile against a response we actually received. An empty list from a
    # FAILED read is not "you hold nothing" -- treating it that way would erase the entire
    # position book on any network blip, and every control reads that book.
    try:
        pos = reads.execute("get_positions", {}, account.pinned(), rhauth.bearer())
        if pos.get("status") == "OK":
            rows = (((pos.get("data") or {}).get("data") or {}).get("results")
                    or (pos.get("data") or {}).get("results") or [])
            state, drift = ledger.reconcile(state, rows)
            for d in drift:
                audit("DRIFT", {"detail": d})
        else:
            audit("RECONCILE-SKIPPED",
                  {"reason": pos.get("status"), "note": "broker unreadable — local book kept"})
    except Exception as e:
        audit("RECONCILE-FAILED", {"error": type(e).__name__,
                                   "note": "local book kept; never zeroed on a failed read"})
    with open(STATE_PATH, "w") as fh:
        json.dump(state, fh, indent=2)
    return state

def _filled_from(result, order):
    """Prefer the broker's reported fill. Fall back to the request ONLY when the broker said
    nothing -- and record that fallback, because it is an assumption, not an observation."""
    data = ((result or {}).get("result") or {}).get("data") or {}
    for qty_key, amt_key in (("filled_quantity", "executed_notional"),
                             ("cumulative_quantity", "filled_notional")):
        q = data.get(qty_key)
        if q is not None:
            try:
                return float(q), float(data.get(amt_key) or 0)
            except (TypeError, ValueError):
                pass
    audit("FILL-ASSUMED", {"symbol": order.get("symbol"),
                           "note": "broker reported no fill quantity; assumed requested size"})
    try:
        if order.get("dollar_amount"):
            return 0.0, float(order["dollar_amount"])
        return float(order.get("quantity") or 0), \
               float(order.get("quantity") or 0) * float(order.get("limit_price") or 0)
    except (TypeError, ValueError):
        return 0.0, 0.0


def upstream_place(order):
    try:
        return _upstream_place(order)
    except Exception as e:                      # a bug must not take the proxy down mid-order
        audit("PLACE-CRASH", {"error": type(e).__name__})
        return {"status": "REFUSED",
                "detail": ("guardrail error (%s) — nothing was transmitted. Check "
                           "get_equity_orders before any retry." % type(e).__name__)}

def _upstream_place(order):
    """The only path to a real broker. Refuses unless explicitly configured."""
    token = rhauth.bearer()
    if not live.transmission_enabled(os.environ, token):
        why = ("GUARDRAIL_UPSTREAM is not 'http'"
               if os.environ.get("GUARDRAIL_UPSTREAM") != "http"
               else "no valid broker token — run guardrail/connect.py")
        return {"status": "SIMULATED", "detail": "not transmitted (%s)" % why, "order": order}

    pinned = account.pinned()
    if not pinned:
        return {"status": "REFUSED", "detail": "no agentic account pinned"}

    from zoneinfo import ZoneInfo
    gate_ok, gate_why = live.market_gate(
        datetime.datetime.now(ZoneInfo("America/New_York")), load_json(LIMITS_PATH, {}) or {})
    if not gate_ok:
        audit("REFUSED", {"stage": "market-gate", "reason": gate_why})
        return {"status": "REFUSED", "detail": gate_why}

    limits = load_json(LIMITS_PATH, {}) or {}
    state = ledger.roll(load_json(STATE_PATH, {}) or {}, datetime.date.today().isoformat())

    normalised = dict(order)
    normalised["type"] = order.get("type") or order.get("order_type")

    # Broker-shaped rules that guard.evaluate knows nothing about: market orders must be
    # notional, hours and time-in-force are forced, and size is tested against REAL buying
    # power rather than a remembered number. These need a live broker, so they run here.
    bp = None
    try:
        acct = reads.execute("get_account", {}, pinned, token)
        bp = float((((acct.get("data") or {}).get("data") or {})
                    .get("buying_power") or {}).get("buying_power"))
    except Exception:
        bp = None
    from zoneinfo import ZoneInfo as _Z
    ok2, why2 = live.check(normalised, limits, state, bp,
                           now=datetime.datetime.now(_Z("America/New_York")))
    if not ok2:
        audit("REFUSED", {"stage": "live-check", "reason": why2})
        return {"status": "REFUSED", "detail": why2}
    sess = (load_json(LIMITS_PATH, {}) or {}).get("session") or {}
    payload = live.build_payload(normalised, pinned,
                                 ref_id=ledger.ref_id_for(normalised, sess.get("start", "day")))
    safe, why = account.enforce("place_equity_order", payload)
    if safe is None:
        audit("REFUSED", {"stage": "account-pin", "reason": why})
        return {"status": "REFUSED", "detail": why}

    try:                                   # review first: see the real quote before it is live
        reviewed = live.review(token, safe)
    except Exception as e:
        audit("REFUSED", {"stage": "review", "error": type(e).__name__})
        return {"status": "REFUSED",
                "detail": "review failed (%s) — not placing" % type(e).__name__}
    audit("reviewed", {"ref_id": safe["ref_id"], "symbol": safe["symbol"]})

    ok, why = live.may_place(reviewed=bool(reviewed))
    if not ok:
        return {"status": "REFUSED", "detail": why}

    try:                                   # place, with the idempotency key
        result = live.place(token, safe)
    except Exception as e:
        audit("PLACE-ERROR", {"ref_id": safe["ref_id"], "error": type(e).__name__})
        return {"status": "REFUSED",
                "detail": ("place failed (%s) — do NOT retry without first checking "
                           "get_equity_orders" % type(e).__name__)}
    audit("PLACED", {"ref_id": safe["ref_id"], "symbol": safe["symbol"],
                     "dollar_amount": safe.get("dollar_amount")})
    return {"status": "PLACED", "ref_id": safe["ref_id"], "review": reviewed, "result": result}

def call_tool(mode, name, args):
    if name not in guard.tools_for_mode(mode):
        audit("tool_denied", {"mode": mode, "tool": name})
        return {"error": "tool %r is not available in mode %r" % (name, mode)}

    if name != "place_order":
        # These were stubs echoing their own arguments back. The Risk desk was sizing against
        # fiction -- confident arithmetic on numbers nobody had.
        return reads.execute(name, args, account.pinned(), rhauth.bearer())

    limits = load_json(LIMITS_PATH, None)
    if limits is None:
        audit("refused", {"reason": "limits.json unreadable"})
        return {"status": "REFUSED", "reason": "limits.json unreadable — refusing to trade"}
    state = ledger.roll(load_json(STATE_PATH, {"realized_pnl_today": 0.0, "notional_today": 0.0,
                                               "open_exposure": 0.0, "positions": {}}),
                        datetime.date.today().isoformat())
    decision = guard.evaluate(args, limits, state, datetime.datetime.now(), MARKET_OPEN)
    if not decision.ok:
        audit("REFUSED", {"order": args, "reason": decision.reason})
        return {"status": "REFUSED", "reason": decision.reason}
    audit("allowed", {"order": args})
    result = upstream_place(args)
    if result.get("status") != "REFUSED":
        commit(args, state, result)
    return result

def serve(mode):
    tools = [{"name": n, "description": DESCRIPTIONS[n],
              "inputSchema": order_schema() if n == "place_order"
              else {"type": "object", "additionalProperties": True, "properties": {}}}
             for n in guard.tools_for_mode(mode)]

    def reply(rid, result=None, error=None):
        msg = {"jsonrpc": "2.0", "id": rid}
        msg["error" if error else "result"] = error or result
        sys.stdout.write(json.dumps(msg) + "\n"); sys.stdout.flush()

    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            req = json.loads(raw)
        except ValueError:
            continue
        method, rid = req.get("method"), req.get("id")
        if method == "initialize":
            reply(rid, {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                        "serverInfo": {"name": "guardrail", "version": "1.0.0"}})
        elif method == "tools/list":
            reply(rid, {"tools": tools})
        elif method == "tools/call":
            p = req.get("params") or {}
            out = call_tool(mode, p.get("name"), p.get("arguments") or {})
            reply(rid, {"content": [{"type": "text", "text": json.dumps(out)}],
                        "isError": out.get("status") in ("REFUSED",) or "error" in out})
        elif rid is not None:
            reply(rid, error={"code": -32601, "message": "method not found"})

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", required=True, choices=["read-market", "read-portfolio", "orders"])
    serve(ap.parse_args().mode)
