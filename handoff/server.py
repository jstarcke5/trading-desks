#!/usr/bin/env python3
"""Handoff MCP server, scoped to ONE desk.

Launched as `--desk analyst`, it exposes only the routes that desk has. The Analyst's `send`
tool cannot address the Executor -- not because it is told not to, but because the route does
not exist in its schema. Its inbox reads only its own queue.
"""
import argparse, datetime, json, pathlib, sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import relay  # noqa: E402

BOX = HERE.parent / "handoffs"

def routes_for(desk):
    return {r: t for r, t in relay.FLOW.items() if r[0] == desk}

def tools_for(desk):
    out = []
    rs = routes_for(desk)
    if rs:
        targets = sorted({r[1] for r in rs})
        kinds = sorted({t for t in rs.values()})
        props = {"to": {"enum": targets}}
        for kind in kinds:
            for f in relay.SCHEMAS[kind]:
                if f != "TYPE":
                    props[f] = {"type": "string", "maxLength": relay.MAX_FIELD_CHARS}
        out.append({
            "name": "send",
            "description": ("Hand a typed artifact to the next desk. You may send %s to %s and "
                            "nowhere else. Only the listed fields travel -- your reasoning does "
                            "not. Every field is one short line." % ("/".join(kinds),
                                                                    "/".join(targets))),
            "inputSchema": {"type": "object", "additionalProperties": False,
                            "required": ["to"], "properties": props},
        })
    out.append({"name": "check_inbox",
                "description": "Read the typed artifacts addressed to this desk. Nothing else.",
                "inputSchema": {"type": "object", "additionalProperties": False, "properties": {}}})
    return out

def call(desk, name, args):
    if name == "check_inbox":
        items = relay.inbox(desk, BOX)
        return {"count": len(items), "artifacts": items} if items else \
               {"count": 0, "note": "Inbox empty. Silence is a normal state — do not invent work."}
    if name != "send":
        return {"error": "no such tool: %r" % name}

    to = args.get("to")
    rs = routes_for(desk)
    kind = rs.get((desk, to))
    if kind is None:
        return {"REFUSED": "no route from %s to %s — that edge does not exist" % (desk, to)}
    artifact = {k: v for k, v in args.items() if k != "to"}
    artifact["TYPE"] = kind
    ok, detail = relay.submit(desk, to, artifact, BOX)
    return {"delivered": detail} if ok else {"REFUSED": detail}

def serve(desk):
    tools = tools_for(desk)
    def reply(rid, result=None, error=None):
        m = {"jsonrpc": "2.0", "id": rid}
        m["error" if error else "result"] = error or result
        sys.stdout.write(json.dumps(m) + "\n"); sys.stdout.flush()
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            req = json.loads(raw)
        except ValueError:
            continue
        method, rid = req.get("method"), req.get("id")
        if method == "initialize":
            reply(rid, {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                        "serverInfo": {"name": "handoff-" + desk, "version": "1.0.0"}})
        elif method == "tools/list":
            reply(rid, {"tools": tools})
        elif method == "tools/call":
            p = req.get("params") or {}
            out = call(desk, p.get("name"), p.get("arguments") or {})
            reply(rid, {"content": [{"type": "text", "text": json.dumps(out)}],
                        "isError": "REFUSED" in out or "error" in out})
        elif rid is not None:
            reply(rid, error={"code": -32601, "message": "method not found"})

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--desk", required=True,
                    choices=["watcher", "analyst", "skeptic", "risk", "executor"])
    serve(ap.parse_args().desk)
