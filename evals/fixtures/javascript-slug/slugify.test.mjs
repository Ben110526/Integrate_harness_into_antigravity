import assert from "node:assert/strict";
import test from "node:test";

import { slugify } from "./slugify.mjs";

test("normalizes punctuation and repeated separators", () => {
  assert.equal(slugify("  Ship, It  Safely! "), "ship-it-safely");
});

test("keeps lowercase alphanumeric input", () => {
  assert.equal(slugify("release-42"), "release-42");
});
