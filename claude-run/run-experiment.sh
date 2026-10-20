#!/usr/bin/env bash
# One real, logged, headless Claude Code run for one experiment in experiments.json.
#   claude -p (host) --stdio--> docker run -i mcp-timeout-lab:0.1 [mcp_log_proxy.py --stdio--> slow_server.py]
# Clean run (as in the other labs): only this server's tools, no personal CLAUDE.md, no user settings, no memory.
# PAID: each run costs a few cents (cheapest model, $1 cap). Do not run before the plan is approved.
# Usage: claude-run/run-experiment.sh E2-tool-timeout-env      (evidence -> tests/out/E2-tool-timeout-env/)
set -uo pipefail
cd "$(dirname "$0")/.."
LAB="$(pwd -W 2>/dev/null || pwd)"
EXP="$1"
OUT="tests/out/$EXP"
[ -e "$OUT" ] && { echo "refusing: $OUT exists (evidence is never overwritten)" >&2; exit 1; }
mkdir -p "$OUT" claude-run/work
read_exp() { python -c "import json,sys; e=json.load(open('claude-run/experiments.json'))['$EXP']; print($1)"; }
PROMPT="$(read_exp "e['prompt']")"
OUTER="$(read_exp "e['outer_s']")"
TIMEOUT_FIELD="$(read_exp "', \"timeout\": %d' % e['server_timeout_ms'] if 'server_timeout_ms' in e else ''")"
ENVS="$(read_exp "' '.join(f'{k}={v}' for k,v in e['env'].items())")"
NAME="slow-lab-$EXP"

cat > "$OUT/mcp-config.json" <<JSON
{ "mcpServers": { "slow": {
  "command": "docker",
  "args": ["run", "-i", "--rm", "--name", "$NAME",
           "-v", "$LAB/$OUT:/out", "mcp-timeout-lab:0.1",
           "python3", "/opt/slow/proxy/mcp_log_proxy.py", "--log", "/out/mcp.jsonl",
           "--", "python3", "/opt/slow/server/slow_server.py", "--out", "/out"]$TIMEOUT_FIELD } } }
JSON

CLAUDE="${CLAUDE:-claude}"
"$CLAUDE" --version > "$OUT/claude-version.txt" 2>&1
echo "$ENVS" > "$OUT/env.txt"
echo "{\"started\": \"$(date -u +%FT%T.%3NZ)\"}" > "$OUT/timeline.jsonl"
(cd claude-run/work && MSYS_NO_PATHCONV=1 env $ENVS timeout "$OUTER" "$CLAUDE" -p "$PROMPT" \
   --model haiku --setting-sources project,local \
   --settings '{"claudeMdExcludes":["**/.claude/CLAUDE.md"],"autoMemoryEnabled":false}' \
   --mcp-config "$LAB/$OUT/mcp-config.json" --strict-mcp-config \
   --tools "" --allowedTools "mcp__slow" --permission-mode dontAsk --max-budget-usd 1 --no-session-persistence \
   --output-format stream-json --verbose < /dev/null) > "$OUT/claude.stream.jsonl" 2> "$OUT/claude.stderr.txt"
echo "{\"exit\": $?, \"ended\": \"$(date -u +%FT%T.%3NZ)\"}" >> "$OUT/timeline.jsonl"
docker rm -f "$NAME" >/dev/null 2>&1      # a hung server container outlives Claude Code otherwise
sed -i "s#$LAB#<lab>#g" "$OUT/mcp-config.json"
# the stream's init line carries the host working directory (JSON-escaped Windows path): show it as <lab> too
python - "$OUT/claude.stream.jsonl" <<'PY'
import io, re, sys
f = sys.argv[1]
t = io.open(f, encoding="utf8", newline="").read()
t = re.sub(r'[A-Za-z]:(?:\\\\[^"\\]+)*\\\\mcp-timeout-lab', "<lab>", t)
io.open(f, "w", encoding="utf8", newline="").write(t)
PY
python tests/analyze.py "$OUT" | tee "$OUT/summary.json"
