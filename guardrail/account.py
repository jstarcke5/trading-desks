#!/usr/bin/env python3
"""Account pinning + tool allowlist for the guardrail.

A broker OAuth token typically sees EVERY account the holder owns -- ordinary brokerage
accounts, retirement accounts, and the agentic one. Robinhood marks the first two agentic_allowed=false, but a limit
enforced only on someone else's server is not our limit. We pin exactly one account number and
refuse every request that names anything else, before it leaves this machine.

Fail closed throughout: no pin means nothing is permitted, and an unknown tool is refused.
"""
import json, os, pathlib

HERE = pathlib.Path(__file__).resolve().parent
PIN_PATH = HERE / "account.json"

class NoAgenticAccount(Exception): pass
class AmbiguousAccount(Exception): pass

# Explicit allowlist. Anything Robinhood adds later is refused until reviewed by a human.
PERMITTED_TOOLS = {
    # reads
    "get_accounts", "get_portfolio", "get_equity_positions", "get_equity_orders",
    "get_equity_quotes", "get_equity_historicals", "get_equity_fundamentals",
    "get_equity_price_book", "get_equity_tradability", "get_equity_tax_lots",
    "get_equity_technical_indicators", "get_realized_pnl", "get_pnl_trade_history",
    "get_financials", "get_earnings_calendar", "get_earnings_results",
    "get_index_quotes", "get_index_historicals", "get_indexes", "search",
    # simulate before acting
    "review_equity_order",
    # act -- equities only, and only ever via the guardrail's checked path
    "place_equity_order", "cancel_equity_order",
}

# Named explicitly so the intent is on the record, not just implied by omission.
FORBIDDEN_TOOLS = {
    "place_option_order", "review_option_order", "exercise_option",
    "cancel_option_exercise", "cancel_option_order", "get_option_level_upgrade_info",
    "get_limited_margin_upgrade_info",
}

# Tools that CHANGE something. Reads may touch any account the user owns; writes may only
# ever touch the pinned agentic account.
WRITE_TOOLS = {"place_equity_order", "cancel_equity_order"}

def is_write(name):
    return name in WRITE_TOOLS

def tool_permitted(name):
    if name in FORBIDDEN_TOOLS:
        return False
    return name in PERMITTED_TOOLS

# ------------------------------------------------------------------ selection
def validate_pinnable(acct):
    if not acct.get("agentic_allowed"):
        raise ValueError("account %s is not agentic_allowed — refusing to pin it"
                         % acct.get("account_number"))
    if acct.get("deactivated") or acct.get("permanently_deactivated"):
        raise ValueError("account %s is deactivated" % acct.get("account_number"))
    if acct.get("state") not in (None, "active"):
        raise ValueError("account %s is not active" % acct.get("account_number"))
    if acct.get("type") == "margin":
        raise ValueError("account %s is a margin account — leverage was measured to destroy "
                         "risk-adjusted returns here; cash only" % acct.get("account_number"))
    if "ira" in str(acct.get("brokerage_account_type", "")).lower():
        raise ValueError("account %s is a retirement account — never in scope"
                         % acct.get("account_number"))
    if not str(acct.get("account_number", "")).strip():
        raise ValueError("account has no account_number")
    return True

def choose(accounts):
    """Pick the single agentic account. Ambiguity is refused, never guessed."""
    agentic = [a for a in (accounts or []) if a.get("agentic_allowed")]
    if not agentic:
        raise NoAgenticAccount("no account has agentic_allowed=true")
    if len(agentic) > 1:
        raise AmbiguousAccount("%d agentic accounts found (%s) — a human must choose"
                               % (len(agentic), ", ".join(a["account_number"] for a in agentic)))
    validate_pinnable(agentic[0])
    return agentic[0]

# ------------------------------------------------------------------ pin store
def pin(acct, path=PIN_PATH):
    validate_pinnable(acct)
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "account_number": str(acct["account_number"]),
        "nickname": acct.get("nickname"),
        "type": acct.get("type"),
        "brokerage_account_type": acct.get("brokerage_account_type"),
    }, indent=2) + "\n")
    os.chmod(p, 0o600)
    return p

def pinned(path=PIN_PATH):
    try:
        d = json.loads(pathlib.Path(path).read_text())
        n = str(d.get("account_number", "")).strip()
        return n or None
    except (OSError, ValueError):
        return None

# ------------------------------------------------------------------ enforcement
def _account_numbers_in(obj):
    """Find account_number anywhere in the payload — nesting must not be a loophole."""
    found = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("account_number", "rhs_account_number") and isinstance(v, (str, int)):
                found.append(str(v))
            else:
                found.extend(_account_numbers_in(v))
    elif isinstance(obj, list):
        for v in obj:
            found.extend(_account_numbers_in(v))
    return found

def check_args(args, path=PIN_PATH):
    want = pinned(path)
    if not want:
        return False, "no account pinned — refusing everything"
    for got in _account_numbers_in(args):
        if got != want:
            return False, ("account %s is not the pinned agentic account (%s) — refused"
                           % (got, want))
    return True, ""

def enforce(tool, args, path=PIN_PATH):
    """Return (safe_args, "") or (None, reason).

    READS pass through untouched — seeing the whole portfolio is useful and harmless, and
    narrowing a read would hide real exposure from the Risk desk.

    WRITES must name the pinned agentic account. A wrong account is REFUSED, never rewritten:
    silently correcting it would hide a bug that should be loud.
    """
    if not is_write(tool):
        return dict(args or {}), ""
    want = pinned(path)
    if not want:
        return None, "no account pinned — refusing every write"
    ok, why = check_args(args, path)
    if not ok:
        return None, why
    out = dict(args or {})
    if "account_number" not in out:
        out["account_number"] = want          # inject, never assume the broker's default
    return out, ""
