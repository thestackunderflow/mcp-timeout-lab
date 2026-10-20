"""Summarize one experiment folder: when each tools/call went out, when (if ever) it was answered or cancelled,
progress notifications, the tool errors Claude Code saw, the final text, model, cost and exit code.
Usage: python tests/analyze.py tests/out/E2-tool-timeout-env"""
import datetime, json, os, sys


def ts(s):
    return datetime.datetime.fromisoformat(s.replace('Z', '+00:00'))


def jsonl(path):
    if not os.path.exists(path):
        return []
    out = []
    for line in open(path, encoding='utf8'):
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def summarize(d):
    mcp = jsonl(os.path.join(d, 'mcp.jsonl'))
    calls = {}
    for r in mcp:
        m = r.get('msg')
        if not isinstance(m, dict):
            continue
        if r['dir'] == 'client->server' and m.get('method') == 'tools/call':
            p = m['params']
            calls[m['id']] = {'id': m['id'], 'tool': p.get('name'), 'arguments': p.get('arguments'), 'sent': r['t'],
                              'token': (p.get('_meta') or {}).get('progressToken'), 'answered_after_s': None,
                              'cancelled_after_s': None, 'cancel_reason': None, 'progress_notifications': 0}
        elif r['dir'] == 'client->server' and m.get('method') == 'notifications/cancelled':
            c = calls.get(m['params'].get('requestId'))
            if c:
                c['cancelled_after_s'] = round((ts(r['t']) - ts(c['sent'])).total_seconds(), 3)
                c['cancel_reason'] = m['params'].get('reason')
        elif r['dir'] == 'server->client' and m.get('method') == 'notifications/progress':
            for c in calls.values():
                if c['token'] == m['params'].get('progressToken'):
                    c['progress_notifications'] += 1
        elif r['dir'] == 'server->client' and m.get('id') in calls:
            c = calls[m['id']]
            c['answered_after_s'] = round((ts(r['t']) - ts(c['sent'])).total_seconds(), 3)
    stream = jsonl(os.path.join(d, 'claude.stream.jsonl'))
    errors, result, model, events = [], None, None, []
    for e in stream:
        if e.get('type') == 'system' and e.get('subtype') == 'init':
            model = e.get('model')
        elif e.get('type') == 'system':
            events.append({k: e.get(k) for k in ('subtype', 'status', 'task_id', 'description') if e.get(k) is not None})
        if e.get('type') == 'user':
            for b in (e.get('message') or {}).get('content') or []:
                if isinstance(b, dict) and b.get('type') == 'tool_result' and b.get('is_error'):
                    c = b.get('content')
                    errors.append(c if isinstance(c, str) else ' '.join(x.get('text', '') for x in c if isinstance(x, dict)))
        if e.get('type') == 'result':
            result = e
    tl = jsonl(os.path.join(d, 'timeline.jsonl'))
    exit_ = next((x['exit'] for x in tl if 'exit' in x), None)
    started = next((x['started'] for x in tl if 'started' in x), None)
    ended = next((x['ended'] for x in tl if 'ended' in x), None)
    return {
        'folder': os.path.basename(os.path.normpath(d)),
        'model': model, 'exit': exit_,
        'wall_s': round((ts(ended) - ts(started)).total_seconds(), 1) if started and ended else None,
        'calls': list(calls.values()), 'tool_errors': errors, 'system_events': events,
        'final_text': result.get('result') if result else None,
        'cost_usd': result.get('total_cost_usd') if result else None,
        'turns': result.get('num_turns') if result else None,
        'server_events': jsonl(os.path.join(d, 'server-events.jsonl')),
    }


if __name__ == '__main__':
    print(json.dumps(summarize(sys.argv[1]), indent=2))
