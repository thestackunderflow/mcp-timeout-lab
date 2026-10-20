"""Tests for the slow MCP server (no AI, no network). A scripted client talks JSON-RPC over stdio, the same way
Claude Code does, and checks what the server does when a tool is slow, silent or hung.
Run (Docker): docker compose run --rm tests"""
import json, os, subprocess, sys, tempfile, threading, time, unittest, queue

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(HERE, '..', 'server', 'slow_server.py')


class Client:
    """Minimal MCP client: one reader thread puts every server line on a queue."""
    def __init__(self, out_dir):
        self.p = subprocess.Popen([sys.executable, SERVER, '--out', out_dir], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
        self.q, self.next_id = queue.Queue(), 0
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.p.stdout:
            self.q.put((time.monotonic(), json.loads(line)))

    def send(self, msg):
        self.p.stdin.write(json.dumps(msg) + '\n'); self.p.stdin.flush()

    def request(self, method, params=None, meta=None):
        self.next_id += 1
        params = dict(params or {})
        if meta: params['_meta'] = meta
        self.send({'jsonrpc': '2.0', 'id': self.next_id, 'method': method, 'params': params})
        return self.next_id

    def wait_for(self, rid, timeout):
        """Returns (response, [notifications seen before it]) or (None, notes) on timeout."""
        notes, end = [], time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                _, m = self.q.get(timeout=max(0.01, end - time.monotonic()))
            except queue.Empty:
                break
            if m.get('id') == rid:
                return m, notes
            notes.append(m)
        return None, notes

    def init(self):
        r, _ = self.wait_for(self.request('initialize', {'protocolVersion': '2025-06-18', 'capabilities': {},
                                                           'clientInfo': {'name': 'test', 'version': '0'}}), 5)
        self.send({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
        return r

    def call(self, name, args, token=None):
        return self.request('tools/call', {'name': name, 'arguments': args}, {'progressToken': token} if token else None)

    def close(self):
        self.p.kill(); self.p.wait()
        for f in (self.p.stdin, self.p.stdout, self.p.stderr):
            f.close()


class SlowServer(unittest.TestCase):
    def setUp(self):
        self.out = tempfile.mkdtemp()
        self.c = Client(self.out)
        self.addCleanup(self.c.close)
        self.init = self.c.init()

    def test_initialize_echoes_protocol_and_names_itself(self):
        self.assertEqual(self.init['result']['protocolVersion'], '2025-06-18')
        self.assertEqual(self.init['result']['serverInfo']['name'], 'slow-lab')

    def test_lists_the_four_tools(self):
        r, _ = self.c.wait_for(self.c.request('tools/list'), 5)
        self.assertEqual(sorted(t['name'] for t in r['result']['tools']), ['hang', 'save_step', 'slow_task', 'wait_seconds'])

    def test_wait_seconds_takes_that_long_and_says_so(self):
        t0 = time.monotonic()
        r, notes = self.c.wait_for(self.c.call('wait_seconds', {'seconds': 2}), 10)
        dt = time.monotonic() - t0
        self.assertGreaterEqual(dt, 2.0); self.assertLess(dt, 3.5)
        self.assertIn('waited 2', r['result']['content'][0]['text'])
        self.assertEqual(notes, [])                  # silent: no progress unless asked

    def test_progress_notifications_only_with_a_token(self):
        rid = self.c.call('wait_seconds', {'seconds': 3, 'progress_every': 1}, token='tok-1')
        r, notes = self.c.wait_for(rid, 10)
        prog = [n for n in notes if n.get('method') == 'notifications/progress']
        self.assertGreaterEqual(len(prog), 2)
        self.assertTrue(all(n['params']['progressToken'] == 'tok-1' for n in prog))
        rid = self.c.call('wait_seconds', {'seconds': 2, 'progress_every': 1})   # no token: nothing to report to
        r, notes = self.c.wait_for(rid, 10)
        self.assertEqual([n for n in notes if n.get('method') == 'notifications/progress'], [])

    def test_hang_never_answers(self):
        r, _ = self.c.wait_for(self.c.call('hang', {}), 4)
        self.assertIsNone(r)

    def test_server_still_answers_other_calls_while_one_hangs_and_logs_the_cancel(self):
        hid = self.c.call('hang', {})
        time.sleep(0.5)
        self.c.send({'jsonrpc': '2.0', 'method': 'notifications/cancelled', 'params': {'requestId': hid, 'reason': 'test'}})
        r, _ = self.c.wait_for(self.c.call('wait_seconds', {'seconds': 0}), 5)
        self.assertIn('waited 0', r['result']['content'][0]['text'])
        log = open(os.path.join(self.out, 'server-events.jsonl'), encoding='utf8').read()
        self.assertIn('"cancelled"', log)
        self.assertIn(f'"request_id": {hid}', log)

    def test_slow_task_saves_each_step_as_it_goes(self):
        r, _ = self.c.wait_for(self.c.call('slow_task', {'steps': 3, 'seconds_per_step': 0.5, 'save_as_you_go': True}), 10)
        self.assertIn('3 of 3 steps', r['result']['content'][0]['text'])
        self.assertEqual(sorted(os.listdir(os.path.join(self.out, 'steps'))), ['step-1.txt', 'step-2.txt', 'step-3.txt'])

    def test_slow_task_without_saving_leaves_nothing_if_it_hangs(self):
        # the lighthouse failure in miniature: work is done in memory, a later step hangs, nothing is on disk
        r, _ = self.c.wait_for(self.c.call('slow_task', {'steps': 3, 'seconds_per_step': 0.2, 'hang_at_step': 3}), 3)
        self.assertIsNone(r)
        self.assertFalse(os.path.exists(os.path.join(self.out, 'steps')))

    def test_save_step_writes_a_file(self):
        r, _ = self.c.wait_for(self.c.call('save_step', {'name': 'base', 'note': 'ok'}), 5)
        self.assertTrue(os.path.exists(os.path.join(self.out, 'steps', 'base.txt')))

    def test_unknown_tool_is_a_tool_error_not_a_crash(self):
        r, _ = self.c.wait_for(self.c.call('nope', {}), 5)
        self.assertTrue(r['result']['isError'])


if __name__ == '__main__':
    unittest.main()
