"""What real Claude Code did in each recorded run (tests/out/E*/), asserted from the saved logs, so the video's claims
are checkable. Recorded 19 Oct 2026 with Claude Code 2.1.303 (claude -p, stream-json, cheapest model).
A missing run folder is skipped, never faked."""
import os, unittest
import analyze

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'out')
HARD = 'MCP server "slow" tool "{}" timed out after 60s'
IDLE = 'MCP server "slow" tool "{}" sent no response or progress for 60s; aborting.'


def run(name):
    d = os.path.join(OUT, name)
    if not os.path.isdir(d):
        raise unittest.SkipTest(f'{name} not recorded')
    return analyze.summarize(d)


def stream(name):
    return open(os.path.join(OUT, name, 'claude.stream.jsonl'), encoding='utf8').read()


class Version(unittest.TestCase):
    def test_every_run_used_the_same_claude_code(self):
        for n in sorted(os.listdir(OUT)) if os.path.isdir(OUT) else []:
            if n.startswith('E'):
                self.assertIn('2.1.303', open(os.path.join(OUT, n, 'claude-version.txt')).read(), n)


class HardLimit(unittest.TestCase):
    """MCP_TOOL_TIMEOUT=60000 (E2) or a per-server "timeout": 60000 (E3): the same error, and the server is told."""
    def check(self, name, tool):
        s = run(name)
        self.assertEqual(s['tool_errors'], [HARD.format(tool)])
        c = s['calls'][0]
        self.assertIsNone(c['answered_after_s'])
        self.assertTrue(59.5 <= c['cancelled_after_s'] <= 61.5, c['cancelled_after_s'])
        self.assertEqual(c['cancel_reason'], 'SdkError: Request timed out')
        return c

    def test_env_variable(self):
        self.check('E2-tool-timeout-env', 'hang')

    def test_per_server_timeout(self):
        self.check('E3-server-timeout', 'hang')

    def test_progress_does_not_extend_the_hard_limit(self):
        c = self.check('E7-hard-limit-with-progress', 'wait_seconds')
        self.assertGreaterEqual(c['progress_notifications'], 5)


class SilenceLimit(unittest.TestCase):
    """CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT=60000: silence aborts the call, progress keeps it alive."""
    def test_silent_hang_aborts_with_the_idle_message_and_no_cancel_is_sent(self):
        s = run('E4-idle-timeout')
        self.assertEqual(len(s['tool_errors']), 1)
        self.assertTrue(s['tool_errors'][0].startswith(IDLE.format('hang')))
        self.assertIsNone(s['calls'][0]['cancelled_after_s'])       # no notifications/cancelled in the log

    def test_silent_slow_call_is_aborted_too(self):
        s = run('E6-idle-silent')
        self.assertTrue(s['tool_errors'][0].startswith(IDLE.format('wait_seconds')))
        self.assertIsNone(s['calls'][0]['answered_after_s'])

    def test_the_same_call_with_progress_finishes(self):
        s = run('E5-idle-with-progress')
        c = s['calls'][0]
        self.assertEqual(s['tool_errors'], [])
        self.assertTrue(149 <= c['answered_after_s'] <= 152)
        self.assertGreaterEqual(c['progress_notifications'], 10)


class Defaults(unittest.TestCase):
    def test_150_s_call_stays_in_the_foreground_in_headless_mode(self):
        s = run('E1-background')
        self.assertEqual(s['tool_errors'], [])
        self.assertTrue(149 <= s['calls'][0]['answered_after_s'] <= 152)
        text = stream('E1-background')
        self.assertNotIn('task_notification', text)
        self.assertEqual(text.count('"heartbeat":true'), 5)          # every 30 s: 30, 60, 90, 120, 150

    def test_hang_with_defaults_is_not_stopped_by_claude_code_in_6_minutes(self):
        s = run('E8-defaults-hang')
        self.assertEqual(s['exit'], 124)                             # our own `timeout 360` killed it
        self.assertEqual(s['tool_errors'], ['Connection closed'])   # the kill, not a Claude Code limit
        self.assertIsNone(s['calls'][0]['cancelled_after_s'])
        self.assertIsNone(s['cost_usd'])                             # killed: no result line


if __name__ == '__main__':
    unittest.main()
