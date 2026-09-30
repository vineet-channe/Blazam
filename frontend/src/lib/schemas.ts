import { z } from "zod";

/**
 * Zod schemas mirroring ../backend/README.md ("HTTP API" + contract notes). Unknown extra
 * keys are allowed (z.object strips them) so backend additions never break the UI.
 */

export const LyricsSchema = z.object({
  plain: z.string().nullish(),
  synced: z.string().nullish(),
});

export const SongSchema = z.object({
  /** null for an external match until auto-learn has indexed it. Never use as a required key. */
  id: z.number().int().nullable(),
  title: z.string(),
  artist: z.string().nullish(),
  album: z.string().nullish(),
  year: z.number().int().nullish(),
  cover_url: z.string().nullish(),
  deezer_id: z.number().nullish(),
  mbid: z.string().nullish(),
  preview_url: z.string().nullish(),
  lyrics: LyricsSchema.nullish(),
});

export const SourceSchema = z.enum(["own", "external"]);

export const RecognizeResponseSchema = z.object({
  status: z.enum(["match", "no_match"]),
  source: SourceSchema.nullable(),
  /** number for own, null for external (AudD has none), 0 for no_match */
  confidence: z.number().nullable(),
  score: z.number(),
  offset_seconds: z.number().nullable(),
  latency_ms: z.number(),
  learned: z.boolean(),
  song: SongSchema.nullable(),
});

export const LibrarySongSchema = SongSchema.extend({
  source: z.string().nullish(),
  n_hashes: z.number().nullish(),
  has_lyrics: z.boolean().nullish(),
});

export const LibraryResponseSchema = z.object({
  items: z.array(LibrarySongSchema),
  total: z.number(),
  page: z.number(),
  page_size: z.number(),
});

export const JobIdSchema = z.object({ job_id: z.string() });

export const JobSchema = z.object({
  job_id: z.string(),
  kind: z.string(),
  status: z.enum(["queued", "running", "done", "failed"]),
  done: z.number(),
  total: z.number(),
  current_title: z.string().nullable(),
  errors: z.array(z.string()),
  created_at: z.number().optional(),
  finished_at: z.number().nullish(),
  result: z.record(z.string(), z.unknown()),
});

export const HistoryItemSchema = z.object({
  id: z.number(),
  created_at: z.number(),
  status: z.enum(["match", "no_match"]),
  source: SourceSchema.nullable(),
  song_id: z.number().nullable(),
  confidence: z.number().nullable(),
  score: z.number().nullish(),
  offset_seconds: z.number().nullable(),
  latency_ms: z.number(),
  learned: z.boolean(),
  song: SongSchema.nullable(),
});

export const HistoryResponseSchema = z.object({ items: z.array(HistoryItemSchema) });

export const StatsSchema = z.object({
  total_songs: z.number(),
  total_hashes: z.number(),
  own_count: z.number(),
  external_count: z.number(),
  no_match_count: z.number(),
  avg_latency_own_ms: z.number().nullable(),
  avg_latency_external_ms: z.number().nullable(),
});

export const HealthSchema = z.object({
  status: z.string(),
  version: z.string().optional(),
  index_loaded: z.boolean().optional(),
  songs_indexed: z.number().optional(),
  hashes_indexed: z.number().optional(),
  external_recognizer: z.string().optional(),
  auto_learn: z.boolean().optional(),
});

/** Our own /api/deezer/search proxy (the backend has no search-only endpoint). */
export const DeezerHitSchema = z.object({
  id: z.number(),
  title: z.string(),
  artist: z.string(),
  album: z.string().nullish(),
  cover: z.string().nullish(),
  duration: z.number().nullish(),
});
export const DeezerSearchSchema = z.object({ items: z.array(DeezerHitSchema) });

export type Song = z.infer<typeof SongSchema>;
export type RecognizeResponse = z.infer<typeof RecognizeResponseSchema>;
export type LibrarySong = z.infer<typeof LibrarySongSchema>;
export type LibraryResponse = z.infer<typeof LibraryResponseSchema>;
export type Job = z.infer<typeof JobSchema>;
export type HistoryItem = z.infer<typeof HistoryItemSchema>;
export type Stats = z.infer<typeof StatsSchema>;
export type Health = z.infer<typeof HealthSchema>;
export type DeezerHit = z.infer<typeof DeezerHitSchema>;
