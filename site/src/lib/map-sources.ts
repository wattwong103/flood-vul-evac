/** Avoid expensive worker re-parsing when only controls or layer metadata change. */
export function updateMapSources<T extends { features: unknown[] }>(
  map: { getSource: (id: string) => { setData: (data: T) => unknown } | undefined },
  collections: Record<string, T>, previous: Map<string, unknown>,
) {
  for (const [id, collection] of Object.entries(collections)) {
    if (previous.get(id) === collection.features) continue;
    const source = map.getSource(id);
    if (source) {
      source.setData(collection);
      previous.set(id, collection.features);
    }
  }
}
