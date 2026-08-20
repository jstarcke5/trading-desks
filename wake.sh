#!/bin/bash
# Headless mode: poke the Analyst only when the watcher has queued something.
cd "$(dirname "$0")"
[ -s watcher/signals.jsonl ] || exit 0          # silence costs nothing
SIG=$(head -1 watcher/signals.jsonl)
claude --strict-mcp-config --mcp-config desks/analyst.mcp.json \
       --settings desks/analyst.settings.json \
       --append-system-prompt-file prompts/analyst.md \
       -p "[Watcher]: $SIG" < /dev/null
tail -n +2 watcher/signals.jsonl > watcher/.tmp && mv watcher/.tmp watcher/signals.jsonl
