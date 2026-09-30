"use client";

import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useState } from "react";
import { RECORD_MS, dismiss, toggleListen } from "@/lib/controller";
import { live } from "@/lib/live";
import { useBlazam, type ErrorKind, type Phase } from "@/lib/store";
import { ResultCard } from "./ResultCard";

const ERRORS: Record<ErrorKind, { title: string; body: string }> = {
  mic_denied: {
    title: "Blazam can’t hear you",
    body: "Microphone access is blocked. Click the lock or tune icon in the address bar, set Microphone to Allow, then try again.",
  },
  mic_unavailable: {
    title: "No microphone found",
    body: "Connect or enable a microphone, and check your system privacy settings allow this browser to use it.",
  },
  mic_unsupported: {
    title: "This browser can’t record here",
    body: "Recording needs a recent Chrome, Edge, Firefox or Safari, on https or localhost.",
  },
  offline: {
    title: "The Blazam server is offline",
    body: "We couldn’t reach the recognizer. Make sure the backend is running on port 8000, then try again.",
  },
  timeout: {
    title: "That took too long",
    body: "The recognizer didn’t answer in 30 seconds. Check your connection and give it another go.",
  },
  bad_audio: {
    title: "That recording didn’t come through",
    body: "The clip was empty or unreadable. Try again and let it run for a few seconds.",
  },
  server: {
    title: "Something went wrong on our side",
    body: "The recognizer hit a snag. Try again in a moment.",
  },
};

function useCountdown(phase: Phase) {
  const [left, setLeft] = useState(Math.ceil(RECORD_MS / 1000));
  useEffect(() => {
    if (phase !== "listening") return;
    const id = setInterval(() => setLeft(Math.max(0, Math.ceil((RECORD_MS * (1 - live.recordProgress)) / 1000))), 200);
    return () => clearInterval(id);
  }, [phase]);
  return phase === "listening" ? left : Math.ceil(RECORD_MS / 1000);
}

/** "prompt" until the user has answered the browser's mic permission question. */
function useMicPermission() {
  const [state, setState] = useState<PermissionState | "unknown">("unknown");
  useEffect(() => {
    let status: PermissionStatus | undefined;
    const update = () => status && setState(status.state);
    navigator.permissions
      ?.query({ name: "microphone" as PermissionName })
      .then((s) => {
        status = s;
        update();
        s.addEventListener("change", update);
      })
      .catch(() => undefined);
    return () => status?.removeEventListener("change", update);
  }, []);
  return state;
}

function Announcer() {
  const phase = useBlazam((s) => s.phase);
  const result = useBlazam((s) => s.result);
  const error = useBlazam((s) => s.error);
  const text =
    phase === "listening"
      ? "Listening. Press Space again to stop early."
      : phase === "processing"
        ? "Identifying the song."
        : phase === "reveal" && result?.song
          ? `Found ${result.song.title}${result.song.artist ? ` by ${result.song.artist}` : ""}, recognized by ${result.source === "own" ? "Blazam’s own engine" : "the external API"}.`
          : phase === "no_match"
            ? "Couldn’t catch that. Try again closer to the source."
            : phase === "error" && error
              ? `${ERRORS[error].title}. ${ERRORS[error].body}`
              : "";
  return (
    <div className="sr-only" aria-live="assertive" aria-atomic="true" data-testid="announcer">
      {text}
    </div>
  );
}

