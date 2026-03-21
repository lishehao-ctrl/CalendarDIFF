"use client";

import { useEffect, useRef, useState } from "react";
import { getSourceObservability, sourceObservabilityCacheKey } from "@/lib/api/sources";
import { getCachedResourceSnapshot, preloadResource } from "@/lib/resource-cache";
import type { SourceObservabilityResponse, SourceRow } from "@/lib/types";

const OBSERVABILITY_STALE_MS = 10_000;

export function useSourceObservabilityMap(sources: SourceRow[]) {
  const [data, setData] = useState<Record<number, SourceObservabilityResponse>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const latestSourcesRef = useRef<SourceRow[]>(sources);
  const sourceIdsKey = sources
    .filter((source) => source.is_active)
    .map((source) => source.source_id)
    .sort((left, right) => left - right)
    .join(",");

  useEffect(() => {
    latestSourcesRef.current = sources;
  }, [sources]);

  useEffect(() => {
    const activeSources = latestSourcesRef.current.filter((source) => source.is_active);
    if (activeSources.length === 0) {
      setData((current) => (Object.keys(current).length === 0 ? current : {}));
      setLoading(false);
      setError(null);
      return;
    }

    let cancelled = false;
    const cachedRows = activeSources.map((source) => ({
      sourceId: source.source_id,
      snapshot: getCachedResourceSnapshot<SourceObservabilityResponse>(
        sourceObservabilityCacheKey(source.source_id),
        OBSERVABILITY_STALE_MS,
      ),
    }));
    const nextCachedData = Object.fromEntries(
      cachedRows
        .filter((row) => row.snapshot.data !== undefined)
        .map((row) => [row.sourceId, row.snapshot.data as SourceObservabilityResponse]),
    );
    const missingCache = cachedRows.some((row) => row.snapshot.data === undefined);
    const needsRefresh = cachedRows.some((row) => !row.snapshot.fresh);

    setData(nextCachedData);
    setLoading(missingCache);
    setError(null);

    if (!needsRefresh) {
      return;
    }

    void Promise.all(
      activeSources.map(async (source) => ({
        sourceId: source.source_id,
        payload: await preloadResource({
          key: sourceObservabilityCacheKey(source.source_id),
          loader: () => getSourceObservability(source.source_id),
          staleMs: OBSERVABILITY_STALE_MS,
        }),
      })),
    )
      .then((rows) => {
        if (cancelled) return;
        setData(Object.fromEntries(rows.map((row) => [row.sourceId, row.payload])));
      })
      .catch((err) => {
        if (cancelled || !missingCache) return;
        setError(err instanceof Error ? err.message : "Unable to load source observability.");
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [sourceIdsKey]);

  return { data, loading, error };
}
