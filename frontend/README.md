# Blazam frontend

**Hear it. Blaze it.** An immersive, Shazam-style music recognizer. You tap a marbled emerald coin
that stands in a misty green landscape. It spins up and throws fire sparks while it records, then
reveals the song.

Next.js 16 (App Router) · TypeScript strict · Tailwind 4 · React Three Fiber 9 + drei 10 +
@react-three/postprocessing 3 · three 0.186 · Framer Motion 13 · Zustand 5 · Zod 4 · Playwright 1.63.

---

## Setup

```bash
# 1. backend (see ../backend/README.md), on :8000
cd ../backend && .venv/bin/uvicorn app.main:app --port 8000

# 2. frontend, on :3000 (the backend's CORS only allows http://localhost:3000)
cd ../frontend
npm install
npm run dev                      # http://localhost:3000

# checks
npm run typecheck && npm run lint && npm run build

# e2e (real backend; needs ffmpeg)
npx playwright install chromium
npm run e2e:audio                # builds e2e/.audio/{own,external,noise}.wav (git-ignored)
npm run test:e2e                 # screenshots of every state land in e2e/screenshots/
```

| env var | default | meaning |
|---|---|---|
| `BLAZAM_API_ORIGIN` | `http://localhost:8000` | backend the production `/backend` proxy forwards to (server-only) |
| `NEXT_PUBLIC_API_URL` | unset | optional override: browser calls this URL directly instead (needs CORS) |
| `NEXT_PUBLIC_RECORD_MS` | `8000` | clip length, clamped to 7000–10000 |

Add `?webgl=0` to any URL to force the no-WebGL fallback.

### Deploy on Vercel (frontend) + Render (backend)

Production builds call the backend through a same-origin proxy: the browser requests
`/backend/api/...` and a Next.js rewrite (`next.config.ts`) forwards it to the backend. The backend
address is a **server-only** variable, so nothing sensitive is public and CORS isn't involved.

1. Deploy the backend on Render first (see "Deploy on Render" in `../backend/README.md`).
2. In Vercel, import the repo with **Root Directory `frontend`**. Set
   `BLAZAM_API_ORIGIN=https://<your-service>.onrender.com` (no `NEXT_PUBLIC_` prefix, no trailing
   slash). Rewrites are resolved at build time, so redeploy after changing it.
3. Don't set `NEXT_PUBLIC_API_URL`; it would bypass the proxy. Never put `AUDD_API_TOKEN` in Vercel.

Local `npm run dev` still calls `http://localhost:8000` directly. The proxy path was checked with
`next build && next start` against the local backend: health, recognition, SSE job streams and the
browser flow all went through `/backend`. Limits of Vercel's proxy (request size, very long
streams) may affect large file uploads on **Add songs**. If an SSE stream is cut, job progress
falls back to polling automatically.

---

## Architecture

```
src/
  app/             routes: / (immersive home), /library, /add, /history, /stats
    layout.tsx     persistent chrome: SceneHost (the Canvas), brand chip, dock, loader, toasts
    api/deezer/    two tiny server routes: search proxy + cover fallback redirect
  lib/             framework-free logic
    schemas.ts     Zod schemas for every backend response (source of truth: ../backend/README.md)
    api.ts         typed fetch client, error classification (offline/timeout/bad_audio/…), SSE follower
    store.ts       Zustand: the phase state machine + UI flags
    controller.ts  orchestrates a recognition: mic -> record -> POST -> reveal | no_match | error
    recorder.ts    MediaRecorder + AnalyserNode (live level), container fallback for Safari
    sound.ts       synthesized Web Audio SFX (ignite, spin whoosh, reveal chime, sputter)
    live.ts        per-frame values shared with WebGL (mic level, spin, bursts), no React renders
    theme.ts       every color (palette, scene tones, spark ramps, chart colors)
  scene/           React Three Fiber: coin, landscape, atmosphere, sparks, rings, camera, post
  ui/              DOM overlay: dock, loader, result card, outcome panels, fallback coin, …
  hooks/           media queries, pointer/gyro, backend health, async loading
e2e/               Playwright specs, fixture, audio prep script
scripts/           make-coin-typeface.mjs (builds public/fonts/coin-b.typeface.json)
```

