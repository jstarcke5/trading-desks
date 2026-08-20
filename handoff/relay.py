#!/usr/bin/env python3
"""Typed handoffs between desks. The contract is the tool, not a document.

Why this exists: CONTRACTS.md described the handoff format, but a description is a rule
someone must follow. The Analyst could paste its entire chain of thought into a message and
the Skeptic would be reading the ARGUMENT rather than the CLAIM -- at which point it is
persuaded rather than adversarial, and the separation of powers has quietly collapsed while
still looking correct on the canvas.

So free prose is given nowhere to go: only these fields exist, each capped to one short line.
The Skeptic receives an artifact, never a case.
"""
import datetime, json, pathlib

MAX_FIELD_CHARS = 400
MAX_LINES = 3          # a field is a value, not an essay

SCHEMAS = {
    "SIGNAL":  ["TYPE", "symbol", "observed", "as_of", "context"],
    "THESIS":  ["TYPE", "symbol", "claim", "mechanism", "horizon", "fee_in_R",
                "evidence", "falsifier", "confidence"],
    "VERDICT": ["TYPE", "symbol", "verdict", "gate", "reason", "residual"],
    "ORDER":   ["TYPE", "symbol", "side", "quantity", "limit_price", "order_type",
                "asset_class", "stop", "headroom", "falsifier"],
    "RESULT":  ["TYPE", "status", "detail"],
}

# The only routes that exist. Anything else has no path, not a blocked path.
FLOW = {
    ("watcher",  "analyst"):  "SIGNAL",
    ("analyst",  "skeptic"):  "THESIS",
    ("skeptic",  "risk"):     "VERDICT",
    ("risk",     "executor"): "ORDER",
    ("executor", "risk"):     "RESULT",
}

def validate(sender, recipient, artifact):
    expected = FLOW.get((sender, recipient))
    if expected is None:
        return False, "no route from %r to %r — that edge does not exist" % (sender, recipient)
    if not isinstance(artifact, dict):
        return False, "artifact must be an object"

    kind = artifact.get("TYPE")
    if kind != expected:
        return False, "the %s→%s edge expects %s, got %r" % (sender, recipient, expected, kind)

    fields = SCHEMAS[expected]
    unknown = set(artifact) - set(fields)
    if unknown:
        return False, ("unknown field(s): %s — this edge carries only %s. Reasoning does not "
                       "travel; only the artifact does."
                       % (", ".join(sorted(unknown)), ", ".join(fields)))
    missing = [f for f in fields if not str(artifact.get(f, "")).strip()]
    if missing:
        return False, "missing or empty: %s" % ", ".join(missing)

    for f in fields:
        v = str(artifact[f])
        if len(v) > MAX_FIELD_CHARS:
            return False, ("%s is too long (%d chars, max %d) — a field is a value, not a case"
                           % (f, len(v), MAX_FIELD_CHARS))
        if v.count("\n") >= MAX_LINES:
            return False, "%s must be a single short line, not a narrative" % f
    return True, ""

def submit(sender, recipient, artifact, root):
    ok, why = validate(sender, recipient, artifact)
    if not ok:
        return False, why
    box = pathlib.Path(root) / recipient
    box.mkdir(parents=True, exist_ok=True)
    stamped = dict(artifact, _from=sender,
                   _at=datetime.datetime.now().isoformat(timespec="seconds"))
    name = "%s-%s.json" % (stamped["_at"].replace(":", ""), sender)
    (box / name).write_text(json.dumps(stamped, indent=2) + "\n")
    return True, str(box / name)

def inbox(desk, root):
    """Only this desk's artifacts. No desk can read another's queue."""
    box = pathlib.Path(root) / desk
    if not box.is_dir():
        return []
    out = []
    for p in sorted(box.glob("*.json")):
        try:
            out.append(json.loads(p.read_text()))
        except ValueError:
            continue
    return out
