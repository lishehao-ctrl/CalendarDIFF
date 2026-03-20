"use client";

import { DependencyList, useCallback, useEffect, useRef, useState } from "react";

export function useApiResource<T>(loader: () => Promise<T>, deps: DependencyList, initialData: T | null = null) {
  const [data, setData] = useState<T | null>(initialData);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const loaderRef = useRef(loader);
  const dataRef = useRef<T | null>(initialData);

  useEffect(() => {
    loaderRef.current = loader;
  }, [loader]);

  useEffect(() => {
    dataRef.current = data;
  }, [data]);

  const refresh = useCallback(async (options?: { background?: boolean }) => {
    const background = Boolean(options?.background && dataRef.current !== null);
    if (!background) {
      setLoading(true);
      setError(null);
    }
    try {
      const next = await loaderRef.current();
      setData(next);
    } catch (err) {
      if (!background) {
        setError(err instanceof Error ? err.message : "Unknown error");
      }
    } finally {
      if (!background) {
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refresh, ...deps]);

  return { data, loading, error, refresh, setData };
}
