import { useEffect, useMemo, useState } from 'react'
import {
  Activity, ArrowRight, BookOpen, Check, ChevronRight, CircleAlert, Clock3, Database, ExternalLink,
  Gauge, Map, Menu, Pause, Play, RotateCcw, Route, ShieldCheck, Users, Waves, X,
} from 'lucide-react'
import { BangkokMap } from './components/BangkokMap'
import { dataSources, scenarios, type SourceStatus } from './data'
import './App.css'

type View = 'scenario' | 'population' | 'data' | 'method'
type Layer = 'population' | 'flood' | 'buildings' | 'routes'
type PopulationPeriod = 'day' | 'evening' | 'night'
const populationPeriods: Record<PopulationPeriod, { label: string; time: string; factor: number; note: string }> = {
  day: { label: 'Day', time: '12:00', factor: 1.42, note: 'work + school attraction' },
  evening: { label: 'Evening', time: '18:00', factor: 1, note: 'commute + return trips' },
  night: { label: 'Night', time: '02:00', factor: 0.78, note: 'resident-weighted presence' },
}
const statusCopy: Record<SourceStatus, { label: string; description: string }> = {
  approved: { label: 'Approved', description: 'Accessible and explicitly reusable' },
  verify: { label: 'Verify', description: 'Public, but the licence needs confirmation' },
  rejected: { label: 'Rejected', description: 'Restricted, scraped or proprietary' },
}
const formatPeople = (value: number) => new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 }).format(value)

function ScenarioPanel({ rainfall, river, tide, populationPeriod, onRainfall, onRiver, onTide, onPopulationPeriod, onPreset, isRunning, onRun, onReset }: {
  rainfall: number; river: number; tide: string
  populationPeriod: PopulationPeriod
  onRainfall: (value: number) => void; onRiver: (value: number) => void; onTide: (value: string) => void; onPopulationPeriod: (value: PopulationPeriod) => void
  onPreset: (name: keyof typeof scenarios) => void; isRunning: boolean; onRun: () => void; onReset: () => void
}) {
  return (
    <aside className="scenario-panel">
      <div className="eyebrow"><span>01</span> Scenario inputs</div>
      <h1>Where does<br /> Bangkok move?</h1>
      <p className="lead">Test how rainfall, river level and high tide reshape safe routes through the city.</p>
      <div className="preset-row" aria-label="Scenario presets">
        {(Object.keys(scenarios) as Array<keyof typeof scenarios>).map((key) => <button key={key} onClick={() => onPreset(key)}>{scenarios[key].label}</button>)}
      </div>
      <div className="control-group">
        <div className="control-heading"><label htmlFor="rainfall">3-hour rainfall</label><output>{rainfall} <small>mm</small></output></div>
        <input id="rainfall" type="range" min="50" max="260" step="5" value={rainfall} onChange={(event) => onRainfall(Number(event.target.value))} />
        <div className="range-labels"><span>50</span><span>260</span></div>
      </div>
      <div className="control-group">
        <div className="control-heading"><label htmlFor="river">River stage anomaly</label><output>+{river.toFixed(1)} <small>m</small></output></div>
        <input id="river" type="range" min="0" max="2.2" step="0.1" value={river} onChange={(event) => onRiver(Number(event.target.value))} />
        <div className="range-labels"><span>normal</span><span>extreme</span></div>
      </div>
      <fieldset className="tide-control">
        <legend>Tide condition</legend>
        <div>{['Normal', 'Rising', 'High'].map((option) => <button key={option} className={tide === option ? 'selected' : ''} onClick={() => onTide(option)} type="button">{tide === option && <Check size={14} />} {option}</button>)}</div>
      </fieldset>
      <fieldset className="population-control">
        <legend>PFLOW population clock</legend>
        <div>{(Object.keys(populationPeriods) as PopulationPeriod[]).map((period) => <button key={period} className={populationPeriod === period ? 'selected' : ''} onClick={() => onPopulationPeriod(period)} type="button"><b>{populationPeriods[period].time}</b><span>{populationPeriods[period].label}</span></button>)}</div>
        <small>{populationPeriods[populationPeriod].note} · illustrative profile</small>
      </fieldset>
      <div className="run-row">
        <button className="run-button" onClick={onRun}>{isRunning ? <Pause size={17} fill="currentColor" /> : <Play size={17} fill="currentColor" />}{isRunning ? 'Pause simulation' : 'Run simulation'}</button>
        <button className="reset-button" onClick={onReset} aria-label="Reset simulation"><RotateCcw size={17} /></button>
      </div>
      <p className="model-note"><CircleAlert size={14} /> Demonstration model. Not for emergency operations.</p>
    </aside>
  )
}

