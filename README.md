# MCP timeout lab

What does Claude Code do when an MCP tool call is slow, silent or hung? A tiny stdio MCP server (`server/slow_server.py`,
standard library only) whose tools wait, report progress, or hang forever on purpose, and real headless Claude Code
runs against it, one timer setting per run. Every message is logged both ways by `proxy/mcp_log_proxy.py`.

## Run the tests (Docker; no AI, no network)

```
docker compose run --rm tests
```

`tests/test_server.py` checks the server with a scripted MCP client. `tests/test_analyze.py` checks the log reader.
`tests/test_evidence.py` asserts what Claude Code did in the recorded runs in `tests/out/E*/`.

## Re-run an experiment (paid: a fraction of a cent each on the cheapest model)

Needs `docker`, `claude` (logged in) and Python on the host. The experiments are defined in `claude-run/experiments.json`.

```
docker compose build
bash claude-run/run-experiment.sh E2-tool-timeout-env      # refuses to overwrite an existing run folder
```

## What we measured (Claude Code 2.1.303, `claude -p`, 19 Oct 2026)

| Run | Setting | Call | What happened |
|---|---|---|---|
| E2 | `MCP_TOOL_TIMEOUT=60000` | hang | error `MCP server "slow" tool "hang" timed out after 60s`; cancel sent to the server at 60.0 s |
| E3 | per-server `"timeout": 60000` | hang | the same error and cancel |
| E4 | `CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT=60000` | hang | error `... sent no response or progress for 60s; aborting. ...`; **no cancel sent** |
| E5 | idle 60 s | 150 s, progress every 10 s | finished: `waited 150 s` |
| E6 | idle 60 s | 150 s, silent | aborted with the idle error |
| E7 | per-server 60 s | 150 s, progress every 10 s | cut at 60 s anyway (progress does not extend the hard limit) |
| E1 | defaults | 150 s, silent | finished; no background task in headless mode; a heartbeat every 30 s |
| E8 | defaults | hang | nothing fired in 6 min; our own `timeout 360` ended it (`Connection closed`) |

Timer defaults are from https://code.claude.com/docs/en/mcp and https://code.claude.com/docs/en/env-vars (fetched 19 Oct 2026).

## Licence

Lab code: Apache License 2.0 (`LICENSE`).
