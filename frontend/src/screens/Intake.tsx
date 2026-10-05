import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { api, ApiError } from "../api";
import { ScopeLine } from "../components/ScopeLine";
import { DemoBanner, useDemoMode } from "../components/DemoBanner";
import { EmberFrame, TopNav } from "../components/Shell";

/** The verdicts a run can end in, floated beside the hero the way the reference floats its portraits. */
const OUTCOMES = [
  { label: "RUNS CLEAN", note: "ran as documented", dot: "bg-signal", side: "left", offset: "top-[26%]" },
  { label: "RUNS AFTER REPAIR", note: "every patch is in the certificate", dot: "bg-signal", side: "left", offset: "top-[56%]" },
  { label: "BLOCKED", note: "with the log line that proves why", dot: "bg-alarm", side: "right", offset: "top-[30%]" },
  { label: "INDETERMINATE", note: "said plainly, never guessed", dot: "bg-warn", side: "right", offset: "top-[60%]" },
] as const;

export function Intake() {
  const [repoUrl, setRepoUrl] = useState("");
  const navigate = useNavigate();
  const demoMode = useDemoMode();

  const mutation = useMutation({
    mutationFn: (url: string) => api.createRun(url),
    onSuccess: (run) => navigate(`/runs/${run.id}`),
  });

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!repoUrl.trim()) return;
    mutation.mutate(repoUrl.trim());
  };

  return (
    <div>
      <EmberFrame className="mt-0">
        <TopNav />

        {OUTCOMES.map((o, i) => (
          <div
            key={o.label}
            aria-hidden="true"
            className={`glass absolute hidden w-52 animate-float-slow rounded-2xl px-4 py-3 text-white xl:block ${o.offset} ${
              o.side === "left" ? "left-8" : "right-8"
            }`}
            style={{ animationDelay: `${i * -1.7}s` }}
          >
            <span className="flex items-center gap-2 font-mono text-[11px] font-semibold tracking-wide">
              <span className={`h-2 w-2 rounded-full ring-2 ring-white/70 ${o.dot}`} />
              {o.label}
            </span>
            <span className="mt-1 block text-xs text-white/80">{o.note}</span>
          </div>
        ))}

        <section className="relative mx-auto max-w-3xl px-5 pb-14 pt-10 text-center sm:pb-20 sm:pt-16">
          <h1 className="ember-text font-display text-[1.85rem] font-bold leading-[1.08] tracking-[-0.02em] text-white sm:text-5xl xl:text-[3.25rem]">
            Paste a paper&apos;s repo.
            <br />
            Rebuild its environment.
            <br />
            Get a verdict from real logs.
          </h1>
          <p className="ember-text mx-auto mt-5 max-w-lg text-base leading-relaxed text-white/90">
            RERUN clones a public GitHub repo into an isolated sandbox, rebuilds its environment from scratch and
            executes it. Does this paper&apos;s code actually run? The answer comes with evidence, not a guess.
          </p>

          <form onSubmit={handleSubmit} className="mx-auto mt-8 max-w-xl text-left">
            <label htmlFor="repo-url" className="sr-only">
              Repository URL
            </label>
            <div className="flex flex-col gap-2 rounded-[22px] bg-white/95 p-2 shadow-card sm:flex-row sm:rounded-full">
              <input
                id="repo-url"
                type="text"
                value={repoUrl}
                onChange={(e) => setRepoUrl(e.target.value)}
                placeholder="https://github.com/author/paper-repo"
                className="min-w-0 flex-1 rounded-full bg-transparent px-4 py-2.5 font-mono text-sm text-text-primary placeholder:text-text-secondary/70 focus:outline-none"
                autoFocus
              />
              <button type="submit" disabled={mutation.isPending || !repoUrl.trim()} className="pill-ink">
                {mutation.isPending ? "Validating…" : "Run execution check"}
              </button>
            </div>
            {mutation.isError && (
              <div
                role="alert"
                className="mt-3 break-words rounded-2xl border border-alarm-dim bg-white px-4 py-3 text-left font-mono text-xs leading-relaxed text-alarm shadow-card"
              >
                {mutation.error instanceof ApiError
                  ? mutation.error.message
                  : "Something went wrong reaching RERUN's backend."}
              </div>
            )}
          </form>

          <div className="mt-5 flex flex-wrap items-center justify-center gap-3">
            <Link to="/gallery" className="pill-light shadow-card">
              Browse recorded audits
            </Link>
            <Link to="/batch" className="glass inline-flex rounded-full px-5 py-2.5 text-sm font-semibold text-white hover:bg-white/25">
              Open Batch Lab
            </Link>
          </div>
        </section>
      </EmberFrame>

      <div className="mx-auto mt-8 max-w-2xl space-y-4 px-1">
        {demoMode && (
          <div>
            <DemoBanner />
            <p className="mt-2 px-1 font-mono text-[11px] text-text-secondary">
              Intake (clone, dependency scan) still runs; the execution step is refused by the backend. Browse the{" "}
              <Link to="/gallery" className="font-semibold text-ember-deep hover:underline">
                Gallery
              </Link>{" "}
              for the recorded audits.
            </p>
          </div>
        )}

        <p className="px-1 text-center text-xs text-text-secondary">
          Checked before a run starts: the repo is public and reachable, and it contains detectable Python code.
        </p>

        <ScopeLine />
      </div>
    </div>
  );
}
