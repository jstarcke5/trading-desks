---
name: falsify
description: Kill protocol for a proposed thesis. Use whenever a thesis, edge, signal, or trade idea arrives and must be attacked before it can proceed. Produces a KILLED or SURVIVED verdict with the specific reason. Not a second opinion — an attack.
---

# Falsify

Your job is to end this idea. If it survives a genuine attempt to end it, it may proceed — and
only then. You are not balancing pros and cons. Nobody asked for balance.

**The standard: an edge that dies under attack was never an edge. Finding that out here is
free. Finding it out with money is not.**

## Order of attack — cheapest kill first

Stop at the first one that lands. Do not run the expensive checks on an idea that dies to a
cheap one.

**1. Cost.** Compute `fee in R = (2 × fee%) ÷ (stop%)`. Over 0.05? **KILLED.** Most ideas die
here, in under a minute, and it is the highest-value minute in this whole process.

**2. Prior art.** Is this a known-dead idea wearing a new name? Check §5 of CLAUDE.md.
Renaming momentum does not revive it. **KILLED** if it is.

**3. Sample.** What is n? Under ~80 observations, there is no result to discuss — only noise
someone got attached to. **KILLED**, and say what n would be needed.

**4. Selection.** Where did the universe come from? If it was assembled after seeing which
names worked, or excludes anything that delisted, the number is fiction. Ask what the result
would be on everything that ever traded.

**5. Beta.** Subtract the index. Most "edges" are market exposure with extra steps. If alpha
dies when you strip beta, it was never alpha.

**6. Durability.** Split the period. Positive in one half and negative in the other is not an
edge, it is a regime you noticed after it ended.

**7. Look-ahead.** Does any input use information unavailable at decision time? A single
shifted bar invalidates everything downstream. This is the failure people miss most often
because the backtest looks *better*, not broken.

**8. The nonsense control.** Would a deliberately meaningless variant score similarly? If yes,
the harness is broken and the result is void no matter how good it looks.

## Then attack yourself

Before you write SURVIVED, argue the opposite for real:

- What would make me wrong about this surviving?
- What is the most charitable case *against* my kill — and does it hold?
- Am I killing this because it is weak, or because killing is easier and looks rigorous?
- Am I passing it because it is strong, or because I have already attacked six things today?

Both failure modes are real. A skeptic who kills everything is as useless as one who kills
nothing — neither carries information.

## Output

```
VERDICT: KILLED | SURVIVED
GATE:    which check ended it (or "cleared all")
REASON:  one sentence, with the number
n:       sample size
IF WRONG: the observation that would reverse this verdict
```

`SURVIVED` obliges you to state what would still kill it later. A verdict with no falsifier
attached is an opinion, and opinions do not clear gates.

Never soften a kill to be agreeable. "Looks fine" is not an output.
