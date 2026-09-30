import { z } from "zod";

// Fallback cover: Cover Art Archive links can fail upstream (archive.org 5xx), so the UI can ask
// for the Deezer album cover of a track instead. Redirects to the image, 404 if there is none.
const Track = z.object({ album: z.object({ cover_xl: z.string().nullish(), cover_big: z.string().nullish() }) });

export async function GET(request: Request) {
  const id = new URL(request.url).searchParams.get("track");
  if (!id || !/^\d+$/.test(id)) return new Response("bad track id", { status: 400 });
  try {
    const res = await fetch(`https://api.deezer.com/track/${id}`, { signal: AbortSignal.timeout(6000), next: { revalidate: 86_400 } });
    const parsed = Track.safeParse(await res.json());
    const url = parsed.success ? (parsed.data.album.cover_xl ?? parsed.data.album.cover_big) : null;
    if (!url) return new Response("no cover", { status: 404 });
    return Response.redirect(url, 302);
  } catch {
    return new Response("upstream unavailable", { status: 502 });
  }
}
