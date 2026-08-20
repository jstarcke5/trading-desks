#!/usr/bin/env python3
"""Generate this machine's desk configs. Run once after cloning.

The desk configs are GENERATED, not shipped. Two reasons, and the second is the important one:

  They contain absolute paths, which differ per machine.

  They contain a deny-list enumerating every top-level entry in your home directory — that is
  how each desk is confined to this project. Shipping one person's list would leak the names of
  every folder they have, which is a fingerprint of the software they run and the work they do.
  So the list is built from YOUR home directory, on YOUR machine, and never committed.
"""
import json, os, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parent
HOME = pathlib.Path.home()

def deny_outside_project():
    """Deny every top-level home entry except this project. Claude Code treats a single leading
    '/' as project-relative — absolute paths need '//'. That mistake silently disabled the whole
    deny list once; it is the reason this is generated rather than hand-written."""
    out = []
    for entry in sorted(os.listdir(HOME)):
        p = HOME / entry
        if p.resolve() == ROOT.resolve():
            continue
        out += ["Read(//%s/**)" % str(p).lstrip("/"), "Read(//%s)" % str(p).lstrip("/")]
    out += ["Read(//etc/**)", "Read(//var/**)", "Read(//private/**)", "Read(//tmp/**)",
            "Read(//Applications/**)", "Read(//Library/**)"]
    return out

SECRETS = ["Read(guardrail/**)", "Read(**/.rh-token.json)", "Read(**/.rh-client.json)",
           "Read(**/.env)", "Read(**/*credential*)", "Read(**/*secret*)"]
SHELL   = ["Bash", "KillShell", "BashOutput"]
SELF    = ["Edit(guardrail/**)", "Write(guardrail/**)", "Edit(desks/**)", "Write(desks/**)",
           "Edit(prompts/**)", "Write(prompts/**)", "Edit(handoff/**)", "Write(handoff/**)",
           "Edit(.claude/**)", "Write(.claude/**)", "Edit(CLAUDE.md)", "Edit(GOAL.md)",
           "Edit(CONTRACTS.md)"]
NO_WEB  = ["WebSearch", "WebFetch"]
JOURNAL = ["Edit(journal/JOURNAL.md)", "Write(journal/JOURNAL.md)",
           "Read(CLAUDE.md)", "Read(CONTRACTS.md)", "Read(GOAL.md)", "Read(prompts/**)"]

DESKS = {                       # desk -> (guardrail mode or None, may use the web)
    "watcher":  ("read-market",    False),
    "analyst":  (None,             True),
    "skeptic":  (None,             True),
    "risk":     ("read-portfolio", False),
    "executor": ("orders",         False),
}
GUARD_TOOLS = {"read-market":    ["get_quote", "get_bars", "market_clock"],
               "read-portfolio": ["get_positions", "get_account"],
               "orders":         ["place_order", "cancel_order", "get_order_status"]}

def main():
    (ROOT / "desks").mkdir(exist_ok=True)
    outside = deny_outside_project()
    for desk, (mode, web) in DESKS.items():
        servers = {"handoff": {"type": "stdio", "command": "python3",
                               "args": [str(ROOT / "handoff" / "server.py"), "--desk", desk]}}
        if mode:
            servers["guardrail"] = {"type": "stdio", "command": "python3",
                                    "args": [str(ROOT / "guardrail" / "server.py"),
                                             "--mode", mode]}
        (ROOT / "desks" / f"{desk}.mcp.json").write_text(
            json.dumps({"mcpServers": servers}, indent=2) + "\n")

        allow = ["mcp__handoff__send", "mcp__handoff__check_inbox"] + JOURNAL
        if mode:
            allow += ["mcp__guardrail__" + t for t in GUARD_TOOLS[mode]]
        deny = SECRETS + outside + SHELL + SELF + ([] if web else NO_WEB)
        if desk == "executor":
            deny += ["Write", "Edit", "NotebookEdit"]
            allow = [a for a in allow if not a.startswith(("Edit(", "Write("))]
        (ROOT / "desks" / f"{desk}.settings.json").write_text(json.dumps(
            {"permissions": {"allow": sorted(set(allow)), "deny": sorted(set(deny))}},
            indent=2) + "\n")
        print("  %-9s %d allow / %d deny" % (desk, len(set(allow)), len(set(deny))))

    cmds = ["# %s\nclaude --strict-mcp-config --mcp-config %s/desks/%s.mcp.json "
            "--settings %s/desks/%s.settings.json --append-system-prompt-file %s/prompts/%s.md"
            % (d.upper(), ROOT, d, ROOT, d, ROOT, d) for d in DESKS]
    (ROOT / "desks" / "START-COMMANDS.txt").write_text(
        "Paste each into that node's start command in October.\n\n" + "\n\n".join(cmds) + "\n")
    print("\nGenerated desks/. Next: python3 guardrail/connect.py to link your broker.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
