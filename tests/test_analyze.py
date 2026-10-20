"""Tests for analyze.py on a hand-made run folder (no AI): it must read the call time, the cancel time, the
error Claude Code returned, progress counts and the cost."""
import json, os, tempfile, unittest
import analyze

MCP = [
    {'t': '2026-10-19T10:00:00.000+00:00', 'dir': 'client->server', 'msg': {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}}},
    {'t': '2026-10-19T10:00:05.000+00:00', 'dir': 'client->server', 'msg': {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'hang', 'arguments': {}, '_meta': {'progressToken': 3}}}},
    {'t': '2026-10-19T10:00:10.000+00:00', 'dir': 'server->client', 'msg': {'jsonrpc': '2.0', 'method': 'notifications/progress', 'params': {'progressToken': 3, 'progress': 1}}},
    {'t': '2026-10-19T10:01:05.250+00:00', 'dir': 'client->server', 'msg': {'jsonrpc': '2.0', 'method': 'notifications/cancelled', 'params': {'requestId': 3, 'reason': 'timeout'}}},
]
STREAM = [
    {'type': 'system', 'subtype': 'init', 'model': 'claude-haiku-5-5', 'mcp_servers': [{'name': 'slow', 'status': 'connected'}]},
    {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'is_error': True, 'content': [{'type': 'text', 'text': 'MCP error -32001: Request timed out'}]}]}},
    {'type': 'result', 'subtype': 'success', 'total_cost_usd': 0.0123, 'num_turns': 2, 'result': 'It timed out.'},
]


class Analyze(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        with open(os.path.join(self.d, 'mcp.jsonl'), 'w') as f:
            f.writelines(json.dumps(x) + '\n' for x in MCP)
        with open(os.path.join(self.d, 'claude.stream.jsonl'), 'w') as f:
            f.writelines(json.dumps(x) + '\n' for x in STREAM)
        with open(os.path.join(self.d, 'timeline.jsonl'), 'w') as f:
            f.write('{"started": "2026-10-19T09:59:58.000Z"}\n{"exit": 0, "ended": "2026-10-19T10:01:10.000Z"}\n')
        self.s = analyze.summarize(self.d)

    def test_call_and_cancel_timing(self):
        c = self.s['calls'][0]
        self.assertEqual(c['tool'], 'hang')
        self.assertAlmostEqual(c['cancelled_after_s'], 60.25)
        self.assertIsNone(c['answered_after_s'])
        self.assertEqual(c['progress_notifications'], 1)

    def test_error_text_cost_model_exit(self):
        self.assertEqual(self.s['tool_errors'], ['MCP error -32001: Request timed out'])
        self.assertEqual(self.s['cost_usd'], 0.0123)
        self.assertEqual(self.s['model'], 'claude-haiku-5-5')
        self.assertEqual(self.s['exit'], 0)
        self.assertEqual(self.s['final_text'], 'It timed out.')

    def test_missing_result_means_killed(self):
        with open(os.path.join(self.d, 'claude.stream.jsonl'), 'w') as f:
            f.write(json.dumps(STREAM[0]) + '\n')
        s = analyze.summarize(self.d)
        self.assertIsNone(s['cost_usd'])
        self.assertIsNone(s['final_text'])


if __name__ == '__main__':
    unittest.main()
