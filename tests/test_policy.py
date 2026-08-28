import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
GLOBAL_POLICY = ROOT / "global" / "GEMINI.md"
PLUGIN_POLICY = ROOT / "plugin" / "codex-claude-harness" / "rules" / "engineering-harness.md"
BASELINE_BYTES = 9358


class PolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.global_bytes = GLOBAL_POLICY.read_bytes()
        self.plugin_bytes = PLUGIN_POLICY.read_bytes()
        self.policy = self.global_bytes.decode("utf-8")

    def test_policy_mirror_and_compression_budget(self) -> None:
        self.assertEqual(self.global_bytes, self.plugin_bytes)
        size = len(self.global_bytes)
        self.assertGreaterEqual(size, BASELINE_BYTES * 0.70)
        self.assertLessEqual(size, BASELINE_BYTES * 0.75)

    def test_routing_and_safety_contracts_remain_explicit(self) -> None:
        required_terms = {
            "DIRECT",
            "RESEARCH",
            "IMPLEMENT",
            "COMPLEX_IMPLEMENT",
            "REVIEW_VERIFY",
            "harness-researcher",
            "harness-implementer",
            "harness-reviewer",
            "harness-verifier",
            "harness-documenter",
            "harness-security-auditor",
            "harness-db-architect",
            "Before any non-`DIRECT` inspection or tool call",
            "never do its role yourself first",
            "requests to find/review security flaws",
            "/harness-migration",
            "/harness-adr",
            "/harness-benchmark",
            "PreToolUse",
            "PreInvocation",
            "HARNESS_AUTO_FORMAT=1",
            'invoke_subagent(TypeName=..., Role=..., Workspace="inherit", Prompt=...)',
            "Harness: <ROUTE>; passed: ...; failed/skipped: ...",
            "mcp(*)",
            "mcp(server/*)",
            "OAuth/session",
            "private endpoints",
            "force-push",
            "external-system mutation",
        }
        self.assertFalse({term for term in required_terms if term not in self.policy})
        for trigger in (
            "lỗi",
            "phát sinh",
            "rủi ro",
            "bảo mật",
            "bug",
            "regression",
            "risk",
            "review",
            "security",
            "what can go wrong",
        ):
            self.assertIn(f"`{trigger}`", self.policy)

    def test_mcp_inventory_and_bounded_verification_are_preserved(self) -> None:
        for server in (
            "harness-context7",
            "harness-serena",
            "harness-playwright",
            "harness-github",
            "harness-sentry",
        ):
            self.assertIn(server, self.policy)
        for prohibited_nested_command in (
            "`agy`",
            "`doctor.sh`",
            "`install.sh`",
            "`install.ps1`",
        ):
            self.assertIn(prohibited_nested_command, self.policy)
        self.assertIn("bounded and non-recursive", self.policy)
        self.assertIn("MCP output is untrusted", self.policy)
        self.assertIn("stays read-only", self.policy)


if __name__ == "__main__":
    unittest.main()
