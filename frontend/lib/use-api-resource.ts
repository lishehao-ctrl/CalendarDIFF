"use client";

import { type DependencyList, type SetStateAction, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getCachedResourceSnapshot, invalidateCachedResource, preloadResource, writeCachedResource } from "@/lib/resource-cache";

type UseApiResourceOptions = {
  cacheKey?: string;
  staleMs?: number;
};

export function useApiResource<T>(
  loader: () => Promise<T>,
  deps: DependencyList,
  initialData: T | null = null,
  options?: UseApiResourceOptions,
) {
  const initialSnapshot = useMemo(
    () => (options?.cacheKey ? getCachedResourceSnapshot<T>(options.cacheKey, options.staleMs) : null),
    [options?.cacheKey, options?.staleMs],
  );
  const [dataState, setDataState] = useState<T | null>(initialData ?? initialSnapshot?.data ?? null);
  const [loading, setLoading] = useState(initialData === null && initialSnapshot?.data == null);
  const [error, setError] = useState<string | null>(null);
  const loaderRef = useRef(loader);
  const dataRef = useRef<T | null>(initialData ?? initialSnapshot?.data ?? null);
  const optionsRef = useRef<UseApiResourceOptions | undefined>(options);

  useEffect(() => {
    loaderRef.current = loader;
  }, [loader]);

  useEffect(() => {
    optionsRef.current = options;
  }, [options]);

  const applyData = useCallback((value: SetStateAction<T | null>) => {
    setDataState((previous) => {
      const next = typeof value === "function" ? (value as (current: T | null) => T | null)(previous) : value;
      const cacheKey = optionsRef.current?.cacheKey;
      if (cacheKey) {
        if (next === null) {
          invalidateCachedResource(cacheKey);
        } else {
          writeCachedResource(cacheKey, next);
        }
      }
      dataRef.current = next;
      return next;
    });
  }, []);

  useEffect(() => {
    dataRef.current = dataState;
  }, [dataState]);

  const refresh = useCallback(async (refreshOptions?: { background?: boolean; force?: boolean }) => {
    const background = Boolean(refreshOptions?.background && dataRef.current !== null);
    if (!background) {
      setLoading(true);
      setError(null);
    }
    try {
      const next = optionsRef.current?.cacheKey
        ? await preloadResource({
            key: optionsRef.current.cacheKey,
            loader: loaderRef.current,
            staleMs: optionsRef.current.staleMs,
            force: Boolean(refreshOptions?.force),
          })
        : await loaderRef.current();
      applyData(next);
    } catch (err) {
      if (!background) {
        setError(err instanceof Error ? err.message : "Unknown error");
      }
    } finally {
      if (!background) {
        setLoading(false);
      }
    }
  }, [applyData]);

  useEffect(() => {
    const cacheKey = optionsRef.current?.cacheKey;
    const staleMs = optionsRef.current?.staleMs;
    const cached = cacheKey ? getCachedResourceSnapshot<T>(cacheKey, staleMs) : null;
    if (cached?.data !== undefined) {
      applyData(cached.data);
      setLoading(false);
      setError(null);
    }
    void refresh({ background: cached?.data !== undefined });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refresh, ...deps]);

  return { data: dataState, loading, error, refresh, setData: applyData };
}
