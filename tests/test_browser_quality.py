import json
import unittest
import urllib.error
import urllib.request

from evals.browser_quality import BrowserProbe, prompt_for, score_report


class BrowserQualityTests(unittest.TestCase):
    def report(self, token):
        return (f"Initial: Waiting for confirmation\nConfirmation: {token}\n"
                "Harness: REVIEW_VERIFY; passed: rendered interaction; failed/skipped: none")

    def test_requires_actual_browser_hits_as_well_as_exact_final_text(self):
        report = self.report("test-confirmation")
        self.assertFalse(score_report(report, "test-confirmation", [])['success'])
        hits = [{'path': '/', 'browser': True},
                {'path': '/confirmation', 'browser': True, 'js_bound': True}]
        self.assertTrue(score_report(report, "test-confirmation", hits)['success'])
        self.assertFalse(score_report(report, "different", hits)['success'])
        self.assertFalse(score_report(report, "test-confirmation",
            [{'path': '/', 'browser': False},
             {'path': '/confirmation', 'browser': False, 'js_bound': True}])['success'])

    def test_user_agent_spoof_without_js_proof_does_not_pass(self):
        report = self.report("test-confirmation")
        hits = [{'path': '/', 'browser': True},
                {'path': '/confirmation', 'browser': True, 'js_bound': False}]
        result = score_report(report, "test-confirmation", hits)
        self.assertFalse(result['confirmation_js_bound'])
        self.assertFalse(result['success'])
        hits = [{'path': '/', 'browser': True}, {'path': '/confirmation', 'browser': True}]
        self.assertFalse(score_report(report, "test-confirmation", hits)['success'])

    def test_missing_duplicate_fenced_and_wrong_route_status_fail(self):
        base = self.report("test-confirmation")
        hits = [{'path': '/', 'browser': True}, {'path': '/confirmation', 'browser': True}]
        for report in (base.split('Harness:')[0], base + '\n' + base,
                       base.replace('REVIEW_VERIFY', 'DIRECT'),
                       base.split('Harness:')[0] + '\n```\n' + base.splitlines()[-1] + '\n```'):
            with self.subTest(report=report):
                self.assertFalse(score_report(report, 'test-confirmation', hits)['harness_status_valid'])

    def test_empty_claim_fields_fail_and_private_token_is_not_retained(self):
        report = self.report('private-fixture-value')
        result = score_report(report, 'private-fixture-value', [])
        self.assertNotIn('private-fixture-value', json.dumps(result))
        self.assertFalse(score_report(report.replace('passed: rendered interaction', 'passed: '),
            'private-fixture-value', [])['harness_status_valid'])
        for invalid in (report.replace('passed: rendered interaction', 'passed:  '),
                        report.replace('failed/skipped: none', 'failed/skipped:  ')):
            self.assertFalse(score_report(invalid, 'private-fixture-value', [])['harness_status_valid'])
        self.assertFalse(result['worker_independence_verified'])

    def test_server_exposes_random_confirmation_only_to_js_bound_request(self):
        probe = BrowserProbe().start()
        self.addCleanup(probe.close)
        request = urllib.request.Request(probe.url, headers={'User-Agent': 'Chrome fixture'})
        with urllib.request.urlopen(request, timeout=3) as response:
            page = response.read().decode()
        self.assertNotIn(probe.token, page)
        self.assertIn('Confirm registration', page)
        with self.assertRaises(urllib.error.HTTPError) as denied:
            urllib.request.urlopen(probe.url + '/confirmation', timeout=3)
        self.assertEqual(denied.exception.code, 403)
        bound = urllib.request.Request(
            probe.url + '/confirmation',
            headers={'User-Agent': 'Chrome fixture', 'X-Confirm-Proof': probe.expected_proof})
        with urllib.request.urlopen(bound, timeout=3) as response:
            confirmation = json.load(response)
        self.assertEqual(confirmation['confirmation'], probe.token)
        self.assertEqual(probe.hits[0], {'path': '/', 'browser': True})
        self.assertEqual(probe.hits[-1],
                         {'path': '/confirmation', 'browser': True, 'js_bound': True})

    def test_prompt_has_no_tool_inventory_or_status_hint(self):
        prompt = prompt_for('http://127.0.0.1:12345')
        for hint in ('MCP', 'Playwright', 'Harness:', 'browser_navigate', '/mcp'):
            self.assertNotIn(hint, prompt)


if __name__ == '__main__':
    unittest.main()
