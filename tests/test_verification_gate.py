#!/usr/bin/env python3
"""Behavior tests for the Antigravity verification Stop hook."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Optional
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
GATE = (
    REPOSITORY
    / "plugin"
    / "codex-claude-harness"
    / "scripts"
    / "verification_gate.py"
)
LAUNCHER = GATE.with_name("verification_gate.cmd")
HOOKS = GATE.parents[1] / "hooks.json"

GATE_SPEC = importlib.util.spec_from_file_location("verification_gate", GATE)
assert GATE_SPEC is not None and GATE_SPEC.loader is not None
GATE_MODULE = importlib.util.module_from_spec(GATE_SPEC)
GATE_SPEC.loader.exec_module(GATE_MODULE)


def _shell_quote(value: str) -> str:
    import shlex

    return shlex.quote(value)


class VerificationGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.workspace = self.base / "workspace"
        self.artifacts = self.base / "artifacts"
        self.workspace.mkdir()
        self.artifacts.mkdir()
        self.common = {
            "artifactDirectoryPath": str(self.artifacts),
            "conversationId": "test-conversation",
            "workspacePaths": [str(self.workspace)],
        }

    def launcher_fixture(self) -> Path:
        directory = self.base / "launcher"
        directory.mkdir()
        launcher = directory / LAUNCHER.name
        shutil.copy2(str(LAUNCHER), str(launcher))
        shutil.copy2(str(GATE), str(directory / GATE.name))
        marker = directory / ".python-runtime"
        marker.write_text(str(Path(sys.executable).resolve()) + "\n", encoding="utf-8")
        if os.name != "nt":
            launcher.chmod(0o700)
            marker.chmod(0o600)
        return launcher

    def call(self, mode: str, payload: dict) -> dict:
        result = subprocess.run(
            [sys.executable, str(GATE), mode],
            input=json.dumps({**self.common, **payload}),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        self.assertEqual(result.stderr, "")
        return json.loads(result.stdout)

    def post(self, step: int, name: str, args: dict, error: str = "") -> dict:
        return self.call(
            "post",
            {
                "stepIdx": step,
                "error": error,
                "toolCall": {"name": name, "args": args},
            },
        )

    def stop(self, execution: int = 0, **overrides) -> dict:
        payload = {
            "executionNum": execution,
            "terminationReason": "NO_TOOL_CALL",
            "fullyIdle": True,
            "error": "",
        }
        payload.update(overrides)
        return self.call("stop", payload)

    def write(
        self,
        step: int = 1,
        target: Optional[Path] = None,
        error: str = "",
        **args,
    ) -> dict:
        return self.post(
            step,
            "replace_file_content",
            {"TargetFile": str(target or self.workspace / "app.py"), **args},
            error=error,
        )

    def command(self, step: int, command: str, error: str = "", **args) -> dict:
        return self.post(
            step,
            "run_command",
            {"CommandLine": command, "Cwd": str(self.workspace), **args},
            error=error,
        )

    def test_no_write_allows_stop(self) -> None:
        self.assertEqual(self.stop(), {"decision": "allow"})

    def test_successful_workspace_write_forces_one_retry(self) -> None:
        self.assertEqual(self.write(), {})
        first = self.stop()
        self.assertEqual(first["decision"], "continue")
        self.assertIn("Workspace files changed", first["reason"])

        second = self.stop(execution=1)
        self.assertEqual(second["decision"], "allow")
        self.assertIn("avoid a loop", second["reason"])

    def test_artifact_and_outside_workspace_writes_are_ignored(self) -> None:
        self.post(
            1,
            "write_to_file",
            {"TargetFile": str(self.workspace / "report.md"), "IsArtifact": True},
        )
        self.write(step=2, target=Path(self.temporary.name) / "outside.py")
        self.assertEqual(self.stop(), {"decision": "allow"})

    def test_failed_write_conservatively_requires_verification(self) -> None:
        self.post(
            1,
            "write_to_file",
            {"TargetFile": str(self.workspace / "app.py")},
            error="permission denied",
        )
        self.assertEqual(self.stop()["decision"], "continue")

    def test_successful_verification_after_write_allows_stop(self) -> None:
        self.write(step=2)
        self.command(3, "python3 -m pytest -q")
        self.assertEqual(self.stop(), {"decision": "allow"})

    def test_python_unittest_module_is_evidence(self) -> None:
        self.write()
        self.command(2, "python -m unittest discover")
        self.assertEqual(self.stop(), {"decision": "allow"})

    def test_additional_test_runners_are_evidence(self) -> None:
        commands = (
            "python -m doctest README.md",
            "python -m twisted.trial package.tests",
            "pytest-bdd tests/features",
            "npx vitest run",
            "npx playwright test",
            "bun test",
            "deno test",
            "cargo llvm-cov",
            "cargo llvm-cov test --workspace",
        )
        state_path = self.artifacts / GATE_MODULE.STATE_FILE
        for command in commands:
            with self.subTest(command=command):
                state_path.unlink(missing_ok=True)
                self.write()
                self.command(2, command)
                self.assertEqual(self.stop(), {"decision": "allow"})

    def test_coverage_requires_a_verification_target(self) -> None:
        accepted = (
            "coverage run -m pytest -q",
            "python -m coverage run --branch -m unittest discover",
            "coverage run --source src tests/test_app.py",
            "coverage run --rcfile=test_config.py -m pytest",
        )
        state_path = self.artifacts / GATE_MODULE.STATE_FILE
        for command in accepted:
            with self.subTest(command=command):
                state_path.unlink(missing_ok=True)
                self.write()
                self.command(2, command)
                self.assertEqual(self.stop(), {"decision": "allow"})

        rejected = (
            "coverage report",
            "coverage run app.py",
            "coverage run app.py -m pytest",
            "coverage run --rcfile test_config.py app.py",
            "python -m coverage run -m application",
        )
        for command in rejected:
            with self.subTest(command=command):
                state_path.unlink(missing_ok=True)
                self.write()
                self.command(2, command)
                self.assertEqual(self.stop()["decision"], "continue")

    def test_test_runner_update_modes_are_mutations(self) -> None:
        commands = (
            "vitest -u",
            "playwright test --update-snapshots",
            "cargo llvm-cov clean",
            "cargo llvm-cov --manifest-path Cargo.toml clean",
        )
        state_path = self.artifacts / GATE_MODULE.STATE_FILE
        for command in commands:
            with self.subTest(command=command):
                state_path.unlink(missing_ok=True)
                self.write()
                self.command(2, command)
                self.assertEqual(self.stop()["decision"], "continue")

    def test_coverage_and_llvm_cov_failure_masking_are_not_evidence(self) -> None:
        commands = (
            "coverage run -m pytest --help",
            "cargo llvm-cov --ignore-run-fail",
            "cargo llvm-cov report",
            "cargo llvm-cov --manifest-path Cargo.toml report",
        )
        state_path = self.artifacts / GATE_MODULE.STATE_FILE
        for command in commands:
            with self.subTest(command=command):
                state_path.unlink(missing_ok=True)
                self.write()
                self.command(2, command)
                self.assertEqual(self.stop()["decision"], "continue")

    def test_failed_or_unrelated_command_is_not_evidence(self) -> None:
        self.write(step=2)
        self.command(3, "pytest -q", error="exit status 1")
        self.command(4, "git status --short")
        self.assertEqual(self.stop()["decision"], "continue")

    def test_verification_before_latest_write_does_not_count(self) -> None:
        self.command(1, "npm test")
        self.write(step=2)
        self.assertEqual(self.stop()["decision"], "continue")

    def test_failure_masking_command_is_not_evidence(self) -> None:
        self.write()
        self.command(2, "npm test || true")
        self.assertEqual(self.stop()["decision"], "continue")

    def test_embedded_check_names_are_not_evidence(self) -> None:
        self.write()
        self.command(2, "echo pytest")
        self.command(3, "echo 'npm test and eslint both passed'")
        self.assertEqual(self.stop()["decision"], "continue")

    def test_help_and_version_commands_are_not_evidence(self) -> None:
        self.write()
        self.command(2, "pytest --help")
        self.command(3, "npm test -- --version")
        self.assertEqual(self.stop()["decision"], "continue")

    def test_bare_playwright_is_not_evidence(self) -> None:
        self.write()
        self.command(2, "playwright")
        self.assertEqual(self.stop()["decision"], "continue")

    def test_shell_syntax_check_is_evidence(self) -> None:
        self.write()
        self.command(2, "bash -n install.sh")
        self.assertEqual(self.stop(), {"decision": "allow"})

    def test_clang_format_requires_real_dry_run_check(self) -> None:
        self.write()
        self.command(2, "clang-format file.cpp")
        self.assertEqual(self.stop()["decision"], "continue")

    def test_clang_format_dry_run_werror_is_evidence(self) -> None:
        self.write()
        self.command(2, "clang-format --dry-run --Werror file.cpp")
        self.assertEqual(self.stop(), {"decision": "allow"})

    def test_failed_in_place_clang_format_resets_evidence(self) -> None:
        self.write()
        self.command(2, "npm test")
        self.command(3, "clang-format -i file.cpp", error="parse failure")
        self.assertEqual(self.stop()["decision"], "continue")

    def test_mutation_after_verification_resets_evidence(self) -> None:
        self.write()
        self.command(2, "npm test")
        self.command(3, "eslint --fix src")
        self.assertEqual(self.stop()["decision"], "continue")

    def test_failed_formatter_or_codegen_still_resets_evidence(self) -> None:
        self.write()
        self.command(2, "npm test")
        self.command(3, "eslint --fix src", error="exit status 2")
        self.command(4, "npm run codegen", error="exit status 1")
        self.assertEqual(self.stop()["decision"], "continue")

    def test_failed_compound_chain_preserves_earlier_mutation(self) -> None:
        self.write()
        self.command(2, "npm test")
        self.command(
            3,
            "prettier --write src && npm test",
            error="test command failed",
        )
        self.assertEqual(self.stop()["decision"], "continue")

    def test_failed_wrapped_chain_preserves_earlier_mutation(self) -> None:
        self.write()
        self.command(2, "npm test")
        self.command(
            3,
            "bash -lc 'prettier --write src && npm test'",
            error="wrapped test command failed",
        )
        self.assertEqual(self.stop()["decision"], "continue")

    def test_failed_powershell_chain_preserves_earlier_mutation(self) -> None:
        self.write()
        self.command(2, "npm test")
        self.command(
            3,
            'pwsh -Command "prettier --write src && npm test"',
            error="wrapped test command failed",
        )
        self.assertEqual(self.stop()["decision"], "continue")

    def test_package_update_and_codegen_reset_evidence(self) -> None:
        self.write()
        self.command(2, "pytest -q")
        self.command(3, "npm install left-pad")
        self.command(4, "npm run codegen")
        self.assertEqual(self.stop()["decision"], "continue")

    def test_mutating_script_and_python_package_install_reset_evidence(self) -> None:
        self.write()
        self.command(2, "npm test")
        self.command(3, "bash scripts/generate.py")
        self.command(4, "pip install -e .")
        self.assertEqual(self.stop()["decision"], "continue")

    def test_update_snapshot_test_is_a_mutation_not_evidence(self) -> None:
        self.write()
        self.command(2, "npm test -- --updateSnapshot")
        self.assertEqual(self.stop()["decision"], "continue")

    def test_ordered_mutation_then_verification_allows_stop(self) -> None:
        self.write()
        self.command(2, "prettier --write src && npm test")
        self.assertEqual(self.stop(), {"decision": "allow"})

    def test_ordered_verification_then_mutation_requires_recheck(self) -> None:
        self.write()
        self.command(2, "npm test && prettier --write src")
        self.assertEqual(self.stop()["decision"], "continue")

    def test_verification_build_and_redirect_do_not_loop(self) -> None:
        self.write()
        self.command(2, "npm run build")
        self.command(3, "pytest -q > test-results.log")
        self.assertEqual(self.stop(), {"decision": "allow"})

    def test_non_verification_redirection_is_a_mutation(self) -> None:
        self.write()
        self.command(2, "npm test")
        self.command(3, "echo generated > src/generated.py")
        self.assertEqual(self.stop()["decision"], "continue")

    def test_quoted_redirection_text_is_not_a_mutation(self) -> None:
        self.write()
        self.command(2, "npm test")
        self.command(3, "echo 'pytest > test-results.log'")
        self.assertEqual(self.stop(), {"decision": "allow"})

    def test_powershell_content_command_is_a_mutation(self) -> None:
        self.write()
        self.command(2, "npm test")
        self.command(3, 'pwsh -Command "Set-Content src/generated.ps1 value"')
        self.assertEqual(self.stop()["decision"], "continue")

    def test_direct_powershell_cmdlet_is_a_mutation(self) -> None:
        self.write()
        self.command(2, "npm test")
        self.command(3, "Set-Content src/generated.ps1 value")
        self.assertEqual(self.stop()["decision"], "continue")

    @unittest.skipUnless(os.name == "nt", "Windows command parsing")
    def test_windows_unquoted_backslash_script_path_is_preserved(self) -> None:
        self.write()
        self.command(2, "npm test")
        self.command(3, r"pwsh -File C:\repo\format.ps1")
        self.assertEqual(self.stop()["decision"], "continue")

    def test_persistent_and_outside_commands_are_not_evidence(self) -> None:
        self.write()
        self.command(2, "npm test", RunPersistent=True)
        self.post(
            3,
            "run_command",
            {
                "CommandLine": "npm test",
                "Cwd": str(Path(self.temporary.name) / "outside"),
            },
        )
        self.assertEqual(self.stop()["decision"], "continue")

    def test_explicit_no_check_reason_allows_stop(self) -> None:
        self.write()
        self.command(
            2,
            "printf '%s\\n' 'HARNESS_NO_RUNNABLE_CHECK: repository has no test or build configuration'",
        )
        self.assertEqual(self.stop(), {"decision": "allow"})

    def test_redirected_no_check_waiver_is_a_mutation(self) -> None:
        self.write()
        self.command(2, "npm test")
        self.command(
            3,
            "printf '%s\\n' 'HARNESS_NO_RUNNABLE_CHECK: repository has no runnable checks' > src/generated.py",
        )
        self.assertEqual(self.stop()["decision"], "continue")

    def test_empty_no_check_reason_does_not_bypass_gate(self) -> None:
        self.write()
        self.command(2, "echo 'HARNESS_NO_RUNNABLE_CHECK: no tests'")
        self.assertEqual(self.stop()["decision"], "continue")

    def test_masked_no_check_reason_does_not_bypass_gate(self) -> None:
        self.write()
        self.command(
            2,
            "false || echo 'HARNESS_NO_RUNNABLE_CHECK: repository has no runnable checks'",
        )
        self.assertEqual(self.stop()["decision"], "continue")

    def test_new_write_resets_a_previous_retry_and_evidence(self) -> None:
        self.write(step=1)
        self.assertEqual(self.stop()["decision"], "continue")
        self.command(2, "git diff --check")
        self.write(step=3)
        self.assertEqual(self.stop(execution=2)["decision"], "continue")

    def test_out_of_order_post_delivery_preserves_newer_evidence(self) -> None:
        self.command(30, "pytest -q")
        self.write(step=20)
        self.assertEqual(self.stop(), {"decision": "allow"})

    def test_out_of_order_post_delivery_preserves_newer_mutation(self) -> None:
        self.write(step=30)
        self.command(20, "pytest -q")
        self.assertEqual(self.stop()["decision"], "continue")

    def test_concurrent_post_updates_merge_without_lost_writes(self) -> None:
        payloads = []
        for step in range(1, 25):
            if step % 2:
                tool_call = {
                    "name": "replace_file_content",
                    "args": {"TargetFile": str(self.workspace / f"app-{step}.py")},
                }
            else:
                tool_call = {
                    "name": "run_command",
                    "args": {
                        "CommandLine": "pytest -q",
                        "Cwd": str(self.workspace),
                    },
                }
            payloads.append(
                {
                    **self.common,
                    "stepIdx": step,
                    "error": "",
                    "toolCall": tool_call,
                }
            )

        def post(payload: dict) -> None:
            result = subprocess.run(
                [sys.executable, str(GATE), "post"],
                input=json.dumps(payload),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )
            self.assertEqual(json.loads(result.stdout), {})
            self.assertEqual(result.stderr, "")

        with ThreadPoolExecutor(max_workers=12) as executor:
            list(executor.map(post, reversed(payloads)))

        state = json.loads(
            (self.artifacts / GATE_MODULE.STATE_FILE).read_text(encoding="utf-8")
        )
        self.assertEqual(state["lastWriteStep"], 23)
        self.assertEqual(state["lastEvidenceStep"], 24)
        self.assertEqual(self.stop(), {"decision": "allow"})

    def test_stale_fallback_state_cleanup_is_bounded_and_selective(self) -> None:
        directory = Path(self.temporary.name) / "fallback"
        directory.mkdir()
        now = time.time()
        stale = directory / f"{GATE_MODULE.TEMP_STATE_PREFIX}{'a' * 24}.json"
        fresh = directory / f"{GATE_MODULE.TEMP_STATE_PREFIX}{'b' * 24}.json"
        unrelated = directory / "codex-claude-harness-not-a-state.json"
        for path in (stale, fresh, unrelated):
            path.write_text("{}", encoding="utf-8")
        os.utime(stale, (now - GATE_MODULE.TEMP_STATE_TTL_SECONDS - 1,) * 2)
        os.utime(fresh, (now,) * 2)
        os.utime(unrelated, (now - GATE_MODULE.TEMP_STATE_TTL_SECONDS - 1,) * 2)

        GATE_MODULE._cleanup_stale_temp_states(directory, now=now)

        self.assertFalse(stale.exists())
        self.assertTrue(fresh.exists())
        self.assertTrue(unrelated.exists())
        self.assertTrue(
            (directory / ".codex-claude-harness-verification.lock").exists()
        )

    def test_stale_cleanup_skips_a_locked_active_state(self) -> None:
        directory = Path(self.temporary.name) / "fallback-locked"
        directory.mkdir()
        now = time.time()
        state = directory / f"{GATE_MODULE.TEMP_STATE_PREFIX}{'c' * 24}.json"
        state.write_text("{}", encoding="utf-8")
        os.utime(state, (now - GATE_MODULE.TEMP_STATE_TTL_SECONDS - 1,) * 2)

        with GATE_MODULE._state_lock(state) as acquired:
            self.assertTrue(acquired)
            GATE_MODULE._cleanup_stale_temp_states(directory, now=now)
            self.assertTrue(state.exists())

    @unittest.skipIf(os.name == "nt", "symlink safety is exercised on POSIX")
    def test_state_lock_does_not_follow_artifact_lock_symlink(self) -> None:
        state = self.artifacts / GATE_MODULE.STATE_FILE
        lock = state.with_name(f"{state.name}.lock")
        victim = self.base / "victim"
        victim.write_text("unchanged", encoding="utf-8")
        lock.symlink_to(victim)

        self.assertEqual(self.write(), {})
        self.assertEqual(victim.read_text(encoding="utf-8"), "unchanged")
        self.assertTrue(lock.is_symlink())
        self.assertFalse(state.exists())

    @unittest.skipIf(os.name == "nt", "symlink safety is exercised on POSIX")
    def test_stale_cleanup_never_follows_state_symlink(self) -> None:
        directory = self.base / "fallback-symlink"
        directory.mkdir()
        victim = self.base / "stale-victim"
        victim.write_text("unchanged", encoding="utf-8")
        stale = directory / f"{GATE_MODULE.TEMP_STATE_PREFIX}{'d' * 24}.json"
        stale.symlink_to(victim)
        old = time.time() - GATE_MODULE.TEMP_STATE_TTL_SECONDS - 1
        os.utime(victim, (old, old))

        GATE_MODULE._cleanup_stale_temp_states(directory, now=time.time())

        self.assertTrue(stale.is_symlink())
        self.assertEqual(victim.read_text(encoding="utf-8"), "unchanged")

    @unittest.skipIf(os.name == "nt", "symlink safety is exercised on POSIX")
    def test_private_state_directory_rejects_symlink(self) -> None:
        temp_root = self.base / "private-root"
        temp_root.mkdir()
        victim = self.base / "private-victim"
        victim.mkdir()
        identity = str(os.getuid())
        directory = temp_root / (GATE_MODULE.TEMP_STATE_DIRECTORY_PREFIX + identity)
        directory.symlink_to(victim, target_is_directory=True)

        self.assertIsNone(GATE_MODULE._private_state_directory(temp_root))
        self.assertEqual(list(victim.iterdir()), [])

    def test_main_removes_stale_unknown_fallback_state(self) -> None:
        directory = Path(self.temporary.name) / "fallback-unknown"
        directory.mkdir()
        state_directory = GATE_MODULE._private_state_directory(directory)
        self.assertIsNotNone(state_directory)
        assert state_directory is not None
        digest = hashlib.sha256(b"unknown").hexdigest()[:24]
        state = state_directory / f"{GATE_MODULE.TEMP_STATE_PREFIX}{digest}.json"
        state.write_text('{"lastWriteStep": 99}', encoding="utf-8")
        stale_time = time.time() - GATE_MODULE.TEMP_STATE_TTL_SECONDS - 1
        os.utime(state, (stale_time, stale_time))
        payload = {
            "executionMode": "normal",
            "isAgentIdle": True,
            "workspacePaths": [str(self.workspace)],
        }

        result = subprocess.run(
            [sys.executable, str(GATE), "stop"],
            input=json.dumps(payload),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            env={**os.environ, "TMPDIR": str(directory)},
        )

        self.assertEqual(json.loads(result.stdout), {"decision": "allow"})
        self.assertEqual(result.stderr, "")
        self.assertFalse(state.exists())

    def test_state_lock_wait_is_bounded(self) -> None:
        state = self.artifacts / GATE_MODULE.STATE_FILE
        original_timeout = GATE_MODULE.STATE_LOCK_TIMEOUT_SECONDS
        GATE_MODULE.STATE_LOCK_TIMEOUT_SECONDS = 0.05
        self.addCleanup(
            setattr,
            GATE_MODULE,
            "STATE_LOCK_TIMEOUT_SECONDS",
            original_timeout,
        )

        with GATE_MODULE._state_lock(state) as acquired:
            self.assertTrue(acquired)
            started = time.monotonic()
            with GATE_MODULE._state_lock(state) as second_acquired:
                elapsed = time.monotonic() - started
                self.assertFalse(second_acquired)
                self.assertLess(elapsed, 0.5)

    def test_error_and_non_idle_stops_are_never_blocked(self) -> None:
        self.write()
        self.assertEqual(
            self.stop(terminationReason="ERROR", error="system failure"),
            {"decision": "allow"},
        )
        self.assertEqual(self.stop(fullyIdle=False), {"decision": "allow"})
        self.assertEqual(
            self.stop(terminationReason="MAX_STEPS_EXCEEDED"),
            {"decision": "allow"},
        )

    def test_missing_post_tool_call_fails_open(self) -> None:
        self.assertEqual(self.call("post", {"stepIdx": 1, "error": ""}), {})
        self.assertEqual(self.stop(), {"decision": "allow"})

    def test_hook_does_not_register_permission_bypassing_pretooluse(self) -> None:
        hooks = json.loads(HOOKS.read_text(encoding="utf-8"))
        verification_gate = hooks["verification-gate"]
        self.assertNotIn("PreToolUse", verification_gate)

    def test_malformed_input_fails_open(self) -> None:
        result = subprocess.run(
            [sys.executable, str(GATE), "stop"],
            input="not-json",
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        self.assertEqual(json.loads(result.stdout), {"decision": "allow"})
        self.assertEqual(result.stderr, "")

    @unittest.skipIf(os.name == "nt", "POSIX launcher branch")
    def test_posix_launcher_uses_pinned_runtime_not_poisoned_path(self) -> None:
        launcher = self.launcher_fixture()
        poison = self.base / "poison"
        poison.mkdir()
        poison_record = self.base / "poison-ran"
        for name in ("python3", "python"):
            executable = poison / name
            executable.write_text(
                "#!/bin/sh\nprintf poison > %s\nexit 91\n" % _shell_quote(str(poison_record)),
                encoding="utf-8",
            )
            executable.chmod(0o700)
        result = subprocess.run(
            ["/bin/sh", str(launcher), "stop"],
            input=json.dumps(
                {
                    **self.common,
                    "executionNum": 0,
                    "terminationReason": "NO_TOOL_CALL",
                    "fullyIdle": True,
                    "error": "",
                }
            ),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            env={**os.environ, "PATH": str(poison)},
        )
        self.assertEqual(json.loads(result.stdout), {"decision": "allow"})
        self.assertEqual(result.stderr, "")
        self.assertFalse(poison_record.exists())

    @unittest.skipUnless(os.name == "nt", "Windows launcher branch")
    def test_windows_launcher_uses_pinned_runtime_not_poisoned_path(self) -> None:
        launcher = self.launcher_fixture()
        poison = self.base / "poison"
        poison.mkdir()
        poison_record = self.base / "poison-ran"
        for name in ("python.cmd", "py.cmd"):
            (poison / name).write_text(
                "@echo off\r\necho poison>\"%s\"\r\nexit /b 91\r\n"
                % poison_record,
                encoding="utf-8",
            )
        command_processor = os.environ.get("COMSPEC", "cmd.exe")
        result = subprocess.run(
            [command_processor, "/d", "/c", str(launcher), "stop"],
            input=json.dumps(
                {
                    **self.common,
                    "executionNum": 0,
                    "terminationReason": "NO_TOOL_CALL",
                    "fullyIdle": True,
                    "error": "",
                }
            ),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            env={**os.environ, "PATH": str(poison)},
        )
        self.assertEqual(json.loads(result.stdout), {"decision": "allow"})
        self.assertEqual(result.stderr, "")
        self.assertFalse(poison_record.exists())


if __name__ == "__main__":
    unittest.main()
