export type SourceStatus = 'approved' | 'verify' | 'rejected'

export type DataSource = {
  agency: string
  dataset: string
  use: string
  format: string
  resolution: string
  licence: string
  status: SourceStatus
  url: string
  note?: string
}

export const dataSources: DataSource[] = [
  {
    agency: 'GISTDA',
    dataset: 'Flood extent · 1-day',
    use: 'Observed flood mask',
    format: 'JSON API',
    resolution: 'Event / daily',
    licence: 'Open Data Common',
    status: 'approved',
    url: 'https://opendata.gistda.or.th/th/dataset/disasters-03',
  },
  {
    agency: 'Copernicus',
    dataset: 'Sentinel-1 SAR',
    use: 'Independent water classification',
    format: 'STAC / COG',
    resolution: '10 m class',
    licence: 'Free, full and open',
    status: 'approved',
    url: 'https://documentation.dataspace.copernicus.eu/APIs/STAC.html',
  },
  {
    agency: 'Thai Meteorological Department',
    dataset: 'Weather services + APIs',
    use: 'Potential rainfall forcing',
    format: 'API / files',
    resolution: 'Service dependent',
    licence: 'Resource audit required',
    status: 'verify',
    url: 'https://www.tmd.go.th/service/tmdData',
    note: 'General TMD terms restrict reuse. Keep out until one specific rainfall resource passes the access and licence gate.',
  },
  {
    agency: 'OpenStreetMap contributors',
    dataset: 'Roads, paths + building tags',
    use: 'Routing graph + footprints',
    format: 'PBF / OSM',
    resolution: 'Feature',
    licence: 'ODbL 1.0',
    status: 'approved',
    url: 'https://www.openstreetmap.org/copyright',
  },
  {
    agency: 'Google Research',
    dataset: 'Open Buildings 2.5D',
    use: 'Building presence + height',
    format: 'Cloud GeoTIFF',
    resolution: '4 m effective',
    licence: 'CC BY 4.0 / ODbL 1.0',
    status: 'approved',
    url: 'https://sites.research.google/gr/open-buildings/temporal/',
    note: 'Validate Bangkok height accuracy against a local sample before operational use.',
  },
  {
    agency: 'WorldPop',
    dataset: 'Global2 population · R2025A',
    use: 'Exposure + synthetic-person seed',
    format: 'GeoTIFF',
    resolution: '100 m class',
    licence: 'CC BY 4.0',
    status: 'approved',
    url: 'https://hub.worldpop.org/project/categories?id=3',
    note: 'A resident grid is not a daytime activity population; activity distributions need separate Bangkok evidence.',
  },
  {
    agency: 'BMA',
    dataset: 'Flood risk + watch locations',
    use: 'Qualitative hotspot checks',
    format: 'CSV',
    resolution: 'Named road / district',
    licence: 'CC Attribution',
    status: 'approved',
    url: 'https://data.bangkok.go.th/dataset/risk-flood-bangkok-area/resource/b719945f-f10b-4b4c-afd2-2e8b43d21726',
  },
  {
    agency: 'BMA',
    dataset: '5-minute water level',
    use: 'Canal + river boundary condition',
    format: 'Data API',
    resolution: '5 minutes',
    licence: 'Not specified',
    status: 'verify',
    url: 'https://data.bangkok.go.th/',
    note: 'Publicly accessible is not enough: do not ingest until reuse permission is explicit.',
  },
  {
    agency: 'BMA',
    dataset: '50-district boundary KML',
    use: 'Potential reporting geography',
    format: 'KML',
    resolution: 'District polygon',
    licence: 'Not specified',
    status: 'verify',
    url: 'https://data.bangkok.go.th/dataset/50/resource/0f40f9b4-617b-46a9-8806-f590da610954',
    note: 'Use OSM administrative boundaries until explicit BMA reuse terms are available.',
  },
]

export const scenarios = {
  monsoon: { label: 'Monsoon burst', rain: 165, river: 1.2, tide: 'Rising' },
  compound: { label: 'Compound flood', rain: 220, river: 1.9, tide: 'High' },
  drainage: { label: 'Drainage stress', rain: 110, river: 0.8, tide: 'Normal' },
} as const
