import { Building2, Layers3, Minus, Navigation, Plus, Users } from 'lucide-react'

type LayerState = { population: boolean; flood: boolean; buildings: boolean; routes: boolean }
type BangkokMapProps = {
  severity: number
  time: number
  isRunning: boolean
  populationPeriod: 'day' | 'evening' | 'night'
  populationFactor: number
  layers: LayerState
  onLayerChange: (layer: keyof LayerState) => void
}

const safeRoute = [
  [230, 535], [280, 482], [348, 454], [416, 400], [500, 365], [582, 310], [650, 258],
]

function pointOnRoute(progress: number) {
  const segmentProgress = progress * (safeRoute.length - 1)
  const index = Math.min(Math.floor(segmentProgress), safeRoute.length - 2)
  const local = segmentProgress - index
  const start = safeRoute[index]
  const end = safeRoute[index + 1]
  return { x: start[0] + (end[0] - start[0]) * local, y: start[1] + (end[1] - start[1]) * local }
}

const buildings = [
  { x: 308, y: 236, w: 24, h: 18, z: 30, risk: 0 }, { x: 342, y: 215, w: 30, h: 24, z: 48, risk: 0 },
  { x: 384, y: 242, w: 22, h: 17, z: 24, risk: 1 }, { x: 425, y: 205, w: 38, h: 25, z: 62, risk: 0 },
  { x: 474, y: 260, w: 27, h: 20, z: 42, risk: 0 }, { x: 527, y: 217, w: 32, h: 22, z: 54, risk: 0 },
  { x: 572, y: 252, w: 22, h: 18, z: 26, risk: 0 }, { x: 616, y: 219, w: 29, h: 22, z: 38, risk: 0 },
  { x: 337, y: 337, w: 27, h: 20, z: 35, risk: 1 }, { x: 385, y: 316, w: 34, h: 24, z: 55, risk: 1 },
  { x: 449, y: 345, w: 25, h: 18, z: 29, risk: 1 }, { x: 500, y: 312, w: 35, h: 24, z: 68, risk: 0 },
  { x: 558, y: 352, w: 28, h: 18, z: 41, risk: 0 }, { x: 607, y: 326, w: 34, h: 24, z: 49, risk: 0 },
  { x: 269, y: 413, w: 27, h: 19, z: 28, risk: 1 }, { x: 324, y: 430, w: 34, h: 23, z: 46, risk: 1 },
  { x: 405, y: 420, w: 29, h: 20, z: 36, risk: 1 }, { x: 474, y: 441, w: 39, h: 26, z: 58, risk: 1 },
  { x: 546, y: 418, w: 26, h: 19, z: 33, risk: 0 }, { x: 618, y: 432, w: 32, h: 23, z: 45, risk: 0 },
]

const minorRoads = [
  'M164 193 L722 517', 'M176 435 L652 144', 'M250 135 L690 462', 'M224 526 L711 249', 'M331 120 L251 570',
  'M471 112 L400 582', 'M606 126 L535 570', 'M718 178 L627 555', 'M193 287 L690 319', 'M213 382 L700 407',
]

const populationCells = [
  { x: 285, y: 184, v: .54 }, { x: 365, y: 176, v: .76 }, { x: 454, y: 184, v: .91 }, { x: 552, y: 177, v: .72 }, { x: 646, y: 188, v: .49 },
  { x: 254, y: 292, v: .68 }, { x: 349, y: 286, v: 1 }, { x: 448, y: 292, v: .84 }, { x: 551, y: 286, v: .94 }, { x: 654, y: 297, v: .62 },
  { x: 251, y: 399, v: .73 }, { x: 354, y: 398, v: .92 }, { x: 455, y: 397, v: .79 }, { x: 558, y: 395, v: .69 }, { x: 652, y: 405, v: .53 },
  { x: 285, y: 498, v: .46 }, { x: 385, y: 496, v: .67 }, { x: 492, y: 501, v: .58 }, { x: 592, y: 500, v: .44 },
]

function ExtrudedBuilding({ x, y, w, h, z, risk, severity }: (typeof buildings)[number] & { severity: number }) {
  const lift = Math.max(8, z * 0.52)
  const threatened = risk === 1 && severity > 0.48
  const fill = threatened ? '#ed694f' : z > 50 ? '#203c47' : '#506b70'
  return (
    <g className="building" aria-label={`${z} metre building`}>
      <polygon points={`${x},${y - lift} ${x + w},${y - lift} ${x + w + 8},${y - lift - 5} ${x + 8},${y - lift - 5}`} fill="#dce7e3" />
      <polygon points={`${x + w},${y - lift} ${x + w},${y + h - lift} ${x + w + 8},${y + h - lift - 5} ${x + w + 8},${y - lift - 5}`} fill="#17333c" opacity=".72" />
      <rect x={x} y={y - lift} width={w} height={h} fill={fill} />
      {threatened && <rect x={x} y={y + h - lift - 5} width={w} height={5} fill="#ffe5b1" opacity=".8" />}
    </g>
  )
}

