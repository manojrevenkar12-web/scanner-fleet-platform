import { useCallback, useEffect, useState } from "react";
import type { Report } from "./types";

export type State = { status: "loading" } | { status: "error"; message: string } | { status: "empty" } | { status: "ready"; report: Report };

export function classify(body: unknown): State {
  const r = body as Partial<Report> | null;
  if (!r || typeof r !== "object" || !r.runs) return { status: "error", message: "The report file is not an evaluation report." };
  if (!r.runs.platform) return { status: "empty" };
  return { status: "ready", report: r as Report };
}

export function useReport(file: string): { state: State; retry: () => void } {
  const [state, setState] = useState<State>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let live = true;
    setState({ status: "loading" });
    fetch(`./data/${file}`)
      .then((r) => {
        if (r.status === 404) return null;
        if (!r.ok) throw new Error(`The server answered ${r.status}.`);
        return r.json();
      })
      .then((body) => live && setState(body === null ? { status: "empty" } : classify(body)))
      .catch((e: Error) => live && setState({ status: "error", message: e.message }));
    return () => {
      live = false;
    };
  }, [file, attempt]);
  const retry = useCallback(() => setAttempt((a) => a + 1), []);
  return { state, retry };
}
