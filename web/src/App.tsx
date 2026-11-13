import { useState } from "react";
import { DiagnosisTable } from "./features/diagnosis/DiagnosisTable";
import { DisputeSummary } from "./features/disputes/DisputeSummary";
import { Figures } from "./features/fleet/Figures";
import { FleetLot, STATE } from "./features/fleet/FleetLot";
import { GuaranteeTable } from "./features/guarantees/GuaranteeTable";
import { ReleaseTimeline } from "./features/releases/ReleaseTimeline";
import { count, tally } from "./shared/data/format";
import type { Report } from "./shared/data/types";
import { useReport } from "./shared/data/useReport";
import { Segmented } from "./shared/ui/Segmented";
import { EmptyState, ErrorState, LoadingReport } from "./shared/ui/States";

type World = "evaluation.json" | "heldout.json";
type Version = "platform" | "first_version";
const REPO = "https://github.com/manojrevenkar12-web/scanner-fleet-platform";

export function App() {
  const [world, setWorld] = useState<World>("evaluation.json");
  const [version, setVersion] = useState<Version>("platform");
  const { state, retry } = useReport(world);
  return (
    <main className="page">
      <header className="masthead">
        <div>
          <h1>Every bay is a scanner. Here is what the platform kept running.</h1>
          <p className="lead">
            A simulated fleet of license-plate scanners on parking sites, running the real platform code through
            leaks, lost links, rain, damaged downloads and a release that crashes on one board.
          </p>
        </div>
      </header>
      <div className="section" style={{ marginTop: "var(--space-6)" }}>
        <div className="controls">
          <Segmented label="Fleet" value={world} onChange={setWorld}
            options={[{ value: "evaluation.json", label: "Development fleet" }, { value: "heldout.json", label: "Held-out fleet" }]} />
          <Segmented label="Version" value={version} onChange={setVersion}
            options={[{ value: "platform", label: "With the platform" }, { value: "first_version", label: "First version" }]} />
        </div>
        {state.status === "loading" && <LoadingReport />}
        {state.status === "error" && <ErrorState message={state.message} onRetry={retry} />}
        {state.status === "empty" && <EmptyState what={world === "heldout.json" ? "held-out report" : "fleet report"}
          command={world === "heldout.json" ? "python scripts/evaluate.py --heldout" : "python scripts/evaluate.py"} />}
      </div>
      {state.status === "ready" && <Body report={state.report} version={version} />}
    </main>
  );
}

function Body({ report, version }: { report: Report; version: Version }) {
  const run = report.runs[version];
  const states = run.device_states ?? "";
  const t = tally(states);
  return (
    <>
      <section className="section" aria-labelledby="lot-h">
        <h2 id="lot-h">{count(report.devices)} devices on {count(report.sites)} sites, {report.days} days</h2>
        {states ? <FleetLot sites={report.device_sites} states={states} /> : <EmptyState what="device states" command="python scripts/evaluate.py" />}
        <div className="legend">
          {Object.entries(STATE).map(([k, s]) => (
            <span key={k}><i style={{ background: s.color }} />{s.label}: {count(t[k] ?? 0)}</span>
          ))}
        </div>
        <Figures run={run} />
      </section>

      <section className="section" aria-labelledby="g-h">
        <h2 id="g-h">What each guarantee is worth</h2>
        <p>Same fleet, faults and releases, with one guarantee switched off at a time.</p>
        <GuaranteeTable runs={report.runs} />
      </section>

      <div className="grid-2">
        <section className="section" aria-labelledby="r-h">
          <h2 id="r-h">Releases</h2>
          <ReleaseTimeline releases={run.releases} days={report.days} />
        </section>
        <section className="section" aria-labelledby="d-h">
          <h2 id="d-h">Faults named from telemetry</h2>
          <DiagnosisTable run={run} />
          <h2>Parking-fine disputes</h2>
          <DisputeSummary d={run.disputes} />
        </section>
      </div>

      <footer className="section note">
        <p>Numbers come from scripts/evaluate.py on fleet "{report.world}" (seed {report.seed}). Source: <a href={REPO}>{REPO}</a></p>
      </footer>
    </>
  );
}
