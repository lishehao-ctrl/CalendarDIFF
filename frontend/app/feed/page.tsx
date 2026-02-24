"use client";

import { BellRing } from "lucide-react";

import { AppNav } from "@/components/dashboard/app-nav";
import { DiffSection } from "@/components/dashboard/sections/diff-section";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { useDashboardData } from "@/lib/hooks/use-dashboard-data";

export default function FeedPage() {
  const {
    configError,
    showDevTools,
    toasts,
    users,
    activeUserId,
    usersLoading,
    usersError,
    handleActiveUserChange,
    activeSourceId,
    changeFilter,
    setChangeFilter,
    changeSourceTypeFilter,
    setChangeSourceTypeFilter,
    feedTermScope,
    setFeedTermScope,
    feedTermId,
    setFeedTermId,
    activeUserTerms,
    filteredChanges,
    changesLoading,
    changesError,
    handleRefreshChanges,
    handleToggleViewed,
    handleDownloadEvidence,
    changeNotes,
    setChangeNote,
    getTaskDisplayTitle,
    getCourseDisplayLabel,
  } = useDashboardData();

  return (
    <div className="container py-4 md:py-6">
      <div className="mx-auto max-w-6xl space-y-4 md:space-y-6">
        <header className="animate-fade-in rounded-2xl border border-line bg-white/90 p-5 shadow-card">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h1 className="inline-flex items-center gap-2 text-2xl font-semibold [font-family:var(--font-heading)] md:text-3xl">
                <BellRing className="h-6 w-6 text-accent" />
                Feed
              </h1>
              <p className="mt-1 text-sm text-muted">
                Review aggregated changes across email and calendar inputs with user and term filters.
              </p>
            </div>
            <AppNav current="feed" activeUserId={activeUserId} activeInputId={activeSourceId} showDev={showDevTools} />
          </div>
        </header>

        {configError ? (
          <Alert>
            <AlertTitle>Configuration Missing</AlertTitle>
            <AlertDescription>{configError}</AlertDescription>
          </Alert>
        ) : null}

        <Card className="animate-fade-in">
          <CardHeader>
            <CardTitle>User Scope</CardTitle>
            <CardDescription>Feed defaults to the selected user context.</CardDescription>
          </CardHeader>
          <CardContent>
            {usersError ? (
              <Alert>
                <AlertTitle>User Load Failed</AlertTitle>
                <AlertDescription>{usersError}</AlertDescription>
              </Alert>
            ) : usersLoading ? (
              <Skeleton className="h-10" />
            ) : !users.length ? (
              <Alert>
                <AlertTitle>No User</AlertTitle>
                <AlertDescription>Initialize user settings first to load feed data.</AlertDescription>
              </Alert>
            ) : (
              <div className="max-w-md space-y-2">
                <Label htmlFor="feed-user">User</Label>
                <Select
                  id="feed-user"
                  value={activeUserId ? String(activeUserId) : ""}
                  onChange={(event) => {
                    const parsed = Number(event.target.value);
                    if (Number.isInteger(parsed) && parsed > 0) {
                      void handleActiveUserChange(parsed);
                    }
                  }}
                >
                  {users.map((user) => (
                    <option key={user.id} value={String(user.id)}>
                      {user.id} - {user.name}
                    </option>
                  ))}
                </Select>
              </div>
            )}
          </CardContent>
        </Card>

        <DiffSection
          changeFilter={changeFilter}
          onChangeFilter={setChangeFilter}
          changeSourceTypeFilter={changeSourceTypeFilter}
          onChangeSourceTypeFilter={setChangeSourceTypeFilter}
          feedTermScope={feedTermScope}
          onFeedTermScopeChange={setFeedTermScope}
          feedTermId={feedTermId}
          onFeedTermIdChange={setFeedTermId}
          activeUserTerms={activeUserTerms}
          changesError={changesError}
          changesLoading={changesLoading}
          filteredChanges={filteredChanges}
          changeNotes={changeNotes}
          onChangeNote={setChangeNote}
          onToggleViewed={handleToggleViewed}
          onDownloadEvidence={handleDownloadEvidence}
          onRefreshChanges={handleRefreshChanges}
          getTaskDisplayTitle={getTaskDisplayTitle}
          getCourseDisplayLabel={getCourseDisplayLabel}
        />
      </div>

      <div className="fixed bottom-4 right-4 z-50 space-y-2">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={cn(
              "max-w-[420px] rounded-xl px-4 py-3 text-sm text-white shadow-xl",
              toast.tone === "success" && "bg-emerald-700",
              toast.tone === "error" && "bg-rose-700",
              toast.tone === "info" && "bg-slate-800"
            )}
          >
            {toast.message}
          </div>
        ))}
      </div>
    </div>
  );
}
