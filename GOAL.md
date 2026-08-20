# GOAL — the objective this canvas serves

Every thesis on this canvas must carry a falsifier. **It would be incoherent for the project
itself not to.** This file is that falsifier.

Without it, nothing can conclude: no gate can be judged too strict or too loose, no quarter can
be told apart from luck, and the enterprise becomes unfalsifiable at the top level — exactly the
sin every desk is forbidden from committing at the thesis level.

---

## The objective

> **Determine, with evidence, whether this architecture can produce risk-adjusted returns
> above a passive benchmark — and abandon it promptly if it cannot.**

Note what that is not. It is not "make money." The primary output of this system is a
**defensible answer**, and "no edge exists here" is a successful outcome delivered cheaply.
That is not a consolation prize; it is the more likely result and by far the cheaper one to
learn now rather than later.

## The parameters — set these before the first live trade

| | |
|---|---|
| Capital at risk | `TBD — an amount acceptable to lose in full` |
| Benchmark | broad-index buy & hold, same period, same capital |
| Horizon | 12 months minimum before any verdict |
| Max tolerable drawdown | `TBD` — breached = halt, not "ride it out" |
| Expected trade frequency | low. Most signals should die at the Skeptic |
| Success | beats benchmark net of costs **and** the calibration score is honest |
| Failure | anything else |

## Kill criteria — pre-registered, and binding

Hit any one of these and the project stops. No renegotiation at the time, because the whole
point of writing them now is that they are decided before the moment they hurt.

1. **Drawdown breach.** Halt immediately.
2. **12 months, no benchmark outperformance net of costs.** The answer is no.
3. **Calibration is dishonest** — stated confidence persistently unmatched by outcomes. A
   system that cannot know what it does not know cannot be trusted with more capital.
4. **Rejection scoring shows the gates were right all along** — i.e. almost nothing killed
   would have worked. Then there was never an edge to find, and the correct action is to stop
   looking, not to loosen the gates.
5. **Any invariant is weakened** to make a trade possible. That is the project failing, not
   the constraint.

## What "getting better" is allowed to mean

Learning updates the **map**. It never touches the **guardrails**.

**May be updated by evidence:** watcher thresholds · confidence priors · the known-dead list ·
per-desk track records · the calibration table.

**May never be updated by any automated process:** `guardrail/limits.json` · the gates in
CLAUDE.md §4 · the invariants in §8 · any desk config · this file.

Enforced structurally, not by instruction: the scorer writes to `learning/` only, and the desks
can write only to `journal/`. **A system that can edit its own constraints has none.**

## The honest expectation

The evidence base says the most likely outcome is kill criterion 2 or 4 — no edge, found
cheaply and early. **That is the bet.** This architecture is built to reach that verdict fast
and at low cost, and to be genuinely convincing if the answer turns out to be the other one.