**The state machine** (`lib/store.ts`) permits only these transitions:
`idle → listening → processing → reveal | no_match | error → idle` (outcomes can also go straight
back to `listening`). Click the coin, the dock's Listen button, or press **Space/Enter** to start. A
second press during listening stops early (at least 2.5 s is always sent).

**Two update channels.** React and Zustand hold coarse UI state such as the phase, result and
toasts. Everything that changes every frame lives on the plain mutable `live` object: mic RMS,
recording progress, pointer, gyro, spin speed and burst requests. The scene reads it in
`useFrame`, so 60 fps animation never re-renders React.

**The persistent canvas.** `SceneHost` is mounted in the root layout and loads the scene with
`next/dynamic(..., { ssr: false })`, so route changes never remount WebGL. Off the home page the
scene is dimmed, blurred and scaled with a CSS transition, and glass panels float over it.

---

## The scene

| piece | how |
|---|---|
| **Coin** (`scene/Coin.tsx`, `coinGeometry.ts`) | `LatheGeometry` profile: dished field, raised inner ring, raised lip, bevel, and a 160-ridge knurled edge (vertices displaced radially; hard edges keep split normals). The embossed **B** on both faces is `Text3D` from `public/fonts/coin-b.typeface.json`, a 1.3 KB single-glyph typeface cut from Fraunces, the display font. |
| **Coin material** (`coinMaterial.ts`) | `MeshPhysicalMaterial` (transmission 0.12, thickness, ior 1.45, clearcoat, sheen, attenuation) patched with `onBeforeCompile`: double domain-warped fbm (simplex 3D) plus warped horizontal strata make alabaster bands, contour-line veins drift slowly, and a fresnel rim, a sweeping rim light and an emissive "lamp inside the stone" follow `uGlow`. The letter is a separate lime-gold emissive material. |
| **Motion** | Physically-flavoured springs. Listening drives angular velocity toward 25 rad/s (slightly modulated by mic level) with a click impulse and a vertical hop. Processing decelerates to about 2.4 rad/s with a pulsing glow. Reveal settles with an under-damped spring one extra turn ahead, which gives the overshoot flip. No-match sputters with random torque and dulls to grey-green. Precession wobble scales with speed. Idle floats and sways and tilts toward the pointer or gyro, more strongly on hover. |
| **Landscape** | Displaced dune plane with a shared height function (`terrain.ts`), a pool bowl carved below y = 0, and a `MeshReflectorMaterial` water plane (the reflection is multiplied by the base color, so the tint is mid-tone, not black). About 1.8k–3.5k instanced grass blades in agave-like clumps with vertex-shader wind. |
| **Atmosphere** | Gradient sky dome with a tight horizon glow and mist bands, `FogExp2`, five additive breathing light shafts, flapping birds, drei `Sparkles` dust. |
| **Rings** (`Rings.tsx`) | One camera-facing quad draws the recording-progress arc (with a hot tip), a live mic-level ring that wobbles with the level, and an orbiting comet while processing. |
| **Camera** (`CameraRig.tsx`) | A 5.5 s eased push-in after the loader, pointer/gyro parallax, and a dolly that frames the coin left of the card (wide screens) or above the sheet (narrow). Shake at peak spin (none under reduced motion). |
| **Post** (`Effects.tsx`) | Mipmap bloom whose intensity follows spin, mic level and breathing; depth of field (high tier) auto-focused on the coin; chromatic aberration spiking at peak spin; neutral tone mapping; vignette; film grain. |

### Spark system (`scene/Sparks.tsx`)

