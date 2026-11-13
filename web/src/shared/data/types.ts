export type Diagnosis = { faults: number; found: number; false_alarms: number; median_hours_to_find: number | null };
export type Disputes = {
  fines: number; wrong_fines: number; disputes: number;
  wrong_fines_upheld: number; wrong_fines_cancelled: number; right_fines_upheld: number; right_fines_cancelled: number;
};
export type ReleaseRun = { version: string; halted: string | null; waves_opened: number; history: [number, string][] };

export type Run = {
  devices: number;
  availability: number;
  device_hours_down: number;
  max_devices_down_at_once: number;
  devices_bricked: number;
  site_visits: number;
  devices_that_ran_the_broken_build: number;
  installs: number;
  bundles_refused: Record<string, number>;
  automatic_rollbacks: number;
  on_latest_release_at_end: number;
  exits: number;
  exits_missed_by_scanners: number;
  exits_lost_in_transit: number;
  releases: ReleaseRun[];
  disputes: Disputes;
  diagnosis: { enabled: boolean } & Partial<Record<"memory_leak" | "crash_loop" | "camera_degraded" | "flaky_uplink", Diagnosis>>;
  device_states?: string;
};

export type Report = {
  world: string; seed: number; days: number; sites: number; devices: number;
  device_types: Record<string, number>; releases: string[]; device_sites: string[];
  runs: Record<string, Run>;
};