function MetricStrip({ severity, time, populationFactor }: { severity: number; time: number; populationFactor: number }) {
  const present = Math.round(82400 * populationFactor)
  const affected = Math.round((14200 + severity * 46800) * populationFactor)
  const roadLoss = Math.round(8 + severity * 53)
  const clearance = Math.round(54 + severity * 47)
  const completion = Math.min(100, Math.round((time / clearance) * 100))
  return (
    <section className="metric-strip" aria-label="Scenario results">
      <div className="time-card"><span><Clock3 size={14} /> SIMULATION TIME</span><strong>{String(Math.floor(time / 60)).padStart(2, '0')}:{String(time % 60).padStart(2, '0')}</strong><div className="timeline"><i style={{ width: `${Math.min(100, time / 1.8)}%` }} /><b style={{ left: `${Math.min(97, time / 1.86)}%` }} /></div><small>18:00 <em>EVACUATION ORDER</em> 21:00</small></div>
      <div className="metric-card"><span><Users size={15} /> PEOPLE PRESENT</span><strong>{formatPeople(present)}</strong><small>PFLOW time-of-day · synthetic</small></div>
      <div className="metric-card"><span><Waves size={15} /> PEOPLE EXPOSED</span><strong>{formatPeople(affected)}</strong><small>subset of people present</small></div>
      <div className="metric-card"><span><Route size={15} /> ROAD CAPACITY LOST</span><strong>{roadLoss}%</strong><small>vs. dry baseline</small></div>
      <div className="metric-card accent"><span><Gauge size={15} /> EVACUATION CLEARANCE</span><strong>{clearance} min</strong><div className="completion"><i style={{ width: `${completion}%` }} /></div><small>{completion}% of agents at safe nodes</small></div>
    </section>
  )
}

