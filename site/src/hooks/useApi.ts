/**
 * A single hook that turns an API call into one of four renderable states:
 * loading, ready, missing (404 / no run yet), or error (API unreachable or
 * failing). No component below ever has to deal with a thrown promise.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, apiGet } from "@/lib/client";

export type AsyncPhase = "idle" | "loading" | "ready" | "missing" | "error";

export type AsyncState<T> = {
  phase: AsyncPhase;
  data: T | null;
  error: ApiError | null;
  /** Increments on every completed load, so children can re-key. */
  loadedAt: number | null;
  reload: () => void;
};

const IDLE: AsyncState<never> = {
  phase: "idle",
  data: null,
  error: null,
  loadedAt: null,
  reload: () => undefined,
};

/**
 * @param path   API path, or `null` to skip the request entirely.
 * @param deps   Extra identity inputs; changing them re-runs the request.
 */
export function useApi<T>(path: string | null, deps: readonly unknown[] = []): AsyncState<T> {
  const [state, setState] = useState<AsyncState<T>>(IDLE as AsyncState<T>);
  const [nonce, setNonce] = useState(0);
  const active = useRef(true);

  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  const depKey = deps.map((value) => JSON.stringify(value ?? null)).join("|");

  useEffect(() => {
    if (path === null) {
      setState(IDLE as AsyncState<T>);
      return;
    }
    const controller = new AbortController();
    setState((current) => ({ ...current, phase: "loading", error: null }));

    apiGet<T>(path, controller.signal)
      .then((data) => {
        if (!active.current) return;
        setState({
          phase: "ready",
          data,
          error: null,
          loadedAt: Date.now(),
          reload: () => undefined,
        });
      })
      .catch((caught: unknown) => {
        if (!active.current) return;
        if (caught instanceof DOMException && caught.name === "AbortError") return;
        const error =
          caught instanceof ApiError
            ? caught
            : new ApiError("http", 0, "Unexpected failure while reading from the API.");
        setState({
          phase: error.kind === "not_found" ? "missing" : "error",
          data: null,
          error,
          loadedAt: null,
          reload: () => undefined,
        });
      });

    return () => controller.abort();
    // `depKey` is the stable identity of `deps`.
  }, [path, depKey, nonce]);

  const reload = useCallback(() => setNonce((value) => value + 1), []);

  return { ...state, reload };
}
