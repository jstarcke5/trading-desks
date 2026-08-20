---
name: thesis-forge
description: Build an investment thesis that can survive attack. Use when a signal arrives and a case must be constructed. Forces mechanism over pattern, and attaches the falsifier before the conclusion is written.
---

# Thesis forge

A pattern says *what happened*. A thesis says *why it should happen again*. Only the second
one is tradeable, and only the second one can be wrong in a useful way.

## 1. Surface the premises before building on them

List every assumption the idea rests on — about the mechanism, the participants, the
constraints, the horizon. For each one ask: **must this be true, or did I inherit it?**

Then take the load-bearing premise and invert it. What would an equally competent analyst who
believes the opposite construct from the same data? If you cannot state their case in a form
they would accept, you do not understand your own yet.

## 2. Name the mechanism

Say who is on the other side of this trade and why they are willing to lose. Real answers
exist — a forced seller, an insurance premium, a mandate constraint, a structural flow.

If your answer is "the market hasn't noticed", you have no mechanism. You are betting you are
faster and better informed than people who do this full time with better data. **You are not.**
That is not pessimism; it is the base rate.

## 3. Decompose before you commit

Break the space into independent dimensions — horizon, instrument, entry condition, exit
condition, sizing, universe. For each, ask what the ideal form looks like, and check three
scales rather than the obvious one:

- **micro** — the single trade: what has to be true at entry?
- **meso** — the campaign: what does a run of twenty look like, including the bad run?
- **macro** — the regime: what kills this entirely, and how would you notice in time?

Then look for the dimension that, if changed, changes all the others. Usually it is **horizon**,
because horizon sets the stop, the stop sets fee-in-R, and fee-in-R decides whether anything
else matters. Shifting one dimension often beats optimising five.

## 4. Read it back through four lenses, separately

Each lens sees what the others structurally cannot. Do not merge them until all four are done.

- **Correct** — does the logic hold, are the numbers right?
- **Robust** — what happens at the edges, in the gap, on the halt, in the thin book?
- **Honest** — where am I fooling myself? Which number did I pick after seeing it?
- **Systemic** — how does this interact with everything else already on?

## 5. Attach the falsifier, then write the conclusion

State in advance the specific observation that would make you abandon this. Not "if it stops
working" — a number, a date, a level, a count.

**A thesis without a pre-stated falsifier is not a thesis. It is a hope with a chart, and it
will be defended rather than tested.**

## Output

```
THESIS:     one sentence
MECHANISM:  who loses, and why they accept it
HORIZON:    and the stop that follows from it
FEE IN R:   the number — if > 0.05, stop here and say so
EVIDENCE:   estimate, n, both-halves check
FALSIFIER:  the specific observation that ends this
CONFIDENCE: and the largest single reason it might be wrong
```

Hand it to the Skeptic. Never route around them, however good it looks — *especially* when it
looks good, because that is exactly when the check is worth most.