function PopulationPage() {
  const profile = [58, 54, 51, 50, 52, 61, 77, 94, 108, 117, 121, 123, 122, 119, 116, 112, 109, 114, 107, 94, 84, 75, 67, 61]
  const stack = [
    { n: '01', title: 'Resident baseline', value: '82.4k', text: 'WorldPop 100 m counts reconciled to approved administrative controls.' },
    { n: '02', title: 'Demographic controls', value: 'age × sex', text: 'Aggregate marginals constrain weights; they are not individual records.' },
    { n: '03', title: 'Synthetic people', value: 'weighted', text: 'Reproducible non-real agents with home cells and explicit uncertainty.' },
    { n: '04', title: 'Dynamic PFLOW presence', value: '118.6k', text: 'Activities and trips move people through the pilot area by time of day.' },
    { n: '05', title: 'Evacuation cohort', value: '31.2k', text: 'Only exposed and scenario-eligible agents enter the evacuation process.' },
  ]
  return (
    <main className="page population-page">
      <section className="page-intro split-intro"><div><div className="eyebrow"><span>02</span> Population model</div><h1>Five populations.<br />No false precision.</h1></div><div className="method-summary"><p>Resident counts seed the model. PFLOW activities create time-of-day presence. Flood exposure selects an evacuation cohort. These quantities are related, but never interchangeable.</p><span className="synthetic-label"><ShieldCheck size={14} /> Synthetic people, never reconstructed identities</span></div></section>
      <div className="population-demo-note"><CircleAlert size={14} /> Illustrative pilot values · not Bangkok estimates · pilot area pending</div>
      <section className="population-stack">{stack.map((item) => <article key={item.n}><span>{item.n}</span><strong>{item.value}</strong><h2>{item.title}</h2><p>{item.text}</p></article>)}</section>
      <section className="population-dashboard">
        <article className="profile-card"><div className="card-heading"><div><span className="section-kicker">ILLUSTRATIVE PILOT PROFILE</span><h2>People present across 24 hours</h2></div><b>PFLOW activity state</b></div><div className="profile-chart" aria-label="Illustrative hourly population profile">{profile.map((value, hour) => <i key={hour} style={{ height: `${Math.round(value / 1.3)}%` }}><span>{hour % 6 === 0 ? `${String(hour).padStart(2, '0')}:00` : ''}</span></i>)}</div><p>Numbers are a prototype profile, not measured live occupancy. A research run replaces it with Bangkok-calibrated activity, destination and trip evidence.</p></article>
        <article className="population-qa"><span className="section-kicker">POPULATION VERSION GATE</span><h2>What must reconcile</h2><ul><li><Check size={15} /> 100 m resident totals → subdistrict controls</li><li><Check size={15} /> age/sex weights → held-out marginals</li><li><Check size={15} /> activities + travellers → people present</li><li><Check size={15} /> exposed + unexposed → people present</li><li><CircleAlert size={15} /> households and vehicle access remain scenarios</li></ul><a href="https://hub.worldpop.org/project/categories?id=3" target="_blank" rel="noreferrer">WorldPop baseline <ExternalLink size={14} /></a></article>
      </section>
      <section className="population-principles"><article><h3>Public resolution</h3><p>Start at 1 km for population and mobility reporting. Move to 500 m only after Bangkok validation and disclosure review.</p></article><article><h3>Building allocation</h3><p>Footprints and height can redistribute estimates. Neither proves residential use, occupancy or refuge safety.</p></article><article><h3>Households later</h3><p>Weighted people are the MVP. Household relationships wait for reusable marginals or approved microdata.</p></article></section>
    </main>
  )
}

function DataRegistry() {
  const [filter, setFilter] = useState<'all' | SourceStatus>('all')
  const filtered = dataSources.filter((source) => filter === 'all' || source.status === filter)
  return (
    <main className="page registry-page">
      <section className="page-intro"><div className="eyebrow"><span>03</span> Evidence ledger</div><h1>Every layer earns its place.</h1><p>Open-data purity is a product requirement: public access and explicit reuse permission. If either is missing, the dataset stays out of the operational pipeline.</p></section>
      <div className="registry-toolbar">
        <div className="registry-filters">{(['all', 'approved', 'verify', 'rejected'] as const).map((status) => <button className={filter === status ? 'active' : ''} key={status} onClick={() => setFilter(status)}>{status === 'all' ? `All sources · ${dataSources.length}` : statusCopy[status].label}</button>)}</div>
        <span className="registry-date">Registry prototype · reviewed 29 Sep 2026</span>
      </div>
      <div className="registry-table" role="table" aria-label="Open data source registry">
        <div className="registry-row registry-header" role="row"><span>STATUS</span><span>SOURCE / DATASET</span><span>MODEL ROLE</span><span>ACCESS</span><span>LICENCE</span><span /></div>
        {filtered.map((source) => <div className="registry-row" role="row" key={`${source.agency}-${source.dataset}`}>
          <span><i className={`status-dot ${source.status}`} />{statusCopy[source.status].label}</span>
          <span><strong>{source.dataset}</strong><small>{source.agency}</small></span><span>{source.use}</span>
          <span><strong>{source.format}</strong><small>{source.resolution}</small></span>
          <span><b className={`licence ${source.status}`}>{source.licence}</b>{source.note && <small>{source.note}</small>}</span>
          <a href={source.url} target="_blank" rel="noreferrer" aria-label={`Open ${source.dataset} source`}><ExternalLink size={17} /></a>
        </div>)}
      </div>
      <section className="policy-grid">
        <article><ShieldCheck size={24} /><h2>The two-part gate</h2><p>A source moves to approved only when it is accessible to anyone and includes explicit permission for reuse.</p></article>
        <article><Database size={24} /><h2>Immutable provenance</h2><p>Every model run records dataset version, retrieval time, licence snapshot, processing code and model parameters.</p></article>
        <article><Activity size={24} /><h2>Model outputs are labelled</h2><p>Observed extent, predicted depth and evacuation results remain visually distinct—never blended into a false “live” layer.</p></article>
      </section>
    </main>
  )
}