- **GPU-stateless.** Each spark is one instance of a quad. The CPU only writes birth state into a
  ring buffer when a spark is emitted: position, velocity, birth time, life, seed and buoyancy.
  Only the touched slice is uploaded (`addUpdateRange`).
- **Analytic motion in the vertex shader.** Exact linear-drag integration with gravity, or heat
  buoyancy for the ~30% of sparks that are embers, plus growing sinusoidal turbulence.
- **Streaks.** The shader projects the head and a slightly older tail, then stretches the quad
  between them in screen space. Fast sparks read as streaks and slow embers as dots.
- **Emission.** Sparks leave tangentially off the rim: the velocity of a point on a disc spinning
  about Y, plus radial fling and upward heat. The rate is proportional to spin^1.4 × (0.35 +
  1.65·micLevel), and brightness also follows the mic.
- **Bursts.** The controller calls `emitBurst()` on click and on reveal (fire) and on failure
  (smoke).
- **Color ramp.** It runs white-hot → gold → orange → ember and is defined in `lib/theme.ts`
  (`FIRE`). Set `ACTIVE_SPARK_RAMP = GREEN_FLAME` for green fire.
- **Smoke.** A second instance of the same system uses normal blending for grey-green puffs.
- **Light and reflection.** A point light at the coin follows emission, so sparks light the fog,
  grass and pool, and they appear in the reflection.
- **Counts.** 5000 on desktop, 1800 on mobile, 900 under reduced motion.
- **Hard-won details, kept as code comments.** The quad basis must stay right-handed or every
  streak is back-face culled. Double-sided rendering is needed because the reflector's mirrored
  camera flips winding. Fire writes depth so depth of field doesn't blur the streaks away. No
  division by zero even in an unused branch, because smoke has head == tail and one NaN pixel
  becomes a black block in bloom.

**Adaptive quality.** `dpr` runs from 1 to 1.75 (1.25 on mobile). drei `PerformanceMonitor`
steps quality from high to medium to low (DoF off, reflector 512 → 256 → 128, fewer grass blades
and dust) and lowers DPR.

**Reduced motion** calms everything: gentler glow, a 7 rad/s spin cap, no shake or chromatic
aberration, and far fewer sparks. **No WebGL** (or `?webgl=0`) swaps in a CSS coin that runs the
same state machine, rings and flow.

---

## How it talks to the backend

Everything follows `../backend/README.md` ("HTTP API" and its contract notes). Each response is
parsed with Zod (`lib/schemas.ts`), and unknown keys are ignored.

- **Recognize.** The clip is recorded with MediaRecorder: `audio/webm;codecs=opus`, falling back
  to ogg and then `audio/mp4`/m4a for Safari. Echo cancellation, noise suppression and AGC are off,
  because they smear spectral peaks. It is posted as multipart field `audio` with a matching
  extension to `POST /api/recognize`, with a 30 s timeout.
  - `confidence` is shown only when it is a number; it is `null` for external matches.
  - `song.id` is never used as a key.
  - `lyrics` is optional, and the Lyrics button appears only when it is present.
  - `song.preview_url` goes straight into an `<audio>` element.
  - `offset_seconds` is shown as "Matched at m:ss".
  - `learned: true` shows the "Added to library" toast.
- **Errors are classified, never shown raw.**
  - Network failure → offline.
  - Abort after 30 s → timeout.
  - 400/422/413 → bad audio.
  - `NotAllowedError` → mic denied, with guidance to re-allow.
  - No device → mic unavailable.
  - Insecure context or unsupported browser → mic unsupported.
  - `/api/health` is polled (two consecutive misses count as offline), so the UI shows "Server
    offline" before anyone clicks.
- **Library, history and stats** are `GET /api/library?q=&page=&page_size=`, `/api/history`
  and `/api/stats`.
