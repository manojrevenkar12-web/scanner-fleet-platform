import { motion, useReducedMotion } from "framer-motion";
import { groupBySite } from "../../shared/data/format";
import { color, motion as m } from "../../shared/theme/tokens";

export const STATE = {
  o: { label: "Ran clean", color: color.ok },
  d: { label: "Field fault, named by diagnosis", color: color.sign },
  f: { label: "Field fault, not named", color: color.missed },
  x: { label: "Ran the broken build, fell back on its own", color: color.fallback },
  b: { label: "Bricked, waited for a technician", color: color.bricked },
} as const;

/** The fleet as a parking lot: one bay per device, sites as rows of bays. */
export function FleetLot({ sites, states }: { sites: string[]; states: string }) {
  const reduce = useReducedMotion();
  const groups = groupBySite(sites, states);
  const total = groups.length;
  return (
    <div className="lot" role="img" aria-label={`${states.length} devices on ${total} sites, coloured by what happened to each`}>
      {groups.map((g, i) => (
        <div className="site" key={g.site} title={g.site}>
          {g.states.map((s, j) => (
            <motion.div
              key={j}
              className="bay"
              initial={false}
              animate={{ backgroundColor: STATE[s as keyof typeof STATE]?.color ?? color.ok }}
              transition={{ duration: reduce ? 0 : m.quick, delay: reduce ? 0 : (i / total) * m.sweep, ease: m.ease }}
            />
          ))}
        </div>
      ))}
    </div>
  );
}
