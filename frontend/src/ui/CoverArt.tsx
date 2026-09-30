"use client";

import { useEffect, useState } from "react";

type Props = {
  cover: string | null | undefined;
  deezerId?: number | null;
  alt: string;
  className?: string;
  eager?: boolean;
};

/** A source that hasn't loaded after this long is treated as failed (upstream hosts can hang). */
const SLOW_MS = 2500;

/**
 * Cover with a fallback chain: the song's cover_url, then the Deezer album cover (via our
 * redirect route), then a designed monogram tile. Upstream cover hosts do fail and stall.
 */
export function CoverArt({ cover, deezerId, alt, className = "", eager = false }: Props) {
  const sources = [cover, deezerId ? `/api/deezer/cover?track=${deezerId}` : null].filter((s): s is string => !!s);
  const [index, setIndex] = useState(0);
  const [loaded, setLoaded] = useState(false);
  const src = sources[index];

  useEffect(() => {
    if (!src || loaded || index >= sources.length - 1) return;
    const t = setTimeout(() => setIndex((i) => i + 1), SLOW_MS);
    return () => clearTimeout(t);
  }, [src, loaded, index, sources.length]);

  return (
    <div className="cover-frame">
      {src ? (
        // eslint-disable-next-line @next/next/no-img-element -- remote covers from several hosts, served as-is
        <img
          key={src}
          src={src}
          alt={alt}
          loading={eager ? "eager" : "lazy"}
          decoding="async"
          className={`h-full w-full object-cover transition-opacity duration-500 ${loaded ? "opacity-100" : "opacity-0"} ${className}`}
          onLoad={() => setLoaded(true)}
          onError={() => setIndex((i) => i + 1)}
        />
      ) : (
        <div className="cover-fallback" role="img" aria-label={alt}>
          <span aria-hidden>B</span>
        </div>
      )}
    </div>
  );
}
