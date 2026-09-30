"use client";

import { AnimatePresence, motion } from "framer-motion";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useAsync } from "@/hooks/useAsync";
import { getLibrary } from "@/lib/api";
import { compact } from "@/lib/format";
import type { LibrarySong } from "@/lib/schemas";
import { CoverArt } from "@/ui/CoverArt";
import { EmptyState, PageShell } from "@/ui/PageShell";

const PAGE_SIZE = 48;

function useDebounced<T>(value: T, ms: number) {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

export default function LibraryPage() {
  const [query, setQuery] = useState("");
  const q = useDebounced(query.trim(), 250);
  // pages reset whenever the query changes: they are stored against the query they belong to
  const [paging, setPaging] = useState({ q: "", pages: 1 });
  const pages = paging.q === q ? paging.pages : 1;
  const [playing, setPlaying] = useState<string | null>(null);
  const audio = useRef<HTMLAudioElement>(null);

  const { data, error, loading, reload } = useAsync(
    async (signal) => {
      const results = await Promise.all(Array.from({ length: pages }, (_, i) => getLibrary({ q, page: i + 1, pageSize: PAGE_SIZE }, signal)));
      return { items: results.flatMap((r) => r.items), total: results[0]?.total ?? 0 };
    },
    [q, pages],
  );

  const toggle = (song: LibrarySong) => {
    const a = audio.current;
    if (!a || !song.preview_url) return;
    if (playing === song.preview_url) {
      a.pause();
      setPlaying(null);
      return;
    }
    a.src = song.preview_url;
    void a.play().then(
      () => setPlaying(song.preview_url ?? null),
      () => setPlaying(null),
    );
  };

  return (
    <PageShell
      kicker="The library"
      title={
        <>
          Every song Blazam <em className="hero-accent">knows</em>
        </>
      }
      aside={data && <p className="font-mono text-[12px] tracking-wide text-[var(--c-ink-muted)]">{compact(data.total)} songs indexed</p>}
    >
      <audio ref={audio} onEnded={() => setPlaying(null)} onPause={() => setPlaying(null)} />
      <div className="glass-strong panel mb-6 flex items-center gap-3 !py-3">
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.6" className="ml-1 shrink-0 text-[var(--c-ink-muted)]" aria-hidden>
          <circle cx="11" cy="11" r="6.5" />
          <path d="M16 16l4 4" strokeLinecap="round" />
        </svg>
        <label htmlFor="lib-search" className="sr-only">
          Search the library
        </label>
        <input
          id="lib-search"
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search by title, artist or album"
          className="input !h-11 !border-0 !bg-transparent !px-1"
          autoComplete="off"
          data-testid="library-search"
        />
      </div>

      {error ? (
        <EmptyState
          title={error.kind === "offline" || error.kind === "timeout" ? "Can’t reach the library" : "The library didn’t load"}
          body="The Blazam server didn’t answer. Make sure it’s running, then try again."
          action={
            <button type="button" className="btn-lime focus-ring" onClick={reload}>
              Retry
            </button>
          }
        />
      ) : data && data.items.length === 0 && !loading ? (
        <EmptyState
          title={q ? `Nothing matches “${q}”` : "The library is empty"}
          body={q ? "Try a different spelling, or add the song from Deezer." : "Seed it with the Deezer chart or upload your own files."}
          action={
            <Link href="/add" className="btn-lime focus-ring">
              Add songs
            </Link>
          }
        />
      ) : (
        <>
          <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 sm:gap-4 lg:grid-cols-4 xl:grid-cols-6" aria-busy={loading} data-testid="library-grid">
            <AnimatePresence initial={false}>
              {(data?.items ?? []).map((s, i) => (
                <motion.li
                  key={s.id ?? `${s.title}-${i}`}
                  initial={{ opacity: 0, y: 16 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: Math.min(i % PAGE_SIZE, 18) * 0.025, duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
                  className="song-card glass"
                >
                  <button
                    type="button"
                    onClick={() => toggle(s)}
                    disabled={!s.preview_url}
                    className="focus-ring group block w-full text-left"
                    aria-label={`${playing === s.preview_url ? "Pause" : "Play"} ${s.title}${s.artist ? ` by ${s.artist}` : ""}`}
                  >
                    <div className="relative aspect-square overflow-hidden rounded-[14px]">
                      <CoverArt cover={s.cover_url} deezerId={s.deezer_id} alt="" />
                      <span
                        className={`absolute right-2 bottom-2 grid h-9 w-9 place-items-center rounded-full bg-[var(--c-lime)] text-[11px] text-[var(--c-bg-deep)] shadow-lg transition ${playing === s.preview_url ? "opacity-100" : "opacity-0 group-hover:opacity-100 group-focus-visible:opacity-100"}`}
                        aria-hidden
                      >
                        {playing === s.preview_url ? "❚❚" : "▶"}
                      </span>
                    </div>
                    <div className="px-1 pt-3 pb-1">
                      <p className="truncate text-[14px] font-medium text-[var(--c-ink)]">{s.title}</p>
                      <p className="truncate text-[12.5px] text-[var(--c-ink-muted)]">{s.artist}</p>
                      <p className="mt-2 flex items-center gap-2 font-mono text-[10px] tracking-wider text-[var(--c-ink-faint)] uppercase">
                        <span>{s.source ?? "library"}</span>
                        {s.year ? <span>· {s.year}</span> : null}
                        {s.has_lyrics ? <span title="Lyrics available">· lyrics</span> : null}
                      </p>
                    </div>
                  </button>
                </motion.li>
              ))}
            </AnimatePresence>
            {loading && !data && Array.from({ length: 12 }, (_, i) => <li key={`sk-${i}`} className="skeleton aspect-[3/4] rounded-[20px]" aria-hidden />)}
          </ul>
          {data && data.items.length < data.total && (
            <div className="mt-8 flex justify-center">
              <button type="button" className="btn-ghost focus-ring" disabled={loading} onClick={() => setPaging({ q, pages: pages + 1 })}>
                {loading ? "Loading…" : `Load more (${data.total - data.items.length} left)`}
              </button>
            </div>
          )}
        </>
      )}
    </PageShell>
  );
}
