import type { ReactNode } from "react";
import type { Blocker } from "../api";

/** Every string here comes from the backend's blocker report (a fixed
 * per-class table plus an error line copied from the sandbox) or from a
 * Tavily result. All of it is rendered as text — React escapes it — and a
 * URL becomes an href only when it is an http(s) URL. */
function isSafeHttpUrl(url: string): boolean {
  try {
    return ["http:", "https:"].includes(new URL(url).protocol);
  } catch {
    return false;
  }
}

const FIXABLE_STYLES: Record<string, string> = {
  deterministic: "border-signal-dim bg-signal-dim/30 text-signal",
  model: "border-warn/40 bg-warn/10 text-warn",
  human: "border-alarm-dim bg-alarm-dim/30 text-alarm",
  platform: "border-border bg-surface-raised text-text-secondary",
};

function Tag({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <span
      className={`inline-flex items-center rounded-sm border px-2 py-0.5 font-mono text-[11px] tracking-wide ${className}`}
    >
      {children}
    </span>
  );
}

export function BlockerCard({ blocker }: { blocker: Blocker }) {
  const fixable = blocker.fixable_by;
  const sources = blocker.sources;
  const hits = sources?.sources ?? null;

  return (
    <section className="rounded-sm border border-border bg-surface px-5 py-4" aria-labelledby="blocker-heading">
      <h2 id="blocker-heading" className="font-mono text-xs uppercase tracking-wide text-text-secondary">
        What blocks it
      </h2>

      <div className="mt-2 flex flex-wrap items-center gap-2">
        <Tag className="border-alarm-dim bg-alarm-dim/30 text-alarm">
          {blocker.class}
          {blocker.family ? ` · ${blocker.family}` : ""}
        </Tag>
        <Tag className="border-border bg-surface-raised text-text-secondary">phase: {blocker.phase}</Tag>
        <Tag className="border-border bg-surface-raised text-text-secondary">attribution: {blocker.attribution}</Tag>
      </div>

      <pre className="mt-3 whitespace-pre-wrap break-all rounded-sm border border-border/60 bg-bg px-3 py-2 font-mono text-[11px] leading-relaxed text-text-primary/90">
        {blocker.evidence}
      </pre>

      <div className="mt-3 flex flex-wrap items-center gap-2 font-mono text-xs">
        <span className="text-text-secondary">Fixable by</span>
        <Tag className={fixable ? FIXABLE_STYLES[fixable] ?? FIXABLE_STYLES.platform : FIXABLE_STYLES.platform}>
          {fixable ?? "unknown"}
        </Tag>
      </div>

      {blocker.what_a_human_must_supply && (
        <p className="mt-3 font-mono text-xs leading-relaxed">
          <span className="text-text-secondary">What a human must supply: </span>
          <span className="text-text-primary">{blocker.what_a_human_must_supply}</span>
        </p>
      )}

      {sources && hits && hits.length > 0 && (
        <div className="mt-3 border-t border-border/60 pt-2">
          <p className="font-mono text-[11px] uppercase tracking-wide text-text-secondary">Where to get it (Tavily)</p>
          <ul className="mt-1 space-y-1">
            {hits.map((hit, i) =>
              isSafeHttpUrl(hit.url) ? (
                <li key={i} className="font-mono text-[11px]">
                  <a
                    href={hit.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="break-all text-signal underline decoration-signal-dim underline-offset-2 hover:opacity-80"
                  >
                    [{i + 1}] {hit.title || hit.url}
                  </a>
                </li>
              ) : (
                <li key={i} className="font-mono text-[11px] text-text-secondary">
                  [{i + 1}] {hit.title || "(source with an unrecognized URL scheme, not linked)"}
                </li>
              ),
            )}
          </ul>
          <p className="mt-1 break-all font-mono text-[10px] text-text-secondary">query: {sources.query}</p>
        </div>
      )}

      {sources && hits === null && (
        <div className="mt-3 border-t border-border/60 pt-2">
          <p className="font-mono text-[11px] uppercase tracking-wide text-text-secondary">Where to get it (Tavily)</p>
          <p className="mt-1 font-mono text-[10px] text-text-secondary">
            no sources{sources.reason ? `: ${sources.reason}` : ""}
          </p>
          {sources.query && <p className="mt-0.5 break-all font-mono text-[10px] text-text-secondary">query: {sources.query}</p>}
        </div>
      )}
    </section>
  );
}
