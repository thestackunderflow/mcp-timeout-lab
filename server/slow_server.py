"""slow-lab: a tiny stdio MCP server whose tools are slow, silent or hung on purpose, to see what an MCP client
(Claude Code) does about it. Standard library only. Every request runs on its own thread, so the server keeps
answering (and logging cancellations) while one call hangs, like a real server stuck inside one operation.

    python3 slow_server.py --out /out

Tools
  wait_seconds(seconds, progress_every?)   sleep; sends notifications/progress every N s if the call has a progressToken
  hang()                                   never answers (ignores cancellation, like a server stuck in native code)
  slow_task(steps, seconds_per_step, save_as_you_go?, hang_at_step?)   multi-step work; optionally saves each step
  save_step(name, note?)                   writes out/steps/<name>.txt
Events (cancellations, call starts and ends) go to out/server-events.jsonl.
"""
import argparse, datetime, json, os, sys, threading, time

TOOLS = [
    {'name': 'wait_seconds', 'description': 'Wait the given number of seconds, then answer. Optionally report progress.',
     'inputSchema': {'type': 'object', 'properties': {
         'seconds': {'type': 'number', 'description': 'how long to wait'},
         'progress_every': {'type': 'number', 'description': 'send a progress notification every N seconds'}},
         'required': ['seconds']}},
    {'name': 'hang', 'description': 'Start a job that never finishes (simulates a server stuck in one operation).',
     'inputSchema': {'type': 'object', 'properties': {}}},
    {'name': 'slow_task', 'description': 'Run a job of several steps. With save_as_you_go each finished step is saved to disk.',
     'inputSchema': {'type': 'object', 'properties': {
         'steps': {'type': 'integer'}, 'seconds_per_step': {'type': 'number'},
         'save_as_you_go': {'type': 'boolean'}, 'hang_at_step': {'type': 'integer'}},
         'required': ['steps', 'seconds_per_step']}},
    {'name': 'save_step', 'description': 'Save a named checkpoint file.',
     'inputSchema': {'type': 'object', 'properties': {'name': {'type': 'string'}, 'note': {'type': 'string'}},
                     'required': ['name']}},
]

out_lock = threading.Lock()
OUT = '/out'


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='milliseconds')


def send(msg):
    with out_lock:
        sys.stdout.write(json.dumps(msg) + '\n'); sys.stdout.flush()


def event(kind, **kw):
    with out_lock:
        with open(os.path.join(OUT, 'server-events.jsonl'), 'a', encoding='utf8') as f:
            f.write(json.dumps({'t': now(), 'event': kind, **kw}) + '\n')


def text(s, error=False):
    r = {'content': [{'type': 'text', 'text': s}]}
    if error: r['isError'] = True
    return r


def save(name, note=''):
    d = os.path.join(OUT, 'steps'); os.makedirs(d, exist_ok=True)
    p = os.path.join(d, f'{name}.txt')
    with open(p, 'w', encoding='utf8') as f:
        f.write(f'{now()} {note}\n')
    return p


def progress(token, done, total, message):
    if token is not None:
        send({'jsonrpc': '2.0', 'method': 'notifications/progress',
              'params': {'progressToken': token, 'progress': done, 'total': total, 'message': message}})


def run_tool(name, args, token):
    if name == 'wait_seconds':
        secs, every = float(args.get('seconds', 0)), args.get('progress_every')
        start = time.monotonic()
        if every and token is not None:
            n = 0
            while time.monotonic() - start + float(every) < secs:
                time.sleep(float(every)); n += 1
                progress(token, round(time.monotonic() - start, 1), secs, f'still working: {n * float(every):g} s')
        time.sleep(max(0.0, secs - (time.monotonic() - start)))
        return text(f'waited {secs:g} s')
    if name == 'hang':
        threading.Event().wait()                       # forever
    if name == 'slow_task':
        steps, per = int(args['steps']), float(args['seconds_per_step'])
        for i in range(1, steps + 1):
            if args.get('hang_at_step') == i:
                threading.Event().wait()
            time.sleep(per)
            if args.get('save_as_you_go'):
                save(f'step-{i}', f'step {i} of {steps} done')
            progress(token, i, steps, f'step {i} of {steps}')
        return text(f'finished {steps} of {steps} steps' + (' (each saved)' if args.get('save_as_you_go') else ''))
    if name == 'save_step':
        return text(f'saved {save(args["name"], args.get("note", ""))}')
    return text(f'unknown tool: {name}', error=True)


def handle_call(rid, params):
    name, args = params.get('name'), params.get('arguments') or {}
    token = (params.get('_meta') or {}).get('progressToken')
    event('call_start', request_id=rid, tool=name, arguments=args, progress_token=token)
    try:
        result = run_tool(name, args, token)
    except Exception as e:                              # a tool error, not a protocol error
        result = text(f'{type(e).__name__}: {e}', error=True)
    event('call_end', request_id=rid, tool=name)
    send({'jsonrpc': '2.0', 'id': rid, 'result': result})


def main():
    global OUT
    ap = argparse.ArgumentParser(); ap.add_argument('--out', default='/out'); OUT = ap.parse_args().out
    os.makedirs(OUT, exist_ok=True)
    for line in sys.stdin:
        if not line.strip(): continue
        msg = json.loads(line)
        method, rid, params = msg.get('method'), msg.get('id'), msg.get('params') or {}
        if method == 'initialize':
            send({'jsonrpc': '2.0', 'id': rid, 'result': {
                'protocolVersion': params.get('protocolVersion', '2025-06-18'),
                'capabilities': {'tools': {}}, 'serverInfo': {'name': 'slow-lab', 'version': '0.1'}}})
        elif method == 'tools/list':
            send({'jsonrpc': '2.0', 'id': rid, 'result': {'tools': TOOLS}})
        elif method == 'tools/call':
            threading.Thread(target=handle_call, args=(rid, params), daemon=True).start()
        elif method == 'notifications/cancelled':
            event('cancelled', request_id=params.get('requestId'), reason=params.get('reason'))
        elif method == 'ping':
            send({'jsonrpc': '2.0', 'id': rid, 'result': {}})
        elif rid is not None:
            send({'jsonrpc': '2.0', 'id': rid, 'error': {'code': -32601, 'message': f'Method not found: {method}'}})
        # other notifications (initialized etc.) need no answer
    event('stdin_closed')


if __name__ == '__main__':
    main()
