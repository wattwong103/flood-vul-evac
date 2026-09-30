const STATIC_LAYER_NOTE =
  "flood source legend names observed, modelled and scenario separately · " +
  "building height is never presented as shelter · unverified refuge records " +
  "are marked, not hidden · observed-water cells are classified extent for one " +
  "year, never depth.";

export function layerFooterText(modelTime: string | null): string {
  if (modelTime === null) {
    return (
      "This view has no selected model time. Static assets and observations remain " +
      "visible without one. Observed-water cells are classified extent for one year, " +
      "never depth · unverified destination records are marked, not hidden."
    );
  }
  return `Selected model time for time-varying layers: ${modelTime} · static assets have no model time · ${STATIC_LAYER_NOTE}`;
}

export function availableModelTimes(
  meshTimes: number[] | null | undefined,
  floodTimes: number[] | null | undefined,
): number[] {
  const source = meshTimes && meshTimes.length > 0 ? meshTimes : (floodTimes ?? []);
  return [...new Set(source)]
    .filter((value) => Number.isFinite(value) && value >= 0)
    .sort((a, b) => a - b);
}

export function shouldLoadStaticFallback(
  primaryPhase: string,
  primaryFeatureCount: number,
): boolean {
  return primaryPhase === "ready" && primaryFeatureCount === 0;
}
