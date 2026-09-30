"use client";

import { motion } from "framer-motion";
import Link from "next/link";
import { useState } from "react";
import { useAsync } from "@/hooks/useAsync";
import { getHistory } from "@/lib/api";
import { formatClock, formatMs, timeAgo } from "@/lib/format";
import { CoverArt } from "@/ui/CoverArt";
import { EmptyState, PageShell } from "@/ui/PageShell";
import { SourceBadge } from "@/ui/SourceBadge";

function dayLabel(unix: number) {
  const d = new Date(unix * 1000);
  const today = new Date();
  const yesterday = new Date(Date.now() - 86_400_000);
  if (d.toDateString() === today.toDateString()) return "Today";
  if (d.toDateString() === yesterday.toDateString()) return "Yesterday";
  return d.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" });
}

export default function HistoryPage() {
  const { data, error, loading, reload } = useAsync((signal) => getHistory(200, signal), []);
  const [now] = useState(() => Date.now());

  const groups: { day: string; items: NonNullable<typeof data>["items"] }[] = [];
  for (const item of data?.items ?? []) {
    const day = dayLabel(item.created_at);
    const last = groups.at(-1);
    if (last?.day === day) last.items.push(item);
    else groups.push({ day, items: [item] });
  }

  return (
    <PageShell
      kicker="History"
      title={
        <>
          Everything it <em className="hero-accent">heard</em>
        </>
      }
      aside={data && <p className="font-mono text-[12px] tracking-wide text-[var(--c-ink-muted)]">{data.items.length} recognitions</p>}
    >
      {error ? (
        <EmptyState
          title="Can’t load the history"
          body="The Blazam server didn’t answer. Make sure it’s running, then try again."
          action={
            <button type="button" className="btn-lime focus-ring" onClick={reload}>
              Retry
            </button>
          }
        />
      ) : loading && !data ? (
        <div className="space-y-3" aria-busy>
          {Array.from({ length: 5 }, (_, i) => (
            <div key={i} className="skeleton h-20 rounded-[20px]" />
          ))}
        </div>
      ) : data && data.items.length === 0 ? (
        <EmptyState
          title="Nothing heard yet"
          body="Tap the coin while a song is playing and it will show up here."
          action={
            <Link href="/" className="btn-lime focus-ring">
              Listen
            </Link>
          }
        />
      ) : (
        <div className="relative" data-testid="history-list">
          {/* the timeline spine */}
          <div className="absolute top-2 bottom-2 left-[19px] w-px bg-gradient-to-b from-[var(--c-glow)]/60 via-[var(--hairline-strong)] to-transparent sm:left-[23px]" aria-hidden />
          {groups.map((g) => (
            <section key={g.day} className="mb-8" aria-label={g.day}>
              <h2 className="kicker mb-3 pl-12 sm:pl-14">{g.day}</h2>
              <ol className="space-y-2.5">
                {g.items.map((it, i) => {
                  const at = formatClock(it.offset_seconds);
                  return (
                    <motion.li
                      key={it.id}
                      initial={{ opacity: 0, x: -12 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ delay: Math.min(i, 12) * 0.04, duration: 0.5 }}
                      className="relative flex items-center gap-3 pl-12 sm:gap-4 sm:pl-14"
                    >
                      <span
                        className={`absolute top-1/2 left-[14px] h-[11px] w-[11px] -translate-y-1/2 rounded-full ring-4 ring-[var(--c-bg-deep)] sm:left-[18px] ${it.status === "match" ? (it.source === "own" ? "bg-[var(--c-lime)] shadow-[0_0_12px_var(--c-lime)]" : "bg-[var(--c-external)]") : "bg-[var(--c-ink-faint)]"}`}
                        aria-hidden
                      />
                      <div className="glass flex min-w-0 flex-1 items-center gap-3 rounded-[18px] p-2.5 pr-4 sm:gap-4">
                        <div className="h-14 w-14 shrink-0 overflow-hidden rounded-[12px]">
                          {it.song ? <CoverArt cover={it.song.cover_url} deezerId={it.song.deezer_id} alt="" /> : <div className="cover-fallback opacity-50"><span>?</span></div>}
                        </div>
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-[15px] text-[var(--c-ink)]">{it.song ? it.song.title : "No match"}</p>
                          <p className="truncate text-[12.5px] text-[var(--c-ink-muted)]">
                            {it.song ? it.song.artist : `Closest own-engine score: ${it.score ?? 0}`}
                            {at && <span className="text-[var(--c-ink-faint)]"> · at {at}</span>}
                          </p>
                        </div>
                        <div className="hidden shrink-0 flex-col items-end gap-1 sm:flex">
                          <SourceBadge source={it.status === "match" ? it.source : null} compact />
                          <span className="font-mono text-[10.5px] text-[var(--c-ink-faint)]">
                            {formatMs(it.latency_ms)}
                            {typeof it.confidence === "number" && it.status === "match" ? ` · ${Math.round(it.confidence * 100)}%` : ""}
                          </span>
                        </div>
                        <time className="shrink-0 text-right font-mono text-[10.5px] text-[var(--c-ink-faint)]" dateTime={new Date(it.created_at * 1000).toISOString()}>
                          {timeAgo(it.created_at, now)}
                        </time>
                      </div>
                    </motion.li>
                  );
                })}
              </ol>
            </section>
          ))}
        </div>
      )}
    </PageShell>
  );
}
