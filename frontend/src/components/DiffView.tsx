export function DiffView({ diff }: { diff: string }) {
  if (!diff.trim()) {
    return <p className="font-mono text-xs text-text-secondary">No diff was proposed.</p>;
  }
  const lines = diff.split("\n");
  return (
    <pre className="max-h-72 overflow-auto rounded-sm bg-bg px-3 py-2.5 font-mono text-[11px] leading-relaxed">
      {lines.map((line, i) => {
        let cls = "text-text-secondary";
        if (line.startsWith("+++") || line.startsWith("---")) cls = "text-text-secondary/70";
        else if (line.startsWith("+")) cls = "text-signal";
        else if (line.startsWith("-")) cls = "text-alarm";
        else if (line.startsWith("@@")) cls = "text-warn";
        return (
          <div key={i} className={cls}>
            {line || " "}
          </div>
        );
      })}
    </pre>
  );
}
