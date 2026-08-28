export function canWriteAudit(role) {
  return role !== "guest";
}
