export function SourceBadge({ source, compact = false }: { source: "own" | "external" | null; compact?: boolean }) {
  if (source === "own") {
    return (
      <span className="badge badge--own" data-testid="badge-own">
        {compact ? "Own engine ⚡" : "Recognized by: Own engine ⚡"}
      </span>
    );
  }
  if (source === "external") {
    return (
      <span className="badge badge--external" data-testid="badge-external">
        {compact ? "External API 🌐" : "Recognized by: External API 🌐"}
      </span>
    );
  }
  return <span className="badge badge--none">No match</span>;
}
