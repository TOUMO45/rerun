import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { api, ApiError } from "../api";
import { ScopeLine } from "../components/ScopeLine";

export function Intake() {
  const [repoUrl, setRepoUrl] = useState("");
  const navigate = useNavigate();

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
    <div className="mx-auto max-w-2xl">
      <div className="mb-10">
        <h1 className="font-display text-3xl font-semibold tracking-tight text-text-primary sm:text-4xl">
          Does this paper&apos;s code actually run?
        </h1>
        <p className="mt-3 max-w-xl text-sm leading-relaxed text-text-secondary">
          Paste a public GitHub repo. RERUN clones it into an isolated sandbox, rebuilds
          its environment from scratch, and executes it — then issues a verdict backed
          by real log evidence, not a guess.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="rounded-sm border border-border bg-surface p-5">
        <label htmlFor="repo-url" className="mb-2 block font-mono text-xs uppercase tracking-wide text-text-secondary">
          Repository URL
        </label>
        <div className="flex flex-col gap-3 sm:flex-row">
          <input
            id="repo-url"
            type="text"
            value={repoUrl}
            onChange={(e) => setRepoUrl(e.target.value)}
            placeholder="https://github.com/author/paper-repo"
            className="flex-1 rounded-sm border border-border bg-bg px-3 py-2.5 font-mono text-sm text-text-primary placeholder:text-text-secondary/50 focus:border-signal-dim"
            autoFocus
          />
          <button
            type="submit"
            disabled={mutation.isPending || !repoUrl.trim()}
            className="rounded-sm bg-signal px-5 py-2.5 font-mono text-sm font-medium text-bg transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {mutation.isPending ? "Validating…" : "Run reproduction check"}
          </button>
        </div>

        {mutation.isError && (
          <div className="mt-4 rounded-sm border border-alarm-dim bg-alarm-dim/10 px-3 py-2.5 font-mono text-xs text-alarm">
            {mutation.error instanceof ApiError
              ? mutation.error.message
              : "Something went wrong reaching RERUN's backend."}
          </div>
        )}

        <p className="mt-4 font-mono text-[11px] text-text-secondary">
          Checks performed before a run starts: repo is public and reachable, and it
          contains detectable Python code.
        </p>
      </form>

      <div className="mt-6">
        <ScopeLine />
      </div>
    </div>
  );
}
