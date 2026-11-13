import { count, share } from "../../shared/data/format";
import type { Run } from "../../shared/data/types";

export function Figures({ run }: { run: Run }) {
  const d = run.disputes;
  const rows = [
    { v: share(run.availability, 2), label: "device availability", bad: run.availability < 0.99 },
    { v: count(run.devices_bricked), label: "devices bricked, waiting for a site visit", bad: run.devices_bricked > 0 },
    { v: count(run.exits_lost_in_transit), label: "exit events lost between scanner and backend", bad: run.exits_lost_in_transit > 0 },
    { v: `${count(d.wrong_fines_upheld)} of ${count(d.wrong_fines_upheld + d.wrong_fines_cancelled)}`,
      label: "disputed wrong fines upheld", bad: d.wrong_fines_upheld > 0 },
  ];
  return (
    <div className="figures" aria-live="polite">
      {rows.map((r) => (
        <div key={r.label}>
          <strong className={r.bad ? "bad" : "good"}>{r.v}</strong>
          <span>{r.label}</span>
        </div>
      ))}
    </div>
  );
}
