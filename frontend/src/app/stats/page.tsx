"use client";

import { motion } from "framer-motion";
import { useState } from "react";
import { useAsync } from "@/hooks/useAsync";
import { getStats } from "@/lib/api";
import { compact, formatMs } from "@/lib/format";
import type { Stats } from "@/lib/schemas";
import { chartColors } from "@/lib/theme";
import { EmptyState, PageShell } from "@/ui/PageShell";

type Slice = { key: "own" | "external" | "noMatch"; label: string; value: number; color: string };

function slicesOf(s: Stats): Slice[] {
  return [
    { key: "own", label: "Own engine", value: s.own_count, color: chartColors.own },
    { key: "external", label: "External API", value: s.external_count, color: chartColors.external },
    { key: "noMatch", label: "No match", value: s.no_match_count, color: chartColors.noMatch },
  ];
}

function arcPath(cx: number, cy: number, r0: number, r1: number, a0: number, a1: number) {
  const p = (r: number, a: number) => [cx + r * Math.sin(a), cy - r * Math.cos(a)];
  const large = a1 - a0 > Math.PI ? 1 : 0;
  const [x0, y0] = p(r1, a0);
  const [x1, y1] = p(r1, a1);
  const [x2, y2] = p(r0, a1);
  const [x3, y3] = p(r0, a0);
  return `M${x0} ${y0} A${r1} ${r1} 0 ${large} 1 ${x1} ${y1} L${x2} ${y2} A${r0} ${r0} 0 ${large} 0 ${x3} ${y3} Z`;
}