- **Import and upload.** `POST /api/library/import` (a Deezer query, or `chart: true` + `limit`
  for "Seed library") and `POST /api/library/upload` (multipart `files`) return `{job_id}`. Progress
  streams over **SSE** from `/api/jobs/{id}/stream` (`progress` frames, then `end`), falling back
  to polling `/api/jobs/{id}` if the stream drops.
- **Two small Next.js routes** cover what the backend doesn't:
  - `/api/deezer/search`: Deezer sends no CORS headers and the backend has no search-only
    endpoint. Clicking a result imports it with the query `"artist title"`, limit 1. Deezer's
    `artist:"" track:""` syntax returned nothing when tested.
  - `/api/deezer/cover?track=`: Cover Art Archive links currently fail upstream (HTTP 500 after
    redirects, about 5 s). `CoverArt` falls back to the Deezer album cover after an error or 2.5 s,
    then to a designed monogram.

---

## 60-second demo script

Before starting: the backend is running (`/api/health` ok), `npm run dev` is running, sound is on,
and a phone or speaker is ready. Use a song that's in the library (open **Library** and pick one,
e.g. *Take on Me*), one that isn't (search **Library** first to make sure), and some noise.

| time | do | say |
|---|---|---|
| 0:00 | Load `/`. The loader counts up, the camera pushes in through the mist and the coin fades up. | "This is Blazam. One coin, one job." |
| 0:08 | Hover the coin: the "Listen" cursor, and the coin brightens and tilts. Play the **indexed** song and click. | "Tap, and it listens." |
| 0:12 | The coin spins up, sparks follow the music's loudness and the ring fills. | "Eight seconds of audio. The sparks are the live mic level." |
| 0:20 | "Identifying…" then the overshoot flip, spark burst, card slides in: **Recognized by: Own engine ⚡**, confidence, matched timestamp, well under a second (325–970 ms observed in-browser). Click **Play preview**, then open **Lyrics**. | "That's our own fingerprinting engine, offline, in a few hundred milliseconds." |
| 0:30 | **Listen again** with the **unindexed** song. The card says **Recognized by: External API 🌐**, has no confidence bar, and a toast says "Added to library". | "Not in the library, so it fell through to the external API, and it learned the song. Play it again and our engine answers." |
| 0:42 | **Listen again** while playing **noise** or talking. The coin sputters, sparks turn to grey-green smoke: "Couldn't catch that." | "No guessing: when neither tier is sure, it says so." |
| 0:50 | Open **/stats**. | "Here's the hybrid design: the donut shows who answered, and this chart compares speed per tier against the one-second target." |

---

## Requirements checklist

**PASS** means implemented *and* run, with the evidence named. **PARTIAL** means implemented but
with a gap stated. **FAIL** means not done. Screenshots are regenerated by `npm run test:e2e` into
`e2e/screenshots/` (git-ignored). The final suite run was **7 passed, 0 failed** against the live
backend.

### 1. Backend contract
| requirement | status | evidence |
|---|---|---|
| Read ../backend/README.md; typed client with Zod | PASS | `lib/schemas.ts`, `lib/api.ts`; shapes cross-checked against live `/api/history`, `/api/library`, `/api/stats`, `/api/recognize` responses |
| MediaRecorder webm/opus + Safari fallback, multipart `audio`, 7–10 s | PARTIAL | webm/opus path exercised in every e2e run; the mp4/m4a Safari path is implemented (`recorder.ts`) but **not run on Safari** |
| `confidence` bar only when a number | PASS | own: `04-reveal-own` (bar shown); external: `06-reveal-external` asserts `confidence` element count 0 |
| `song.id` never a required key | PASS | keys use `id ?? title-index`; the external response has `id: null` and renders |
| `lyrics` optional | PASS | Lyrics button only when present; `04b-lyrics` (drawer), external card has none |
| `preview_url` straight into `<audio>` | PASS | flow test fetches the preview URL (200/206); Play preview in the card, play on Library cards |
| SSE job progress | PASS | pages test: Deezer import, chart seed and upload jobs all reach `done` via `/api/jobs/{id}/stream` (`10-add-live-job`, `10b-add-seed-upload-done`) |
| Port 3000, `NEXT_PUBLIC_API_URL` | PASS | `npm run dev` = `next dev -p 3000`; `lib/api.ts` |

