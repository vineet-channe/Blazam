"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError } from "@/lib/api";

type Settled<T> = { key: string; data: T | null; error: ApiError | null };

/**
 * Loads with an AbortSignal and re-runs whenever `deps` (primitives) change; `reload` forces a
 * refetch. Loading is derived (the last settled result belongs to other deps), so no state is
 * set synchronously inside the effect.
 */
export function useAsync<T>(load: (signal: AbortSignal) => Promise<T>, deps: readonly (string | number | boolean | null)[]) {
  const [nonce, setNonce] = useState(0);
  const key = JSON.stringify([...deps, nonce]);
  const [settled, setSettled] = useState<Settled<T>>({ key: "", data: null, error: null });
  useEffect(() => {
    const ctrl = new AbortController();
    load(ctrl.signal).then(
      (data) => !ctrl.signal.aborted && setSettled({ key, data, error: null }),
      (e: unknown) => {
        if (ctrl.signal.aborted) return;
        setSettled((s) => ({ key, data: s.data, error: e instanceof ApiError ? e : new ApiError("server", String(e)) }));
      },
    );
    return () => ctrl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `key` encodes the caller's deps
  }, [key]);
  const reload = useCallback(() => setNonce((n) => n + 1), []);
  const loading = settled.key !== key;
  // keep showing the previous data while the next load is in flight
  return { data: settled.data, error: loading ? null : settled.error, loading, reload };
}
