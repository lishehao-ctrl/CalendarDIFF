"use client";

import { useMemo, useState } from "react";
import { Link2, RefreshCcw, ShieldCheck, ShieldX, Unlink2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { EmptyState, ErrorState, LoadingState } from "@/components/data-states";
import { batchDecideLinkAlerts, batchDecideLinkCandidates, decideLinkAlert, decideLinkCandidate, deleteLinkBlock, deleteReviewLink, getReviewSummary, listLinkAlerts, listLinkBlocks, listLinkCandidates, listReviewLinks, relinkObservation } from "@/lib/api/review";
import { formatDateTime, formatStatusLabel } from "@/lib/presenters";
import type { LinkAlert, LinkBlock, LinkCandidate, LinkRow, ReviewSummary } from "@/lib/types";
import { useApiResource } from "@/lib/use-api-resource";

type Banner = {
  tone: "info" | "error";
  text: string;
} | null;

const blankRelink = {
  source_id: "",
  external_event_id: "",
  entity_uid: "",
  note: ""
};

export function LinkReviewPanel() {
  const summary = useApiResource<ReviewSummary>(() => getReviewSummary(), []);
  const candidates = useApiResource<LinkCandidate[]>(() => listLinkCandidates({ status: "pending", limit: 50 }), []);
  const links = useApiResource<LinkRow[]>(() => listReviewLinks({ limit: 50 }), []);
  const alerts = useApiResource<LinkAlert[]>(() => listLinkAlerts({ status: "pending", limit: 50 }), []);
  const blocks = useApiResource<LinkBlock[]>(() => listLinkBlocks({ limit: 50 }), []);

  const [busy, setBusy] = useState<string | null>(null);
  const [banner, setBanner] = useState<Banner>(null);
  const [relinkForm, setRelinkForm] = useState(blankRelink);

  const candidateIds = useMemo(() => (candidates.data || []).map((row) => row.id), [candidates.data]);
  const alertIds = useMemo(() => (alerts.data || []).map((row) => row.id), [alerts.data]);

  async function refreshAll() {
    await Promise.all([
      candidates.refresh(),
      links.refresh(),
      alerts.refresh(),
      blocks.refresh(),
      summary.refresh()
    ]);
  }

  async function candidateDecision(id: number, decision: "approve" | "reject") {
    setBusy(`candidate:${id}`);
    setBanner(null);
    try {
      await decideLinkCandidate(id, { decision, note: `ui_${decision}` });
      setBanner({ tone: "info", text: `Candidate #${id} ${decision}d.` });
      await refreshAll();
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : "Candidate decision failed" });
    } finally {
      setBusy(null);
    }
  }

  async function batchCandidateDecision(decision: "approve" | "reject") {
    if (candidateIds.length === 0) {
      return;
    }
    setBusy(`candidate-batch:${decision}`);
    setBanner(null);
    try {
      await batchDecideLinkCandidates({ ids: candidateIds, decision, note: `ui_batch_${decision}` });
      setBanner({ tone: "info", text: `Applied ${decision} to ${candidateIds.length} visible candidates.` });
      await refreshAll();
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : "Batch candidate decision failed" });
    } finally {
      setBusy(null);
    }
  }

  async function alertDecision(id: number, action: "dismiss" | "mark-safe") {
    setBusy(`alert:${id}`);
    setBanner(null);
    try {
      await decideLinkAlert(id, action, { note: `ui_${action}` });
      setBanner({ tone: "info", text: `Alert #${id} ${action.replace("-", " ")} complete.` });
      await refreshAll();
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : "Alert decision failed" });
    } finally {
      setBusy(null);
    }
  }

  async function batchAlertDecision(decision: "dismiss" | "mark_safe") {
    if (alertIds.length === 0) {
      return;
    }
    setBusy(`alert-batch:${decision}`);
    setBanner(null);
    try {
      await batchDecideLinkAlerts({ ids: alertIds, decision, note: `ui_batch_${decision}` });
      setBanner({ tone: "info", text: `Applied ${decision} to ${alertIds.length} visible alerts.` });
      await refreshAll();
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : "Batch alert decision failed" });
    } finally {
      setBusy(null);
    }
  }

  async function unlink(id: number) {
    setBusy(`link:${id}`);
    setBanner(null);
    try {
      await deleteReviewLink(id, { block: true, note: "ui_unlink" });
      setBanner({ tone: "info", text: `Link #${id} removed and blocked for re-link safety.` });
      await refreshAll();
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : "Unlink failed" });
    } finally {
      setBusy(null);
    }
  }

  async function unblock(blockId: number) {
    setBusy(`block:${blockId}`);
    setBanner(null);
    try {
      await deleteLinkBlock(blockId);
      setBanner({ tone: "info", text: `Block #${blockId} removed.` });
      await refreshAll();
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : "Unblock failed" });
    } finally {
      setBusy(null);
    }
  }

  function primeRelink(payload: { source_id: number; external_event_id: string; entity_uid: string }) {
    setRelinkForm({
      source_id: String(payload.source_id),
      external_event_id: payload.external_event_id,
      entity_uid: payload.entity_uid,
      note: ""
    });
  }

  async function submitRelink() {
    if (!relinkForm.source_id || !relinkForm.external_event_id || !relinkForm.entity_uid) {
      return;
    }
    setBusy("relink");
    setBanner(null);
    try {
      await relinkObservation({
        source_id: Number(relinkForm.source_id),
        external_event_id: relinkForm.external_event_id,
        entity_uid: relinkForm.entity_uid,
        clear_block: true,
        note: relinkForm.note || null
      });
      setBanner({ tone: "info", text: `Relinked ${relinkForm.external_event_id} to ${relinkForm.entity_uid}.` });
      setRelinkForm(blankRelink);
      await refreshAll();
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : "Relink failed" });
    } finally {
      setBusy(null);
    }
  }

  if (summary.loading || candidates.loading || links.loading || alerts.loading || blocks.loading) {
    return <LoadingState label="link review" />;
  }
  if (summary.error || candidates.error || links.error || alerts.error || blocks.error) {
    return <ErrorState message={summary.error || candidates.error || links.error || alerts.error || blocks.error || "Unknown error"} />;
  }

  return (
    <div className="space-y-5">
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Card className="p-5">
          <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Pending candidates</p>
          <p className="mt-3 text-3xl font-semibold">{summary.data?.link_candidates_pending ?? 0}</p>
          <p className="mt-2 text-sm text-[#596270]">Ambiguous source-to-entity matches waiting for human confirmation.</p>
        </Card>
        <Card className="p-5">
          <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Pending alerts</p>
          <p className="mt-3 text-3xl font-semibold">{summary.data?.link_alerts_pending ?? 0}</p>
          <p className="mt-2 text-sm text-[#596270]">Auto-links that still require policy review before you trust them.</p>
        </Card>
        <Card className="p-5">
          <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Active links</p>
          <p className="mt-3 text-3xl font-semibold">{links.data?.length ?? 0}</p>
          <p className="mt-2 text-sm text-[#596270]">Current link graph visible through the review API window.</p>
        </Card>
        <Card className="p-5">
          <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Manual blocks</p>
          <p className="mt-3 text-3xl font-semibold">{blocks.data?.length ?? 0}</p>
          <p className="mt-2 text-sm text-[#596270]">Explicit “do not link” safeguards created by human review.</p>
        </Card>
      </div>

      {banner ? (
        <Card className={banner.tone === "error" ? "border-[#efc4b5] bg-[#fff3ef] p-4" : "border-[rgba(31,94,255,0.18)] bg-[rgba(31,94,255,0.08)] p-4"}>
          <p className="text-sm text-[#314051]">{banner.text}</p>
        </Card>
      ) : null}

      <div className="grid gap-5 xl:grid-cols-[1.02fr_0.98fr_1fr]">
        <Card className="p-5">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Candidate queue</p>
              <h3 className="mt-3 text-xl font-semibold">Link candidates</h3>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button size="sm" variant="ghost" onClick={() => void batchCandidateDecision("reject")} disabled={candidateIds.length === 0 || busy === "candidate-batch:reject"}>
                <ShieldX className="mr-2 h-4 w-4" />
                Reject visible
              </Button>
              <Button size="sm" onClick={() => void batchCandidateDecision("approve")} disabled={candidateIds.length === 0 || busy === "candidate-batch:approve"}>
                <ShieldCheck className="mr-2 h-4 w-4" />
                Approve visible
              </Button>
            </div>
          </div>
          <div className="mt-4 space-y-3">
            {(candidates.data || []).length === 0 ? (
              <EmptyState title="No pending candidates" description="Strong signals auto-link directly; ambiguous joins land here." />
            ) : (
              (candidates.data || []).map((row) => (
                <Card key={row.id} className="bg-white/60 p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="font-semibold text-ink">{row.external_event_id}</p>
                        <Badge tone="pending">{formatStatusLabel(row.reason_code)}</Badge>
                      </div>
                      <p className="mt-2 text-sm text-[#314051]">{row.proposed_entity?.course_best_display || row.proposed_entity_uid || "No proposed entity"}</p>
                      <div className="mt-2 flex flex-wrap gap-2 text-xs text-[#6d7885]">
                        <span>Source #{row.source_id}</span>
                        <span>•</span>
                        <span>Score {row.score?.toFixed(2) ?? "n/a"}</span>
                        {row.updated_at ? (
                          <>
                            <span>•</span>
                            <span>Updated {formatDateTime(row.updated_at)}</span>
                          </>
                        ) : null}
                      </div>
                    </div>
                    {row.proposed_entity_uid ? (
                      <Button size="sm" variant="ghost" onClick={() => primeRelink({ source_id: row.source_id, external_event_id: row.external_event_id, entity_uid: row.proposed_entity_uid as string })}>
                        Prime relink
                      </Button>
                    ) : null}
                  </div>
                  <div className="mt-4 flex flex-wrap gap-2">
                    <Button size="sm" variant="danger" onClick={() => void candidateDecision(row.id, "reject")} disabled={busy === `candidate:${row.id}`}>
                      Reject
                    </Button>
                    <Button size="sm" onClick={() => void candidateDecision(row.id, "approve")} disabled={busy === `candidate:${row.id}`}>
                      Approve
                    </Button>
                  </div>
                </Card>
              ))
            )}
          </div>
        </Card>

        <div className="space-y-5">
          <Card className="p-5">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Resolved graph</p>
                <h3 className="mt-3 text-xl font-semibold">Active links</h3>
              </div>
              <Badge tone="approved">{links.data?.length ?? 0}</Badge>
            </div>
            <div className="mt-4 space-y-3">
              {(links.data || []).length === 0 ? (
                <EmptyState title="No active links" description="Approved candidates and relinks will appear here." />
              ) : (
                (links.data || []).map((row) => (
                  <Card key={row.id} className="bg-white/60 p-4">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <div className="flex flex-wrap items-center gap-2">
                          <p className="font-semibold text-ink">{row.external_event_id}</p>
                          <Badge tone="approved">{formatStatusLabel(row.link_origin)}</Badge>
                        </div>
                        <p className="mt-2 text-sm text-[#314051]">{row.linked_entity?.course_best_display || row.entity_uid}</p>
                        <div className="mt-2 flex flex-wrap gap-2 text-xs text-[#6d7885]">
                          <span>{formatStatusLabel(row.source_kind)}</span>
                          <span>•</span>
                          <span>Score {row.link_score?.toFixed(2) ?? "n/a"}</span>
                        </div>
                      </div>
                      <Button size="sm" variant="ghost" onClick={() => primeRelink({ source_id: row.source_id, external_event_id: row.external_event_id, entity_uid: row.entity_uid })}>
                        Prepare relink
                      </Button>
                    </div>
                    <Button className="mt-4" size="sm" variant="ghost" onClick={() => void unlink(row.id)} disabled={busy === `link:${row.id}`}>
                      <Unlink2 className="mr-2 h-4 w-4" />
                      Unlink and block
                    </Button>
                  </Card>
                ))
              )}
            </div>
          </Card>

          <Card className="p-5">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Manual relink</p>
                <h3 className="mt-3 text-xl font-semibold">Repair a binding</h3>
              </div>
              <Link2 className="h-5 w-5 text-[#6d7885]" />
            </div>
            <div className="mt-4 space-y-3">
              <Input placeholder="source id" value={relinkForm.source_id} onChange={(event) => setRelinkForm((prev) => ({ ...prev, source_id: event.target.value }))} />
              <Input placeholder="external event id" value={relinkForm.external_event_id} onChange={(event) => setRelinkForm((prev) => ({ ...prev, external_event_id: event.target.value }))} />
              <Input placeholder="entity uid" value={relinkForm.entity_uid} onChange={(event) => setRelinkForm((prev) => ({ ...prev, entity_uid: event.target.value }))} />
              <Input placeholder="note (optional)" value={relinkForm.note} onChange={(event) => setRelinkForm((prev) => ({ ...prev, note: event.target.value }))} />
              <Button className="w-full" onClick={() => void submitRelink()} disabled={busy === "relink" || !relinkForm.source_id || !relinkForm.external_event_id || !relinkForm.entity_uid}>
                {busy === "relink" ? "Relinking..." : "Submit relink"}
              </Button>
            </div>
          </Card>

          <Card className="p-5">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Do-not-link list</p>
                <h3 className="mt-3 text-xl font-semibold">Blocks</h3>
              </div>
              <Badge tone="info">{blocks.data?.length ?? 0}</Badge>
            </div>
            <div className="mt-4 space-y-3">
              {(blocks.data || []).length === 0 ? (
                <EmptyState title="No manual blocks" description="Rejected candidates generate blocks; relinks can optionally clear them." />
              ) : (
                (blocks.data || []).map((row) => (
                  <Card key={row.id} className="bg-white/60 p-4">
                    <p className="font-semibold text-ink">{row.external_event_id}</p>
                    <p className="mt-2 text-sm text-[#314051]">Blocked entity {row.blocked_entity_uid}</p>
                    <p className="mt-2 text-xs text-[#6d7885]">Created {formatDateTime(row.created_at)}</p>
                    <Button className="mt-4" size="sm" variant="ghost" onClick={() => void unblock(row.id)} disabled={busy === `block:${row.id}`}>
                      <RefreshCcw className="mr-2 h-4 w-4" />
                      Remove block
                    </Button>
                  </Card>
                ))
              )}
            </div>
          </Card>
        </div>

        <Card className="p-5">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Risk desk</p>
              <h3 className="mt-3 text-xl font-semibold">Link alerts</h3>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button size="sm" variant="ghost" onClick={() => void batchAlertDecision("dismiss")} disabled={alertIds.length === 0 || busy === "alert-batch:dismiss"}>
                Dismiss visible
              </Button>
              <Button size="sm" onClick={() => void batchAlertDecision("mark_safe")} disabled={alertIds.length === 0 || busy === "alert-batch:mark_safe"}>
                Mark safe visible
              </Button>
            </div>
          </div>
          <div className="mt-4 space-y-3">
            {(alerts.data || []).length === 0 ? (
              <EmptyState title="No pending alerts" description="Auto-links without canonical changes would surface here for policy review." />
            ) : (
              (alerts.data || []).map((row) => (
                <Card key={row.id} className="bg-white/60 p-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="font-semibold text-ink">{row.external_event_id}</p>
                    <Badge tone="pending">{formatStatusLabel(row.risk_level || "medium")}</Badge>
                  </div>
                  <p className="mt-2 text-sm text-[#314051]">{row.linked_entity?.course_best_display || row.entity_uid}</p>
                  <div className="mt-2 flex flex-wrap gap-2 text-xs text-[#6d7885]">
                    <span>{formatStatusLabel(row.reason_code)}</span>
                    {row.reviewed_at ? (
                      <>
                        <span>•</span>
                        <span>Reviewed {formatDateTime(row.reviewed_at)}</span>
                      </>
                    ) : null}
                  </div>
                  <div className="mt-4 flex flex-wrap gap-2">
                    <Button size="sm" variant="ghost" onClick={() => void alertDecision(row.id, "dismiss")} disabled={busy === `alert:${row.id}`}>
                      Dismiss
                    </Button>
                    <Button size="sm" onClick={() => void alertDecision(row.id, "mark-safe")} disabled={busy === `alert:${row.id}`}>
                      Mark safe
                    </Button>
                  </div>
                </Card>
              ))
            )}
          </div>
        </Card>
      </div>
    </div>
  );
}
