"use client";

import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { dismiss, toggleListen } from "@/lib/controller";
import { formatClock, formatMs, lyricLines } from "@/lib/format";
import type { RecognizeResponse } from "@/lib/schemas";
import { useBlazam } from "@/lib/store";
import { CoverArt } from "./CoverArt";
import { SourceBadge } from "./SourceBadge";

function PreviewButton({ url }: { url: string }) {
  const audio = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState(false);
  const [progress, setProgress] = useState(0);
  const [failed, setFailed] = useState(false);

  const toggle = async () => {
    const a = audio.current;
    if (!a) return;
    if (a.paused) {
      try {
        await a.play();
      } catch {
        setFailed(true);
      }
    } else a.pause();
  };

  return (
    <>
      <audio
        ref={audio}
        src={url}
        preload="none"
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => setProgress(0)}
        onError={() => setFailed(true)}
        onTimeUpdate={(e) => setProgress(e.currentTarget.duration ? e.currentTarget.currentTime / e.currentTarget.duration : 0)}
      />
      <button type="button" onClick={toggle} disabled={failed} className="btn-ghost focus-ring" data-testid="play-preview">
        <span className="relative grid h-6 w-6 place-items-center" aria-hidden>
          <svg viewBox="0 0 24 24" className="absolute inset-0 -rotate-90">
            <circle cx="12" cy="12" r="10.5" fill="none" stroke="currentColor" strokeOpacity="0.2" strokeWidth="1.5" />
            <circle cx="12" cy="12" r="10.5" fill="none" stroke="var(--c-lime)" strokeWidth="1.5" pathLength={100} strokeDasharray="100" strokeDashoffset={100 - progress * 100} />
          </svg>
          {playing ? <span className="text-[9px]">❚❚</span> : <span className="ml-0.5 text-[9px]">▶</span>}
        </span>
        {failed ? "Preview unavailable" : playing ? "Pause" : "Play preview"}
      </button>
    </>
  );
}

function LyricsDrawer({ lines, title, onClose }: { lines: string[]; title: string; onClose: () => void }) {
  const closeBtn = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    closeBtn.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <>
      <motion.div
        className="pointer-events-auto fixed inset-0 z-[54] bg-[color-mix(in_oklab,var(--c-bg-deep)_55%,transparent)]"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        onClick={onClose}
        aria-hidden
      />
      <motion.aside
        role="dialog"
        aria-modal="true"
        aria-label={`Lyrics for ${title}`}
        initial={{ x: "100%", opacity: 0.4 }}
        animate={{ x: 0, opacity: 1 }}
        exit={{ x: "100%", opacity: 0 }}
        transition={{ type: "spring", stiffness: 220, damping: 30 }}
        className="glass-strong drawer-surface pointer-events-auto fixed top-0 right-0 bottom-0 z-[55] flex w-full max-w-md flex-col rounded-l-[28px] p-6 sm:p-8"
        data-testid="lyrics"
      >
        <div className="mb-6 flex items-center justify-between">
          <p className="kicker">Lyrics</p>
          <button ref={closeBtn} type="button" onClick={onClose} className="btn-icon focus-ring" aria-label="Close lyrics">
            ×
          </button>
        </div>
        <h3 className="font-display mb-6 text-3xl text-[var(--c-ink)]">{title}</h3>
        <div className="scroll-soft -mr-4 flex-1 overflow-y-auto pr-4 pb-24 text-[17px] leading-relaxed text-[var(--c-ink-muted)]">
          {lines.map((l, i) => (l.trim() ? <p key={i}>{l}</p> : <br key={i} />))}
        </div>
      </motion.aside>
    </>
  );
}

