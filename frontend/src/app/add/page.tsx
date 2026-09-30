"use client";

import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useRef, useState, type DragEvent, type FormEvent } from "react";
import { ApiError, followJob, searchDeezer, startImport, startUpload } from "@/lib/api";
import type { DeezerHit, Job } from "@/lib/schemas";
import { PageShell } from "@/ui/PageShell";

const AUDIO_EXT = /\.(wav|flac|ogg|oga|opus|mp3|webm|m4a|mp4|aac|aiff?)$/i;

function errorText(e: unknown) {
  if (e instanceof ApiError) {
    if (e.kind === "offline" || e.kind === "timeout") return "Can’t reach the Blazam server. Is it running?";
    if (e.kind === "too_large") return "That file is too large for the server.";
    return e.message;
  }
  return "Something went wrong.";
}

/** Live job progress from the SSE stream. */
function JobProgress({ jobId, label, onDone }: { jobId: string; label: string; onDone?: (job: Job) => void }) {
  const [job, setJob] = useState<Job | null>(null);
  const done = useRef(onDone);
  useEffect(() => {
    done.current = onDone;
  }, [onDone]);
  useEffect(
    () =>
      followJob(jobId, (j) => {
        setJob(j);
        if (j.status === "done" || j.status === "failed") done.current?.(j);
      }),
    [jobId],
  );
  const pct = job && job.total > 0 ? Math.round((job.done / job.total) * 100) : 0;
  const finished = job?.status === "done" || job?.status === "failed";
  const result = job?.result as { indexed?: number; skipped_existing?: number; failed?: number } | undefined;
  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="stat-chip" data-testid="job" data-status={job?.status ?? "queued"}>
      <div className="flex items-baseline justify-between gap-3 text-[13px]">
        <span className="truncate text-[var(--c-ink)]">{label}</span>
        <span className="shrink-0 font-mono text-[11px] text-[var(--c-ink-muted)] tabular-nums">
          {job ? (job.total ? `${job.done}/${job.total}` : job.status) : "queued"}
        </span>
      </div>
      <div className="progress-track mt-2.5" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct} aria-label={`${label} progress`}>
        <div className="progress-fill" style={{ width: `${finished ? 100 : Math.max(pct, 4)}%` }} />
      </div>
      <p className="mt-2 truncate text-[12px] text-[var(--c-ink-muted)]" aria-live="polite">
        {!job
          ? "Connecting to the job stream…"
          : job.status === "failed"
            ? `Failed: ${job.errors.at(-1) ?? "unknown error"}`
            : finished && job.total === 0
              ? "Nothing found on Deezer for this request."
              : finished
              ? `Done: ${result?.indexed ?? 0} indexed, ${result?.skipped_existing ?? 0} already known${result?.failed ? `, ${result.failed} failed` : ""}`
              : job.current_title
                ? `Fingerprinting ${job.current_title}`
                : "Starting…"}
      </p>
      {finished && job && job.errors.length > 0 && job.status !== "failed" && (
        <details className="mt-1 text-[11.5px] text-[var(--c-ink-faint)]">
          <summary className="cursor-pointer">{job.errors.length} skipped</summary>
          <ul className="mt-1 space-y-0.5">
            {job.errors.slice(0, 8).map((e, i) => (
              <li key={i} className="truncate">
                {e}
              </li>
            ))}
          </ul>
        </details>
      )}
    </motion.div>
  );
}

type JobEntry = { id: string; label: string };

