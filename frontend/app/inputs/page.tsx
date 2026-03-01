"use client";

import { useEffect } from "react";
import { Inbox, Link2, Loader2, RefreshCw, Trash2 } from "lucide-react";

import { DashboardPage, DashboardPageHeader } from "@/components/dashboard/page-shell";
import { SectionState } from "@/components/dashboard/section-state";
import { DashboardToastStack } from "@/components/dashboard/toast-stack";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useInputsSettingsData } from "@/lib/hooks/use-inputs-settings-data";

export default function InputsPage() {
  const {
    configError,
    toasts,
    needsOnboarding,
    sourceRows,
    sourcesLoading,
    sourcesError,
    activeSourceId,
    deletingSourceId,
    connectingGmail,
    handleRefresh,
    handleDeleteSource,
    handleConnectGmail,
  } = useInputsSettingsData();

  useEffect(() => {
    if (!needsOnboarding) {
      return;
    }
    window.location.replace("/ui/onboarding");
  }, [needsOnboarding]);

  const activeSources = sourceRows.filter((row) => row.is_active);
  const inactiveCount = sourceRows.length - activeSources.length;

  return (
    <DashboardPage>
      <DashboardPageHeader
        icon={Inbox}
        title="Sources"
        description="Manage Gmail and calendar sources."
        current="inputs"
        activeInputId={activeSourceId}
        showOnboardingNav={needsOnboarding}
        actions={
          <Button variant="secondary" asChild>
            <a href="/ui/processing">Open Processing</a>
          </Button>
        }
      />

      {configError ? (
        <Alert>
          <AlertTitle>Configuration Missing</AlertTitle>
          <AlertDescription>{configError}</AlertDescription>
        </Alert>
      ) : null}

      <Card className="animate-in">
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <CardTitle>Source Management</CardTitle>
              <CardDescription>Connect multiple Gmail mailboxes and deactivate unused sources.</CardDescription>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Button variant="secondary" onClick={() => void handleRefresh()} disabled={sourcesLoading}>
                {sourcesLoading ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <RefreshCw className="mr-2 h-4 w-4" />
                )}
                Refresh
              </Button>
              <Button onClick={() => void handleConnectGmail()} disabled={connectingGmail}>
                {connectingGmail ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Link2 className="mr-2 h-4 w-4" />}
                Connect Gmail
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {inactiveCount > 0 ? (
            <Alert>
              <AlertTitle>Inactive Sources Hidden from Runtime</AlertTitle>
              <AlertDescription>
                {inactiveCount} inactive source{inactiveCount > 1 ? "s are" : " is"} retained for audit history.
              </AlertDescription>
            </Alert>
          ) : null}

          <SectionState
            isLoading={sourcesLoading}
            error={sourcesError}
            isEmpty={!sourcesLoading && !sourcesError && activeSources.length === 0}
            loadingRows={3}
            errorTitle="Failed to Load Sources"
            emptyTitle="No Active Sources"
            emptyDescription="Complete onboarding first, then connect sources from this page."
          >
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Source</TableHead>
                  <TableHead>Kind</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Last Polled</TableHead>
                  <TableHead>Last Error</TableHead>
                  <TableHead className="w-[220px]">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {activeSources.map((row) => {
                  const deleting = deletingSourceId === row.source_id;
                  const isCalendar = row.source_kind === "calendar";
                  return (
                    <TableRow key={row.source_id}>
                      <TableCell className="font-medium">
                        <div>{row.display_name ?? `${row.provider}:${row.source_key.slice(0, 8)}`}</div>
                        <div className="mt-1 text-xs text-muted">{`source-${row.source_id}`}</div>
                      </TableCell>
                      <TableCell>
                        <Badge variant={row.source_kind === "email" ? "warning" : "muted"}>
                          {String(row.source_kind).toUpperCase()}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <Badge variant="success">active</Badge>
                      </TableCell>
                      <TableCell>{row.last_polled_at ?? "-"}</TableCell>
                      <TableCell>{row.last_error_code ?? "-"}</TableCell>
                      <TableCell>
                        {isCalendar ? (
                          <Button size="sm" variant="outline" disabled>
                            Managed via source config
                          </Button>
                        ) : (
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => void handleDeleteSource(row.source_id)}
                            disabled={deletingSourceId !== null}
                          >
                            {deleting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Trash2 className="mr-2 h-4 w-4" />}
                            Deactivate
                          </Button>
                        )}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </SectionState>
        </CardContent>
      </Card>

      <DashboardToastStack toasts={toasts} />
    </DashboardPage>
  );
}
