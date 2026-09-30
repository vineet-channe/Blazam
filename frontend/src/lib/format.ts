export function formatClock(seconds: number | null | undefined): string | null {
  if (seconds == null || !Number.isFinite(seconds)) return null;
  const s = Math.max(0, Math.round(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export function formatMs(ms: number | null | undefined): string {
  if (ms == null) return "–";
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)} s` : `${Math.round(ms)} ms`;
}

export function timeAgo(unixSeconds: number, now = Date.now()): string {
  const d = Math.max(0, now / 1000 - unixSeconds);
  if (d < 45) return "just now";
  if (d < 3600) return `${Math.round(d / 60)} min ago`;
  if (d < 86_400) return `${Math.round(d / 3600)} h ago`;
  if (d < 86_400 * 7) return `${Math.round(d / 86_400)} d ago`;
  return new Date(unixSeconds * 1000).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

export const compact = (n: number) => new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(n);

/** LRC "[mm:ss.xx] line" -> plain lines */
export function lyricLines(lyrics: { plain?: string | null; synced?: string | null } | null | undefined): string[] {
  const text = lyrics?.plain || lyrics?.synced?.replace(/\[[^\]]*\]\s?/g, "") || "";
  return text.split(/\r?\n/);
}
