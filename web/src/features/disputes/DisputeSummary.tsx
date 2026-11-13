import { count } from "../../shared/data/format";
import type { Disputes } from "../../shared/data/types";

export function DisputeSummary({ d }: { d: Disputes }) {
  const wrong = d.wrong_fines_upheld + d.wrong_fines_cancelled;
  const right = d.right_fines_upheld + d.right_fines_cancelled;
  return (
    <table>
      <thead><tr><th>Disputed fines</th><th className="num">Cancelled</th><th className="num">Upheld</th></tr></thead>
      <tbody>
        <tr><td>The scanner missed the exit ({count(wrong)})</td><td className="num">{count(d.wrong_fines_cancelled)}</td>
          <td className={`num ${d.wrong_fines_upheld ? "bad" : ""}`}>{count(d.wrong_fines_upheld)}</td></tr>
        <tr><td>The driver really overstayed ({count(right)})</td><td className="num">{count(d.right_fines_cancelled)}</td>
          <td className="num">{count(d.right_fines_upheld)}</td></tr>
      </tbody>
    </table>
  );
}
