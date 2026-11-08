import { useCallback, useEffect, useRef, useState } from "react";

/** Fetch `fn` now and every `intervalMs` (pass null to pause polling). */
export function usePoll<T>(fn: () => Promise<T>, intervalMs: number | null, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fnRef = useRef(fn);
  fnRef.current = fn;

  const refresh = useCallback(async () => {
    try {
      setData(await fnRef.current());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    setData(null);
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    if (intervalMs == null) return;
    const t = setInterval(refresh, intervalMs);
    return () => clearInterval(t);
  }, [intervalMs, refresh]);

  return { data, error, refresh };
}
