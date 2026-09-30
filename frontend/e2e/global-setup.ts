import { existsSync } from "node:fs";
import { AUDIO } from "./helpers";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** Refuse to run against a dead backend: these tests exist to exercise the real one. */
export default async function globalSetup() {
  try {
    const res = await fetch(`${API}/api/health`, { signal: AbortSignal.timeout(5000) });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
  } catch (e) {
    throw new Error(`Blazam backend is not reachable at ${API}/api/health (${String(e)}). Start it first: cd ../backend && .venv/bin/uvicorn app.main:app --port 8000`);
  }
  const missing = Object.values(AUDIO).filter((f) => !existsSync(f));
  if (missing.length) throw new Error(`Missing test audio ${missing.join(", ")}. Run: e2e/prepare-audio.sh 1 "ABBA Dancing Queen"`);
}
