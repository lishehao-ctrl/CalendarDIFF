import { CheckCircle2, Eye, Loader2, RefreshCw, Trash2 } from "lucide-react";

import { SectionState } from "@/components/dashboard/section-state";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmailQueueItem, EmailRoute } from "@/lib/types";

type EmailReviewSectionProps = {
  items: EmailQueueItem[];
  loading: boolean;
  error: string | null;
  refreshing: boolean;
  busyEmailId: string | null;
  onRefresh: () => void | Promise<void>;
  onApply: (emailId: string) => void | Promise<void>;
  onRoute: (emailId: string, route: EmailRoute) => void | Promise<void>;
  onMarkViewed: (emailId: string) => void | Promise<void>;
};

export function EmailReviewSection({
  items,
  loading,
  error,
  refreshing,
  busyEmailId,
  onRefresh,
  onApply,
  onRoute,
  onMarkViewed,
}: EmailReviewSectionProps) {
  return (
    <section className="section-anchor">
      <Card className="animate-in">
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <CardTitle>Email Review Queue</CardTitle>
              <CardDescription>
                Review deterministic email rule outputs and apply selected items to the canonical timeline.
              </CardDescription>
            </div>
            <Button variant="secondary" onClick={() => void onRefresh()} disabled={refreshing}>
              {refreshing ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-2 h-4 w-4" />}
              Refresh Queue
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <SectionState
            isLoading={loading}
            error={error}
            isEmpty={!loading && !error && items.length === 0}
            loadingRows={3}
            errorTitle="Failed to Load Queue"
            emptyTitle="No Review Items"
            emptyDescription="No emails currently require manual review."
          >
            <div className="stagger-fade space-y-3">
              {items.map((item) => {
                const busy = busyEmailId === item.email_id;
                return (
                  <article key={item.email_id} className="rounded-2xl border border-line bg-white p-4 shadow-card">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div className="space-y-1">
                        <h3 className="text-base font-semibold text-ink">{item.subject ?? item.email_id}</h3>
                        <p className="text-sm text-muted">
                          {item.from_addr ?? "Unknown sender"} · {item.date_rfc822 ?? "Unknown date"}
                        </p>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        <Badge variant="warning">{item.event_type ?? "unknown"}</Badge>
                        <Badge variant="muted">confidence {item.confidence.toFixed(2)}</Badge>
                        <Badge variant={item.flags.viewed ? "muted" : "warning"}>{item.flags.viewed ? "Viewed" : "Unviewed"}</Badge>
                      </div>
                    </div>

                    <div className="mt-3 grid gap-3 lg:grid-cols-2">
                      <div className="rounded-xl border border-line bg-slate-50/70 p-3">
                        <p className="text-xs font-semibold uppercase tracking-wide text-muted">Course Hints</p>
                        <div className="mt-2 flex flex-wrap gap-2">
                          {item.course_hints.length ? (
                            item.course_hints.map((hint) => (
                              <Badge key={`${item.email_id}-course-${hint}`} variant="muted">
                                {hint}
                              </Badge>
                            ))
                          ) : (
                            <span className="text-sm text-muted">No course hints.</span>
                          )}
                        </div>
                        <p className="mt-3 text-xs font-semibold uppercase tracking-wide text-muted">Reasons</p>
                        <ul className="mt-2 space-y-1 text-sm text-muted">
                          {item.reasons.length ? item.reasons.map((reason, idx) => <li key={`${item.email_id}-reason-${idx}`}>- {reason}</li>) : <li>- none</li>}
                        </ul>
                      </div>

                      <div className="rounded-xl border border-line bg-slate-50/70 p-3">
                        <p className="text-xs font-semibold uppercase tracking-wide text-muted">Action Items</p>
                        <div className="mt-2 space-y-2 text-sm text-muted">
                          {item.action_items.length ? (
                            item.action_items.map((action, idx) => (
                              <div key={`${item.email_id}-action-${idx}`} className="rounded-lg border border-line bg-white p-2">
                                <div>action: {action.action ?? "-"}</div>
                                <div>due: {action.due_iso ?? "-"}</div>
                                <div>where: {action.where ?? "-"}</div>
                              </div>
                            ))
                          ) : (
                            <p>No structured action items.</p>
                          )}
                        </div>
                      </div>
                    </div>

                    <details className="mt-3 rounded-xl border border-line bg-white">
                      <summary className="cursor-pointer px-3 py-2 text-sm font-medium text-ink">Rule analysis details</summary>
                      <div className="border-t border-line p-3 text-sm text-muted">
                        <p className="text-xs font-semibold uppercase tracking-wide text-muted">Matched snippets</p>
                        <ul className="mt-2 space-y-1">
                          {item.rule_analysis.matched_snippets.length ? (
                            item.rule_analysis.matched_snippets.map((row, idx) => (
                              <li key={`${item.email_id}-snippet-${idx}`}>
                                <span className="font-medium text-ink">{row.rule}:</span> {row.snippet}
                              </li>
                            ))
                          ) : (
                            <li>none</li>
                          )}
                        </ul>
                        <p className="mt-3 text-xs font-semibold uppercase tracking-wide text-muted">Drop reason codes</p>
                        <div className="mt-2 flex flex-wrap gap-2">
                          {item.rule_analysis.drop_reason_codes.length ? (
                            item.rule_analysis.drop_reason_codes.map((code) => (
                              <Badge key={`${item.email_id}-drop-${code}`} variant="muted">
                                {code}
                              </Badge>
                            ))
                          ) : (
                            <span>none</span>
                          )}
                        </div>
                      </div>
                    </details>

                    <div className="mt-3 flex flex-wrap items-center gap-2">
                      <Button onClick={() => void onApply(item.email_id)} disabled={busy}>
                        {busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <CheckCircle2 className="mr-2 h-4 w-4" />}
                        Apply
                      </Button>
                      <Button variant="secondary" onClick={() => void onMarkViewed(item.email_id)} disabled={busy}>
                        <Eye className="mr-2 h-4 w-4" />
                        Mark viewed
                      </Button>
                      <Button variant="outline" onClick={() => void onRoute(item.email_id, "archive")} disabled={busy}>
                        Archive
                      </Button>
                      <Button variant="outline" onClick={() => void onRoute(item.email_id, "drop")} disabled={busy}>
                        <Trash2 className="mr-2 h-4 w-4" />
                        Drop
                      </Button>
                    </div>
                  </article>
                );
              })}
            </div>
          </SectionState>
        </CardContent>
      </Card>
    </section>
  );
}
