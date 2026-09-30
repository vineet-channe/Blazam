import type { Metadata, Viewport } from "next";
import { Fraunces, Geist, Geist_Mono } from "next/font/google";
import { cssVariables, palette } from "@/lib/theme";
import { BrandChip, CursorLabel, ToastHost, TopRight } from "@/ui/Chrome";
import { Dock } from "@/ui/Dock";
import { Loader } from "@/ui/Loader";
import { SceneHost } from "@/ui/SceneHost";
import "./globals.css";

const display = Fraunces({ subsets: ["latin"], axes: ["opsz", "SOFT"], style: ["normal", "italic"], variable: "--font-display" });
const sans = Geist({ subsets: ["latin"], variable: "--font-sans" });
const mono = Geist_Mono({ subsets: ["latin"], variable: "--font-mono" });

export const metadata: Metadata = {
  title: { default: "Blazam · Hear it. Blaze it.", template: "%s · Blazam" },
  description: "Hold up your phone, tap the coin, and Blazam names the song.",
};

export const viewport: Viewport = { themeColor: palette.bgDeep, colorScheme: "dark" };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" style={cssVariables as React.CSSProperties} className={`${display.variable} ${sans.variable} ${mono.variable}`}>
      <body>
        <a href="#main" className="skip-link focus-ring">
          Skip to content
        </a>
        <SceneHost />
        <BrandChip />
        <TopRight />
        <main id="main" className="relative z-10">
          {children}
        </main>
        <Dock />
        <ToastHost />
        <CursorLabel />
        <Loader />
      </body>
    </html>
  );
}
