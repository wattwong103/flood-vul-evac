/**
 * App shell: navigation, run selection context, reduced-motion mode, and the
 * persistent research-prototype framing.
 *
 * Navigation is a real tab widget: arrow keys move between screens, and the
 * active screen is exposed through ARIA rather than colour alone.
 */

import { useEffect, useState } from "react";
import {
  BookOpen,
  Database,
  Gauge,
  Menu,
  Satellite,
  ShieldAlert,
  Users,
  X,
} from "lucide-react";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ScenarioLab } from "@/screens/ScenarioLab";
import { Population } from "@/screens/Population";
import { DataRegistry } from "@/screens/DataRegistry";
import { Method } from "@/screens/Method";
import { RunDetail } from "@/screens/RunDetail";
import { ObservedAssets } from "@/screens/ObservedAssets";
import { RunProvider, useRuns, API_BASE_URL } from "@/lib/run-context";
import { resolveValidationStatus } from "@/components/primitives";
import { formatText } from "@/lib/format";
import "./App.css";

const MOTION_KEY = "bkkflow.reducedMotion";

function prefersReducedMotion(): boolean {
  try {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch {
    return false;
  }
}

function Shell() {
  const [view, setView] = useState("scenario");
  const [mobileOpen, setMobileOpen] = useState(false);
  const [reducedMotion, setReducedMotion] = useState(prefersReducedMotion);

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(MOTION_KEY);
      if (stored === "true") setReducedMotion(true);
      if (stored === "false") setReducedMotion(false);
    } catch {
      /* the OS preference remains the default */
    }
  }, []);

  useEffect(() => {
    const root = document.documentElement;
    root.dataset.reducedMotion = reducedMotion ? "true" : "false";
    try {
      window.localStorage.setItem(MOTION_KEY, String(reducedMotion));
    } catch {
      /* not fatal */
    }
  }, [reducedMotion]);

  const select = (next: string) => {
    setView(next);
    setMobileOpen(false);
    window.scrollTo({ top: 0, behavior: reducedMotion ? "auto" : "smooth" });
  };

  return (
    <div className="app">
      <a className="skip-link" href="#main">
        Skip to content
      </a>

      <header className="topbar">
        <button className="brand" onClick={() => select("scenario")}>
          <span className="brand-mark" aria-hidden="true">
            <i />
            <i />
            <i />
          </span>
          <span>
            <strong>
              BKK<span>/</span>FLOW
            </strong>
            <small>OPEN FLOOD + EVACUATION RESEARCH PROTOTYPE</small>
          </span>
        </button>

        <nav className={mobileOpen ? "open" : ""} aria-label="Primary">
          <button
            className={view === "scenario" ? "active" : ""}
            aria-current={view === "scenario" ? "page" : undefined}
            onClick={() => select("scenario")}
          >
            <Gauge size={15} aria-hidden="true" /> Scenario lab
          </button>
          <button
            className={view === "population" ? "active" : ""}
            aria-current={view === "population" ? "page" : undefined}
            onClick={() => select("population")}
          >
            <Users size={15} aria-hidden="true" /> Population
          </button>
          <button
            className={view === "data" ? "active" : ""}
            aria-current={view === "data" ? "page" : undefined}
            onClick={() => select("data")}
          >
            <Database size={15} aria-hidden="true" /> Data registry
          </button>
          <button
            className={view === "method" ? "active" : ""}
            aria-current={view === "method" ? "page" : undefined}
            onClick={() => select("method")}
          >
            <BookOpen size={15} aria-hidden="true" /> Method
          </button>
          <button
            className={view === "observed" ? "active" : ""}
            aria-current={view === "observed" ? "page" : undefined}
            onClick={() => select("observed")}
          >
            <Satellite size={15} aria-hidden="true" /> Observed &amp; assets
          </button>
          <button
            className={view === "run" ? "active" : ""}
            aria-current={view === "run" ? "page" : undefined}
            onClick={() => select("run")}
          >
            <ShieldAlert size={15} aria-hidden="true" /> Run detail
          </button>
        </nav>

        <div className="topbar-tools">
          <label className="motion-toggle">
            <Switch
              checked={reducedMotion}
              onCheckedChange={setReducedMotion}
              aria-label="Reduce motion"
            />
            <span>Reduce motion</span>
          </label>
          <button
            className="menu-button"
            onClick={() => setMobileOpen((open) => !open)}
            aria-label={mobileOpen ? "Close menu" : "Open menu"}
            aria-expanded={mobileOpen}
          >
            {mobileOpen ? <X size={20} /> : <Menu size={20} />}
          </button>
        </div>
      </header>

      <div className="prototype-banner" role="note">
        <ShieldAlert size={15} aria-hidden="true" />
        <span>
          <b>Research prototype.</b> Not a warning, routing or emergency service. Most
          figures are model outputs at a stated model time. The JRC surface-water layer
          is an observation, and it measures extent only — not depth.
        </span>
        <ApiStatus />
      </div>

      <Tabs value={view} onValueChange={select} className="view-tabs">
        <TabsList className="sr-only" aria-label="Screens">
          <TabsTrigger value="scenario">Scenario lab</TabsTrigger>
          <TabsTrigger value="population">Population</TabsTrigger>
          <TabsTrigger value="data">Data registry</TabsTrigger>
          <TabsTrigger value="method">Method</TabsTrigger>
          <TabsTrigger value="observed">Observed &amp; assets</TabsTrigger>
          <TabsTrigger value="run">Run detail</TabsTrigger>
        </TabsList>

        <main id="main">
          <TabsContent value="scenario">
            <ScenarioLab reducedMotion={reducedMotion} />
          </TabsContent>
          <TabsContent value="population">
            <Population />
          </TabsContent>
          <TabsContent value="data">
            <DataRegistry />
          </TabsContent>
          <TabsContent value="method">
            <Method />
          </TabsContent>
          <TabsContent value="observed">
            <ObservedAssets reducedMotion={reducedMotion} />
          </TabsContent>
          <TabsContent value="run">
            <RunDetail />
          </TabsContent>
        </main>
      </Tabs>
    </div>
  );
}

/** Live reachability of the API, so a blank screen is never ambiguous. */
function ApiStatus() {
  const { runs, stats, activeRunId } = useRuns();
  const status = resolveValidationStatus(
    stats.data?.validation_status ?? runs.data?.[0]?.validation_status ?? null,
  );

  return (
    <span className="api-status">
      <span
        aria-hidden="true"
        className={`api-dot state-${runs.phase}`}
      />
      <span className="mono">{API_BASE_URL}</span>
      <span>
        {runs.phase === "error"
          ? "unreachable"
          : runs.phase === "loading"
            ? "checking"
            : runs.phase === "missing"
              ? "no run yet"
              : activeRunId
                ? `run ${activeRunId.slice(0, 8)} · ${formatText(status)}`
                : "no completed run"}
      </span>
    </span>
  );
}

export default function App() {
  return (
    <RunProvider>
      <Shell />
    </RunProvider>
  );
}