function Donut({ slices }: { slices: Slice[] }) {
  const [hover, setHover] = useState<Slice["key"] | null>(null);
  const total = slices.reduce((a, s) => a + s.value, 0);
  const visible = slices.filter((s) => s.value > 0);
  // 2px surface gap between segments, expressed as an angle at the outer radius
  const gap = visible.length > 1 ? 2 / 96 : 0;
  const arcs = visible.map((s, i) => {
    const start = (visible.slice(0, i).reduce((acc, v) => acc + v.value, 0) / total) * Math.PI * 2;
    const span = (s.value / total) * Math.PI * 2;
    return { ...s, a0: start + gap / 2, a1: start + span - gap / 2 };
  });
  const active = slices.find((s) => s.key === hover);
  const headline = active ?? slices[0];
  return (
    <div className="flex flex-col items-center gap-6 sm:flex-row sm:items-center sm:gap-10">
      <div className="relative h-[220px] w-[220px] shrink-0">
        <svg viewBox="0 0 200 200" className="h-full w-full" role="img" aria-label={slices.map((s) => `${s.label} ${s.value}`).join(", ")}>
          {arcs.length === 1 ? (
            <circle cx="100" cy="100" r="81" fill="none" stroke={arcs[0].color} strokeWidth="30" />
          ) : (
            arcs.map((s) => (
              <motion.path
                key={s.key}
                d={arcPath(100, 100, 66, 96, s.a0, s.a1)}
                fill={s.color}
                initial={{ opacity: 0, scale: 0.9 }}
                animate={{ opacity: hover && hover !== s.key ? 0.35 : 1, scale: 1 }}
                style={{ transformOrigin: "100px 100px" }}
                transition={{ duration: 0.5 }}
                onMouseEnter={() => setHover(s.key)}
                onMouseLeave={() => setHover(null)}
                data-testid={`donut-${s.key}`}
              />
            ))
          )}
        </svg>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center text-center">
          <span className="font-display text-4xl text-[var(--c-ink)] tabular-nums">{total ? Math.round((headline.value / total) * 100) : 0}%</span>
          <span className="mt-1 max-w-[110px] text-[11.5px] leading-tight text-[var(--c-ink-muted)]">{headline.label}</span>
        </div>
      </div>
      <ul className="w-full space-y-2" aria-label="Legend">
        {slices.map((s) => (
          <li
            key={s.key}
            onMouseEnter={() => setHover(s.key)}
            onMouseLeave={() => setHover(null)}
            className={`flex items-center gap-3 rounded-xl px-3 py-2 transition ${hover === s.key ? "bg-white/5" : ""}`}
          >
            <span className="h-3 w-3 shrink-0 rounded-[4px]" style={{ background: s.color }} aria-hidden />
            <span className="flex-1 text-[14px] text-[var(--c-ink)]">{s.label}</span>
            <span className="font-mono text-[13px] text-[var(--c-ink)] tabular-nums">{s.value}</span>
            <span className="w-12 text-right font-mono text-[12px] text-[var(--c-ink-muted)] tabular-nums">{total ? `${Math.round((s.value / total) * 100)}%` : "–"}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Average latency per tier on one ms axis, with the < 1 s product target marked. */
function LatencyBars({ stats }: { stats: Stats }) {
  const rows = [
    { key: "own", label: "Own engine", ms: stats.avg_latency_own_ms, color: chartColors.own },
    { key: "external", label: "External API", ms: stats.avg_latency_external_ms, color: chartColors.external },
  ];
  const max = Math.max(1000, ...rows.map((r) => r.ms ?? 0)) * 1.1;
  const [hover, setHover] = useState<string | null>(null);
  const target = (1000 / max) * 100;
  return (
    <div className="grid grid-cols-[6.75rem_1fr_4rem] items-center gap-x-3 gap-y-5">
      <span />
      <div className="relative h-3" aria-hidden>
        <span className="absolute -translate-x-1/2 font-mono text-[10px] whitespace-nowrap text-[var(--c-ink-muted)]" style={{ left: `${target}%` }}>
          1 s target
        </span>
      </div>
      <span />
      {rows.map((r) => (
        <div key={r.key} className="contents">
          <span className="text-[13px] text-[var(--c-ink-muted)]">{r.label}</span>
          <div className="relative h-6 border-l border-[var(--hairline-strong)]" onMouseEnter={() => setHover(r.key)} onMouseLeave={() => setHover(null)}>
            {r.ms != null ? (
              <motion.div
                className="absolute top-0 left-0 h-6 rounded-r-[4px]"
                style={{ background: r.color, opacity: hover && hover !== r.key ? 0.4 : 1 }}
                initial={{ width: 0 }}
                animate={{ width: `${(r.ms / max) * 100}%` }}
                transition={{ duration: 1, ease: [0.22, 1, 0.36, 1] }}
                title={`${r.label}: ${formatMs(r.ms)} average`}
              />
            ) : (
              <span className="absolute inset-y-0 left-2 flex items-center text-[12px] text-[var(--c-ink-faint)]">no data yet</span>
            )}
            <span className="absolute -top-2 -bottom-2 w-px bg-[var(--c-ink-faint)]" style={{ left: `${target}%` }} aria-hidden />
          </div>
          <span className="text-right font-mono text-[13px] text-[var(--c-ink)] tabular-nums">{formatMs(r.ms)}</span>
        </div>
      ))}
      <span />
      <div className="flex justify-between font-mono text-[10px] text-[var(--c-ink-faint)]" aria-hidden>
        <span>0</span>
        <span>{formatMs(max)}</span>
      </div>
      <span />
    </div>
  );
}

function Tile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="glass-strong panel">
      <p className="text-[12.5px] text-[var(--c-ink-muted)]">{label}</p>
      <p className="font-display mt-2 text-[clamp(2.2rem,4vw,3.4rem)] leading-none text-[var(--c-ink)] tabular-nums">{value}</p>
      {hint && <p className="mt-2 text-[12px] text-[var(--c-ink-faint)]">{hint}</p>}
    </div>
  );
}

export default function StatsPage() {
  const { data, error, loading, reload } = useAsync((signal) => getStats(signal), []);
  const [table, setTable] = useState(false);

  const total = data ? data.own_count + data.external_count + data.no_match_count : 0;
  const matched = data ? data.own_count + data.external_count : 0;

  return (
    <PageShell
      kicker="Stats"
      title={
        <>
          Two tiers, <em className="hero-accent">one answer</em>
        </>
      }
    >
      {error ? (
        <EmptyState
          title="Can’t load the stats"
          body="The Blazam server didn’t answer. Make sure it’s running, then try again."
          action={
            <button type="button" className="btn-lime focus-ring" onClick={reload}>
              Retry
            </button>
          }
        />
      ) : loading || !data ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4" aria-busy>
          {Array.from({ length: 4 }, (_, i) => (
            <div key={i} className="skeleton h-36 rounded-[26px]" />
          ))}
        </div>
      ) : (
        <div className="space-y-4" data-testid="stats">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Tile label="Songs in the library" value={compact(data.total_songs)} hint={`${compact(data.total_hashes)} fingerprint hashes`} />
            <Tile label="Recognitions" value={String(total)} hint={`${matched} matched`} />
            <Tile label="Answered by own engine" value={matched ? `${Math.round((data.own_count / matched) * 100)}%` : "–"} hint="of all matches, offline" />
            <Tile label="Own engine speed" value={formatMs(data.avg_latency_own_ms)} hint="average, end to end" />
          </div>

          <div className="grid gap-4 lg:grid-cols-5">
            <section className="glass-strong panel lg:col-span-3" aria-labelledby="split-h">
              <div className="mb-6 flex items-start justify-between gap-4">
                <div>
                  <h2 id="split-h" className="font-display text-2xl text-[var(--c-ink)]">
                    Who answered
                  </h2>
                  <p className="mt-1 text-[13px] text-[var(--c-ink-muted)]">Every recognition, by the tier that settled it.</p>
                </div>
                <button type="button" className="btn-ghost focus-ring !h-8 shrink-0 !px-3 text-[12px]" aria-pressed={table} onClick={() => setTable((t) => !t)}>
                  {table ? "Chart" : "Table"}
                </button>
              </div>
              {table ? (
                <table className="w-full text-left text-[14px]">
                  <thead className="text-[12px] text-[var(--c-ink-muted)]">
                    <tr>
                      <th className="py-2 font-normal">Outcome</th>
                      <th className="py-2 text-right font-normal">Count</th>
                      <th className="py-2 text-right font-normal">Avg latency</th>
                    </tr>
                  </thead>
                  <tbody className="text-[var(--c-ink)]">
                    <tr className="border-t border-[var(--hairline)]">
                      <td className="py-2">Own engine</td>
                      <td className="py-2 text-right tabular-nums">{data.own_count}</td>
                      <td className="py-2 text-right tabular-nums">{formatMs(data.avg_latency_own_ms)}</td>
                    </tr>
                    <tr className="border-t border-[var(--hairline)]">
                      <td className="py-2">External API</td>
                      <td className="py-2 text-right tabular-nums">{data.external_count}</td>
                      <td className="py-2 text-right tabular-nums">{formatMs(data.avg_latency_external_ms)}</td>
                    </tr>
                    <tr className="border-t border-[var(--hairline)]">
                      <td className="py-2">No match</td>
                      <td className="py-2 text-right tabular-nums">{data.no_match_count}</td>
                      <td className="py-2 text-right">–</td>
                    </tr>
                  </tbody>
                </table>
              ) : total ? (
                <Donut slices={slicesOf(data)} />
              ) : (
                <p className="py-10 text-center text-[14px] text-[var(--c-ink-muted)]">No recognitions yet. Tap the coin to make some.</p>
              )}
            </section>

            <section className="glass-strong panel lg:col-span-2" aria-labelledby="lat-h">
              <h2 id="lat-h" className="font-display text-2xl text-[var(--c-ink)]">
                Speed per tier
              </h2>
              <p className="mt-1 mb-9 text-[13px] text-[var(--c-ink-muted)]">Average time from upload to answer.</p>
              <LatencyBars stats={data} />
            </section>
          </div>

          <section className="glass-strong panel" aria-labelledby="flow-h">
            <h2 id="flow-h" className="font-display text-2xl text-[var(--c-ink)]">
              How a recognition flows
            </h2>
            <ol className="mt-6 grid gap-3 md:grid-cols-3">
              {[
                { n: "Tier 1", t: "Own engine", d: "Landmark fingerprints matched offline against the in-memory index.", v: `${data.own_count} answered`, c: chartColors.own },
                { n: "Tier 2", t: "External API", d: "Only when Tier 1 is unsure. Auto-learn indexes the song so next time Tier 1 answers.", v: `${data.external_count} answered`, c: chartColors.external },
                { n: "Else", t: "No match", d: "Neither tier was confident. Nothing is guessed.", v: `${data.no_match_count} times`, c: chartColors.noMatch },
              ].map((s, i) => (
                <li key={s.n} className="stat-chip relative !p-4">
                  <p className="flex items-center gap-2 font-mono text-[11px] tracking-wider text-[var(--c-ink-muted)] uppercase">
                    <span className="h-2 w-2 rounded-full" style={{ background: s.c }} aria-hidden />
                    {s.n}
                  </p>
                  <p className="mt-2 text-[16px] text-[var(--c-ink)]">{s.t}</p>
                  <p className="mt-1 text-[13px] leading-relaxed text-[var(--c-ink-muted)]">{s.d}</p>
                  <p className="mt-3 font-mono text-[12px] text-[var(--c-ink)]">{s.v}</p>
                  {i < 2 && (
                    <span className="absolute top-1/2 -right-3 z-10 hidden -translate-y-1/2 text-[var(--c-ink-faint)] md:block" aria-hidden>
                      →
                    </span>
                  )}
                </li>
              ))}
            </ol>
          </section>
        </div>
      )}
    </PageShell>
  );
}
