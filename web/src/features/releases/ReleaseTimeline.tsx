import type { ReleaseRun } from "../../shared/data/types";

export function ReleaseTimeline({ releases, days }: { releases: ReleaseRun[]; days: number }) {
  if (!releases.length) return <p className="note">No release shipped in this fleet.</p>;
  return (
    <div style={{ display: "grid", gap: "var(--space-5)" }}>
      {releases.map((r) => (
        <div key={r.version}>
          <h3>{r.version}: {r.waves_opened} {r.waves_opened === 1 ? "wave" : "waves"} opened{r.halted ? ", then halted" : ""}</h3>
          <ol className="timeline">
            {r.history.map(([h, what], i) => (
              <li key={i}><time>day {(h / 24 + 1).toFixed(1)}</time><span>{what}</span></li>
            ))}
          </ol>
        </div>
      ))}
      <p className="note">Days count from the start of the {days}-day simulation; installs run in a nightly window.</p>
    </div>
  );
}
