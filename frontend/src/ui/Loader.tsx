"use client";

import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useRef, useState } from "react";
import { useBlazam } from "@/lib/store";

const MIN_MS = 1400;
const GIVE_UP_MS = 12_000;

/** "B." and a counter while the scene chunk, the coin font and the first frames come in. */
export function Loader() {
  const webgl = useBlazam((s) => s.webgl);
  const ready = useBlazam((s) => s.sceneReady);
  const [shown, setShown] = useState(0);
  const [done, setDone] = useState(false);
  const started = useRef(0);

  useEffect(() => {
    started.current = performance.now();
    let raf = 0;
    const tick = () => {
      const s = useBlazam.getState();
      const elapsed = performance.now() - started.current;
      const target = s.webgl === "none" || s.sceneReady || elapsed > GIVE_UP_MS ? 100 : s.webgl === "ok" ? 72 : 30;
      // never faster than MIN_MS, eased toward the current target
      const cap = Math.min(100, (elapsed / MIN_MS) * 100);
      setShown((v) => {
        const next = v + (Math.min(target, cap) - v) * 0.08;
        return next > 99.6 ? 100 : next;
      });
      raf = requestAnimationFrame(tick);
    };
    tick();
    return () => cancelAnimationFrame(raf);
  }, []);

  useEffect(() => {
    if (shown < 100 || done) return;
    const t = setTimeout(() => {
      setDone(true);
      useBlazam.getState().set({ introStarted: true });
    }, 350);
    return () => clearTimeout(t);
  }, [shown, done]);

  return (
    <AnimatePresence>
      {!done && (
        <motion.div
          key="loader"
          className="fixed inset-0 z-[60] flex flex-col items-center justify-center bg-[var(--c-bg-deep)]"
          exit={{ opacity: 0, transition: { duration: 1.1, ease: [0.65, 0, 0.35, 1] } }}
          role="progressbar"
          aria-label="Loading Blazam"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(shown)}
          data-testid="loader"
          data-webgl={webgl}
          data-ready={ready}
        >
          <motion.div
            initial={{ opacity: 0, y: 12, filter: "blur(8px)" }}
            animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
            transition={{ duration: 0.9, ease: "easeOut" }}
            className="font-display text-[clamp(5rem,14vw,9rem)] leading-none text-[var(--c-ink)]"
          >
            B<span className="text-[var(--c-lime)]">.</span>
          </motion.div>
          <div className="mt-10 w-48">
            <div className="h-px w-full overflow-hidden bg-[color-mix(in_oklab,var(--c-glow-soft)_14%,transparent)]">
              <div className="h-full bg-[var(--c-glow)] transition-none" style={{ width: `${shown}%`, boxShadow: "0 0 12px var(--c-glow)" }} />
            </div>
            <div className="mt-3 flex justify-between font-mono text-[11px] tracking-[0.2em] text-[var(--c-ink-muted)] uppercase">
              <span>Tuning in</span>
              <span className="tabular-nums">{String(Math.round(shown)).padStart(3, "0")}</span>
            </div>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
