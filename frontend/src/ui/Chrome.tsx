"use client";

import { AnimatePresence, motion } from "framer-motion";
import Link from "next/link";
import { useEffect, useRef } from "react";
import { useBlazam } from "@/lib/store";

/** Small brand chip, top-left (echoes the reference's avatar chip). */
export function BrandChip() {
  return (
    <Link href="/" className="brand-chip focus-ring fixed top-4 left-4 z-40 sm:top-5 sm:left-5" aria-label="Blazam, home">
      <span className="brand-chip__coin" aria-hidden>
        B
      </span>
      <span className="flex flex-col leading-tight">
        <span className="text-[13px] font-medium text-[var(--c-ink)]">Blazam</span>
        <span className="text-[11px] text-[var(--c-ink-muted)]">Hear it. Blaze it.</span>
      </span>
    </Link>
  );
}

/** Top-right: backend status and the sound toggle. */
export function TopRight() {
  const muted = useBlazam((s) => s.muted);
  const backend = useBlazam((s) => s.backend);
  const setMuted = useBlazam((s) => s.setMuted);
  return (
    <div className="fixed top-4 right-4 z-40 flex items-center gap-2 sm:top-5 sm:right-5">
      <AnimatePresence>
        {backend === "down" && (
          <motion.div
            initial={{ opacity: 0, y: -6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            className="glass flex items-center gap-2 rounded-full px-3 py-2 text-[12px] text-[var(--c-ink)]"
            role="status"
            data-testid="backend-offline"
          >
            <span className="h-1.5 w-1.5 rounded-full bg-[var(--c-danger)] shadow-[0_0_10px_var(--c-danger)]" aria-hidden />
            Server offline
          </motion.div>
        )}
      </AnimatePresence>
      <button
        type="button"
        onClick={() => setMuted(!muted)}
        aria-pressed={muted}
        aria-label={muted ? "Unmute sound effects" : "Mute sound effects"}
        className="glass focus-ring grid h-10 w-10 place-items-center rounded-full text-[var(--c-ink)] transition hover:text-[var(--c-lime)]"
      >
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" aria-hidden>
          <path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z" />
          {muted ? (
            <path d="M16 9.5l5 5M21 9.5l-5 5" />
          ) : (
            <>
              <path d="M16 9a4 4 0 0 1 0 6" />
              <path d="M18.5 6.5a7.5 7.5 0 0 1 0 11" />
            </>
          )}
        </svg>
      </button>
    </div>
  );
}

/** Custom cursor label that follows the pointer while it is over the coin. */
export function CursorLabel() {
  const hover = useBlazam((s) => s.coinHover);
  const phase = useBlazam((s) => s.phase);
  const el = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const move = (e: PointerEvent) => {
      if (el.current) el.current.style.transform = `translate3d(${e.clientX}px, ${e.clientY}px, 0)`;
    };
    window.addEventListener("pointermove", move, { passive: true });
    return () => window.removeEventListener("pointermove", move);
  }, []);
  const label = phase === "listening" ? "Stop" : phase === "processing" ? "…" : "Listen";
  return (
    <div ref={el} className="pointer-events-none fixed top-0 left-0 z-50 hidden md:block" aria-hidden>
      <div className={`cursor-label ${hover ? "is-on" : ""}`}>
        <span className="cursor-label__dot" />
        {label}
      </div>
    </div>
  );
}

export function ToastHost() {
  const toast = useBlazam((s) => s.toast);
  const set = useBlazam((s) => s.set);
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => set({ toast: null }), 4200);
    return () => clearTimeout(t);
  }, [toast, set]);
  return (
    <div className="pointer-events-none fixed top-20 left-1/2 z-50 -translate-x-1/2" role="status" aria-live="polite">
      <AnimatePresence>
        {toast && (
          <motion.div
            key={toast.id}
            initial={{ opacity: 0, y: -14, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ type: "spring", stiffness: 300, damping: 26 }}
            className="glass-strong flex items-center gap-2.5 rounded-full py-2 pr-4 pl-2 text-[13px] text-[var(--c-ink)]"
            data-testid="toast"
          >
            <span className="grid h-6 w-6 place-items-center rounded-full bg-[var(--c-lime)] text-[12px] text-[var(--c-bg-deep)]" aria-hidden>
              ✓
            </span>
            {toast.text}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