### 2. Specifics, 3. Stack
| requirement | status | evidence |
|---|---|---|
| Name Blazam, coin letter B, tagline | PASS | brand chip, loader, hero type, coin |
| Reference viewed, mood recreated in green | PASS | composition mirrors the reference: hero object over a reflective pool, silhouettes, haze, bottom dock |
| Next.js App Router latest stable, TS strict, Tailwind, R3F, drei, postprocessing, Framer Motion, Zustand, Zod | PASS | `package.json` (next 16.3.7 …); `tsconfig` strict |
| Library APIs verified against installed versions | PASS | checked `.d.ts` for MeshReflectorMaterial, Text3D, Center, PerformanceMonitor, DepthOfField (world-unit focus), ToneMapping, `addUpdateRange`; Next 16 docs in `node_modules/next/dist/docs` |

### 4. Look and feel
| requirement | status | evidence |
|---|---|---|
| Palette in one theme file | PASS | `lib/theme.ts` (injected as CSS variables) |
| Dunes, grass silhouettes, fog, light shafts, reflective pool, birds, dust | PASS | `01-idle`; birds are small and distant by design |
| Bloom, grain, vignette, chromatic aberration, depth of field | PASS | `scene/Effects.tsx`; DoF on the high tier only |
| Floating dock (logo tile, segmented, lime Listen), brand chip | PASS | every screenshot; icon mode below 640 px (`13-mobile-idle`, `13b-idle-360`) |
| Display font + sans via next/font | PASS | Fraunces (display) + Geist / Geist Mono |
| Loader with "B." and progress, then push-in and fade-up | PASS | `Loader.tsx`; camera intro in `CameraRig.tsx` |

### 5. Coin
| requirement | status | evidence |
|---|---|---|
| Thick beveled coin on its edge, hovering over the pool with a reflection | PASS | `01-idle` |
| Ridged rim, raised inner ring, embossed B on both faces (Text3D + bundled typeface) | PASS | `coinGeometry.ts`, `public/fonts/coin-b.typeface.json` |
| Marbled translucent emerald: physical material + onBeforeCompile fbm veins, fresnel, emissive, lime-gold B | PASS | `coinMaterial.ts` |
| Idle float, sway, parallax tilt, sweeping rim light, breathing bloom | PASS | `Coin.tsx`, `Effects.tsx` |
| Gyro parallax | PARTIAL | `deviceorientation` is used where the browser delivers it; iOS 13+ needs an explicit permission request, which is **not** implemented |
| Hover brighten + tilt + "Listen" cursor | PASS | `01b-hover` (test asserts the label) |

### 6. The click event
| requirement | status | evidence |
|---|---|---|
| State machine; click, Space, Enter | PASS | `store.ts`; tests use Space and a real mouse click on the coin |
| Spin-up to about 25 rad/s, wobble, bounce | PASS | `02-listening-sparks` |
| GPU sparks with custom shader, additive, 5k/1.8k, tangential + heat, gravity, drag, turbulence, flicker, ramp constants, reflect in pool, follow mic, bursts | PASS | `02-listening-sparks` (streaks, embers, reflection) |
| Bloom scales with spin; CA + shake at peak | PASS | `Effects.tsx`, `CameraRig.tsx` |
| Whoosh/ignite sound + mute toggle | PARTIAL | synthesized in `sound.ts` and runs without errors in every test, but **audio output was not verified** (headless) |
| Record 8 s (clamp 7–10), progress ring + level ring, click to stop early | PASS | `02-listening-sparks`; early stop has a 2.5 s floor |
| Processing: decelerate, pulsing glow, "Identifying…" | PASS | `03-processing` |
| Match: overshoot flip, dolly, burst, glass card with every field, badge, toast, buttons | PASS | `04-reveal-own`, `06-reveal-external`, `04b-lyrics` |
| No match: sputter, grey-green smoke, message | PASS | `05-no-match` (real backend, noise) |
| Designed errors: mic denied, backend offline, timeout | PARTIAL | mic denied `07-error-mic-denied` (real browser denial); offline `08-error-offline` (stubbed network failure); **timeout is implemented but not exercised** |

