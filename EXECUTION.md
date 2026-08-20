# How this actually executes

Read this before expecting it to run itself. There are **two layers with different
lifecycles**, and conflating them is the main way people are surprised.

---

## Layer 1 — the Watcher daemon. Always on, zero tokens, zero attention.

`watcher/watch.py` is a plain Python loop. **It is not an agent.** It never calls a model, so
it costs nothing to leave running forever.

Every 5 minutes it: checks the market is open → checks the data is not fabricated → tests each
threshold → and almost always writes nothing. When something genuinely crosses, it appends one
`SIGNAL` to `watcher/signals.jsonl` and re-arms only after the condition resets.

Install it and forget it:
```bash
cp watcher/com.trading-canvas.watcher.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.trading-canvas.watcher.plist
tail -f watcher/watcher.log     # mostly the word "quiet", which is correct
```
**This layer needs nothing from you, ever.** It is the alarm clock.

---

## Layer 2 — the desks. These do NOT run continuously, and cannot.

Two facts that decide everything about how this feels to operate:

1. **October is a GUI app.** Close it and every desk stops. There is no headless October.
2. **A Claude session is turn-based.** It answers, then waits. It does not sit in a loop
   watching for work — something has to poke it.

So "five agents always running, trading for me" is **not** what this is, and any design that
claims otherwise is either burning tokens continuously or not doing anything.

### Mode A — Watched (what the canvas is for)
You open October. Desks pick up queued signals and work while you watch, wired together on the
board. You approve what needs approving.

- Costs tokens only while open.
- You see every handoff happen.
- **Nothing runs when the app is closed.**

### Mode B — Headless (automatic, but nothing to watch)
A cron job pokes the desks when — and only when — the watcher has queued something:

```bash
# only fires when signals.jsonl is non-empty; silent days cost nothing
*/15 9-16 * * 1-5  cd ~/trading-canvas && ./wake.sh
```
Runs without you. But it runs *outside* October, so there is no canvas to look at.

**The tension is real: automatic and watchable pull against each other**, because the watchable
part is a desktop app that must be open. Pick per session; they share all the same configs, so
switching costs nothing.

---

## What one signal actually triggers

```
watcher daemon                 zero tokens, runs 24/7
   │  writes SIGNAL only on a real crossing
   ▼
Watcher desk    reads the queue, sends SIGNAL ─────────► Analyst
Analyst         thesis-forge → THESIS  (or: fee-in-R too high, stops here)
   ▼
Skeptic         falsify → KILLED (journal, stop) | SURVIVED
   ▼
Risk            size-and-veto → VETO (journal, stop) | ORDER
   ▼
Executor        one submission through the guardrail → RESULT back to Risk
```

**Most signals die at the Analyst or the Skeptic.** That is the system working, not failing.
The expected steady state of this canvas is silence.

---

## What still needs a human, permanently

- Opening and funding the account; authorising the broker.
- Setting the limits in `guardrail/limits.json`.
- **Deciding whether a human approves each trade.** Note the tension: `CLAUDE.md` instructs the
  desks to act autonomously and never seek approval, and the generated Executor config
  pre-approves the order tool. **There is no built-in per-trade confirmation.** If you want one,
  you must remove `mcp__guardrail__place_order` from the Executor's allow list so each order
  raises a prompt.
- Reading the journal. Nothing else scores the calls, so nothing else makes this teach anything.

## What will never happen without you deciding it

`guardrail/server.py` transmits nothing unless **all three** of these hold:

1. `GUARDRAIL_UPSTREAM=http` in the environment
2. a valid broker token on disk (`guardrail/connect.py`)
3. **`guardrail/.armed` exists** — a file you create by hand

Absent any one, every order returns `SIMULATED`, including one a desk is talked into sending.

**This is not a claim that the system cannot trade.** The live order path is implemented and
works. These are three switches you control, not a missing feature — an earlier version of this
document said the live branch was unimplemented, which stopped being true and was dangerously
reassuring while it stood.