function MethodPage() {
  const steps = [
    { number: '01', title: 'People + activities', text: 'Generate weighted synthetic people and Bangkok-calibrated daily activity chains. Japan-side population and behaviour parameters are not transferred.', icon: Users },
    { number: '02', title: 'Trips + trajectories', text: 'Create mode-labelled trips and route them on a dated OSM graph while retaining PFLOW-compatible trip and waypoint records.', icon: Route },
    { number: '03', title: 'Flood intervention', text: 'Turn observed extent and modelled depth into time-varying edge impedance, building exposure and explicit refuge constraints.', icon: Waves },
    { number: '04', title: 'Aggregate + validate', text: 'Publish mesh/link volumes, clearance distributions and uncertainty. Contract compatibility never substitutes for Bangkok ground truth.', icon: Activity },
  ]
  return (
    <main className="page method-page">
      <section className="page-intro split-intro"><div><div className="eyebrow"><span>04</span> PFLOW → Bangkok method</div><h1>Keep the contract.<br />Rebuild the evidence.</h1></div><div className="method-summary"><p>PFLOW supplies the research spine: people → activities → trips → trajectories → mesh and link volumes. Bangkok gets new open inputs, behavioural calibration, flood intervention and validation.</p><a href="https://github.com/jupedsim/jupedsim" target="_blank" rel="noreferrer">Optional bottleneck-scale pedestrian engine <ExternalLink size={14} /></a></div></section>
      <section className="method-flow">{steps.map(({ number, title, text, icon: Icon }, index) => <article key={title}><div className="method-number">{number}</div><Icon size={30} strokeWidth={1.5} /><h2>{title}</h2><p>{text}</p>{index < steps.length - 1 && <ArrowRight className="method-arrow" size={20} />}</article>)}</section>
      <section className="equation-panel"><div><span>PFLOW CORE</span><p>people + activities → trips + trajectories</p></div><ChevronRight /><div><span>BANGKOK EXTENSION</span><p>flood depth + buildings → constraints</p></div><ChevronRight /><div><span>RESEARCH OUTPUT</span><p>volumes + exposure + clearance</p></div></section>
      <section className="validation-section"><div><span className="section-kicker">WHAT MUST BE TRUE BEFORE LAUNCH</span><h2>Compatibility is not validation.</h2></div><ol><li><b>Population and behaviour.</b> Fit synthetic people, activities, trip rates, purposes, timing and modes to held-out Bangkok evidence.</li><li><b>Flood accuracy.</b> Validate extent against held-out observations and depth against licensed local measurements.</li><li><b>Building height.</b> Compare Open Buildings 2.5D with a representative Bangkok sample; published non-Thailand error is not local accuracy.</li><li><b>Refuge truth.</b> Never infer “safe” from height alone; capacity, access, management and structural suitability require verification.</li></ol></section>
    </main>
  )
}

