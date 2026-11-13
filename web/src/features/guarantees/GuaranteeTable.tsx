import { count, guaranteeName, share } from "../../shared/data/format";
import type { Run } from "../../shared/data/types";

export function GuaranteeTable({ runs }: { runs: Record<string, Run> }) {
  const rows = Object.entries(runs).filter(([k]) => k.startsWith("without_"));
  if (!rows.length) return <p className="note">The held-out fleet was run with every guarantee on and every guarantee off only.</p>;
  return (
    <table>
      <thead>
        <tr><th>Switched off</th><th className="num">Availability</th><th className="num">Bricked</th><th className="num">Ran the broken build</th>
          <th className="num">Exits lost in transit</th><th className="num">Wrong fines upheld</th></tr>
      </thead>
      <tbody>
        {rows.map(([k, r]) => (
          <tr key={k}>
            <td>{guaranteeName(k.replace("without_", ""))}</td>
            <td className="num">{share(r.availability, 2)}</td>
            <td className={`num ${r.devices_bricked ? "bad" : ""}`}>{count(r.devices_bricked)}</td>
            <td className="num">{count(r.devices_that_ran_the_broken_build)}</td>
            <td className={`num ${r.exits_lost_in_transit ? "bad" : ""}`}>{count(r.exits_lost_in_transit)}</td>
            <td className={`num ${r.disputes.wrong_fines_upheld ? "bad" : ""}`}>{count(r.disputes.wrong_fines_upheld)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
