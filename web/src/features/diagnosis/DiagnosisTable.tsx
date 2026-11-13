import { faultName, hours } from "../../shared/data/format";
import type { Run } from "../../shared/data/types";

const KINDS = ["memory_leak", "crash_loop", "camera_degraded", "flaky_uplink"] as const;

export function DiagnosisTable({ run }: { run: Run }) {
  if (!run.diagnosis.enabled) return <p className="note">Diagnosis is off in this run: faults show up as tickets, not as named issues.</p>;
  return (
    <table>
      <thead><tr><th>Fault</th><th className="num">Devices</th><th className="num">Named</th><th className="num">False alarms</th><th className="num">Median time to name</th></tr></thead>
      <tbody>
        {KINDS.map((k) => {
          const d = run.diagnosis[k];
          if (!d) return null;
          return (
            <tr key={k}><td>{faultName(k)}</td><td className="num">{d.faults}</td><td className="num">{d.found}</td>
              <td className="num">{d.false_alarms}</td><td className="num">{hours(d.median_hours_to_find)}</td></tr>
          );
        })}
      </tbody>
    </table>
  );
}