### 7. Structure and pages
| requirement | status | evidence |
|---|---|---|
| Persistent Canvas in root layout (dynamic, ssr false); other routes dim and blur | PASS | `ui/SceneHost.tsx`; `09-library` … `12-stats` |
| /library searchable glass grid, hover glow | PASS | `09-library`; the test searches "Dancing Queen" |
| /add: Deezer search + import, seed with count, drag-and-drop upload, live SSE | PASS | `10-add-live-job`, `10b-add-seed-upload-done` (drop uses the same handler as the file input the test drives) |
| /history timeline with source badges | PASS | `11-history` |
| /stats: library size, donut, latency per tier | PASS | `12-stats`; chart colors pass the dataviz validator (lightness, chroma, CVD, contrast) |

### 8. Quality bars
| requirement | status | evidence |
|---|---|---|
| 60 fps on a recent laptop; DPR [1, 1.75]; PerformanceMonitor; fewer particles on mobile | PASS | Apple M2, Chromium, 1440×900 @2x: 59–60 fps idle and 60 fps listening at DPR 1.75 (p95 16.8 ms) after warm-up; the first seconds dip while shaders compile |
| prefers-reduced-motion | PARTIAL | implemented throughout; screenshot evidence covers the reduced-motion **fallback** (`15/16`), not the reduced-motion WebGL scene |
| WebGL fallback with the same flow | PASS | `15-fallback-idle`, `16-fallback-reveal` (full recognition via `?webgl=0`) |
| Keyboard trigger, aria-live, focus states, mic guidance | PASS | Space/Enter/Escape; the announcer is asserted in tests; lime focus ring; mic hint in idle and the denied panel |
| Responsive 360 px to ultrawide | PASS | `13b-idle-360`, `13-mobile-idle`, `14-mobile-reveal` (390), `13b-idle-2560` |
| Clean structure, ESLint + tsc passing | PASS | `npm run lint`, `npm run typecheck`, `npm run build` all clean. One scoped lint override: `react-hooks/immutability` is off in `src/scene/**`, because R3F mutates three.js objects in `useFrame` by design |

### 9. Verification, 10. Deliverables
| requirement | status | evidence |
|---|---|---|
| Real backend, `/api/health` first | PASS | `e2e/global-setup.ts` refuses to run otherwise |
| Screenshots of every state | PASS | 21 files in `e2e/screenshots/` (listed by the final run) |
| Stub only what can't be triggered, and say so | PASS | two stubs, both named `STUB:` in the test titles: the external card (replays a recorded real AudD response, `e2e/fixtures/external-match.json`, because a live external match auto-learns the song) and backend offline (network failure). A **live** external match was also run once: *Dancing Queen – ABBA*, `confidence: null`, `learned: true`, and the song was auto-indexed as id 586 |
| Playwright smoke test of the full flow | PASS | `e2e/flow.spec.ts` |
| README, demo script, checklist | PASS | this file |

### Known gaps
- iOS gyro permission prompt, Safari recording and audible SFX were not verified on real devices.
- The e2e suite changes the backend library. It imports *Dreams – Fleetwood Mac* and the current
  chart top 10 (new tracks only), and the one live external run auto-learned *Dancing Queen*.
- Cover Art Archive was returning HTTP 500 during testing; covers fall back to Deezer.
