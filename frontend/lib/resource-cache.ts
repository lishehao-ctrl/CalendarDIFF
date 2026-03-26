"use client";

import { translate } from "@/lib/i18n/runtime";

type ResourceCacheEntry<T> = {
  data?: T;
  promise?: Promise<T>;
  updatedAt: number;
  error?: string | null;
};

const resourceCache = new Map<string, ResourceCacheEntry<unknown>>();

const DEFAULT_STALE_MS = 15_000;

function isFresh<T>(entry: ResourceCacheEntry<T> | undefined, staleMs: number) {
  return Boolean(entry && entry.data !== undefined && Date.now() - entry.updatedAt < staleMs);
}

export function getCachedResourceSnapshot<T>(key: string, staleMs = DEFAULT_STALE_MS) {
  const entry = resourceCache.get(key) as ResourceCacheEntry<T> | undefined;
  return {
    data: entry?.data,
    error: entry?.error || null,
    updatedAt: entry?.updatedAt || 0,
    fresh: isFresh(entry, staleMs),
  };
}

export function writeCachedResource<T>(key: string, data: T) {
  resourceCache.set(key, {
    data,
    error: null,
    updatedAt: Date.now(),
  });
  return data;
}

export function invalidateCachedResource(key: string) {
  resourceCache.delete(key);
}

export async function preloadResource<T>({
  key,
  loader,
  staleMs = DEFAULT_STALE_MS,
  force = false,
}: {
  key: string;
  loader: () => Promise<T>;
  staleMs?: number;
  force?: boolean;
}): Promise<T> {
  const existing = resourceCache.get(key) as ResourceCacheEntry<T> | undefined;

  if (!force) {
    if (existing?.promise) {
      return existing.promise;
    }
    if (isFresh(existing, staleMs) && existing?.data !== undefined) {
      return existing.data;
    }
  }

  const request = loader()
    .then((data) => {
      writeCachedResource(key, data);
      return data;
    })
    .catch((error) => {
      if (existing?.data !== undefined) {
        resourceCache.set(key, {
          data: existing.data,
          updatedAt: existing.updatedAt,
          error: error instanceof Error ? error.message : translate("common.labels.requestError"),
        });
      } else {
        resourceCache.delete(key);
      }
      throw error;
    });

  resourceCache.set(key, {
    data: existing?.data,
    updatedAt: existing?.updatedAt || 0,
    error: null,
    promise: request,
  });

  return request;
}