function App() {
  const [view, setView] = useState<View>('scenario')
  const [mobileMenu, setMobileMenu] = useState(false)
  const [rainfall, setRainfall] = useState(165)
  const [river, setRiver] = useState(1.2)
  const [tide, setTide] = useState('Rising')
  const [populationPeriod, setPopulationPeriod] = useState<PopulationPeriod>('evening')
  const [time, setTime] = useState(42)
  const [isRunning, setIsRunning] = useState(false)
  const [layers, setLayers] = useState<Record<Layer, boolean>>({ population: true, flood: true, buildings: true, routes: true })
  const severity = useMemo(() => Math.min(1, Math.max(0.12, ((rainfall - 50) / 210) * 0.58 + (river / 2.2) * 0.34 + (tide === 'High' ? 0.16 : tide === 'Rising' ? 0.08 : 0))), [rainfall, river, tide])

  useEffect(() => {
    if (!isRunning) return
    const timer = window.setInterval(() => setTime((current) => { if (current >= 180) { setIsRunning(false); return 180 } return current + 1 }), 110)
    return () => window.clearInterval(timer)
  }, [isRunning])

  const selectView = (nextView: View) => { setView(nextView); setMobileMenu(false); window.scrollTo({ top: 0, behavior: 'smooth' }) }
  const applyPreset = (name: keyof typeof scenarios) => { const scenario = scenarios[name]; setRainfall(scenario.rain); setRiver(scenario.river); setTide(scenario.tide); setTime(0); setIsRunning(true) }
  const reset = () => { setTime(0); setIsRunning(false) }

  return (
    <div className="app">
      <header className="topbar">
        <button className="brand" onClick={() => selectView('scenario')} aria-label="Bangkok Flow home"><span className="brand-mark"><i /><i /><i /></span><strong>BKK<span>/</span>FLOW</strong><small>OPEN FLOOD + EVACUATION LAB</small></button>
        <nav className={mobileMenu ? 'open' : ''} aria-label="Primary navigation"><button className={view === 'scenario' ? 'active' : ''} onClick={() => selectView('scenario')}><Map size={16} /> Scenario lab</button><button className={view === 'population' ? 'active' : ''} onClick={() => selectView('population')}><Users size={16} /> Population</button><button className={view === 'data' ? 'active' : ''} onClick={() => selectView('data')}><Database size={16} /> Data registry</button><button className={view === 'method' ? 'active' : ''} onClick={() => selectView('method')}><BookOpen size={16} /> Method</button></nav>
        <div className="prototype-badge"><i /> RESEARCH PROTOTYPE</div><button className="menu-button" onClick={() => setMobileMenu(!mobileMenu)} aria-label="Toggle menu">{mobileMenu ? <X /> : <Menu />}</button>
      </header>
      {view === 'scenario' && <main className="scenario-view"><ScenarioPanel rainfall={rainfall} river={river} tide={tide} populationPeriod={populationPeriod} onRainfall={setRainfall} onRiver={setRiver} onTide={setTide} onPopulationPeriod={setPopulationPeriod} onPreset={applyPreset} isRunning={isRunning} onRun={() => setIsRunning((current) => !current)} onReset={reset} /><section className="map-stage"><div className="map-status"><i className={isRunning ? 'running' : ''} /><span>{isRunning ? 'MODEL RUNNING' : 'SCENARIO READY'}</span><b>Illustrative synthetic population · not live occupancy</b></div><BangkokMap severity={severity} time={time} isRunning={isRunning} populationPeriod={populationPeriod} populationFactor={populationPeriods[populationPeriod].factor} layers={layers} onLayerChange={(layer) => setLayers((current) => ({ ...current, [layer]: !current[layer] }))} /><MetricStrip severity={severity} time={time} populationFactor={populationPeriods[populationPeriod].factor} /></section></main>}
      {view === 'population' && <PopulationPage />}{view === 'data' && <DataRegistry />}{view === 'method' && <MethodPage />}
    </div>
  )
}

export default App
