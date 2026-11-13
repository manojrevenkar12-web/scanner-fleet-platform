import { space } from "../theme/tokens";

export function Skeleton({ height, width = "100%" }: { height: number; width?: string }) {
  return <div className="skeleton" style={{ height, width }} aria-hidden="true" />;
}

export function LoadingReport() {
  return (
    <div role="status" aria-label="Loading the fleet report" style={{ display: "grid", gap: space[4] }}>
      <Skeleton height={space[8] * 3} />
      <Skeleton height={space[6]} width="60%" />
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="state" role="alert">
      <h3>The fleet report did not load</h3>
      <p>{message} Run python scripts/evaluate.py to regenerate it, then try again.</p>
      <button onClick={onRetry}>Load the report again</button>
    </div>
  );
}

export function EmptyState({ what, command }: { what: string; command: string }) {
  return (
    <div className="state">
      <h3>No {what} yet</h3>
      <p>Run {command} to produce it. The page picks it up on the next load.</p>
    </div>
  );
}
