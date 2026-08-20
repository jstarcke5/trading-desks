#!/usr/bin/env python3
"""Read passthrough to the broker.

Found as a stub: every read tool returned SIMULATED and never called Robinhood, so the Risk
desk would have been sizing against numbers it did not have -- confident arithmetic on fiction.

Reads may target ANY account the user owns; only writes are pinned to the agentic account.
Seeing total exposure across accounts is exactly what good sizing needs.
"""
import json, pathlib, sys, urllib.request

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import live  # noqa: E402  (shares the transport)

# local name -> the broker tool it actually calls. Nothing here can place an order.
BROKER_TOOL = {
    "get_quote":     "get_equity_quotes",
    "get_bars":      "get_equity_historicals",
    "get_positions": "get_equity_positions",
    "get_account":   "get_portfolio",
    "market_clock":  "get_equity_tradability",
}

def build_args(local_tool, args, pinned):
    a = dict(args or {})
    if local_tool in ("get_quote", "get_bars"):
        syms = a.pop("symbols", None) or a.pop("symbol", None)
        if isinstance(syms, str):
            syms = [syms]
        syms = [str(s).strip().upper() for s in (syms or []) if str(s).strip()]
        if not syms:
            raise ValueError("%s requires at least one symbol" % local_tool)
        a["symbols"] = syms
    if local_tool in ("get_positions", "get_account", "market_clock"):
        a.setdefault("account_number", pinned)     # default to the agentic one, but a caller
    return a                                        # may name another -- reads are not pinned

def execute(local_tool, args, pinned, token):
    target = BROKER_TOOL.get(local_tool)
    if target is None:
        return {"error": "no such read tool: %r" % local_tool}
    if not token:
        return {"status": "SIMULATED", "tool": local_tool,
                "detail": "no broker token — run guardrail/connect.py", "args": args}
    try:
        payload = build_args(local_tool, args, pinned)
    except ValueError as e:
        return {"error": str(e)}
    try:
        return {"status": "OK", "tool": local_tool, "data": live._call(token, target, payload)}
    except Exception as e:
        return {"status": "ERROR", "tool": local_tool, "detail": type(e).__name__}
