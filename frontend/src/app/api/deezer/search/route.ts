import { z } from "zod";

// The Blazam backend imports by Deezer query but has no search-only endpoint, and Deezer's API
// sends no CORS headers, so the Add page searches through this tiny server-side proxy.

const DeezerTrack = z.object({
  id: z.number(),
  title: z.string(),
  duration: z.number().optional(),
  artist: z.object({ name: z.string() }),
  album: z.object({ title: z.string().optional(), cover_medium: z.string().optional() }).optional(),
});
const DeezerSearch = z.object({ data: z.array(DeezerTrack).default([]) });

export async function GET(request: Request) {
  const q = new URL(request.url).searchParams.get("q")?.trim() ?? "";
  if (q.length < 2) return Response.json({ items: [] });
  try {
    const res = await fetch(`https://api.deezer.com/search?q=${encodeURIComponent(q)}&limit=12`, {
      signal: AbortSignal.timeout(8000),
      next: { revalidate: 600 },
    });
    const parsed = DeezerSearch.safeParse(await res.json());
    if (!res.ok || !parsed.success) return Response.json({ items: [] }, { status: 502 });
    const items = parsed.data.data.map((t) => ({
      id: t.id,
      title: t.title,
      artist: t.artist.name,
      album: t.album?.title ?? null,
      cover: t.album?.cover_medium ?? null,
      duration: t.duration ?? null,
    }));
    return Response.json({ items });
  } catch {
    return Response.json({ items: [] }, { status: 502 });
  }
}
