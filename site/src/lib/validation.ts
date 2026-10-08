/** Unwrap the API report and retain the pipeline's recorded check evidence. */
export function validationChecks(value: unknown): Array<Record<string, unknown>> {
  if (!value || typeof value !== "object") return [];
  const envelope = value as Record<string, unknown>;
  if (envelope.available === false) return [];
  const report = (envelope.validation ?? envelope) as Record<string, unknown>;
  if (!Array.isArray(report.checks)) return [];
  return report.checks.filter(check => check && typeof check === "object").map(check => ({
    ...check,
    name: check.name ?? check.check_id ?? check.check,
    result: check.result ?? check.observed,
    notes: check.notes ?? check.detail ?? check.description,
  }));
}