export function BangkokMap({ severity, time, isRunning, populationPeriod, populationFactor, layers, onLayerChange }: BangkokMapProps) {
  const depth = Math.round(12 + severity * 88)
  const floodScale = 0.9 + severity * 0.18
  const currentStage = time < 18 ? 0 : time < 42 ? 1 : time < 68 ? 2 : time < 92 ? 3 : 4
  const stageLabels = ['People', 'Activities', 'Trips', 'Trajectories', 'Flood + evacuation']
  return (
    <div className="map-shell">
      <svg className="city-map" viewBox="0 0 860 650" role="img" aria-labelledby="map-title map-desc">
        <title id="map-title">Illustrative Bangkok flood and evacuation scenario</title>
        <desc id="map-desc">A stylised map showing synthetic time-of-day population, the Chao Phraya River, flood extent, building heights, roads and animated evacuation agents.</desc>
        <defs>
          <pattern id="grid" width="32" height="32" patternUnits="userSpaceOnUse"><path d="M32 0H0V32" fill="none" stroke="#98aaa7" strokeWidth=".65" opacity=".34" /></pattern>
          <filter id="shadow" x="-30%" y="-30%" width="160%" height="160%"><feDropShadow dx="0" dy="3" stdDeviation="4" floodColor="#163039" floodOpacity=".18" /></filter>
          <linearGradient id="flood-fill" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#99d8dc" stopOpacity=".8" /><stop offset="1" stopColor="#45aaba" stopOpacity=".9" /></linearGradient>
        </defs>
        <rect width="860" height="650" fill="#e8eeea" /><rect width="860" height="650" fill="url(#grid)" />
        <g className="districts" fill="none" stroke="#9aaba7" strokeWidth="1" strokeDasharray="3 5" opacity=".7">
          <path d="M102 154L318 88 403 192 286 310 94 280Z" /><path d="M403 192L600 86 791 179 710 323 503 296Z" />
          <path d="M94 280L286 310 314 512 129 578 52 425Z" /><path d="M286 310L503 296 710 323 768 528 559 598 314 512Z" />
        </g>
        {layers.population && <g className={`population-layer ${populationPeriod}`} aria-label={`${populationPeriod} synthetic population density`}>
          {populationCells.map((cell, index) => <g key={index}><circle cx={cell.x} cy={cell.y} r={20 + cell.v * 26 * populationFactor} fill="#eda651" opacity={.045 + cell.v * .09 * populationFactor} /><circle cx={cell.x} cy={cell.y} r={5 + cell.v * 10 * populationFactor} fill="#c85e43" opacity={.12 + cell.v * .13 * populationFactor} /></g>)}
        </g>}
        {minorRoads.map((road) => <g key={road}><path d={road} fill="none" stroke="#f6f3e9" strokeWidth="9" /><path d={road} fill="none" stroke="#788b88" strokeWidth="1.2" strokeDasharray="3 6" opacity=".7" /></g>)}
        <g className="major-roads" fill="none" strokeLinecap="round">
          <path d="M117 488 C275 415 371 367 502 250 C596 165 700 120 805 96" stroke="#fbf8ef" strokeWidth="16" /><path d="M117 488 C275 415 371 367 502 250 C596 165 700 120 805 96" stroke="#d3a14c" strokeWidth="2.6" />
          <path d="M148 168 C276 233 407 280 742 540" stroke="#fbf8ef" strokeWidth="15" /><path d="M148 168 C276 233 407 280 742 540" stroke="#d3a14c" strokeWidth="2.6" />
        </g>
        <path className="river-bank" d="M69 -20 C125 73 102 144 150 204 C204 273 186 339 147 398 C112 451 130 524 206 670" fill="none" stroke="#f4f0e5" strokeWidth="67" />
        <path d="M69 -20 C125 73 102 144 150 204 C204 273 186 339 147 398 C112 451 130 524 206 670" fill="none" stroke="#5aa9b7" strokeWidth="53" />
        <path d="M67 -20 C123 73 100 144 148 204 C202 273 184 339 145 398 C110 451 128 524 204 670" fill="none" stroke="#a7e2e2" strokeWidth="2" opacity=".8" />
        {layers.flood && <g style={{ transform: `scale(${floodScale})`, transformOrigin: '430px 355px' }} className="flood-layer">
          <path d="M184 337C252 273 326 290 373 320C428 355 451 330 517 347C582 363 622 420 588 471C554 522 487 493 426 511C352 533 302 495 236 486C181 478 151 407 184 337Z" fill="url(#flood-fill)" opacity={0.42 + severity * 0.35} />
          <path d="M266 353C315 326 349 342 389 368C429 393 466 367 511 384C548 398 565 429 540 454C508 486 454 459 410 473C352 490 311 461 275 446C233 429 230 374 266 353Z" fill="#3b9eae" opacity={0.26 + severity * 0.38} />
          <path d="M345 381C383 357 420 389 455 393C491 397 521 416 506 439C489 466 448 444 414 451C379 458 330 425 345 381Z" fill="#216f83" opacity={0.18 + severity * 0.34} />
        </g>}
        {layers.buildings && <g filter="url(#shadow)">{buildings.map((building, index) => <ExtrudedBuilding key={index} {...building} severity={severity} />)}</g>}
        {layers.routes && <g>
          <path d="M230 535 L280 482 L348 454 L416 400 L500 365 L582 310 L650 258" fill="none" stroke="#f8f2df" strokeWidth="12" strokeLinecap="round" opacity=".9" />
          <path d="M230 535 L280 482 L348 454 L416 400 L500 365 L582 310 L650 258" fill="none" stroke="#127465" strokeWidth="5" strokeLinecap="round" strokeDasharray="10 7" />
          <path d="M232 535 L311 475 L382 470 L446 432" fill="none" stroke="#a33d35" strokeWidth="5" strokeLinecap="round" strokeDasharray="7 7" />
          <line x1="435" y1="421" x2="458" y2="445" stroke="#a33d35" strokeWidth="6" /><line x1="458" y1="421" x2="435" y2="445" stroke="#a33d35" strokeWidth="6" />
          {Array.from({ length: 9 }).map((_, index) => { const point = pointOnRoute(((time / 180) * 1.18 + index * 0.085) % 1); return <circle key={index} cx={point.x} cy={point.y} r={index % 3 === 0 ? 5 : 4} fill={isRunning ? '#fff7dc' : '#e9c66a'} stroke="#0d5149" strokeWidth="2" /> })}
        </g>}
        <g transform="translate(646 233)" className="shelter-pin"><circle r="22" fill="#f8f2df" stroke="#163d3a" strokeWidth="2" /><path d="M-9 3L0-6 9 3V11H3V4H-3V11H-9Z" fill="#163d3a" /><circle r="30" fill="none" stroke="#163d3a" strokeWidth="1.5" opacity=".3" /></g>
        <g transform="translate(226 541)"><circle r="10" fill="#f0a94b" stroke="#fff7dc" strokeWidth="3" /></g>
        <g className="map-labels" fill="#294746"><text x="268" y="178">RATCHATHEWI</text><text x="551" y="162">HUAI KHWANG</text><text x="280" y="554">PATHUM WAN</text><text x="596" y="515">KLONG TOEI</text><text x="76" y="324" transform="rotate(78 76 324)" fill="#f1fbf8">CHAO PHRAYA</text></g>
        <g className="road-labels" fill="#87602f"><text x="485" y="238" transform="rotate(-40 485 238)">Phetchaburi Rd</text><text x="421" y="292" transform="rotate(30 421 292)">Rama IX Rd</text></g>
        <g transform="translate(670 552)" className="map-key"><rect width="166" height="76" rx="3" fill="#fbf8ef" stroke="#9aaba7" /><circle cx="18" cy="16" r="7" fill="#d87849" opacity=".55" /><text x="31" y="20">Synthetic presence</text><rect x="13" y="32" width="10" height="10" fill="#216f83" /><text x="31" y="41">Flood depth</text><path d="M13 59H61" stroke="#127465" strokeWidth="4" strokeDasharray="8 5" /><text x="70" y="63">Safe route</text></g>
      </svg>
      <div className="map-caption"><span>MODELLED DEPTH</span><strong>{depth} cm</strong><small>at selected road</small></div>
      <div className="layer-control" aria-label="Map layers">
        <button className={layers.population ? 'active' : ''} onClick={() => onLayerChange('population')} aria-pressed={layers.population}><Users size={15} />Population</button>
        <button className={layers.flood ? 'active' : ''} onClick={() => onLayerChange('flood')} aria-pressed={layers.flood}><span className="water-dot" />Flood</button>
        <button className={layers.buildings ? 'active' : ''} onClick={() => onLayerChange('buildings')} aria-pressed={layers.buildings}><Building2 size={15} />Height</button>
        <button className={layers.routes ? 'active' : ''} onClick={() => onLayerChange('routes')} aria-pressed={layers.routes}><Navigation size={15} />Routes</button>
      </div>
      <div className="pflow-stage-rail" aria-label="PFLOW simulation stages"><span>PFLOW / BKK</span>{stageLabels.map((label, index) => <div className={index < currentStage ? 'done' : index === currentStage ? 'current' : ''} key={label}><i>{index < currentStage ? '✓' : index + 1}</i><b>{label}</b></div>)}</div>
      <div className="map-tools" aria-hidden="true"><button tabIndex={-1}><Plus size={17} /></button><button tabIndex={-1}><Minus size={17} /></button><button tabIndex={-1}><Layers3 size={17} /></button></div>
    </div>
  )
}
