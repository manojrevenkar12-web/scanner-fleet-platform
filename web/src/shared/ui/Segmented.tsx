import { motion } from "framer-motion";
import { motion as m } from "../theme/tokens";

export function Segmented<T extends string>({ options, value, onChange, label }: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
  label: string;
}) {
  return (
    <div className="segmented" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} aria-pressed={o.value === value} onClick={() => onChange(o.value)}>
          {o.value === value && (
            <motion.div layoutId={`thumb-${label}`} className="thumb" transition={{ duration: m.quick, ease: m.ease }} />
          )}
          <span>{o.label}</span>
        </button>
      ))}
    </div>
  );
}
