#!/usr/bin/env python3
"""Fetch real daily bars and write the watcher's feed. Stdlib only, no broker, no account.

Deliberately a separate process from watch.py: fetching touches the network, evaluating does
not. The watcher stays offline and reads a file, so a bad or hostile feed cannot reach it as
anything other than data -- and it re-runs the sanity check itself before trusting any of it.

FAILS CLOSED: if the data does not pass the sanity check, the existing feed is left untouched
rather than overwritten with something worse.
"""
import argparse, json, pathlib, statistics, sys, urllib.request

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import watch  # noqa: E402

SRC = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range={rng}&interval=1d"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh) trading-canvas/1.0"}

def fetch_bars(symbol, rng="6mo", timeout=20):
    url = SRC.format(sym=symbol, rng=rng)
    raw = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()
    res = json.loads(raw)["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    out = []
    for i, ts in enumerate(res["timestamp"]):
        o, h, l, c, v = (q["open"][i], q["high"][i], q["low"][i], q["close"][i], q["volume"][i])
        if None in (o, h, l, c, v):
            continue                      # a gap is dropped, never interpolated
        out.append({"date": ts, "open": o, "high": h, "low": l, "close": c, "volume": v})
    return out

def realised_vol(bars, window):
    """Annualised close-to-close vol over the last `window` bars, in percent."""
    closes = [b["close"] for b in bars][-(window + 1):]
    if len(closes) < window + 1:
        return None
    rets = [(closes[i] / closes[i - 1] - 1.0) for i in range(1, len(closes))]
    if len(rets) < 2:
        return None
    return statistics.stdev(rets) * (252 ** 0.5) * 100.0

def rolling_vol_median(bars, window, lookback):
    vals = []
    for end in range(len(bars) - lookback, len(bars) + 1):
        if end <= window:
            continue
        v = realised_vol(bars[:end], window)
        if v is not None:
            vals.append(v)
    return statistics.median(vals) if vals else None

def build(symbols, rng="6mo"):
    feed, problems = {}, []
    for sym in symbols:
        try:
            bars = fetch_bars(sym, rng)
        except Exception as e:                       # network, shape, anything
            problems.append("%s: fetch failed (%s)" % (sym, type(e).__name__))
            continue
        ok, why = watch.data_is_sane(bars)
        if not ok:
            problems.append("%s: %s" % (sym, why))   # fail closed, do not include it
            continue
        v20 = realised_vol(bars, 20)
        med = rolling_vol_median(bars, 20, 30)
        if v20 is None or med is None:
            problems.append("%s: not enough history to compute vol" % sym)
            continue
        feed[sym] = {"vol_20d": round(v20, 2), "vol_30d_median": round(med, 2),
                     "as_of": str(bars[-1]["date"]), "bars": bars[-60:]}
    return feed, problems

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="SPY,QQQ")
    ap.add_argument("--out", default=str(HERE / "feed.json"))
    ap.add_argument("--range", default="6mo")
    a = ap.parse_args()
    feed, problems = build([s.strip().upper() for s in a.symbols.split(",") if s.strip()], a.range)
    for p in problems:
        watch.log("FEED PROBLEM " + p)
    if not feed:
        watch.log("no usable data -- existing feed left untouched (fail closed)")
        return 1
    pathlib.Path(a.out).write_text(json.dumps(feed, indent=2) + "\n")
    for sym, d in feed.items():
        watch.log("feed %s  vol_20d=%.2f  median=%.2f  bars=%d"
                  % (sym, d["vol_20d"], d["vol_30d_median"], len(d["bars"])))
    return 0

if __name__ == "__main__":
    sys.exit(main())
