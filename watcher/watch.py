#!/usr/bin/env python3
"""Watcher daemon — the canvas's alarm clock.

This is NOT an agent. It is a plain polling loop that costs zero tokens. It exists so that
nothing on the canvas burns anything until something actually happens.

It never interprets. It detects a threshold crossing on closed bars and writes one SIGNAL.
Silence is the expected output on almost every poll.
"""
import argparse, datetime, json, pathlib, sys, time
from zoneinfo import ZoneInfo

MARKET_TZ = ZoneInfo("America/New_York")   # market hours are ET, never local time

MIN_BARS = 20

# Plausibility bounds on COMPUTED metrics. Checking the bars was not enough: a hostile or
# corrupted feed could set vol_20d to infinity, or crush the baseline to 0.0001 and produce a
# 136,500x ratio -- both fired signals. Bars can be sane while the numbers derived from them
# are not, and the derived numbers are what the rules actually read.
METRIC_CEILING  = 300.0   # annualised vol %. 2008 peaked near 90; 300 is corrupt data.
BASELINE_FLOOR  = 1.0     # a baseline below this manufactures an arbitrary ratio.
MAX_RATIO       = 20.0    # a genuine crisis is ~5x. 20x is a broken feed, not an event.

def plausible(value, floor=0.0, ceiling=METRIC_CEILING):
    """Return the value as a float only if it is finite, in range, and genuinely numeric.
    Strings are refused rather than coerced -- a typed feed that starts accepting strings is a
    feed whose shape nobody is checking."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    v = float(value)
    if v != v or v in (float("inf"), float("-inf")):    # NaN / infinity
        return None
    if not (floor <= v <= ceiling) or v <= 0.0:
        return None
    return v

# ---------------------------------------------------------------- data sanity
def data_is_sane(bars):
    """Robinhood served fabricated intraday bars -- interpolated:true, zero volume, flat OHLC.
    It was caught only because an RVOL filter divided by zero. Any study without this check is
    silently meaningless, and a fabricated series looks exactly like a real one."""
    if not bars or len(bars) < MIN_BARS:
        return False, "only %d bars (need %d)" % (len(bars or []), MIN_BARS)
    if any(b.get("interpolated") for b in bars):
        return False, "interpolated bars present -- data is fabricated"
    if any(float(b.get("volume", 0)) <= 0 for b in bars):
        return False, "zero volume bars present"
    flat = sum(1 for b in bars
               if b.get("open") == b.get("high") == b.get("low") == b.get("close"))
    if flat > len(bars) * 0.5:
        return False, "flat OHLC on %d/%d bars" % (flat, len(bars))
    return True, ""

# ---------------------------------------------------------------- market hours
def to_market_time(now):
    """Market hours are Eastern. A naive datetime is assumed to already be ET; an aware one is
    converted. Using local time was a real bug -- correct by accident on an ET machine, wrong
    everywhere else and wrong after travel."""
    if now.tzinfo is None:
        return now
    return now.astimezone(MARKET_TZ).replace(tzinfo=None)

def market_is_open(now, rules):
    et = to_market_time(now)
    if et.weekday() >= 5:
        return False
    o = datetime.datetime.strptime(rules["market_open"], "%H:%M").time()
    c = datetime.datetime.strptime(rules["market_close"], "%H:%M").time()
    return o <= et.time() <= c

# ---------------------------------------------------------------- thresholds
OPS = {">": lambda a, b: a > b, "<": lambda a, b: a < b,
       ">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b}

def evaluate(metrics, rule):
    """Return a SIGNAL dict if the rule crossed, else None. No interpretation, ever.

    op "x>" compares the metric to its OWN baseline as a multiple. Real data showed why this
    matters: an absolute vol threshold fires every day, because "high" is only meaningful
    relative to what is normal for that symbol.
    """
    value = plausible(metrics.get(rule["metric"]))
    if value is None:
        return None
    baseline = metrics.get(rule.get("baseline", ""))

    if rule["op"] in ("x>", "x<"):
        base = plausible(baseline, floor=BASELINE_FLOOR)
        if base is None:
            return None
        ratio = value / base
        if not (0.0 < ratio < MAX_RATIO):
            log("METRIC REFUSED %s: ratio %.1f outside plausible range" % (rule["symbol"], ratio))
            return None
        baseline = base
        hit = ratio > float(rule["threshold"]) if rule["op"] == "x>" \
            else ratio < float(rule["threshold"])
        if not hit:
            return None
        observed = "%s %.2f = %.2fx its %s of %.2f (rule: %s %s)" % (
            rule["metric"], float(value), ratio, rule.get("baseline"), float(baseline),
            rule["op"], rule["threshold"])
        return {"TYPE": "SIGNAL", "symbol": rule["symbol"], "observed": observed,
                "as_of": metrics.get("as_of", "unknown"),
                "context": "%.2fx normal for this symbol" % ratio,
                "key": "%s:%s:%s%s" % (rule["symbol"], rule["metric"], rule["op"],
                                       rule["threshold"])}

    op = OPS.get(rule["op"])
    if op is None or not op(float(value), float(rule["threshold"])):
        return None
    context = ("baseline %s = %s" % (rule.get("baseline"), baseline)
               if baseline is not None else "no baseline configured")
    return {
        "TYPE": "SIGNAL",
        "symbol": rule["symbol"],
        "observed": "%s %s (rule: %s %s %s)" % (rule["metric"], value, rule["metric"],
                                                rule["op"], rule["threshold"]),
        "as_of": metrics.get("as_of", "unknown"),
        "context": context,
        "key": "%s:%s:%s%s" % (rule["symbol"], rule["metric"], rule["op"], rule["threshold"]),
    }

# ---------------------------------------------------------------- dedupe
def emit_if_new(signal, seen_path):
    """A threshold that STAYS crossed is one event, not one per poll. Without this the canvas
    is woken every cycle and the token cost is unbounded."""
    seen = {}
    if seen_path.exists():
        try:
            seen = json.loads(seen_path.read_text())
        except ValueError:
            seen = {}
    if signal is None:
        return False
    key = signal["key"]
    if seen.get(key):
        return False
    seen[key] = True
    seen_path.parent.mkdir(parents=True, exist_ok=True)
    seen_path.write_text(json.dumps(seen))
    return True

def clear_if_reset(key, seen_path):
    if not seen_path.exists():
        return
    try:
        seen = json.loads(seen_path.read_text())
    except ValueError:
        return
    if seen.pop(key, None) is not None:
        seen_path.write_text(json.dumps(seen))

# ---------------------------------------------------------------- poll
def poll(feed, rules, now, out_path, seen_path):
    """One cycle. Returns how many SIGNALs were written -- normally zero."""
    return poll_status(feed, rules, now, out_path, seen_path)["written"]

def poll_status(feed, rules, now, out_path, seen_path):
    """One cycle, with a DISTINGUISHABLE outcome.

    Returning 0 for both "market closed" and "nothing crossed" was a real bug: a dead feed
    during market hours looked exactly like a calm afternoon in the log. Silence that cannot
    be told apart from failure is the most dangerous kind.
    """
    if not market_is_open(now, rules):
        return {"state": "closed", "written": 0, "problems": []}
    if not feed:
        return {"state": "no-data", "written": 0,
                "problems": ["feed is empty -- fetch.py has not run, or it failed"]}

    written, problems, checked = 0, [], 0
    for rule in rules["rules"]:
        data = feed.get(rule["symbol"])
        if not data:
            problems.append("%s: no data in feed" % rule["symbol"])
            continue
        ok, why = data_is_sane(data.get("bars") or [])
        if not ok:
            problems.append("%s: %s" % (rule["symbol"], why))
            log("DATA REFUSED %s: %s" % (rule["symbol"], why))
            continue
        checked += 1
        signal = evaluate(data, rule)
        key = "%s:%s:%s%s" % (rule["symbol"], rule["metric"], rule["op"], rule["threshold"])
        if signal is None:
            clear_if_reset(key, seen_path)          # armed again for next time
            continue
        if emit_if_new(signal, seen_path):
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with open(out_path, "a") as fh:
                fh.write(json.dumps(dict(signal, emitted_at=now.isoformat())) + "\n")
            written += 1
            log("SIGNAL %s %s" % (signal["symbol"], signal["observed"]))

    if written:
        state = "signal"
    elif checked == 0:
        state = "data-refused"
    else:
        state = "quiet"
    return {"state": state, "written": written, "problems": problems, "checked": checked}

def log(msg):
    sys.stderr.write("%s  %s\n" % (datetime.datetime.now().isoformat(timespec="seconds"), msg))
    sys.stderr.flush()

# ---------------------------------------------------------------- feed
def load_feed(path):
    """Pluggable. Defaults to a local file so the watcher runs with no broker connected.
    There is deliberately no live fetch here -- wire it only after Robinhood's real tools are
    enumerated, and route it through the guardrail's read-market mode."""
    try:
        return json.loads(pathlib.Path(path).read_text())
    except (OSError, ValueError):
        return {}

def main():
    here = pathlib.Path(__file__).resolve().parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--rules", default=str(here / "thresholds.json"))
    ap.add_argument("--feed", default=str(here / "feed.json"))
    ap.add_argument("--out", default=str(here / "signals.jsonl"))
    ap.add_argument("--seen", default=str(here / "seen.json"))
    ap.add_argument("--interval", type=int, default=300, help="seconds between polls")
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    rules = json.loads(pathlib.Path(a.rules).read_text())
    while True:
        st = poll_status(load_feed(a.feed), rules, datetime.datetime.now(MARKET_TZ),
                         pathlib.Path(a.out), pathlib.Path(a.seen))
        if st["state"] == "signal":
            pass                                   # already logged per signal
        elif st["state"] == "closed":
            log("market closed")
        elif st["state"] == "quiet":
            log("quiet (%d symbol(s) checked, nothing crossed)" % st["checked"])
        else:
            log("PROBLEM [%s] %s" % (st["state"], "; ".join(st["problems"]) or "unknown"))
        if a.once:
            return 0
        time.sleep(a.interval)

if __name__ == "__main__":
    sys.exit(main())
