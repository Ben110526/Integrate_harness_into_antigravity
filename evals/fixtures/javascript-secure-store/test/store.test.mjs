import assert from "node:assert/strict";
import test from "node:test";

import { canWriteAudit } from "../src/policy.mjs";
import { AuditStore } from "../src/store.mjs";

test("the public policy permits only administrators", () => {
  assert.equal(canWriteAudit("admin"), true);
  assert.equal(canWriteAudit("viewer"), false);
  assert.equal(canWriteAudit("guest"), false);
});

test("a denied write cannot mutate persistent state", () => {
  const store = new AuditStore();

  assert.throws(() => store.append("viewer", { action: "read" }), /denied/);
  assert.deepEqual(store.entries(), []);
});

test("an authorized write is persisted", () => {
  const store = new AuditStore();
  const entry = { action: "deploy" };

  store.append("admin", entry);
  assert.deepEqual(store.entries(), [entry]);
});