export function HomeStage() {
  const phase = useBlazam((s) => s.phase);
  const result = useBlazam((s) => s.result);
  const error = useBlazam((s) => s.error);
  const introStarted = useBlazam((s) => s.introStarted);
  const backend = useBlazam((s) => s.backend);
  const left = useCountdown(phase);
  const mic = useMicPermission();

  // Space / Enter trigger from anywhere on the home page, unless a control has focus
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // the lyrics drawer handles its own Escape
      if (useBlazam.getState().lyricsOpen) return;
      if (e.key === "Escape") return dismiss();
      if (e.key !== " " && e.key !== "Enter") return;
      if (e.repeat) return;
      const el = e.target as HTMLElement | null;
      if (el && el !== document.body && el.closest("button, a, input, textarea, select, [role=dialog], [contenteditable]")) return;
      e.preventDefault();
      toggleListen();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const heroVisible = introStarted && (phase === "idle" || phase === "listening");

  return (
    <div className="pointer-events-none fixed inset-0 z-10">
      <h1 className="sr-only">Blazam, music recognition. Hear it. Blaze it.</h1>
      <Announcer />

      {/* hero type */}
      <AnimatePresence>
        {heroVisible && (
          <motion.div
            key="hero"
            initial={{ opacity: 0, y: 24 }}
            animate={{ opacity: phase === "listening" ? 0.25 : 1, y: 0 }}
            exit={{ opacity: 0, y: -10, transition: { duration: 0.5 } }}
            transition={{ delay: 1.6, duration: 1.4, ease: [0.22, 1, 0.36, 1] }}
            className="hero-type absolute bottom-[8.5rem] left-5 sm:left-10 lg:bottom-[9rem] lg:left-14"
            aria-hidden
          >
            <p className="kicker mb-4">Music recognition · Est. 2026</p>
            <p className="font-display text-[clamp(3rem,8.5vw,8.5rem)] leading-[0.86] tracking-[-0.02em] text-[var(--c-ink)]">
              Hear it.
              <br />
              <em className="hero-accent">Blaze it.</em>
            </p>
          </motion.div>
        )}
      </AnimatePresence>

      {/* status line above the dock */}
      <div className="absolute inset-x-0 bottom-[6.2rem] flex justify-center px-4">
        <AnimatePresence mode="wait">
          {introStarted && (phase === "idle" || phase === "listening" || phase === "processing") && (
            <motion.div
              key={phase}
              initial={{ opacity: 0, y: 8, filter: "blur(6px)" }}
              animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
              exit={{ opacity: 0, y: -6, filter: "blur(6px)" }}
              transition={{ duration: 0.45, delay: phase === "idle" ? 2 : 0 }}
              className="status-line"
              data-testid={`status-${phase}`}
            >
              {phase === "idle" && (
                <>
                  <span>{backend === "down" ? "Server offline, recognition will fail until it’s back" : "Tap the coin to listen"}</span>
                  <kbd>Space</kbd>
                  {mic === "prompt" && backend !== "down" && (
                    <span className="hidden text-[var(--c-ink-muted)] md:inline" data-testid="mic-hint">
                      · your browser will ask for the mic, choose Allow
                    </span>
                  )}
                </>
              )}
              {phase === "listening" && (
                <>
                  <span className="rec-dot" aria-hidden />
                  <span>Listening</span>
                  <span className="tabular-nums text-[var(--c-ink-muted)]">{left}s</span>
                  <span className="hidden text-[var(--c-ink-faint)] sm:inline">· tap to stop early</span>
                </>
              )}
              {phase === "processing" && <span className="shimmer-text">Identifying…</span>}
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* outcomes */}
      <AnimatePresence mode="wait">
        {phase === "reveal" && result && (
          <div key="reveal" className="result-slot">
            <ResultCard result={result} />
          </div>
        )}
        {phase === "no_match" && (
          <OutcomePanel
            key="nomatch"
            testId="no-match"
            kicker="No match"
            title="Couldn’t catch that."
            body="Try again closer to the source."
            hint={result ? `Closest own-engine score: ${result.score}` : undefined}
          />
        )}
        {phase === "error" && error && <OutcomePanel key={`err-${error}`} testId={`error-${error}`} kicker="Hmm" tone="danger" title={ERRORS[error].title} body={ERRORS[error].body} />}
      </AnimatePresence>
    </div>
  );
}

function OutcomePanel({ title, body, hint, kicker, tone, testId }: { title: string; body: string; hint?: string; kicker: string; tone?: "danger"; testId: string }) {
  return (
    <motion.section
      initial={{ opacity: 0, y: 30, filter: "blur(10px)" }}
      animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
      exit={{ opacity: 0, y: 16, filter: "blur(8px)", transition: { duration: 0.3 } }}
      transition={{ delay: 0.35, type: "spring", stiffness: 140, damping: 22 }}
      className="outcome-panel glass-strong pointer-events-auto"
      data-testid={testId}
      role={tone === "danger" ? "alert" : undefined}
    >
      <p className={`kicker ${tone === "danger" ? "text-[var(--c-danger)]" : ""}`}>{kicker}</p>
      <h2 className="font-display mt-2 text-[clamp(1.7rem,3vw,2.4rem)] leading-tight text-[var(--c-ink)]">{title}</h2>
      <p className="mt-2 text-[15px] leading-relaxed text-[var(--c-ink-muted)]">{body}</p>
      {hint && <p className="mt-3 font-mono text-[11px] tracking-wide text-[var(--c-ink-faint)]">{hint}</p>}
      <div className="mt-5 flex gap-2">
        <button type="button" onClick={toggleListen} className="btn-lime focus-ring">
          Try again
        </button>
        <button type="button" onClick={dismiss} className="btn-ghost focus-ring">
          Dismiss
        </button>
      </div>
    </motion.section>
  );
}
