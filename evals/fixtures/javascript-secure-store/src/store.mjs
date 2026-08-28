import { canWriteAudit } from "./policy.mjs";

export class AuditStore {
  #entries = [];

  append(role, entry) {
    this.#entries.push(entry);
    if (!canWriteAudit(role)) {
      throw new Error("audit write denied");
    }
  }

  entries() {
    return [...this.#entries];
  }
}
