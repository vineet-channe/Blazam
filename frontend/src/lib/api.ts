import type { z } from "zod";
import {
  DeezerSearchSchema,
  HealthSchema,
  HistoryResponseSchema,
  JobIdSchema,
  JobSchema,
  LibraryResponseSchema,
  RecognizeResponseSchema,
  StatsSchema,
  type Job,
} from "./schemas";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

export type ApiErrorKind = "offline" | "timeout" | "bad_audio" | "too_large" | "not_found" | "server" | "invalid";

export class ApiError extends Error {
  constructor(
    public readonly kind: ApiErrorKind,
    message: string,
    public readonly status?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type RequestOpts = { timeoutMs?: number; signal?: AbortSignal; init?: RequestInit };

async function request<S extends z.ZodType>(url: string, schema: S, opts: RequestOpts = {}): Promise<z.infer<S>> {
  const { timeoutMs = 15_000, signal, init } = opts;
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(new DOMException("timeout", "TimeoutError")), timeoutMs);
  const onAbort = () => ctrl.abort(signal?.reason);
  signal?.addEventListener("abort", onAbort, { once: true });
  let res: Response;
  try {
    res = await fetch(url, { ...init, signal: ctrl.signal });
  } catch (e) {
    if (ctrl.signal.reason instanceof DOMException && ctrl.signal.reason.name === "TimeoutError") {
      throw new ApiError("timeout", "The server took too long to answer.");
    }
    if (signal?.aborted) throw e;
    throw new ApiError("offline", "Can't reach the Blazam server.");
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", onAbort);
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body: unknown = await res.json();
      if (body && typeof body === "object" && "detail" in body) detail = String(body.detail);
    } catch {
      /* body was not JSON */
    }
    const kind: ApiErrorKind =
      res.status === 400 || res.status === 422 ? "bad_audio" : res.status === 413 ? "too_large" : res.status === 404 ? "not_found" : "server";
    throw new ApiError(kind, detail, res.status);
  }
  const parsed = schema.safeParse(await res.json());
  if (!parsed.success) throw new ApiError("invalid", "Unexpected response from the server.");
  return parsed.data;
}

const api = (path: string) => `${API_URL}${path}`;

export function recognize(blob: Blob, filename: string, signal?: AbortSignal) {
  const body = new FormData();
  body.append("audio", blob, filename);
  return request(api("/api/recognize"), RecognizeResponseSchema, { timeoutMs: 30_000, signal, init: { method: "POST", body } });
}

export function getHealth(signal?: AbortSignal) {
  return request(api("/api/health"), HealthSchema, { timeoutMs: 8_000, signal });
}

export function getLibrary(params: { q?: string; page?: number; pageSize?: number }, signal?: AbortSignal) {
  const qs = new URLSearchParams({ q: params.q ?? "", page: String(params.page ?? 1), page_size: String(params.pageSize ?? 48) });
  return request(api(`/api/library?${qs}`), LibraryResponseSchema, { signal });
}

export type ImportBody = { source: "deezer"; limit: number } & (
  | { query: string }
  | { chart: true }
  | { playlist_id: string }
  | { artist_id: string }
);

export function startImport(body: ImportBody) {
  return request(api("/api/library/import"), JobIdSchema, {
    init: { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) },
  });
}

export function startUpload(files: File[]) {
  const body = new FormData();
  for (const f of files) body.append("files", f, f.name);
  return request(api("/api/library/upload"), JobIdSchema, { timeoutMs: 120_000, init: { method: "POST", body } });
}

export function getJob(id: string) {
  return request(api(`/api/jobs/${encodeURIComponent(id)}`), JobSchema);
}

export function getHistory(limit = 100, signal?: AbortSignal) {
  return request(api(`/api/history?limit=${limit}`), HistoryResponseSchema, { signal });
}

export function getStats(signal?: AbortSignal) {
  return request(api("/api/stats"), StatsSchema, { signal });
}

export function searchDeezer(q: string, signal?: AbortSignal) {
  return request(`/api/deezer/search?q=${encodeURIComponent(q)}`, DeezerSearchSchema, { signal });
}

/**
 * Follow a job over SSE (`event: progress` frames, then `event: end`).
 * Falls back to polling if the stream errors before the job ends.
 */
export function followJob(id: string, onUpdate: (job: Job) => void): () => void {
  let closed = false;
  let pollTimer: ReturnType<typeof setTimeout> | undefined;
  const es = new EventSource(api(`/api/jobs/${encodeURIComponent(id)}/stream`));

  const handle = (ev: MessageEvent<string>) => {
    const parsed = JobSchema.safeParse(JSON.parse(ev.data));
    if (parsed.success) onUpdate(parsed.data);
  };
  es.addEventListener("progress", handle as EventListener);
  es.addEventListener("end", ((ev: MessageEvent<string>) => {
    handle(ev);
    es.close();
    closed = true;
  }) as EventListener);

  const poll = async () => {
    if (closed) return;
    try {
      const job = await getJob(id);
      onUpdate(job);
      if (job.status === "done" || job.status === "failed") return;
    } catch {
      /* keep polling; the panel shows the last known state */
    }
    pollTimer = setTimeout(poll, 1000);
  };
  es.onerror = () => {
    if (closed) return;
    es.close();
    void poll();
  };

  return () => {
    closed = true;
    es.close();
    clearTimeout(pollTimer);
  };
}
