/**
 * Formatting helpers. A missing value is never rendered as `0`; it renders as
 * "not available", because a null in this contract means "the model did not
 * produce it", not "the model produced zero".
 */

export const NOT_AVAILABLE = "not available";

/**
 * A second, distinct absence. `null` in a run's stats means the model was asked
 * and did not produce the quantity, which is a different fact from the API not
 * publishing the field at all. Neither is ever rendered as `0`.
 */
export const NOT_COMPUTED = "not computed";

/** True when a measure is absent because the model did not compute it. */
export function isNotComputed(value: number | null | undefined): boolean {
  return isMissing(value) || !Number.isFinite(value);
}

export function isMissing(value: unknown): value is null | undefined {
  return value === null || value === undefined;
}

/** Whole-person counts. */
export function formatPeople(value: number | null | undefined): string {
  if (isMissing(value) || !Number.isFinite(value)) return NOT_AVAILABLE;
  return new Intl.NumberFormat("en-GB", { maximumFractionDigits: 0 }).format(value);
}

export function formatCompact(value: number | null | undefined): string {
  if (isMissing(value) || !Number.isFinite(value)) return NOT_AVAILABLE;
  return new Intl.NumberFormat("en-GB", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
}

/** A share expressed 0..1 in the payload, shown as a percentage. */
export function formatShare(
  value: number | null | undefined,
  digits = 1,
): string {
  if (isMissing(value) || !Number.isFinite(value)) return NOT_AVAILABLE;
  return `${(value * 100).toFixed(digits)}%`;
}

export function formatNumber(
  value: number | null | undefined,
  digits = 2,
): string {
  if (isMissing(value) || !Number.isFinite(value)) return NOT_AVAILABLE;
  return new Intl.NumberFormat("en-GB", {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits,
  }).format(value);
}

export function formatCount(value: number | null | undefined): string {
  if (isMissing(value) || !Number.isFinite(value)) return NOT_AVAILABLE;
  return new Intl.NumberFormat("en-GB").format(value);
}

export function formatText(value: string | null | undefined): string {
  if (isMissing(value)) return NOT_AVAILABLE;
  const trimmed = String(value).trim();
  return trimmed.length > 0 ? trimmed : NOT_AVAILABLE;
}

/** Absolute render of a possibly-negative delta such as `+1.20 m`. */
export function formatSigned(
  value: number | null | undefined,
  digits = 2,
  unit = "",
): string {
  if (isMissing(value) || !Number.isFinite(value)) return NOT_AVAILABLE;
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(digits)}${unit ? ` ${unit}` : ""}`;
}

/** Seconds since midnight as `HH:MM`. */
export function formatModelClock(seconds: number | null | undefined): string {
  if (isMissing(seconds) || !Number.isFinite(seconds)) return NOT_AVAILABLE;
  const total = Math.max(0, Math.round(seconds));
  const hours = Math.floor(total / 3600) % 24;
  const minutes = Math.floor((total % 3600) / 60);
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`;
}

export function formatTimestamp(value: string | null | undefined): string {
  if (isMissing(value)) return NOT_AVAILABLE;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value);
  return parsed.toISOString().replace("T", " ").replace(/\.\d+Z$/, "Z");
}

export function formatDuration(seconds: number | null | undefined): string {
  if (isMissing(seconds) || !Number.isFinite(seconds)) return NOT_AVAILABLE;
  if (seconds < 60) return `${seconds.toFixed(1)} s`;
  const minutes = Math.floor(seconds / 60);
  const rest = Math.round(seconds % 60);
  return `${minutes} min ${String(rest).padStart(2, "0")} s`;
}

/** Read a nested property without assuming the field exists. */
export function prop<T>(value: unknown, key: string): T | null {
  if (!value || typeof value !== "object") return null;
  const found = (value as Record<string, unknown>)[key];
  return found === undefined ? null : (found as T);
}

export function propString(value: unknown, key: string): string | null {
  const found = prop<unknown>(value, key);
  if (typeof found === "string") return found;
  if (typeof found === "number" && Number.isFinite(found)) return String(found);
  return null;
}

export function propNumber(value: unknown, key: string): number | null {
  const found = prop<unknown>(value, key);
  if (typeof found === "number" && Number.isFinite(found)) return found;
  if (typeof found === "boolean") return found ? 1 : 0;
  return null;
}

export function propBoolean(value: unknown, key: string): boolean | null {
  const found = prop<unknown>(value, key);
  if (typeof found === "boolean") return found;
  if (found === "true") return true;
  if (found === "false") return false;
  return null;
}

/** Case-insensitive, whitespace-tolerant status read. */
export function normaliseStatus(value: string | null | undefined): string {
  return (value ?? "").trim().toLowerCase();
}
