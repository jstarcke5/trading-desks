---
name: elevate
description: Enrichment pass over work that is already correct. Use after something passes its checks, to find what would make it genuinely excellent rather than merely right — then re-test the premises the enrichment exposes.
---

# Elevate

Run this **after** the work is correct, never instead of making it correct. Correctness is the
floor. This is about the distance between the floor and good.

Most work stops at "it passes." That is where the interesting part starts, because passing only
proves nothing is broken — it says nothing about whether the thing was worth building in the
shape you built it.

## 1. Find the cross-dimensional synergies

Look at the independent dimensions of the work and ask which pairs are currently ignoring each
other. Enrichment usually lives in the joins, not in any single part.

The question is not "is each piece good?" but **"does any piece make another piece
unnecessary?"** The best improvement often deletes something. A control that makes a second
control redundant is worth more than two controls, because there is now one thing to keep true
instead of two things to keep in sync.

## 2. Ask what would make this excellent, not adequate

For each dimension: if this were done by someone who does only this, what would be different?
Be specific. "More rigorous" is not an answer. "States n and the both-halves split inline, so
the reader cannot skip it" is.

Watch for the difference between **more** and **better**. Adding a fifth check to a process
that already has four is usually motion. Making one of the four impossible to skip is progress.

## 3. Make the right thing structural, not disciplined

The strongest enrichment converts a rule someone must remember into a property of the system
that holds without anyone remembering.

- A charter saying "don't do X" is discipline. Removing the tool that does X is structure.
- "Record every decision" is discipline. A handoff format that will not parse without the
  decision recorded is structure.

Ask of every rule you rely on: **what would make this true by construction?** Then ask the
harder follow-up — *does it fail loudly if it stops being true?* A structural guarantee that
degrades silently is worse than a rule someone checks, because it buys confidence it no longer
earns.

## 4. Then go back and re-test the premises

This is the step that gets skipped, and it is where the value is.

Your enrichment probably assumed something. Go back to the premises you accepted at the start
and ask: **does what I just found mean one of them should have been challenged?** And the
mirror: did I challenge something that turned out to be load-bearing and fine, and waste
effort defending a decision that was never in doubt?

Both directions carry information. Finding that an early premise was wrong is the most valuable
outcome available here, precisely because everything downstream inherited it.

## 5. Falsify the enrichment itself

New does not mean better. Before you keep any of it:

- What does this cost — in complexity, in things that must stay in sync, in ways to be wrong?
- Would a reasonable person call this over-engineering? If yes, they are probably right.
- Am I enriching because the work needs it, or because I want the work to look considered?

**Hold both at once: generate boldly, falsify honestly.** Neither dominates. An enrichment pass
that keeps everything it generated did not run its second half.

## Output

```
SYNERGIES:     dimensions that should be talking and are not
STRUCTURAL:    rules converted into properties (and how each fails loudly)
DELETED:       what became unnecessary — often the best line here
PREMISE SHIFT: which starting assumption this proved wrong
REJECTED:      enrichments generated and then discarded, with the reason
```

If `REJECTED` is empty, run it again. You generated but did not falsify.
