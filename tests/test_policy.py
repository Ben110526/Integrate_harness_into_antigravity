import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
GLOBAL_POLICY = ROOT / "global" / "GEMINI.md"
PLUGIN_POLICY = ROOT / "plugin" / "codex-claude-harness" / "rules" / "engineering-harness.md"
CLARIFY_SKILL = (
    ROOT
    / "plugin"
    / "codex-claude-harness"
    / "skills"
    / "harness-clarify"
    / "SKILL.md"
)
AGENT_DIRECTORY = ROOT / "plugin" / "codex-claude-harness" / "agents"
SKILL_DIRECTORY = AGENT_DIRECTORY.parent / "skills"
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
        self.assertLessEqual(size, BASELINE_BYTES * 0.82)

    def test_routing_and_safety_contracts_remain_explicit(self) -> None:
        required_terms = {
            "DIRECT",
            "LOCAL_LOOKUP",
            "RESEARCH",
            "IMPLEMENT",
            "COMPLEX_IMPLEMENT",
            "REVIEW_ONLY",
            "REVIEW_VERIFY",
            "harness-researcher",
            "harness-implementer",
            "harness-reviewer",
            "harness-verifier",
            "harness-documenter",
            "harness-security-auditor",
            "harness-db-architect",
            "Before a route branch that requires a subagent",
            "invoke it before doing that role yourself",
            "requests to find/review security flaws",
            "/harness-migration",
            "/harness-adr",
            "/harness-benchmark",
            "/harness-clarify",
            "ask_question",
            "[UNRESOLVED]",
            "PreToolUse",
            "PreInvocation",
            "HARNESS_AUTO_FORMAT=1",
            "stable `AC-*` IDs",
            'invoke_subagent(TypeName=..., Role=..., Workspace="inherit", Prompt=...)',
            "Harness: <ROUTE>; passed: ...; failed/skipped: ...",
            "mcp(*)",
            "mcp(server/*)",
            "OAuth/session",
            "private endpoints",
            "force-push",
            "external-system mutation",
            "[label](relative/path:line)",
            "explicit Markdown and `file://` links",
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

    def test_low_cost_routes_have_strict_escalation_boundaries(self) -> None:
        local_lookup_contract = {
            "one exact positive local path/symbol lookup",
            "at most two `view_file`/`grep_search` calls",
            "No shell, MCP, network, write",
            "absence conclusion",
            "cross-file diagnosis",
            "Zero/multiple/conflicting results",
            "third read MUST escalate",
        }
        self.assertFalse(
            {term for term in local_lookup_contract if term not in self.policy}
        )

        review_contract = {
            "theoretical/static review without executable behavioral claims",
            "concrete code bugs/risks",
            "runtime/reproduction/security behavior, or changed code",
            "independent `harness-reviewer` + `harness-verifier`",
            "Source plus possible errors is `REVIEW_VERIFY`",
            "Concrete/executable findings promote to `REVIEW_VERIFY` before reporting",
        }
        self.assertFalse({term for term in review_contract if term not in self.policy})

    def test_implement_inline_fast_path_is_tiny_deterministic_and_risk_bounded(
        self,
    ) -> None:
        eligibility_contract = {
            "`IMPLEMENT` inline fast path requires ALL",
            "one deterministic acceptance outcome in one existing regular workspace file",
            "one contiguous hunk of at most 10 changed lines",
            "reviews the exact diff",
            "runs one narrow check",
            "existing focused behavioral check for source",
            "The inline fast path is the only write-route exception",
            "report `Harness: IMPLEMENT; mode: inline-fast-path; passed: ...; failed/skipped: ...`",
        }
        self.assertFalse(
            {term for term in eligibility_contract if term not in self.policy}
        )

        exclusion_contract = {
            "create/delete/rename",
            "no multi-constraint task",
            "dirty overlap/external action",
            "public contract/config/install/CI/build/dependency",
            "auth/security/data/migration/concurrency/permissions/secrets/legal/operator-workflow",
            "Promote before another write on scope growth",
            "needed AC ledger",
            "missing/failed/inconclusive evidence",
            "Size never overrides risk.",
        }
        self.assertFalse(
            {term for term in exclusion_contract if term not in self.policy}
        )

    def test_final_write_creates_verification_debt_not_an_automatic_waiver(
        self,
    ) -> None:
        for term in (
            "After the final write, verification is debt",
            "run the narrowest relevant runnable check",
            "Waive only if none exists",
            "never call it a pass",
        ):
            self.assertIn(term, self.policy)

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
        self.assertIn("stay read-only", self.policy)

    def test_clarification_is_material_parent_owned_and_bounded(self) -> None:
        skill = CLARIFY_SKILL.read_text(encoding="utf-8")
        for required in (
            "ask_question",
            "[UNRESOLVED]",
            "main agent",
            "two or three",
            "(Recommended)",
            "write-in",
            "single-select",
            "multi-select",
            "headless",
            "cancel",
            "OAuth",
            "credential",
            "permission",
        ):
            self.assertIn(required, skill)

        for path in AGENT_DIRECTORY.glob("*.md"):
            text = path.read_text(encoding="utf-8")
            frontmatter = text.split("---", 2)[1]
            self.assertNotIn("ask_question", frontmatter, path)
            self.assertIn("[UNRESOLVED]", text, path)

    def test_multimilestone_skill_is_discoverable_without_expanding_global_budget(self) -> None:
        self.assertIn("For authorized multi-milestone work, load `/harness-run`", self.policy)
        expected = {
            "harness-adr", "harness-benchmark", "harness-clarify", "harness-debug",
            "harness-implement", "harness-mcp-profile", "harness-migration",
            "harness-plan", "harness-review", "harness-run", "harness-ship",
            "harness-test",
        }
        self.assertEqual({path.parent.name for path in SKILL_DIRECTORY.glob("*/SKILL.md")}, expected)
        for name in ("harness-plan", "harness-implement", "harness-ship"):
            self.assertIn("../harness-run/SKILL.md", (SKILL_DIRECTORY / name / "SKILL.md").read_text())

    def test_run_contract_preserves_routing_authority_and_bounded_dispatch(self) -> None:
        run = (SKILL_DIRECTORY / "harness-run" / "SKILL.md").read_text(encoding="utf-8")
        for term in (
            "plan-only request stays", "Keep tiny edits", "Never infer permission",
            "Keep exactly one coordinator", "required role", "independent checks",
            "self-contained handoff", "`send_message`", "worker ID is still valid",
            "Otherwise invoke", "one active milestone", "non-final",
            "tool call within the active", "user cancellation", "resource/runtime",
            "Never force continuation unconditionally", "all required ACs",
            "An unrelated passing suite", "not task completion",
        ):
            self.assertIn(term, run, term)

    def test_resume_contract_requires_provenance_and_does_not_invent_persistence(self) -> None:
        run = (SKILL_DIRECTORY / "harness-run" / "SKILL.md").read_text(encoding="utf-8")
        for term in (
            "brief revision", "superseded ACs", "requirement source",
            "canonical workspace", "content SHA-256", "missing/deleted markers",
            "uncommitted, new, and deleted", "before/after source fingerprint",
            "mark affected evidence stale", "Preserve user changes",
            "corrupt/incomplete", "not an authenticated runner receipt",
            "Do not create `.harness/tasks/**`", "ordinary workspace write",
            "`IsArtifact=True`", "durable resume is unverified",
            "cancellation, and no-progress limits", "version-1 MCP install profile",
        ):
            self.assertIn(term, run, term)

    def test_workflow_docs_distinguish_contracts_from_live_native_proof(self) -> None:
        guide = (ROOT / "docs" / "long-running-workflow.md").read_text(encoding="utf-8")
        for term in (
            "instruction-level workflow", "Gated native pilot", "explicit permission",
            "installed version or help output", "live-verification-2026-09-07.md",
            "observations do not establish the full pilot protocol",
            "at least three matched runs",
            "permission prompts separately", "Missing trace", "Fake CLI tests",
            "cancel", "plan-only", "source edit before resume",
        ):
            self.assertIn(term, guide, term)
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("docs/long-running-workflow.md", readme)
        self.assertIn("bash ./doctor.sh", readme)
        self.assertNotIn(".\\doctor.ps1", readme)


if __name__ == "__main__":
    unittest.main()