function SearchPanel() {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<DeezerHit[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [jobs, setJobs] = useState<JobEntry[]>([]);
  const [imported, setImported] = useState<Set<number>>(new Set());

  const search = async (e: FormEvent) => {
    e.preventDefault();
    if (q.trim().length < 2) return;
    setBusy(true);
    setErr(null);
    try {
      setHits((await searchDeezer(q.trim())).items);
    } catch {
      setErr("Deezer search is unavailable right now.");
    } finally {
      setBusy(false);
    }
  };

  const importHit = async (h: DeezerHit) => {
    setErr(null);
    try {
      // the backend imports the top hit of a Deezer search; a plain "artist title" query pins the
      // clicked track (Deezer's artist:"" track:"" syntax returned nothing when tested)
      const { job_id } = await startImport({ source: "deezer", query: `${h.artist} ${h.title}`, limit: 1 });
      setImported((s) => new Set(s).add(h.id));
      setJobs((j) => [{ id: job_id, label: `${h.artist} – ${h.title}` }, ...j]);
    } catch (e) {
      setErr(errorText(e));
    }
  };

  return (
    <section className="glass-strong panel flex flex-col" aria-labelledby="search-h">
      <p className="kicker">01</p>
      <h2 id="search-h" className="font-display mt-2 text-3xl text-[var(--c-ink)]">
        Search Deezer
      </h2>
      <p className="mt-1 text-[14px] text-[var(--c-ink-muted)]">Find a track, click to fingerprint it into the library.</p>
      <form onSubmit={search} className="mt-5 flex gap-2" role="search">
        <label htmlFor="dz-q" className="sr-only">
          Search Deezer
        </label>
        <input id="dz-q" className="input" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Artist or title" data-testid="deezer-query" />
        <button type="submit" className="btn-lime focus-ring !h-12 shrink-0" disabled={busy || q.trim().length < 2}>
          {busy ? "…" : "Search"}
        </button>
      </form>
      {err && (
        <p className="mt-3 text-[13px] text-[var(--c-danger)]" role="alert">
          {err}
        </p>
      )}
      {jobs.length > 0 && (
        <div className="mt-4 space-y-2">
          {jobs.map((j) => (
            <JobProgress key={j.id} jobId={j.id} label={j.label} />
          ))}
        </div>
      )}
      <ul className="scroll-soft mt-4 max-h-[340px] space-y-1.5 overflow-y-auto pr-1" data-testid="deezer-results">
        {hits?.length === 0 && <li className="text-[13px] text-[var(--c-ink-muted)]">No results on Deezer.</li>}
        {hits?.map((h) => (
          <li key={h.id}>
            <button
              type="button"
              onClick={() => importHit(h)}
              disabled={imported.has(h.id)}
              className="focus-ring flex w-full items-center gap-3 rounded-xl p-1.5 text-left transition hover:bg-white/5 disabled:opacity-60"
            >
              {/* eslint-disable-next-line @next/next/no-img-element -- Deezer CDN thumbnail */}
              {h.cover ? <img src={h.cover} alt="" className="h-11 w-11 rounded-lg object-cover" loading="lazy" /> : <span className="h-11 w-11 rounded-lg bg-white/5" />}
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[14px] text-[var(--c-ink)]">{h.title}</span>
                <span className="block truncate text-[12px] text-[var(--c-ink-muted)]">{h.artist}</span>
              </span>
              <span className={`badge ${imported.has(h.id) ? "badge--own" : "badge--none"}`}>{imported.has(h.id) ? "Queued" : "Import"}</span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

const SEED_COUNTS = [10, 25, 50, 100] as const;

function SeedPanel() {
  const [count, setCount] = useState<(typeof SEED_COUNTS)[number]>(25);
  const [job, setJob] = useState<JobEntry | null>(null);
  const [running, setRunning] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const seed = async () => {
    setErr(null);
    try {
      const { job_id } = await startImport({ source: "deezer", chart: true, limit: count });
      setJob({ id: job_id, label: `Deezer chart · top ${count}` });
      setRunning(true);
    } catch (e) {
      setErr(errorText(e));
    }
  };

  return (
    <section className="glass-strong panel flex flex-col" aria-labelledby="seed-h">
      <p className="kicker">02</p>
      <h2 id="seed-h" className="font-display mt-2 text-3xl text-[var(--c-ink)]">
        Seed library
      </h2>
      <p className="mt-1 text-[14px] text-[var(--c-ink-muted)]">Pull the current Deezer chart. Songs already indexed are skipped.</p>
      <fieldset className="mt-5">
        <legend className="mb-2 text-[12px] text-[var(--c-ink-muted)]">How many tracks</legend>
        <div className="grid grid-cols-4 gap-1.5 rounded-[14px] border border-[var(--hairline)] p-1">
          {SEED_COUNTS.map((n) => (
            <label key={n} className={`focus-within:outline-2 focus-within:outline-[var(--c-lime)] cursor-pointer rounded-[10px] py-2.5 text-center text-[14px] transition ${count === n ? "bg-[var(--c-lime)] font-semibold text-[var(--c-bg-deep)]" : "text-[var(--c-ink-muted)] hover:text-[var(--c-ink)]"}`}>
              <input type="radio" name="seed-count" value={n} checked={count === n} onChange={() => setCount(n)} className="sr-only" />
              {n}
            </label>
          ))}
        </div>
      </fieldset>
      <button type="button" onClick={seed} disabled={running} className="btn-lime focus-ring mt-5 justify-center" data-testid="seed-start">
        {running ? "Seeding…" : `Seed ${count} chart tracks`}
      </button>
      {err && (
        <p className="mt-3 text-[13px] text-[var(--c-danger)]" role="alert">
          {err}
        </p>
      )}
      <div className="mt-4">{job && <JobProgress key={job.id} jobId={job.id} label={job.label} onDone={() => setRunning(false)} />}</div>
    </section>
  );
}

function UploadPanel() {
  const [over, setOver] = useState(false);
  const [jobs, setJobs] = useState<JobEntry[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  const upload = async (list: FileList | File[]) => {
    const files = Array.from(list).filter((f) => AUDIO_EXT.test(f.name));
    setErr(null);
    if (!files.length) {
      setErr("Drop audio files: mp3, m4a, wav, flac, ogg, opus or webm.");
      return;
    }
    try {
      const { job_id } = await startUpload(files);
      setJobs((j) => [{ id: job_id, label: files.length === 1 ? files[0].name : `${files.length} files` }, ...j]);
    } catch (e) {
      setErr(errorText(e));
    }
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setOver(false);
    void upload(e.dataTransfer.files);
  };

  return (
    <section className="glass-strong panel flex flex-col" aria-labelledby="up-h">
      <p className="kicker">03</p>
      <h2 id="up-h" className="font-display mt-2 text-3xl text-[var(--c-ink)]">
        Upload files
      </h2>
      <p className="mt-1 text-[14px] text-[var(--c-ink-muted)]">
        Name them <span className="text-[var(--c-ink)]">Artist - Title.mp3</span>, or let the tags speak.
      </p>
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={onDrop}
        className={`dropzone mt-5 flex flex-1 flex-col items-center justify-center gap-3 px-4 py-10 text-center ${over ? "is-over" : ""}`}
        data-testid="dropzone"
      >
        <svg viewBox="0 0 24 24" width="30" height="30" fill="none" stroke="currentColor" strokeWidth="1.4" className="text-[var(--c-glow)]" aria-hidden>
          <path d="M12 15V4M7.5 8.5 12 4l4.5 4.5M5 15v3.5A1.5 1.5 0 0 0 6.5 20h11a1.5 1.5 0 0 0 1.5-1.5V15" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        <p className="text-[14px] text-[var(--c-ink)]">Drop audio here</p>
        <button type="button" className="btn-ghost focus-ring !h-9 text-[13px]" onClick={() => input.current?.click()}>
          or browse
        </button>
        <input
          ref={input}
          type="file"
          accept="audio/*,.opus,.flac,.m4a,.webm"
          multiple
          className="sr-only"
          aria-label="Choose audio files to upload"
          data-testid="upload-input"
          onChange={(e) => {
            if (e.target.files) void upload(e.target.files);
            e.target.value = "";
          }}
        />
      </div>
      {err && (
        <p className="mt-3 text-[13px] text-[var(--c-danger)]" role="alert">
          {err}
        </p>
      )}
      <div className="mt-4 space-y-2">
        <AnimatePresence>
          {jobs.map((j) => (
            <JobProgress key={j.id} jobId={j.id} label={j.label} />
          ))}
        </AnimatePresence>
      </div>
    </section>
  );
}

export default function AddPage() {
  return (
    <PageShell
      kicker="Grow the library"
      title={
        <>
          Teach it <em className="hero-accent">new songs</em>
        </>
      }
    >
      <div className="grid gap-4 lg:grid-cols-3">
        <SearchPanel />
        <SeedPanel />
        <UploadPanel />
      </div>
    </PageShell>
  );
}
