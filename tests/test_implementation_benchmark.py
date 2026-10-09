import contextlib
import copy
import io
import json
import os
import stat
import pathlib
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from evals import implementation_benchmark as benchmark


class ImplementationBenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="harness-benchmark-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = pathlib.Path(self.temporary.name)
        self.fixture = self.root / "fixture"
        self.fixture.mkdir()
        (self.fixture / "calc.py").write_text("def one(): return 0\ndef two(): return 0\n", encoding="utf-8")
        (self.fixture / "test_calc.py").write_text(
            "import unittest\nfrom calc import one, two\n"
            "class Cases(unittest.TestCase):\n"
            " def test_one(self): self.assertEqual(one(), 1)\n"
            " def test_two(self): self.assertEqual(two(), 2)\n", encoding="utf-8")
        (self.fixture / "notes.md").write_text("baseline\n", encoding="utf-8")
        self.case = {
            "id": "bounded-implementation", "fixture": "fixture", "route": "COMPLEX_IMPLEMENT",
            "prompt": "Implement one and two; preserve notes.md.", "expect_change": True,
            "require_result": True, "requires": ["python3"],
            "required_changed_paths": ["calc.py"], "allowed_changed_paths": ["calc.py"],
            "preexisting_changes": {"notes.md": "User-owned edit.\n"},
            "verify": ["python3", "-m", "unittest", "-q"],
            "acceptance_criteria": [
                {"id": "AC-1", "description": "one returns 1", "verify": ["python3", "-m", "unittest", "-q", "test_calc.Cases.test_one"]},
                {"id": "AC-2", "description": "two returns 2", "verify": ["python3", "-m", "unittest", "-q", "test_calc.Cases.test_two"]},
            ],
        }
        self.manifest = self.root / "cases.json"
        self.manifest.write_text(json.dumps([self.case]), encoding="utf-8")
        self.addCleanup(mock.patch.stopall)
        self.home = self.root / "home"
        self.policy_target = self.home / ".gemini" / "GEMINI.md"
        self.policy_target.parent.mkdir(parents=True)
        self.write_policy(benchmark.ROOT)
        mock.patch.object(pathlib.Path, "home", return_value=self.home).start()
        mock.patch.object(benchmark, "CASES_PATH", self.manifest).start()
        mock.patch.object(benchmark.quota, "safe_fixture_path", return_value=self.fixture).start()
        mock.patch.object(benchmark.quota, "matching_installed_digest", return_value="b" * 64).start()
        original_which = shutil.which
        mock.patch.object(benchmark.shutil, "which", side_effect=lambda name: "/fake/agy" if name == "agy" else original_which(name)).start()
        self.original_run = subprocess.run
        self.calls = []
        self.behaviors = []
        self.versions = []
        self.version_observations = 0
        mock.patch.object(benchmark.subprocess, "run", side_effect=self.fake_cli).start()

    def write_policy(self, source):
        content = (source / "global" / "GEMINI.md").read_bytes().replace(b"\r\n", b"\n").rstrip(b"\n")
        self.policy_target.write_bytes(b"User notes before.\n" + benchmark.POLICY_START + b"\n" + content
                                       + b"\n" + benchmark.POLICY_END + b"\nUser notes after.\n")

    def response(self, complete=True):
        rows = [{"id": "AC-1", "status": "passed", "evidenceSteps": [1]}]
        rows.append({"id": "AC-2", "status": "passed", "evidenceSteps": [2]} if complete else
                    {"id": "AC-2", "status": "unverified", "evidenceSteps": [], "reason": "second behavior remains incomplete"})
        return "Harness: COMPLEX_IMPLEMENT; passed: observed; failed/skipped: none\nHARNESS_RESULT: " + json.dumps({
            "status": "complete" if complete else "partial", "requirements": rows,
        })

    def fake_cli(self, command, **kwargs):
        if command[0] != "agy":
            return self.original_run(command, **kwargs)
        if command[1:] == ["--version"]:
            self.version_observations += 1
            version = self.versions.pop(0) if self.versions else "1.2.7"
            return subprocess.CompletedProcess(command, 1 if version is None else 0,
                                               "Antigravity " + (version or "") + "\n", "PRIVATE version diagnostics")
        workspace = pathlib.Path(kwargs["cwd"])
        self.calls.append((str(workspace), (workspace / "calc.py").read_text(), (workspace / "notes.md").read_text(), list(command)))
        behavior = self.behaviors.pop(0) if self.behaviors else "complete"
        if behavior == "timeout":
            raise subprocess.TimeoutExpired(command, kwargs["timeout"], output="PRIVATE response and conversation-ID")
        source = "def one(): return 1\ndef two(): return " + ("2" if (behavior in {"complete", "protected", "usage_missing"} or behavior.startswith("chmod_")) else "0") + "\n"
        (workspace / "calc.py").write_text(source, encoding="utf-8")
        if behavior.startswith("chmod_"):
            relative = {"chmod_test": "test_calc.py", "chmod_notes": "notes.md", "chmod_directory": "documents", "chmod_root": ".", "chmod_source": "calc.py"}[behavior]
            path = workspace / relative
            bit = stat.S_IWGRP if behavior in {"chmod_directory", "chmod_root"} else stat.S_IXUSR
            path.chmod(stat.S_IMODE(path.stat().st_mode) ^ bit)
        if behavior == "protected":
            (workspace / "test_calc.py").write_text("# weakened tests\n", encoding="utf-8")
        payload = {
            "status": "SUCCESS", "response": self.response(behavior != "partial"),
            "duration_seconds": 0.25, "conversation_id": "PRIVATE conversation-ID",
            "usage": {field: 3 for field in benchmark.quota.USAGE_FIELDS},
        }
        if behavior == "usage_missing":
            del payload["usage"]
        output = json.dumps(payload)
        if command[command.index("--output-format") + 1] == "stream-json":
            output = json.dumps({"event": "result", "result": payload}) + "\n"
        return subprocess.CompletedProcess(command, 1 if behavior == "cli_failure" else 0, output, "PRIVATE diagnostics")

    def main(self, extra=None, confirm=True):
        arguments = ["--case", self.case["id"], "--repeat", "3", "--permission-profile", "normal-ask", "--mcp-profile", "default"]
        if confirm:
            arguments.append("--confirm-quota-use")
        arguments.extend(extra or [])
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            code = benchmark.main(arguments)
        raw = stream.getvalue()
        self.assertNotIn("PRIVATE", raw)
        self.assertNotIn("conversation_id", raw)
        return code, [json.loads(line) for line in raw.splitlines()]

    def test_without_explicit_opt_in_no_cli_or_model_calls(self):
        code, records = self.main(confirm=False)
        self.assertEqual(code, 2)
        self.assertEqual(records[0]["event"], "implementation_benchmark_refused")
        self.assertEqual(self.calls, [])
        benchmark.quota.matching_installed_digest.assert_not_called()

    def test_fresh_copy_repeats_independent_ac_and_matched_metadata(self):
        before = benchmark.snapshot(self.fixture)
        code, records = self.main()
        self.assertEqual(code, 0)
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(self.version_observations, 7)
        self.assertEqual(len({item[0] for item in self.calls}), 3)
        self.assertTrue(all(item[1] == "def one(): return 0\ndef two(): return 0\n" for item in self.calls))
        self.assertTrue(all(item[2] == "User-owned edit.\n" for item in self.calls))
        self.assertTrue(all("--sandbox" in item[3] and "--mode=accept-edits" in item[3] for item in self.calls))
        self.assertEqual(benchmark.snapshot(self.fixture), before)
        samples = [item for item in records if item["event"] == "implementation_benchmark_sample"]
        self.assertTrue(all(item["initial_prompt_complete"] for item in samples))
        self.assertTrue(all(item["comparison_valid"] and item["profile_error"] is None for item in samples))
        self.assertTrue(all(item["version_before"] == item["version_after"] == "1.2.7" for item in samples))
        self.assertTrue(all(item["model_call_started"] for item in samples))
        self.assertTrue(all(item["report_truthfulness"] is True for item in samples))
        self.assertTrue(all(item["suite"]["executed"] == 2 for item in samples))
        self.assertTrue(all([ac["executed"] for ac in item["acceptance"]] == [1, 1] for item in samples))
        self.assertEqual(len({item["comparison_key"] for item in samples}), 1)
        for field in ("fixture_digest", "manifest_digest", "runner_digest", "source_behavior_digest", "installed_behavior_digest", "source_global_policy_digest", "installed_global_policy_digest"):
            self.assertEqual(len(samples[0][field]), 64)
        summary = next(item for item in records if item["event"] == "implementation_benchmark_summary")
        self.assertEqual(summary["requested_samples"], 3)
        self.assertEqual(summary["complete_samples"], 3)
        self.assertEqual(summary["duration_all"]["count"], 3)
        self.assertEqual(summary["usage_observed_samples"], 3)
        self.assertEqual(summary["quota_calls_started"], 3)
        self.assertEqual(summary["profile_valid_samples"], 3)
        self.assertEqual(summary["profile_invalid_samples"], 0)
        self.assertTrue(summary["comparison_valid"])
        self.assertEqual(summary["benchmark_protocol"], 3)

    def test_timeout_and_cli_failure_stay_in_denominator_and_duration(self):
        self.behaviors = ["complete", "timeout", "cli_failure"]
        code, records = self.main()
        self.assertEqual(code, 1)
        samples = [item for item in records if item["event"] == "implementation_benchmark_sample"]
        self.assertEqual([item["failure_kind"] for item in samples], [None, "timeout", "cli_exit"])
        self.assertEqual(samples[1]["usage"], None)
        self.assertTrue(samples[1]["comparison_valid"])
        self.assertTrue(samples[1]["model_call_started"])
        self.assertTrue(all(ac["status"] == "failed" for ac in samples[1]["acceptance"]))
        summary = next(item for item in records if item["event"] == "implementation_benchmark_summary")
        self.assertEqual(summary["requested_samples"], 3)
        self.assertEqual(summary["failed_samples"], 2)
        self.assertEqual(summary["initial_prompt_completion_rate"], 1 / 3)
        self.assertEqual(summary["duration_all"]["count"], 3)
        self.assertEqual(summary["duration_success"]["count"], 1)
        self.assertEqual(summary["usage_observed_samples"], 2)
        for sample, duration in zip(samples, [1, 30, 60]):
            sample["duration_seconds"] = duration
        exact = benchmark.summarize(samples)
        self.assertEqual(exact["duration_all"], {"count": 3, "median_seconds": 30, "minimum_seconds": 1, "maximum_seconds": 60})
        self.assertEqual(exact["duration_success"]["median_seconds"], 1)

    def test_false_complete_and_honest_partial_are_separate_outcomes(self):
        self.behaviors = ["false_complete", "partial", "complete"]
        code, records = self.main()
        self.assertEqual(code, 1)
        samples = [item for item in records if item["event"] == "implementation_benchmark_sample"]
        self.assertTrue(samples[0]["false_complete"])
        self.assertFalse(samples[0]["report_truthfulness"])
        self.assertTrue(samples[1]["honest_partial"])
        self.assertTrue(samples[1]["report_truthfulness"])
        self.assertFalse(samples[1]["initial_prompt_complete"])
        summary = next(item for item in records if item["event"] == "implementation_benchmark_summary")
        self.assertEqual(summary["false_complete_samples"], 1)
        self.assertEqual(summary["honest_partial_samples"], 1)
        self.assertEqual(summary["ac_pass_counts"], {"AC-1": 3, "AC-2": 1})

    def test_protected_test_mutation_cannot_be_oracle_evidence(self):
        self.behaviors = ["protected"]
        sample = benchmark.run_sample(self.case, "model-high", "json", 10)
        self.assertFalse(sample["source_scope_valid"])
        self.assertEqual(sample["failure_kind"], "protected_scope")
        self.assertTrue(sample["false_complete"])
        self.assertEqual(sample["suite"], None)
        self.assertTrue(all(item["status"] == "unverified" for item in sample["acceptance"]))

    def test_case_and_ac_minimum_test_counts_are_enforced(self):
        suite_case = copy.deepcopy(self.case)
        suite_case["minimum_tests"] = 3
        sample = benchmark.run_sample(suite_case, "model-high", "json", 10)
        self.assertEqual(sample["suite"]["executed"], 2)
        self.assertEqual(sample["suite"]["status"], "unverified")
        self.assertTrue(all(item["status"] == "passed" for item in sample["acceptance"]))
        self.assertTrue(sample["false_complete"])
        self.assertFalse(sample["report_truthfulness"])
        self.assertFalse(sample["initial_prompt_complete"])
        ac_case = copy.deepcopy(self.case)
        ac_case["acceptance_criteria"][0]["minimum_tests"] = 2
        sample = benchmark.run_sample(ac_case, "model-high", "json", 10)
        self.assertEqual(sample["suite"]["status"], "passed")
        self.assertEqual(sample["acceptance"][0]["executed"], 1)
        self.assertEqual(sample["acceptance"][0]["status"], "unverified")
        self.assertTrue(sample["false_complete"])
        self.assertFalse(sample["initial_prompt_complete"])

    def test_complete_report_with_missing_required_source_change_is_not_truthful(self):
        (self.fixture / "extra.py").write_text("# required but not changed\n", encoding="utf-8")
        case = copy.deepcopy(self.case)
        case["required_changed_paths"].append("extra.py")
        case["allowed_changed_paths"].append("extra.py")
        sample = benchmark.run_sample(case, "model-high", "json", 10)
        self.assertTrue(sample["all_required_ac_verified"])
        self.assertEqual(sample["suite"]["status"], "passed")
        self.assertFalse(sample["source_scope_valid"])
        self.assertFalse(sample["task_fulfillment"])
        self.assertTrue(sample["false_complete"])
        self.assertFalse(sample["report_truthfulness"])

    def test_invalid_minimum_counts_refuse_without_model_calls(self):
        for value in (True, 0, -1, "2"):
            for location in ("case", "criterion"):
                case = copy.deepcopy(self.case)
                target = case if location == "case" else case["acceptance_criteria"][0]
                target["minimum_tests"] = value
                self.manifest.write_text(json.dumps([case]), encoding="utf-8")
                with self.subTest(value=value, location=location), self.assertRaises(benchmark.quota.BenchmarkError):
                    benchmark.selected_cases([case["id"]])
        self.assertEqual(self.calls, [])

    def test_stream_json_and_missing_usage_never_invent_usage(self):
        self.behaviors = ["usage_missing"]
        sample = benchmark.run_sample(self.case, "model-high", "stream-json", 10)
        self.assertTrue(sample["initial_prompt_complete"])
        self.assertIsNone(sample["usage"])
        summary = benchmark.summarize([sample])
        self.assertEqual(summary["usage_observed_samples"], 0)
        self.assertIsNone(summary["usage_totals_observed"])

    def test_bounds_and_stale_install_refuse_before_model_calls(self):
        for arguments in (["--repeat", "2"], ["--repeat", "11"], ["--timeout-seconds", "1801"]):
            with self.subTest(arguments=arguments):
                self.assertEqual(self.main(arguments)[0], 2)
        benchmark.quota.matching_installed_digest.side_effect = benchmark.quota.BenchmarkError("private detail")
        self.assertEqual(self.main()[0], 2)
        self.assertEqual(self.calls, [])

    def test_case_selection_rejects_shared_oracles_and_protected_source(self):
        for mutation in ("shared", "protected", "missing_report"):
            case = copy.deepcopy(self.case)
            if mutation == "shared":
                case["acceptance_criteria"][1]["verify"] = case["acceptance_criteria"][0]["verify"]
            elif mutation == "protected":
                case["allowed_changed_paths"].append("test_calc.py")
            else:
                case["require_result"] = False
            self.manifest.write_text(json.dumps([case]), encoding="utf-8")
            with self.subTest(mutation=mutation), self.assertRaises(benchmark.quota.BenchmarkError):
                benchmark.selected_cases([case["id"]])
        self.assertEqual(self.calls, [])

    def test_alternate_harness_source_is_matched_without_switching_evaluator(self):
        source = self.root / "baseline"
        plugin = source / "plugin" / "codex-claude-harness"
        rules = plugin / "rules"
        rules.mkdir(parents=True)
        (rules / "policy.md").write_text("baseline behavior\n", encoding="utf-8")
        (source / "global").mkdir()
        (source / "global" / "GEMINI.md").write_text("baseline global policy\n", encoding="utf-8")
        self.write_policy(source)
        hooks = self.root / "empty-hooks"
        hooks.mkdir()
        revision = benchmark.initialize_repository(source, hooks)
        home = self.root / "home"
        installed = home / ".gemini" / "config" / "plugins" / "codex-claude-harness"
        installed.parent.mkdir(parents=True)
        shutil.copytree(plugin, installed)
        with mock.patch.object(pathlib.Path, "home", return_value=home):
            code, records = self.main(["--harness-source", str(source), "--label", "baseline"])
        self.assertEqual(code, 0)
        sample = next(item for item in records if item["event"] == "implementation_benchmark_sample")
        self.assertEqual(sample["source_revision"], revision)
        self.assertEqual(sample["source_behavior_digest"], benchmark.quota.behavior_digest(plugin))
        self.assertEqual(sample["source_behavior_digest"], sample["installed_behavior_digest"])
        self.assertFalse(sample["source_worktree_dirty"])
        self.assertEqual(sample["manifest_digest"], __import__("hashlib").sha256(self.manifest.read_bytes()).hexdigest())
        self.calls.clear()
        (rules / "policy.md").write_text("changed but not installed\n", encoding="utf-8")
        with mock.patch.object(pathlib.Path, "home", return_value=home):
            self.assertEqual(self.main(["--harness-source", str(source)])[0], 2)
        self.assertEqual(self.calls, [])

    @unittest.skipIf(os.name == "nt", "POSIX permission modes")
    def test_chmod_of_protected_files_user_notes_and_directories_fails_integrity(self):
        (self.fixture / "documents").mkdir()
        (self.fixture / "documents" / "readme.md").write_text("protected documentation\n", encoding="utf-8")
        for behavior, changed in (("chmod_test", "test_calc.py"), ("chmod_notes", "notes.md"), ("chmod_directory", "documents"), ("chmod_root", ".")):
            self.behaviors = [behavior]
            case = copy.deepcopy(self.case)
            if behavior == "chmod_notes":
                case["allowed_changed_paths"].append("notes.md")
            sample = benchmark.run_sample(case, "model-high", "json", 10)
            with self.subTest(behavior=behavior):
                self.assertEqual(sample["source_scope_valid"], behavior == "chmod_notes")
                self.assertFalse(sample["task_fulfillment"])
                self.assertIn(changed, sample["changed_paths"])
                self.assertEqual(sample["failure_kind"], "protected_scope")
                self.assertTrue(sample["false_complete"])
                if behavior == "chmod_notes":
                    self.assertFalse(sample["preexisting_changes_preserved"])

    @unittest.skipIf(os.name == "nt", "POSIX permission modes")
    def test_allowed_source_mode_is_transferred_to_trusted_oracle(self):
        from evals import oracles
        original = oracles.verify_command
        observed = []
        def inspect(workspace, argv, minimum_tests=1):
            observed.append(stat.S_IMODE((workspace / "calc.py").stat().st_mode))
            return original(workspace, argv, minimum_tests)
        mode = stat.S_IMODE((self.fixture / "calc.py").stat().st_mode) ^ stat.S_IXUSR
        self.behaviors = ["chmod_source"]
        with mock.patch.object(oracles, "verify_command", side_effect=inspect):
            sample = benchmark.run_sample(self.case, "model-high", "json", 10)
        self.assertTrue(sample["initial_prompt_complete"])
        self.assertEqual(observed, [mode, mode, mode])
        before = benchmark.snapshot_digest(benchmark.snapshot(self.fixture))
        (self.fixture / "calc.py").chmod(mode)
        self.assertNotEqual(before, benchmark.snapshot_digest(benchmark.snapshot(self.fixture)))

    def test_missing_mismatched_or_ambiguous_global_policy_refuses_without_calls(self):
        matching = self.policy_target.read_bytes()
        values = (None, b"Only unmanaged user notes.\n", matching.replace(b"auto-harness:start", b"auto-harness:wrong"),
                  matching.replace(benchmark.POLICY_START + b"\n", benchmark.POLICY_START + b"\nchanged policy\n"),
                  matching + b"\n" + benchmark.POLICY_START)
        for value in values:
            if value is None:
                self.policy_target.unlink()
            else:
                self.policy_target.write_bytes(value)
            with self.subTest(value=value is None):
                self.assertEqual(self.main()[0], 2)
        self.assertEqual(self.calls, [])

    def test_missing_selected_source_global_policy_refuses_without_model_calls(self):
        source = self.root / "missing-policy-source"
        source.mkdir()
        self.assertEqual(self.main(["--harness-source", str(source)])[0], 2)
        self.assertEqual(self.calls, [])

    def test_global_policy_hash_ignores_unmanaged_user_bytes_and_accepts_crlf(self):
        first = benchmark.matching_global_policy_digest(benchmark.ROOT)
        payload = self.policy_target.read_bytes()
        self.policy_target.write_bytes(payload.replace(b"User notes before.", b"Private user configuration omitted.").replace(b"User notes after.", b"Different local user notes.").replace(b"\n", b"\r\n"))
        second = benchmark.matching_global_policy_digest(benchmark.ROOT)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)

    def test_cli_drift_before_each_call_refuses_all_samples_without_quota(self):
        self.versions = ["1.2.7", "1.3.2", "1.3.2", "1.3.2"]
        code, records = self.main()
        self.assertEqual(code, 1)
        self.assertEqual(self.calls, [])
        samples = [item for item in records if item["event"] == "implementation_benchmark_sample"]
        self.assertEqual(len(samples), 3)
        self.assertTrue(all(item["version_before"] == "1.3.2" and item["version_after"] is None for item in samples))
        self.assertTrue(all(not item["model_call_started"] and not item["comparison_valid"] for item in samples))
        self.assertTrue(all(item["profile_error"] == "cli_version_before_changed" for item in samples))
        self.assertTrue(all(item["comparison_key"] is None for item in samples))
        summary = next(item for item in records if item["event"] == "implementation_benchmark_summary")
        self.assertIsNone(summary["comparison_key"])
        self.assertEqual(summary["requested_samples"], 3)
        self.assertEqual(summary["quota_calls_started"], 0)
        self.assertEqual(summary["failed_samples"], 3)
        self.assertEqual(summary["profile_valid_samples"], 0)
        self.assertEqual(summary["profile_invalid_samples"], 3)
        self.assertEqual(summary["duration_all"]["count"], 3)

    def test_cli_drift_after_call_preserves_actual_outcome_but_invalidates_comparison(self):
        self.versions = ["1.2.7", "1.2.7", "1.3.2", "1.2.7", "1.2.7", "1.2.7", "1.2.7"]
        code, records = self.main()
        self.assertEqual(code, 1)
        self.assertEqual(len(self.calls), 3)
        samples = [item for item in records if item["event"] == "implementation_benchmark_sample"]
        first = samples[0]
        self.assertEqual(first["version_before"], "1.2.7")
        self.assertEqual(first["version_after"], "1.3.2")
        self.assertEqual(first["profile_error"], "cli_version_after_changed")
        self.assertTrue(first["model_call_started"])
        self.assertFalse(first["comparison_valid"])
        self.assertIsNone(first["comparison_key"])
        self.assertTrue(first["task_fulfillment"])
        self.assertTrue(first["initial_prompt_complete"])
        self.assertTrue(first["report_truthfulness"])
        self.assertFalse(first["false_complete"])
        self.assertEqual(first["status"], "SUCCESS")
        summary = next(item for item in records if item["event"] == "implementation_benchmark_summary")
        self.assertEqual(summary["requested_samples"], 3)
        self.assertEqual(summary["quota_calls_started"], 3)
        self.assertEqual(summary["complete_samples"], 3)
        self.assertEqual(summary["failed_samples"], 0)
        self.assertEqual(summary["profile_valid_samples"], 2)
        self.assertEqual(summary["profile_valid_complete_samples"], 2)
        self.assertEqual(summary["profile_invalid_samples"], 1)
        self.assertIsNone(summary["comparison_key"])
        self.assertFalse(records[-1]["comparison_valid"])

    def test_unavailable_cli_version_before_or_after_call_invalidates_only_profile(self):
        self.versions = [None]
        before = benchmark.run_sample(self.case, "model-high", "json", 10, expected_cli_version="1.2.7")
        self.assertEqual(self.calls, [])
        self.assertIsNone(before["version_before"])
        self.assertFalse(before["model_call_started"])
        self.assertFalse(before["comparison_valid"])
        self.assertEqual(before["profile_error"], "cli_version_before_unavailable")
        self.versions = ["1.2.7", None]
        after = benchmark.run_sample(self.case, "model-high", "json", 10, expected_cli_version="1.2.7")
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(after["model_call_started"])
        self.assertTrue(after["task_fulfillment"])
        self.assertTrue(after["report_truthfulness"])
        self.assertTrue(after["initial_prompt_complete"])
        self.assertFalse(after["comparison_valid"])
        self.assertEqual(after["profile_error"], "cli_version_after_unavailable")
        self.assertIsNone(after["version_after"])

    def test_fixture_and_manifest_changes_change_hashes(self):
        original = benchmark.snapshot_digest(benchmark.snapshot(self.fixture))
        (self.fixture / "calc.py").write_text("def one(): return -1\n", encoding="utf-8")
        self.assertNotEqual(original, benchmark.snapshot_digest(benchmark.snapshot(self.fixture)))
        self.assertNotEqual(benchmark.digest_json(self.case), benchmark.digest_json({**self.case, "prompt": "new brief"}))

    def test_comparison_key_matches_baseline_and_candidate_only_when_environment_matches(self):
        first = self.main(["--label", "baseline"])[1]
        second = self.main(["--label", "candidate"])[1]
        third = self.main(["--label", "candidate", "--permission-profile", "different"])[1]
        key = lambda records: next(item["comparison_key"] for item in records if item["event"] == "implementation_benchmark_summary")
        self.assertEqual(key(first), key(second))
        self.assertNotEqual(key(first), key(third))


if __name__ == "__main__":
    unittest.main()
