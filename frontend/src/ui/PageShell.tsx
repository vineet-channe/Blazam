"use client";

import { motion } from "framer-motion";
import type { ReactNode } from "react";

/** Glass-panel page frame floating over the dimmed scene. */
export function PageShell({ kicker, title, aside, children }: { kicker: string; title: ReactNode; aside?: ReactNode; children: ReactNode }) {
  return (
    <div className="page mx-auto w-full max-w-7xl">
      <motion.header
        initial={{ opacity: 0, y: 24, filter: "blur(8px)" }}
        animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
        transition={{ duration: 0.9, ease: [0.22, 1, 0.36, 1] }}
        className="mb-8 flex flex-wrap items-end justify-between gap-4 sm:mb-12"
      >
        <div>
          <p className="kicker mb-3">{kicker}</p>
          <h1 className="page-title text-[var(--c-ink)]">{title}</h1>
        </div>
        {aside}
      </motion.header>
      <motion.div initial={{ opacity: 0, y: 30 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.9, delay: 0.15, ease: [0.22, 1, 0.36, 1] }}>
        {children}
      </motion.div>
    </div>
  );
}

/** Designed empty / error state used by every page. */
export function EmptyState({ title, body, action }: { title: string; body: string; action?: ReactNode }) {
  return (
    <div className="glass-strong panel flex flex-col items-center py-14 text-center" role="status">
      <div className="font-display mb-4 text-5xl text-[var(--c-glow)] opacity-70" aria-hidden>
        B.
      </div>
      <h2 className="font-display text-2xl text-[var(--c-ink)]">{title}</h2>
      <p className="mt-2 max-w-md text-[15px] text-[var(--c-ink-muted)]">{body}</p>
      {action && <div className="mt-6">{action}</div>}
    </div>
  );
}
