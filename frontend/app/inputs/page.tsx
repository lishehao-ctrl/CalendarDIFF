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
    inputs,
    inputsLoading,
    inputsError,
    activeInputId,
    deletingInputId,
    connectingGmail,
    handleRefresh,
    handleDeleteInput,
    handleConnectGmail,
  } = useInputsSettingsData();

  useEffect(() => {
    if (!needsOnboarding) {
      return;
    }
    window.location.replace("/ui/onboarding");
  }, [needsOnboarding]);

  const activeInputs = inputs.filter((row) => row.is_active);
  const inactiveCount = inputs.length - activeInputs.length;

  return (
    <DashboardPage>
      <DashboardPageHeader
        icon={Inbox}
        title="Inputs"
        description="Manage Gmail input sources. ICS is configured via onboarding."
        current="inputs"
        activeInputId={activeInputId}
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
              <CardTitle>Input Management</CardTitle>
              <CardDescription>Connect multiple Gmail mailboxes and deactivate unused inputs.</CardDescription>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Button variant="secondary" onClick={() => void handleRefresh()} disabled={inputsLoading}>
                {inputsLoading ? (
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
              <AlertTitle>Inactive Inputs Hidden from Runtime</AlertTitle>
              <AlertDescription>
                {inactiveCount} inactive input{inactiveCount > 1 ? "s are" : " is"} retained for audit history.
              </AlertDescription>
            </Alert>
          ) : null}

          <SectionState
            isLoading={inputsLoading}
            error={inputsError}
            isEmpty={!inputsLoading && !inputsError && activeInputs.length === 0}
            loadingRows={3}
            errorTitle="Failed to Load Inputs"
            emptyTitle="No Active Inputs"
            emptyDescription="Complete onboarding first, then connect Gmail inputs from this page."
          >
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Input</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Last Checked</TableHead>
                  <TableHead>Last Result</TableHead>
                  <TableHead className="w-[220px]">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {activeInputs.map((row) => {
                  const deleting = deletingInputId === row.id;
                  const isIcs = row.type === "ics";
                  return (
                    <TableRow key={row.id}>
                      <TableCell className="font-medium">
                        <div>{row.display_label}</div>
                        <div className="mt-1 text-xs text-muted">{`input-${row.id}`}</div>
                      </TableCell>
                      <TableCell>
                        <Badge variant={row.type === "email" ? "warning" : "muted"}>{row.type.toUpperCase()}</Badge>
                      </TableCell>
                      <TableCell>
                        <Badge variant="success">active</Badge>
                      </TableCell>
                      <TableCell>{row.last_checked_at ?? "-"}</TableCell>
                      <TableCell>{row.last_result ?? "-"}</TableCell>
                      <TableCell>
                        {isIcs ? (
                          <Button size="sm" variant="outline" disabled>
                            Managed in onboarding
                          </Button>
                        ) : (
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => void handleDeleteInput(row.id)}
                            disabled={deletingInputId !== null}
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
