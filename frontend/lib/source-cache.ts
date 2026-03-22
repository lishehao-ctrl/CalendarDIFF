"use client";

import { sourceListCacheKey, sourceObservabilityCacheKey, sourceSyncHistoryCacheKey } from "@/lib/api/sources";
import { invalidateCachedResource } from "@/lib/resource-cache";

export function invalidateSourceListCaches() {
  invalidateCachedResource(sourceListCacheKey("active"));
  invalidateCachedResource(sourceListCacheKey("archived"));
  invalidateCachedResource(sourceListCacheKey("all"));
}

export function invalidateSourceCaches(sourceId?: number, syncHistoryLimit = 8) {
  invalidateSourceListCaches();
  if (sourceId == null) {
    return;
  }
  invalidateCachedResource(sourceObservabilityCacheKey(sourceId));
  invalidateCachedResource(sourceSyncHistoryCacheKey(sourceId, syncHistoryLimit));
}
