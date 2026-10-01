/** Verification=false describes every ordinary building too; it is not candidacy. */
export function isRefugeRecord(properties: Record<string, unknown> | null | undefined): boolean {
  if (!properties) return false;
  return properties.refuge_verified === true || properties.refuge_verified === "true"
    || properties.refuge_status === "osm_tagged_candidate_unverified"
    || (typeof properties.refuge_id === "string" && properties.refuge_id.length > 0)
    || (typeof properties.refuge_name === "string" && properties.refuge_name.length > 0);
}
