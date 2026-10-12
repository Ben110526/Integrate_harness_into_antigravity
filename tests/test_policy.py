import json
import pathlib
import re
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
BASELINE_BYTES = 9358
# Fixed allowance for cumulative v2 registration and independent scope/delivery reports.
COMPLETION_PROTOCOL_BUDGET_BYTES = 3600


class PolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.global_bytes = GLOBAL_POLICY.read_bytes()
        self.plugin_bytes = PLUGIN_POLICY.read_bytes()
        self.policy = self.global_bytes.decode("utf-8")

    def test_policy_mirror_and_compression_budget(self) -> None:
        self.assertEqual(self.global_bytes, self.plugin_bytes)
        size = len(self.global_bytes)
        self.assertGreaterEqual(size, BASELINE_BYTES * 0.70)
        self.assertLessEqual(size, BASELINE_BYTES * 0.82 + COMPLETION_PROTOCOL_BUDGET_BYTES)

    def test_completion_and_business_rule_contracts_are_always_on(self) -> None:
        for required in (
            "without omission or dilution", "harness-task-contract.json",
            "IsArtifact: true", "HARNESS_RESULT:", "evidenceSteps",
            "Unchanged rows stay immutable", "2/4 passed means partial",
            "Never invent business rules", "Assumptions are labeled",
            "cannot establish semantic request coverage",
        ):
            self.assertIn(required, self.policy)

    def test_cumulative_task_and_review_protocol_examples_are_consistent(self) -> None:
        inline_json = re.findall(r"`(\{[^`]+\})`", self.policy)
        examples = [json.loads(value) for value in inline_json]
        contract = next(value for value in examples if value.get("version") == 2)
        scope = next(value for value in examples if value.get("phase") == "scope")
        self.assertEqual(contract["revision"], 1)
        self.assertRegex(contract["taskId"], r"^[A-Za-z0-9_-]+$")
        self.assertEqual(scope["taskId"], contract["taskId"])
        self.assertEqual(scope["revision"], contract["revision"])
        ids = {row["id"] for row in contract["requirements"]}
        self.assertEqual(set(scope["coveredIds"]), ids)
        for row in contract["requirements"]:
            self.assertIs(type(row["sourceStep"]), int)
            self.assertIn(row["verification"], {"static", "behavioral"})
        result = json.loads(re.search(r"HARNESS_RESULT: (\{[^`]+\})`", self.policy)[1])
        self.assertEqual(result["taskId"], contract["taskId"])
        self.assertEqual(result["revision"], contract["revision"])
        self.assertEqual({row["id"] for row in result["requirements"]}, ids)
        for term in (
            "cumulative task intent", "status questions", "do not reset",
            "scopeChanges", "replacesTask", "Never reuse retired IDs",
            "before the first task write", "independent scope review before product edits",
            "harness-acceptance-review.json", 'phase:"delivery"',
            "reason explains evidence relevance", "worker independence",
            "Disclose inaccessible context",
        ):
            self.assertIn(term, self.policy)

    def test_review_roles_require_independent_scope_and_per_ac_delivery(self) -> None:
        reviewer = (AGENT_DIRECTORY / "harness-reviewer.md").read_text()
        verifier = (AGENT_DIRECTORY / "harness-verifier.md").read_text()
        implementer = (AGENT_DIRECTORY / "harness-implementer.md").read_text()
        for term in ("pre-write scope review", "coveredIds", "unmappedRequests"):
            self.assertIn(term, reviewer)
        for text in (reviewer, verifier):
            for term in ("cumulative user intent", "evidenceSteps", "nonempty reason", "rerun"):
                self.assertIn(term, text)
        self.assertIn("Begin product edits only after parent confirms independent scope review", implementer)

    def test_task_protocol_docs_have_matching_v2_examples(self) -> None:
        docs = (ROOT / "docs" / "task-completion.md").read_text()
        blocks = [json.loads(value) for value in re.findall(r"```json\n(.*?)\n```", docs, re.DOTALL)]
        contract = next(value for value in blocks if value.get("version") == 2)
        reports = [value for value in blocks if "phase" in value]
        self.assertEqual({value["phase"] for value in reports}, {"scope", "delivery"})
        ids = {row["id"] for row in contract["requirements"]}
        for report in reports:
            self.assertEqual(report["taskId"], contract["taskId"])
            self.assertEqual(report["revision"], contract["revision"])
            reported = report.get("coveredIds", [row["id"] for row in report.get("requirements", [])])
            self.assertEqual(set(reported), ids)
        delivery = next(report for report in reports if report["phase"] == "delivery")
        self.assertTrue(all(row["reason"].strip() for row in delivery["requirements"]))
        self.assertIn("Partial/blocked results may omit reviews for unfinished rows only", docs)
        self.assertIn("every passed row still requires current delivery relevance review", docs)
        self.assertIn("failed checks persist across turns of the active task", docs)
        self.assertNotIn("failed checks in the current user turn", docs)
        self.assertIn("cannot be downgraded", docs)

    def test_mcp_routing_is_adaptive_bounded_and_permission_preserving(self) -> None:
        directory = ROOT / "plugin" / "codex-claude-harness" / "skills" / "harness-mcp-profile"
        for path in (GLOBAL_POLICY, directory / "SKILL.md", directory / "references" / "profiles.md", ROOT / "docs" / "mcp-profiles.md"):
            text = path.read_text()
            for term in ("authorized", "dependent", "bounded independent read-only", "scope", "fallback"):
                self.assertIn(term, text, path)
            self.assertNotIn("Start with one server", text, path)
            self.assertNotIn("must start with one server", text, path)
            self.assertNotIn("exactly one narrow read-only query", text, path)
            self.assertIn("unverified", text, path)
        skill = (directory / "SKILL.md").read_text()
        self.assertIn("no fixed server/query quota", skill)
        self.assertIn("Do not parallelize dependent calls, writes, approvals or mutations", skill)
        self.assertIn("not a closed inventory", skill)
        self.assertIn("Do not install a runtime/server", skill)
        self.assertIn("not arbitrary MCP calls", skill)
        self.assertIn("relevance, freshness, reliability and cost", self.policy)
        self.assertNotIn("use MCP only when", self.policy)
        self.assertNotIn("do not call MCP", skill)
        self.assertIn("semantic MCP can be useful even when `rg` is also available", skill)
        self.assertIn("Passed rows need current delivery review even in partial", self.policy)
        self.assertIn("Keep failed checks across active-task turns", self.policy)

    def test_automatic_discovery_preserves_approval_and_leaf_workflow(self) -> None:
        skill = (ROOT / "plugin/codex-claude-harness/skills/harness-mcp-profile/SKILL.md").read_text()
        for term in ("native session inventory", "schemas", "private global", "no retries",
                     "permission changes", "In headless", "main-agent-only",
                     "one final focused check bundle", "new writes, failures"):
            self.assertIn(term, self.policy)
        for term in ("exact exposed identity", "normal Ask prompt", "denial ends",
                     "rendered-browser QA cannot be replaced", "Headless cannot obtain Ask"):
            self.assertIn(term, skill)
        for role in ("implementer", "reviewer", "verifier", "researcher"):
            self.assertIn("leaf assignment directly", (AGENT_DIRECTORY / ("harness-" + role + ".md")).read_text())

    def test_isolated_api_routing_preserves_contract_and_risk_boundaries(self) -> None:
        skill = (ROOT / "plugin/codex-claude-harness/skills/harness-implement/SKILL.md").read_text()
        for term in ("breaking/consumer-facing public-interface", "inspecting absence",
                     "integration consumers/complex risks", "inline exclusions stay unchanged"):
            self.assertIn(term, self.policy)
        for term in ("inspecting call sites/integrations", "compatibility", "external-state",
                     "auth/security", "dependency/platform", "concurrency", "migration",
                     "independent pre-write scope review", "independent per-AC delivery",
                     "fresh behavioral checks", "Do not lower risk merely because the diff is short"):
            self.assertIn(term, skill)

    def test_mcp_discovery_has_a_native_execution_completion_condition(self) -> None:
        skill = (ROOT / "plugin/codex-claude-harness/skills/harness-mcp-profile/SKILL.md").read_text()
        for term in ("Ready schema/args: invoke authorized native tool",
                     "no repo/tests connection proof except configuration diagnosis",
                     "No native invoker: blocked; no alternate client"):
            self.assertIn(term, self.policy)
        for term in ("Discovery is complete", "valid arguments", "authorized next action",
                     "actual result or Ask prompt establishes dispatch",
                     "unless configuration diagnosis is the task", "report blocked promptly",
                     "never create an alternate client", "Legitimate source inspection"):
            self.assertIn(term, skill)

    def test_main_owns_final_result_and_repairs_do_not_restart_valid_work(self) -> None:
        skill = (ROOT / "plugin/codex-claude-harness/skills/harness-implement/SKILL.md").read_text()
        self.assertIn("independent scope review before product edits", self.policy)
        self.assertNotIn("Invoke an independent reviewer before product edits", self.policy)
        self.assertIn("isolated APIs with no doc deliverable need none", self.policy)
        self.assertIn("does not waive requested documentation", skill)
        self.assertIn("actual consumers/operators", skill)
        for role in ("implementer", "reviewer", "verifier", "researcher"):
            text = (AGENT_DIRECTORY / ("harness-" + role + ".md")).read_text()
            self.assertIn("do not emit a `HARNESS_RESULT` envelope", text)
        self.assertIn("Only main emits", self.policy)
        self.assertIn("one final", self.policy)
        self.assertIn("replace the response", self.policy)
        self.assertIn("repair only invalid fields", skill)
        self.assertIn("retain valid scope/reviews/evidence", skill)
        self.assertIn("do not rerun checks solely", skill)

    def test_mcp_dispatch_uses_current_invoker_not_cached_server_alias(self) -> None:
        skill = (ROOT / "plugin/codex-claude-harness/skills/harness-mcp-profile/SKILL.md").read_text()
        for term in ("exposed native MCP invoker definition first", "only when that exact native function is exposed",
                     "cannot register an invoker", "unknown tool", "dispatch failure before Ask",
                     "without guessing tool aliases", "stop without scanning schemas"):
            self.assertIn(term, skill)
        self.assertNotIn("then invoke native `call_mcp_tool`", skill)

    def test_browser_locators_follow_exposed_schema_without_guessed_ref_engine(self) -> None:
        skill = (ROOT / "plugin/codex-claude-harness/skills/harness-mcp-profile/SKILL.md").read_text()
        for term in ("current exposed schema is authoritative", "CSS selector",
                     "snapshot ref is not automatically valid CSS", "documented locator field and syntax",
                     "ref field only when the schema explicitly supports it", "Do not invent a `ref=` selector engine"):
            self.assertIn(term, skill)

    def test_normal_verifier_reuse_requires_new_delivery_and_preserves_complex_review(self) -> None:
        verifier = (AGENT_DIRECTORY / "harness-verifier.md").read_text()
        skill = (ROOT / "plugin/codex-claude-harness/skills/harness-implement/SKILL.md").read_text()
        implement_route = next(line for line in self.policy.splitlines() if line.startswith("- `IMPLEMENT`:"))
        complex_route = next(line for line in self.policy.splitlines() if line.startswith("- `COMPLEX_IMPLEMENT`:"))
        self.assertIn("`harness-verifier` scope → main edits → fresh verifier delivery", implement_route)
        self.assertIn("delegate `harness-implementer` for useful splits or explicit requests", implement_route)
        self.assertIn("main implements directly", skill)
        self.assertIn("user explicitly requests delegation", skill)
        self.assertIn("independent parallel ownership or context isolation materially helps", skill)
        self.assertIn("main cannot assess its own delivery", skill)
        self.assertIn("After main or delegated implementation", skill)
        self.assertIn("scope must pass before writes", self.policy)
        self.assertIn("existing conversation", self.policy)
        self.assertIn("no scope proof reuse", self.policy)
        self.assertIn("parallel independent reviewer + verifier", complex_route)
        for term in ("Stay read-only and independent from the author (main or delegated implementer)", "phase: scope",
                     "passing scope review before implementation", "known existing conversation",
                     "`send_message`", "Do not search for other agents", "current revision",
                     "full active AC inventory, final diff and observed final check bundle",
                     "fresh `phase: delivery`", "scope summary is never delivery proof"):
            self.assertIn(term, verifier)
        for term in ("implementation waits for a passing scope report", "known existing verifier conversation",
                     "current revision, full active AC inventory, final diff and observed final check bundle",
                     "never reuse a scope summary as delivery proof", "inline exclusions are unchanged"):
            self.assertIn(term, skill)

    def test_mcp_execution_delegation_requires_worker_tools_without_losing_review(self) -> None:
        skill = (ROOT / "plugin/codex-claude-harness/skills/harness-mcp-profile/SKILL.md").read_text()
        for text in (self.policy, skill):
            for term in ("Main owns MCP discovery/execution", "worker inventory confirms required tools",
                         "delegated independent", "observed results", "worker returns blocked promptly"):
                self.assertIn(term, text)
        self.assertIn("never assume tool inheritance", self.policy)
        self.assertIn("including the native MCP invoker", skill)
        self.assertIn("under the same Ask permissions", skill)
        self.assertIn("denial ends that dependent action", skill)

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
            "Only inline skips ledger/scope/delivery",
            "report `mode: inline-fast-path` in the `Harness:` line",
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


if __name__ == "__main__":
    unittest.main()
