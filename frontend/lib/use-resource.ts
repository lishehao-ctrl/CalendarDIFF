"use client";

import { useCallback, useEffect, useState } from "react";
import { backendFetch } from "@/lib/backend";

export function useResource<T>(path: string, initialData: T | null = null) {
  const [data, setData] = useState<T | null>(initialData);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const next = await backendFetch<T>(path);
      setData(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { data, loading, error, refresh, setData };
}
