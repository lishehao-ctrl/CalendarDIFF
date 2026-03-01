import { Loader2, RefreshCw } from "lucide-react";

import { SectionState } from "@/components/dashboard/section-state";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { InputSource } from "@/lib/types";

type ProcessingSectionProps = {
  sourceRows: InputSource[];
  activeSourceId: number | null;
  sourcesLoading: boolean;
  sourcesError: string | null;
  manualSyncingSourceId: number | null;
  manualSyncBusySourceId: number | null;
  manualSyncBusyMessage: string | null;
  manualSyncRetryAfterSeconds: number | null;
  manualSyncAutoRetried: boolean;
  onActiveSourceChange: (sourceId: number) => void | Promise<void>;
  onRefreshSources: () => void | Promise<void>;
  onRunManualSync: (sourceId: number) => void | Promise<void>;
  onRetryManualSyncBusy: () => void | Promise<void>;
};

export function ProcessingSection({
  sourceRows,
  activeSourceId,
  sourcesLoading,
  sourcesError,
  manualSyncingSourceId,
  manualSyncBusySourceId,
  manualSyncBusyMessage,
  manualSyncRetryAfterSeconds,
  manualSyncAutoRetried,
  onActiveSourceChange,
  onRefreshSources,
  onRunManualSync,
  onRetryManualSyncBusy,
}: ProcessingSectionProps) {
  const syncingSource = manualSyncingSourceId ? sourceRows.find((source) => source.source_id === manualSyncingSourceId) : null;
  const busySource = manualSyncBusySourceId ? sourceRows.find((source) => source.source_id === manualSyncBusySourceId) : null;

  return (
    <section id="processing" className="section-anchor">
      <Card className="animate-in">
        <CardHeader>
          <CardTitle>Source Queue and Manual Sync</CardTitle>
          <CardDescription>Choose a source, run manual sync, and inspect the latest queue state.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-end gap-3">
            <div className="min-w-[240px] flex-1 space-y-2">
              <Label htmlFor="active-source">Active Source</Label>
              <Select
                id="active-source"
                value={activeSourceId ? String(activeSourceId) : ""}
                onChange={(event) => {
                  const value = Number(event.target.value);
                  if (Number.isInteger(value) && value > 0) {
                    void onActiveSourceChange(value);
                  }
                }}
                disabled={!sourceRows.length}
              >
                <option value="">Select a source</option>
                {sourceRows.map((source) => (
                  <option key={source.source_id} value={String(source.source_id)}>
                    {source.source_id} - {readSourceLabel(source)}
                  </option>
                ))}
              </Select>
            </div>
            <Button variant="secondary" onClick={() => void onRefreshSources()} disabled={sourcesLoading}>
              {sourcesLoading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-2 h-4 w-4" />}
              Refresh Sources
            </Button>
          </div>

          {manualSyncingSourceId !== null ? (
            <Alert>
              <AlertTitle className="flex items-center gap-2">
                <Loader2 className="h-4 w-4 animate-spin" />
                Attempting sync...
              </AlertTitle>
              <AlertDescription>
                {syncingSource ? `Source "${readSourceLabel(syncingSource)}" is synchronizing.` : "Manual sync is in progress."}
              </AlertDescription>
            </Alert>
          ) : null}

          {manualSyncBusySourceId !== null ? (
            <Alert>
              <AlertTitle>Sync in progress</AlertTitle>
              <AlertDescription>
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <span>
                    {manualSyncAutoRetried
                      ? `${busySource ? `Source "${readSourceLabel(busySource)}"` : "This source"} is still syncing. Click Retry now.`
                      : `${busySource ? `Source "${readSourceLabel(busySource)}"` : "This source"} is syncing. Auto retry in ${
                          manualSyncRetryAfterSeconds ?? 10
                        }s.`}
                    {manualSyncBusyMessage ? ` (${manualSyncBusyMessage})` : ""}
                  </span>
                  <Button size="sm" variant="secondary" onClick={() => void onRetryManualSyncBusy()} disabled={manualSyncingSourceId !== null}>
                    Retry now
                  </Button>
                </div>
              </AlertDescription>
            </Alert>
          ) : null}

          <SectionState
            isLoading={sourcesLoading}
            error={sourcesError}
            isEmpty={!sourcesLoading && !sourcesError && sourceRows.length === 0}
            loadingRows={3}
            errorTitle="Source List Failed"
            emptyTitle="Empty Sources"
            emptyDescription="Finish onboarding to create the first source."
          >
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Kind</TableHead>
                  <TableHead>Interval</TableHead>
                  <TableHead>Last Error Code</TableHead>
                  <TableHead>Next Poll</TableHead>
                  <TableHead>Last Polled</TableHead>
                  <TableHead className="w-[220px]">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sourceRows.map((source) => (
                  <TableRow key={source.source_id}>
                    <TableCell className="font-medium">
                      <div>{readSourceLabel(source)}</div>
                      <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted">
                        <span>{`source-${source.source_id}`}</span>
                        <Badge variant="muted">{source.provider}</Badge>
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge variant={readSourceHealthVariant(source)}>{readSourceHealthLabel(source)}</Badge>
                    </TableCell>
                    <TableCell>
                      <Badge variant={source.source_kind === "email" ? "warning" : "muted"}>
                        {String(source.source_kind).toUpperCase()}
                      </Badge>
                    </TableCell>
                    <TableCell>{Math.max(1, Math.round(source.poll_interval_seconds / 60))} min</TableCell>
                    <TableCell>{source.last_error_code ?? "-"}</TableCell>
                    <TableCell>{source.next_poll_at ?? "-"}</TableCell>
                    <TableCell>{source.last_polled_at ?? "-"}</TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-2">
                        <Button
                          size="sm"
                          onClick={() => void onRunManualSync(source.source_id)}
                          disabled={manualSyncingSourceId !== null}
                        >
                          {manualSyncingSourceId === source.source_id ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                          {manualSyncingSourceId === source.source_id ? "Syncing..." : "Sync now"}
                        </Button>
                      </div>
                      {source.last_error_message ? <div className="mt-2 text-xs text-rose-700">{source.last_error_message}</div> : null}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </SectionState>
        </CardContent>
      </Card>
    </section>
  );
}

function readSourceLabel(source: InputSource): string {
  if (source.display_name && source.display_name.trim()) {
    return source.display_name.trim();
  }
  return `${source.provider}:${source.source_key.slice(0, 8)}`;
}

function readSourceHealthVariant(source: InputSource): "success" | "warning" | "danger" {
  if (source.last_error_code || source.last_error_message) {
    return "danger";
  }
  if (isSourceStale(source)) {
    return "warning";
  }
  return "success";
}

function readSourceHealthLabel(source: InputSource): string {
  const variant = readSourceHealthVariant(source);
  if (variant === "danger") {
    return "failed";
  }
  if (variant === "warning") {
    return "stale";
  }
  return "healthy";
}

function isSourceStale(source: InputSource): boolean {
  if (!source.last_polled_at) {
    return false;
  }
  const checkedTs = Date.parse(source.last_polled_at);
  if (Number.isNaN(checkedTs)) {
    return false;
  }
  const thresholdMs = source.poll_interval_seconds * 2 * 1000;
  return Date.now() - checkedTs > thresholdMs;
}
