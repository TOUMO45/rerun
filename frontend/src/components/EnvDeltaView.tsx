import type { EnvChange } from "../api";

function describe(change: EnvChange): string {
  switch (change.op) {
    case "pin":
      return `pin ${change.package}==${change.version}`;
    case "unpin":
      return `unpin ${change.package}`;
    case "add":
      return change.version ? `add ${change.package}==${change.version}` : `add ${change.package}`;
    case "remove":
      return `remove ${change.package}`;
    case "pip_git":
      return `pip install ${change.package} from ${change.git_url} @ ${change.commit}`;
    case "apt":
      return `apt install ${change.package}`;
    case "python":
      return `python ${change.version}`;
    default:
      return `${change.op} ${change.package ?? ""}`;
  }
}

/** Structured build-plan edits — rendered as text, never as links or HTML. */
export function EnvDeltaView({ changes }: { changes: EnvChange[] }) {
  if (changes.length === 0) {
    return <p className="font-mono text-xs text-text-secondary">No environment changes.</p>;
  }
  return (
    <ul className="space-y-2 rounded-sm bg-bg px-3 py-2.5">
      {changes.map((change, i) => (
        <li key={i} className="font-mono text-[11px] leading-relaxed">
          <span className="text-signal">{describe(change)}</span>
          {change.justification && <span className="text-text-secondary"> — {change.justification}</span>}
          {change.evidence && (
            <div className="text-text-secondary/70">
              evidence: <span className="text-text-secondary">{change.evidence}</span>
            </div>
          )}
        </li>
      ))}
    </ul>
  );
}
