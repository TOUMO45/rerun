import type { ReviewFlag as ReviewFlagData } from "../api";

/** harness-v1.10 flag mode (owner, 2026-10-09): the behavioural checks would have refused a patch this run adopted. Advisory: the verdict beside it is
 * harness-v1.9.0's and the flag does not change it. The use was chosen after the measured results were seen, which the note says. */
export function ReviewFlag({ review }: { review: ReviewFlagData }) {
  return (
    <section
      aria-label="Review required"
      className="rounded-sm border border-warn/40 bg-warn/10 px-4 py-3 font-mono text-xs text-warn"
      data-testid="review-required"
    >
      <p className="font-semibold">
        {review.status.replace("_", " ")}: {review.reasons.join(", ")}
      </p>
      <ul className="mt-2 space-y-1 text-[11px] leading-relaxed">
        {review.findings.map((f, i) => (
          <li key={`${f.reason}-${i}`}>
            <span className="font-semibold">{f.reason}</span> ({f.stage}
            {f.file ? `, ${f.file}${f.line ? `:${f.line}` : ""}` : ""}) — {f.detail}
          </li>
        ))}
      </ul>
      <p className="mt-2 text-[10px] leading-snug text-text-secondary" data-testid="review-note">
        {review.note}
      </p>
    </section>
  );
}
