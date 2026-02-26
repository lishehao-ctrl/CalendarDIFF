import { Loader2, RefreshCw } from "lucide-react";

import { SectionState } from "@/components/dashboard/section-state";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Input } from "@/lib/types";

type ProcessingSectionProps = {
  inputs: Input[];
  activeInputId: number | null;
  inputsLoading: boolean;
  inputsError: string | null;
  manualSyncingInputId: number | null;
  manualSyncBusyInputId: number | null;
  manualSyncBusyMessage: string | null;
  manualSyncRetryAfterSeconds: number | null;
  manualSyncAutoRetried: boolean;
  onActiveInputChange: (inputId: number) => void | Promise<void>;
  onRefreshInputs: () => void | Promise<void>;
  onRunManualSync: (inputId: number) => void | Promise<void>;
  onRetryManualSyncBusy: () => void | Promise<void>;
};

export function ProcessingSection({
  inputs,
  activeInputId,
  inputsLoading,
  inputsError,
  manualSyncingInputId,
  manualSyncBusyInputId,
  manualSyncBusyMessage,
  manualSyncRetryAfterSeconds,
  manualSyncAutoRetried,
  onActiveInputChange,
  onRefreshInputs,
  onRunManualSync,
  onRetryManualSyncBusy,
}: ProcessingSectionProps) {
  const syncingInput = manualSyncingInputId ? inputs.find((input) => input.id === manualSyncingInputId) : null;
  const busyInput = manualSyncBusyInputId ? inputs.find((input) => input.id === manualSyncBusyInputId) : null;

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
                value={activeInputId ? String(activeInputId) : ""}
                onChange={(event) => {
                  const value = Number(event.target.value);
                  if (Number.isInteger(value) && value > 0) {
                    void onActiveInputChange(value);
                  }
                }}
                disabled={!inputs.length}
              >
                <option value="">Select an input</option>
                {inputs.map((input) => (
                  <option key={input.id} value={String(input.id)}>
                    {input.id} - {input.display_label}
                  </option>
                ))}
              </Select>
            </div>
            <Button variant="secondary" onClick={() => void onRefreshInputs()} disabled={inputsLoading}>
              {inputsLoading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-2 h-4 w-4" />}
              Refresh Inputs
            </Button>
          </div>

          {manualSyncingInputId !== null ? (
            <Alert>
              <AlertTitle className="flex items-center gap-2">
                <Loader2 className="h-4 w-4 animate-spin" />
                Attempting sync...
              </AlertTitle>
              <AlertDescription>
                {syncingInput ? `Input "${syncingInput.display_label}" is synchronizing.` : "Manual sync is in progress."}
              </AlertDescription>
            </Alert>
          ) : null}

          {manualSyncBusyInputId !== null ? (
            <Alert>
              <AlertTitle>Sync in progress</AlertTitle>
              <AlertDescription>
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <span>
                    {manualSyncAutoRetried
                      ? `${busyInput ? `Input "${busyInput.display_label}"` : "This input"} is still syncing. Click Retry now.`
                      : `${busyInput ? `Input "${busyInput.display_label}"` : "This input"} is syncing. Auto retry in ${
                          manualSyncRetryAfterSeconds ?? 10
                        }s.`}
                    {manualSyncBusyMessage ? ` (${manualSyncBusyMessage})` : ""}
                  </span>
                  <Button size="sm" variant="secondary" onClick={() => void onRetryManualSyncBusy()} disabled={manualSyncingInputId !== null}>
                    Retry now
                  </Button>
                </div>
              </AlertDescription>
            </Alert>
          ) : null}

          <SectionState
            isLoading={inputsLoading}
            error={inputsError}
            isEmpty={!inputsLoading && !inputsError && inputs.length === 0}
            loadingRows={3}
            errorTitle="Input List Failed"
            emptyTitle="Empty Inputs"
            emptyDescription="Finish onboarding to create the first ICS input."
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
                {inputs.map((input) => (
                  <TableRow key={input.id}>
                    <TableCell className="font-medium">
                      <div>{input.display_label}</div>
                      <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted">
                        <span>{`input-${input.id}`}</span>
                        <Badge variant="muted">{input.type === "email" ? "Global" : "Primary"}</Badge>
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge variant={readInputHealthVariant(input)}>{readInputHealthLabel(input)}</Badge>
                    </TableCell>
                    <TableCell>
                      <Badge variant={input.type === "email" ? "warning" : "muted"}>{input.type.toUpperCase()}</Badge>
                    </TableCell>
                    <TableCell>{input.interval_minutes} min</TableCell>
                    <TableCell>{input.last_result ?? "-"}</TableCell>
                    <TableCell>{input.next_check_at ?? "-"}</TableCell>
                    <TableCell>{input.last_checked_at ?? "-"}</TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-2">
                        <Button size="sm" onClick={() => void onRunManualSync(input.id)} disabled={manualSyncingInputId !== null}>
                          {manualSyncingInputId === input.id ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                          {manualSyncingInputId === input.id ? "Syncing..." : "Sync now"}
                        </Button>
                      </div>
                      {input.last_error ? <div className="mt-2 text-xs text-rose-700">{input.last_error}</div> : null}
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

function readInputHealthVariant(input: Input): "success" | "warning" | "danger" {
  const failedStatuses = new Set(["FETCH_FAILED", "PARSE_FAILED", "DIFF_FAILED", "EMAIL_FAILED"]);
  if ((input.last_result && failedStatuses.has(input.last_result)) || input.last_error) {
    return "danger";
  }
  if (isInputStale(input)) {
    return "warning";
  }
  return "success";
}

function readInputHealthLabel(input: Input): string {
  const variant = readInputHealthVariant(input);
  if (variant === "danger") {
    return "failed";
  }
  if (variant === "warning") {
    return "stale";
  }
  return "healthy";
}

function isInputStale(input: Input): boolean {
  if (!input.last_checked_at) {
    return false;
  }
  const checkedTs = Date.parse(input.last_checked_at);
  if (Number.isNaN(checkedTs)) {
    return false;
  }
  const thresholdMs = input.interval_minutes * 2 * 60 * 1000;
  return Date.now() - checkedTs > thresholdMs;
}
