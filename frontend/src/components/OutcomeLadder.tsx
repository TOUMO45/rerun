import type { OutcomeLevels } from "../api";

/** The three rungs, in the order a run climbs them. Each is a count of stored
 * fields (outcome_levels.py), so a rung can be reached on a BLOCKED
 * certificate and a reviewer still reads how far the run got. */
interface Rung {
  key: keyof OutcomeLevels;
  label: string;
  reached: boolean;
}

function originLabel(origin: string | null): string {
  if (origin === null) return "unexplained";
  if (origin === "time_machine") return "time machine";
  return origin;
}

export function OutcomeLadder({ levels }: { levels: OutcomeLevels }) {
  const rungs: Rung[] = [
    { key: "env_resolved", label: "Environment resolved", reached: levels.env_resolved },
    { key: "entrypoint_runs", label: "Entrypoint runs (60 s smoke)", reached: levels.entrypoint_runs },
    {
      key: "first_error_cleared",
      label: levels.first_error_cleared
        ? `First error cleared by: ${originLabel(levels.first_error_cleared_by)}`
        : "First error cleared by: —",
      reached: levels.first_error_cleared,
    },
  ];

  return (
    <section className="rounded-sm border border-border bg-surface px-5 py-4" aria-labelledby="outcome-ladder-heading">
      <h2 id="outcome-ladder-heading" className="font-mono text-xs uppercase tracking-wide text-text-secondary">
        Outcome ladder
      </h2>
      <ol className="mt-2 space-y-1.5">
        {rungs.map((rung) => (
          <li
            key={rung.key}
            data-testid={`rung-${rung.key}`}
            data-reached={rung.reached ? "true" : "false"}
            className="flex items-center gap-3 font-mono text-xs"
          >
            <span
              className={`inline-flex h-5 min-w-[5.5rem] items-center justify-center rounded-sm border px-2 text-[10px] uppercase tracking-wide ${
                rung.reached
                  ? "border-signal-dim bg-signal-dim/30 text-signal"
                  : "border-border bg-surface-raised text-text-secondary"
              }`}
            >
              {rung.reached ? "reached" : "not reached"}
            </span>
            <span className={rung.reached ? "text-text-primary" : "text-text-secondary"}>{rung.label}</span>
          </li>
        ))}
      </ol>
      <p className="mt-2 font-mono text-[11px] leading-relaxed text-text-secondary">
        Each rung is a count of stored fields, not a judgment; only the TEST phase&apos;s 600 s sustained check confirms
        a smoke pass.
      </p>
    </section>
  );
}
