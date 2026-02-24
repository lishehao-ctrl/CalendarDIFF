import { useEffect, useMemo, useState } from "react";

import { apiRequest } from "@/lib/api";
import { getRuntimeConfig } from "@/lib/config";
import { AppConfig, Source, SourceRun } from "@/lib/types";

const RUN_LIMIT_OPTIONS = [20, 50, 100, 200] as const;
export type RunLimitOption = (typeof RUN_LIMIT_OPTIONS)[number];

type SourceIdQueryParse = {
  sourceId: number | null;
  error: string | null;
};

export function useSourceRunsPage() {
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [configError, setConfigError] = useState<string | null>(null);

  const [sources, setSources] = useState<Source[]>([]);
  const [sourcesLoading, setSourcesLoading] = useState(false);
  const [sourcesError, setSourcesError] = useState<string | null>(null);

  const [sourceIdQueryError, setSourceIdQueryError] = useState<string | null>(null);
  const [selectedSourceId, setSelectedSourceId] = useState<number | null>(null);
  const [limit, setLimit] = useState<RunLimitOption>(20);

  const [runs, setRuns] = useState<SourceRun[]>([]);
  const [runsLoading, setRunsLoading] = useState(false);
  const [runsError, setRunsError] = useState<string | null>(null);
  const [runsLastRefreshedAt, setRunsLastRefreshedAt] = useState<Date | null>(null);

  useEffect(() => {
    const runtimeConfig = getRuntimeConfig();
    if (!runtimeConfig.apiKey) {
      setConfigError("Missing API key from /ui/app-config.js");
      return;
    }

    setConfig(runtimeConfig);

    const applySourceIdFromUrl = () => {
      const parsed = parseSourceIdFromLocation();
      setSelectedSourceId(parsed.sourceId);
      setSourceIdQueryError(parsed.error);
    };

    applySourceIdFromUrl();
    window.addEventListener("popstate", applySourceIdFromUrl);
    return () => {
      window.removeEventListener("popstate", applySourceIdFromUrl);
    };
  }, []);

  useEffect(() => {
    if (!config) {
      return;
    }
    void loadSources(config);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config]);

  const selectedSource = useMemo(() => {
    if (selectedSourceId === null) {
      return null;
    }
    return sources.find((item) => item.id === selectedSourceId) ?? null;
  }, [selectedSourceId, sources]);

  useEffect(() => {
    if (!config || !selectedSource) {
      setRuns([]);
      setRunsError(null);
      setRunsLastRefreshedAt(null);
      return;
    }
    setRunsLastRefreshedAt(null);
    void loadRuns(config, selectedSource.id, limit);
  }, [config, selectedSource, limit]);

  async function loadSources(runtimeConfig?: AppConfig) {
    const runtime = runtimeConfig ?? config;
    if (!runtime) {
      return;
    }

    setSourcesLoading(true);
    setSourcesError(null);
    try {
      const rows = await apiRequest<Source[]>(runtime, "/v1/inputs");
      setSources(rows);

      if (selectedSourceId !== null && !rows.some((item) => item.id === selectedSourceId)) {
        setSourceIdQueryError(`Input ${selectedSourceId} was not found.`);
        setSelectedSourceId(null);
      }
    } catch (error) {
      setSourcesError(toErrorMessage(error));
    } finally {
      setSourcesLoading(false);
    }
  }

  async function loadRuns(runtimeConfig: AppConfig, sourceId: number, selectedLimit: RunLimitOption) {
    setRunsLoading(true);
    setRunsError(null);
    try {
      const rows = await apiRequest<SourceRun[]>(runtimeConfig, `/v1/inputs/${sourceId}/runs?limit=${selectedLimit}`);
      setRuns(rows);
      setRunsLastRefreshedAt(new Date());
    } catch (error) {
      setRunsError(toErrorMessage(error));
    } finally {
      setRunsLoading(false);
    }
  }

  function selectSource(sourceId: number | null) {
    if (sourceId !== null && (!Number.isInteger(sourceId) || sourceId <= 0)) {
      setSourceIdQueryError(`Invalid input_id query parameter: ${sourceId}`);
      setSelectedSourceId(null);
      syncUrlSourceId(null);
      return;
    }
    setSelectedSourceId(sourceId);
    setSourceIdQueryError(null);
    syncUrlSourceId(sourceId);
  }

  function selectLimit(nextLimit: RunLimitOption) {
    setLimit(nextLimit);
  }

  async function handleRefresh() {
    await loadSources();
  }

  return {
    configError,
    sources,
    sourcesLoading,
    sourcesError,
    selectedSourceId,
    selectedSource,
    sourceIdQueryError,
    selectSource,
    runs,
    runsLoading,
    runsError,
    runsLastRefreshedAt,
    limit,
    runLimitOptions: RUN_LIMIT_OPTIONS,
    selectLimit,
    handleRefresh,
  };
}

function parseSourceIdFromLocation(): SourceIdQueryParse {
  if (typeof window === "undefined") {
    return { sourceId: null, error: null };
  }

  const params = new URLSearchParams(window.location.search);
  const rawSourceId = params.get("input_id");
  if (rawSourceId === null || rawSourceId.trim() === "") {
    return { sourceId: null, error: null };
  }

  const parsedSourceId = Number(rawSourceId);
  if (!Number.isInteger(parsedSourceId) || parsedSourceId <= 0) {
    return {
      sourceId: null,
      error: `Invalid input_id query parameter: ${rawSourceId}`,
    };
  }

  return { sourceId: parsedSourceId, error: null };
}

function syncUrlSourceId(sourceId: number | null): void {
  if (typeof window === "undefined") {
    return;
  }
  const url = new URL(window.location.href);
  if (sourceId === null) {
    url.searchParams.delete("input_id");
  } else {
    url.searchParams.set("input_id", String(sourceId));
  }
  window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
}

function toErrorMessage(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}
