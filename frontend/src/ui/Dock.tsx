"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import type { ReactNode } from "react";
import { toggleListen } from "@/lib/controller";
import { sfx } from "@/lib/sound";
import { useBlazam } from "@/lib/store";

const icon = (d: ReactNode) => (
  <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden className="sm:hidden">
    {d}
  </svg>
);

const LINKS = [
  { href: "/library", label: "Library", icon: icon(<><rect x="4" y="4" width="6.5" height="6.5" rx="1.5" /><rect x="13.5" y="4" width="6.5" height="6.5" rx="1.5" /><rect x="4" y="13.5" width="6.5" height="6.5" rx="1.5" /><rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1.5" /></>) },
  { href: "/add", label: "Add songs", icon: icon(<path d="M12 5v14M5 12h14" />) },
  { href: "/history", label: "History", icon: icon(<><circle cx="12" cy="12" r="8" /><path d="M12 8v4l2.5 2" /></>) },
  { href: "/stats", label: "Stats", icon: icon(<path d="M5 19V11M10 19V5M15 19v-6M20 19V9" />) },
] as const;

/** Floating dark-glass pill, bottom center: logo tile + segmented nav, Listen in lime. */
export function Dock() {
  const pathname = usePathname();
  const router = useRouter();
  const phase = useBlazam((s) => s.phase);
  const listening = phase === "listening";

  const onListen = () => {
    sfx.unlock();
    if (pathname !== "/") router.push("/");
    toggleListen();
  };

  return (
    <nav aria-label="Main" className="fixed bottom-[max(1rem,env(safe-area-inset-bottom))] left-1/2 z-40 -translate-x-1/2">
      <div className="glass-strong dock-shell flex items-stretch gap-1 rounded-[18px] p-1.5">
        <Link href="/" aria-label="Blazam home" className="dock-logo focus-ring">
          B<span className="text-[var(--c-lime)]">.</span>
        </Link>
        <button
          type="button"
          onClick={onListen}
          disabled={phase === "processing"}
          aria-pressed={listening}
          className={`dock-btn dock-btn--primary focus-ring ${listening ? "is-live" : ""}`}
          data-testid="dock-listen"
        >
          <span className="dock-dot" aria-hidden />
          {listening ? "Stop" : phase === "processing" ? "Wait" : "Listen"}
        </button>
        {LINKS.map((l) => {
          const active = pathname.startsWith(l.href);
          return (
            <Link key={l.href} href={l.href} aria-current={active ? "page" : undefined} aria-label={l.label} className={`dock-btn focus-ring ${active ? "is-active" : ""}`}>
              {l.icon}
              <span className="hidden sm:inline">{l.label}</span>
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
