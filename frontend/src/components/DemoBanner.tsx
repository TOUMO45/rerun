import { useQuery } from "@tanstack/react-query";
import { api } from "../api";

/** True when `/healthz` reports DEMO mode (recorded audits replayed; live execution refused by the backend). */
export function useDemoMode(): boolean {
  const health = useQuery({ queryKey: ["health"], queryFn: api.health, staleTime: 60_000, retry: false });
  return health.data?.demo_mode === true;
}

export function DemoBanner() {
  return (
    <div
      role="status"
      className="rounded-sm border border-warn/40 bg-warn/10 px-4 py-2.5 font-mono text-xs text-warn"
    >
      <span className="font-semibold">Demo: </span>
      replaying recorded audits; live runs are off.
    </div>
  );
}
