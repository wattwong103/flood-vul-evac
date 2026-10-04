/** MapLibre expression for a nullable string property, without match branches. */
export function stringPropertyExpression(key: string): unknown[] {
  return ["to-string", ["coalesce", ["get", key], ""]];
}
