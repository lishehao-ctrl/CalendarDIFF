"use client";

import { changesListCacheKey, changesSummaryCacheKey, getChangesSummary, listChanges } from "@/lib/api/changes";
import {
  familiesCoursesCacheKey,
  familiesListCacheKey,
  familiesRawTypesCacheKey,
  familiesStatusCacheKey,
  familiesSuggestionsCacheKey,
  getFamiliesStatus,
  listFamilies,
  listFamilyCourses,
  listFamilyRawTypeSuggestions,
  listFamilyRawTypes,
} from "@/lib/api/families";
import { getMcpTokens, getSettingsProfile, settingsMcpTokensCacheKey, settingsProfileCacheKey } from "@/lib/api/settings";
import { listManualEvents, manualEventsCacheKey } from "@/lib/api/manual";
import { getSourceObservability, listSources, sourceListCacheKey, sourceObservabilityCacheKey } from "@/lib/api/sources";
import { preloadResource } from "@/lib/resource-cache";
import type { SourceRow } from "@/lib/types";

const NAV_STALE_MS = 15_000;
const OBSERVABILITY_STALE_MS = 10_000;

function normalizeWorkspacePath(href: string) {
  if (href === "/preview") {
    return "/";
  }
  if (href.startsWith("/preview/")) {
    return href.slice("/preview".length);
  }
  return href;
}

async function preloadActiveSourceObservability(rows: SourceRow[]) {
  await Promise.all(
    rows
      .filter((source) => source.is_active)
      .map((source) =>
        preloadResource({
          key: sourceObservabilityCacheKey(source.source_id),
          loader: () => getSourceObservability(source.source_id),
          staleMs: OBSERVABILITY_STALE_MS,
        }).catch(() => undefined),
      ),
  );
}

function preloadOverviewLane() {
  void preloadResource({
    key: changesSummaryCacheKey(),
    loader: getChangesSummary,
    staleMs: NAV_STALE_MS,
  }).catch(() => undefined);

  void preloadResource({
    key: sourceListCacheKey("active"),
    loader: () => listSources({ status: "active" }),
    staleMs: NAV_STALE_MS,
  })
    .then((rows) => preloadActiveSourceObservability(rows))
    .catch(() => undefined);
}

function preloadSourcesLane() {
  void preloadResource({
    key: sourceListCacheKey("active"),
    loader: () => listSources({ status: "active" }),
    staleMs: NAV_STALE_MS,
  })
    .then((rows) => preloadActiveSourceObservability(rows))
    .catch(() => undefined);

  void preloadResource({
    key: sourceListCacheKey("archived"),
    loader: () => listSources({ status: "archived" }),
    staleMs: NAV_STALE_MS,
  }).catch(() => undefined);

  void preloadResource({
    key: sourceListCacheKey("all"),
    loader: () => listSources({ status: "all" }),
    staleMs: NAV_STALE_MS,
  }).catch(() => undefined);
}

function preloadChangesLane() {
  void preloadResource({
    key: changesSummaryCacheKey(),
    loader: getChangesSummary,
    staleMs: NAV_STALE_MS,
  }).catch(() => undefined);

  void preloadResource({
    key: sourceListCacheKey("all"),
    loader: () => listSources({ status: "all" }),
    staleMs: NAV_STALE_MS,
  }).catch(() => undefined);

  const defaultParams = {
    review_status: "pending" as const,
    review_bucket: "changes" as const,
    limit: 50,
    source_id: null,
  };

  void preloadResource({
    key: changesListCacheKey(defaultParams),
    loader: () => listChanges(defaultParams),
    staleMs: NAV_STALE_MS,
  }).catch(() => undefined);
}

function preloadSettingsLane() {
  void preloadResource({
    key: settingsProfileCacheKey(),
    loader: getSettingsProfile,
    staleMs: NAV_STALE_MS,
  }).catch(() => undefined);

  void preloadResource({
    key: settingsMcpTokensCacheKey(),
    loader: getMcpTokens,
    staleMs: NAV_STALE_MS,
  }).catch(() => undefined);
}

function preloadFamiliesLane() {
  void preloadResource({
    key: familiesListCacheKey(),
    loader: () => listFamilies(),
    staleMs: NAV_STALE_MS,
  }).catch(() => undefined);

  void preloadResource({
    key: familiesStatusCacheKey(),
    loader: getFamiliesStatus,
    staleMs: NAV_STALE_MS,
  }).catch(() => undefined);

  void preloadResource({
    key: familiesCoursesCacheKey(),
    loader: listFamilyCourses,
    staleMs: NAV_STALE_MS,
  }).catch(() => undefined);

  void preloadResource({
    key: familiesRawTypesCacheKey(),
    loader: () => listFamilyRawTypes(),
    staleMs: NAV_STALE_MS,
  }).catch(() => undefined);

  void preloadResource({
    key: familiesSuggestionsCacheKey({ status: "pending", limit: 100 }),
    loader: () => listFamilyRawTypeSuggestions({ status: "pending", limit: 100 }),
    staleMs: NAV_STALE_MS,
  }).catch(() => undefined);

  void preloadResource({
    key: manualEventsCacheKey(),
    loader: () => listManualEvents(),
    staleMs: NAV_STALE_MS,
  }).catch(() => undefined);
}

function preloadManualLane() {
  void preloadResource({
    key: manualEventsCacheKey(),
    loader: () => listManualEvents(),
    staleMs: NAV_STALE_MS,
  }).catch(() => undefined);

  void preloadResource({
    key: familiesListCacheKey(),
    loader: () => listFamilies(),
    staleMs: NAV_STALE_MS,
  }).catch(() => undefined);
}

export function preloadWorkspaceLane(href: string) {
  const pathname = normalizeWorkspacePath(href);

  if (pathname === "/" || pathname.startsWith("/initial-review")) {
    preloadOverviewLane();
    return;
  }
  if (pathname.startsWith("/sources")) {
    preloadSourcesLane();
    return;
  }
  if (pathname.startsWith("/changes")) {
    preloadChangesLane();
    return;
  }
  if (pathname.startsWith("/families")) {
    preloadFamiliesLane();
    return;
  }
  if (pathname.startsWith("/manual")) {
    preloadManualLane();
    return;
  }
  if (pathname.startsWith("/settings")) {
    preloadSettingsLane();
  }
}