export function ResultCard({ result }: { result: RecognizeResponse }) {
  const lyricsOpen = useBlazam((s) => s.lyricsOpen);
  const set = useBlazam((s) => s.set);
  const song = result.song;
  const card = useRef<HTMLDivElement>(null);
  useEffect(() => {
    card.current?.focus({ preventScroll: true });
  }, []);
  if (!song) return null;
  const lines = lyricLines(song.lyrics);
  const hasLyrics = lines.some((l) => l.trim());
  const at = formatClock(result.offset_seconds);
  const meta = [song.album, song.year].filter(Boolean).join(" · ");

  return (
    <>
      <motion.section
        ref={card}
        tabIndex={-1}
        aria-labelledby="result-title"
        initial={{ opacity: 0, x: 60, y: 10, filter: "blur(12px)" }}
        animate={{ opacity: 1, x: 0, y: 0, filter: "blur(0px)" }}
        exit={{ opacity: 0, x: 40, filter: "blur(10px)", transition: { duration: 0.35 } }}
        transition={{ delay: 0.55, type: "spring", stiffness: 120, damping: 20 }}
        className="result-card glass-strong pointer-events-auto relative w-full rounded-[28px] p-5 outline-none sm:p-7"
        data-testid="result-card"
        data-source={result.source}
      >
        <button type="button" onClick={dismiss} className="btn-icon focus-ring absolute top-4 right-4 z-10" aria-label="Close result">
          ×
        </button>
        <div className="flex gap-5 sm:flex-col sm:gap-6">
          <div className="relative w-24 shrink-0 sm:w-full">
            <div className="cover-glow" aria-hidden />
            <div className="relative aspect-square overflow-hidden rounded-2xl ring-1 ring-white/10 sm:rounded-[20px]">
              <CoverArt cover={song.cover_url} deezerId={song.deezer_id} alt={`Cover of ${song.album ?? song.title}`} eager />
            </div>
          </div>
          <div className="min-w-0 flex-1 pr-8 sm:pr-0">
            <SourceBadge source={result.source} />
            <h2 id="result-title" className="font-display mt-3 text-[clamp(1.6rem,3.2vw,2.6rem)] leading-[1.02] text-[var(--c-ink)] [overflow-wrap:anywhere]">
              {song.title}
            </h2>
            <p className="mt-1.5 truncate text-[15px] text-[var(--c-glow-soft)]">{song.artist}</p>
            {meta && <p className="mt-0.5 truncate text-[13px] text-[var(--c-ink-muted)]">{meta}</p>}
          </div>
        </div>

        <dl className="mt-5 grid grid-cols-2 gap-3 text-[12px] sm:mt-6">
          {at && (
            <div className="stat-chip">
              <dt>Matched at</dt>
              <dd className="tabular-nums">{at}</dd>
            </div>
          )}
          <div className="stat-chip">
            <dt>Answered in</dt>
            <dd className="tabular-nums">{formatMs(result.latency_ms)}</dd>
          </div>
          {typeof result.confidence === "number" && (
            <div className="stat-chip col-span-2" data-testid="confidence">
              <dt className="flex justify-between">
                <span>Confidence</span>
                <span className="tabular-nums text-[var(--c-ink)]">{Math.round(result.confidence * 100)}%</span>
              </dt>
              <dd className="mt-2 h-1.5 overflow-hidden rounded-full bg-white/8">
                <motion.div
                  className="h-full rounded-full bg-gradient-to-r from-[var(--c-glow)] to-[var(--c-lime)] shadow-[0_0_14px_var(--c-glow)]"
                  initial={{ width: 0 }}
                  animate={{ width: `${Math.max(3, result.confidence * 100)}%` }}
                  transition={{ delay: 0.9, duration: 1.1, ease: [0.22, 1, 0.36, 1] }}
                />
              </dd>
            </div>
          )}
        </dl>

        <div className="mt-5 flex flex-wrap gap-2 sm:mt-6">
          {song.preview_url && <PreviewButton key={song.preview_url} url={song.preview_url} />}
          {hasLyrics && (
            <button type="button" onClick={() => set({ lyricsOpen: true })} className="btn-ghost focus-ring" data-testid="open-lyrics">
              Lyrics
            </button>
          )}
          <button type="button" onClick={toggleListen} className="btn-lime focus-ring ml-auto">
            Listen again
          </button>
        </div>
      </motion.section>
      {/* portaled to <body> so it layers above the fixed top-right controls, not inside <main> */}
      {createPortal(
        <AnimatePresence>{lyricsOpen && hasLyrics && <LyricsDrawer lines={lines} title={song.title} onClose={() => set({ lyricsOpen: false })} />}</AnimatePresence>,
        document.body,
      )}
    </>
  );
}
