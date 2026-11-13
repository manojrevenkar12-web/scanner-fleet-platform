const whole = new Intl.NumberFormat("en-GB");
export const count = (n: number) => whole.format(n);
export const share = (n: number, digits = 1) => `${(n * 100).toFixed(digits)}%`;
export const hours = (h: number | null) => (h === null ? "not found" : h < 48 ? `${h.toFixed(1)} h` : `${(h / 24).toFixed(1)} days`);

const GUARANTEE: Record<string, string> = {
  store_and_forward: "Store and forward through outages",
  ab_updates: "A/B slots with automatic fallback",
  verify_bundles: "Signed, checked update bundles",
  staged_rollout: "Staged rollout with canary gate",
  fleet_diagnosis: "Fleet diagnosis from telemetry",
  dispute_device_check: "Fine disputes checked against scanners",
  ab_updates_and_staged_rollout: "A/B slots and staged rollout",
};
export const guaranteeName = (k: string) => GUARANTEE[k] ?? k.replace(/_/g, " ");

const FAULT: Record<string, string> = {
  memory_leak: "Memory leak", crash_loop: "Crash loop", camera_degraded: "Camera worse than its neighbours", flaky_uplink: "Flaky uplink",
};
export const faultName = (k: string) => FAULT[k] ?? k;

/** Sites in order, each with its devices' states, for the fleet grid. */
export function groupBySite(sites: string[], states: string): { site: string; states: string[] }[] {
  const out: { site: string; states: string[] }[] = [];
  sites.forEach((s, i) => {
    const last = out[out.length - 1];
    if (last && last.site === s) last.states.push(states[i]);
    else out.push({ site: s, states: [states[i]] });
  });
  return out;
}

export function tally(states: string): Record<string, number> {
  const t: Record<string, number> = {};
  for (const c of states) t[c] = (t[c] ?? 0) + 1;
  return t;
}
