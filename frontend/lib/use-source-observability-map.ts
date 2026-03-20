"use client";

import { useEffect, useRef, useState } from "react";
import { getSourceObservability } from "@/lib/api/sources";
import type { SourceObservabilityResponse, SourceRow } from "@/lib/types";

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
    setLoading(true);
    setError(null);

    void Promise.all(
      activeSources.map(async (source) => ({
        sourceId: source.source_id,
        payload: await getSourceObservability(source.source_id),
      })),
    )
      .then((rows) => {
        if (cancelled) return;
        setData(Object.fromEntries(rows.map((row) => [row.sourceId, row.payload])));
      })
      .catch((err) => {
        if (cancelled) return;
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
