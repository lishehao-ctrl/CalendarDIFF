import { Clock3, Loader2, RefreshCw } from "lucide-react";

import { SectionState } from "@/components/dashboard/section-state";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Source } from "@/lib/types";

type ProcessingSectionProps = {
  sources: Source[];
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
  sources,
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
  const syncingSource = manualSyncingSourceId ? sources.find((source) => source.id === manualSyncingSourceId) : null;
  const busySource = manualSyncBusySourceId ? sources.find((source) => source.id === manualSyncBusySourceId) : null;

  return (
    <section id="processing" className="section-anchor">
      <Card className="animate-in">
        <CardHeader>
          <CardTitle>Input Queue and Manual Sync</CardTitle>
          <CardDescription>Choose an input, run manual sync, and inspect the latest queue state.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-end gap-3">
            <div className="min-w-[240px] flex-1 space-y-2">
              <Label htmlFor="active-source">Active Input</Label>
              <Select
                id="active-source"
                value={activeSourceId ? String(activeSourceId) : ""}
                onChange={(event) => {
                  const value = Number(event.target.value);
                  if (Number.isInteger(value) && value > 0) {
                    void onActiveSourceChange(value);
                  }
                }}
                disabled={!sources.length}
              >
                <option value="">Select an input</option>
                {sources.map((source) => (
                  <option key={source.id} value={String(source.id)}>
                    {source.id} - {source.display_label}
                  </option>
                ))}
              </Select>
            </div>
            <Button variant="secondary" onClick={() => void onRefreshSources()} disabled={sourcesLoading}>
              {sourcesLoading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-2 h-4 w-4" />}
              Refresh Inputs
            </Button>
          </div>

          {manualSyncingSourceId !== null ? (
            <Alert>
              <AlertTitle className="flex items-center gap-2">
                <Loader2 className="h-4 w-4 animate-spin" />
                Attempting sync...
              </AlertTitle>
              <AlertDescription>
                {syncingSource ? `Input "${syncingSource.display_label}" is synchronizing.` : "Manual sync is in progress."}
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
                      ? `${busySource ? `Input "${busySource.display_label}"` : "This input"} is still syncing. Click Retry now.`
                      : `${busySource ? `Input "${busySource.display_label}"` : "This input"} is syncing. Auto retry in ${
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
            isEmpty={!sourcesLoading && !sourcesError && sources.length === 0}
            loadingRows={3}
            errorTitle="Input List Failed"
            emptyTitle="Empty Inputs"
            emptyDescription="Create your first input in Inputs workspace."
          >
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Interval</TableHead>
                  <TableHead>Last Result</TableHead>
                  <TableHead>Next Check</TableHead>
                  <TableHead>Last Checked</TableHead>
                  <TableHead className="w-[220px]">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sources.map((source) => (
                  <TableRow key={source.id}>
                    <TableCell className="font-medium">
                      <div>{source.display_label}</div>
                      <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted">
                        <span>{`input-${source.id}`}</span>
                        <Badge variant="muted">{source.term_label ?? "Global"}</Badge>
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge variant={readSourceHealthVariant(source)}>{readSourceHealthLabel(source)}</Badge>
                    </TableCell>
                    <TableCell>
                      <Badge variant={source.type === "email" ? "warning" : "muted"}>{source.type.toUpperCase()}</Badge>
                    </TableCell>
                    <TableCell>{source.interval_minutes} min</TableCell>
                    <TableCell>{source.last_result ?? "-"}</TableCell>
                    <TableCell>{source.next_check_at ?? "-"}</TableCell>
                    <TableCell>{source.last_checked_at ?? "-"}</TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-2">
                        <Button size="sm" onClick={() => void onRunManualSync(source.id)} disabled={manualSyncingSourceId !== null}>
                          {manualSyncingSourceId === source.id ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                          {manualSyncingSourceId === source.id ? "Syncing..." : "Sync now"}
                        </Button>
                        <Button size="sm" variant="secondary" asChild>
                          <a href={`/ui/runs?input_id=${source.id}`}>
                            <Clock3 className="mr-2 h-4 w-4" />
                            Run history
                          </a>
                        </Button>
                      </div>
                      {source.last_error ? <div className="mt-2 text-xs text-rose-700">{source.last_error}</div> : null}
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

function readSourceHealthVariant(source: Source): "success" | "warning" | "danger" {
  const failedStatuses = new Set(["FETCH_FAILED", "PARSE_FAILED", "DIFF_FAILED", "EMAIL_FAILED"]);
  if ((source.last_result && failedStatuses.has(source.last_result)) || source.last_error) {
    return "danger";
  }
  if (isSourceStale(source)) {
    return "warning";
  }
  return "success";
}

function readSourceHealthLabel(source: Source): string {
  const variant = readSourceHealthVariant(source);
  if (variant === "danger") {
    return "failed";
  }
  if (variant === "warning") {
    return "stale";
  }
  return "healthy";
}

function isSourceStale(source: Source): boolean {
  if (!source.last_checked_at) {
    return false;
  }
  const checkedTs = Date.parse(source.last_checked_at);
  if (Number.isNaN(checkedTs)) {
    return false;
  }
  const thresholdMs = source.interval_minutes * 2 * 60 * 1000;
  return Date.now() - checkedTs > thresholdMs;
}
