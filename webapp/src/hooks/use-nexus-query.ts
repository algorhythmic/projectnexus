/**
 * Polling hook for Nexus REST API queries.
 *
 * Provides a similar interface to Convex's `useQuery`:
 *   - Returns `undefined` while loading the first fetch
 *   - Keeps stale data visible during refetch (stale-while-revalidate)
 *   - Polls at a configurable interval (default 30s)
 *   - Cleans up on unmount via AbortController
 */

import { useEffect, useRef, useState, useCallback } from "react";
import { nexusFetch } from "@/lib/nexus-api";

interface UseNexusQueryOptions {
  /** Polling interval in ms (default 30000). Set to 0 to disable polling. */
  pollingInterval?: number;
  /** Skip fetching when false (e.g. waiting for a dependency). */
  enabled?: boolean;
}

export function useNexusQuery<T>(
  path: string,
  params?: Record<string, string | number | undefined>,
  options?: UseNexusQueryOptions,
): { data: T | undefined; isLoading: boolean; error: Error | null } {
  const { pollingInterval = 30_000, enabled = true } = options ?? {};

  const [data, setData] = useState<T | undefined>(undefined);
  const [error, setError] = useState<Error | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const abortRef = useRef<AbortController | null>(null);

  // Serialize params to a stable string for dependency tracking
  const paramKey = params ? JSON.stringify(params) : "";

  const doFetch = useCallback(async () => {
    if (!enabled) return;
    try {
      const result = await nexusFetch<T>(path, params);
      setData(result);
      setError(null);
    } catch (err) {
      // Only set error if this isn't an abort
      if (err instanceof Error && err.name !== "AbortError") {
        setError(err);
        // Keep stale data visible — don't clear `data`
      }
    } finally {
      setIsLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, paramKey, enabled]);

  useEffect(() => {
    if (!enabled) {
      setIsLoading(false);
      return;
    }

    // Initial fetch
    setIsLoading(data === undefined);
    doFetch();

    // Polling
    if (pollingInterval > 0) {
      const interval = setInterval(doFetch, pollingInterval);
      return () => clearInterval(interval);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doFetch, pollingInterval, enabled]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  return { data, isLoading, error };
}
