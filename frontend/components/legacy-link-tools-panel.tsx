"use client";

import { useMemo, useState } from "react";
import { Link2, RefreshCcw, Unlink2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { EmptyState, ErrorState, LoadingState } from "@/components/data-states";
import {
  batchDecideLinkCandidates,
  decideLinkCandidate,
  deleteLinkBlock,
  deleteReviewLink,
  getReviewSummary,
  listLinkBlocks,
  listLinkCandidates,
  listReviewLinks,
  relinkObservation,
} from "@/lib/api/review";
import { formatDateTime, formatStatusLabel } from "@/lib/presenters";
import type { LinkBlock, LinkCandidate, LinkRow, ReviewSummary } from "@/lib/types";
import { useApiResource } from "@/lib/use-api-resource";

type Banner = {
  tone: "info" | "error";
  text: string;
} | null;

function LinkReviewError({ message }: { message: string }) {
  const showSourcesCta = message.includes("Connect at least one active source in Sources");
  return <ErrorState message={message} actionLabel={showSourcesCta ? "Open Sources" : undefined} actionHref={showSourcesCta ? "/sources" : undefined} />;
}

const blankRelink = {
  source_id: "",
  external_event_id: "",
  entity_uid: "",
  note: ""
};

export function LegacyLinkToolsPanel() {
  const summary = useApiResource<ReviewSummary>(() => getReviewSummary(), []);
  const candidates = useApiResource<LinkCandidate[]>(() => listLinkCandidates({ status: "pending", limit: 50 }), []);
  const links = useApiResource<LinkRow[]>(() => listReviewLinks({ limit: 50 }), []);
  const blocks = useApiResource<LinkBlock[]>(() => listLinkBlocks({ limit: 50 }), []);

  const [busy, setBusy] = useState<string | null>(null);
  const [banner, setBanner] = useState<Banner>(null);
  const [relinkForm, setRelinkForm] = useState(blankRelink);

  const candidateIds = useMemo(() => (candidates.data || []).map((row) => row.id), [candidates.data]);

  async function refreshAll() {
    await Promise.all([candidates.refresh(), links.refresh(), blocks.refresh(), summary.refresh()]);
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

  async function unlink(id: number) {
    setBusy(`link:${id}`);
    setBanner(null);
    try {
      await deleteReviewLink(id, { block: true, note: "ui_unlink" });
      setBanner({ tone: "info", text: `Link #${id} removed and blocked for safety.` });
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

  if (summary.loading || candidates.loading || links.loading || blocks.loading) {
    return <LoadingState label="legacy links" />;
  }
  if (summary.error || candidates.error || links.error || blocks.error) {
    return <LinkReviewError message={summary.error || candidates.error || links.error || blocks.error || "Unknown error"} />;
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 rounded-[1.2rem] border border-line/80 bg-white/72 px-4 py-3 shadow-[var(--shadow-panel)] md:flex-row md:items-center md:justify-between">
        <div className="flex flex-wrap items-center gap-2 text-sm text-[#596270]">
          <span className="rounded-full bg-[rgba(20,32,44,0.06)] px-3 py-1.5 text-ink">
            {summary.data?.link_candidates_pending ?? 0} candidates
          </span>
          <span className="rounded-full bg-[rgba(20,32,44,0.06)] px-3 py-1.5 text-ink">{links.data?.length ?? 0} links</span>
          <span className="rounded-full bg-[rgba(20,32,44,0.06)] px-3 py-1.5 text-ink">{blocks.data?.length ?? 0} blocks</span>
        </div>
        <p className="text-sm text-[#596270]">Updated {formatDateTime(summary.data?.generated_at, "Just now")}</p>
      </div>

      {banner ? (
        <Card className={banner.tone === "error" ? "border-[#efc4b5] bg-[#fff3ef] p-4" : "border-[rgba(31,94,255,0.18)] bg-[rgba(31,94,255,0.08)] p-4"}>
          <p className="text-sm text-[#314051]">{banner.text}</p>
        </Card>
      ) : null}

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.08fr)_minmax(320px,0.92fr)]">
        <Card className="p-4">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="max-w-2xl">
              <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Match queue</p>
              <h3 className="mt-2 text-lg font-semibold">Candidates</h3>
              <p className="mt-1 text-sm text-[#596270]">Approve or reject ambiguous matches.</p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button size="sm" variant="ghost" onClick={() => void batchCandidateDecision("reject")} disabled={candidateIds.length === 0 || busy === "candidate-batch:reject"}>
                Reject visible
              </Button>
              <Button size="sm" onClick={() => void batchCandidateDecision("approve")} disabled={candidateIds.length === 0 || busy === "candidate-batch:approve"}>
                Approve visible
              </Button>
            </div>
          </div>
          <div className="mt-4 space-y-3">
            {(candidates.data || []).length === 0 ? (
              <EmptyState title="No pending candidates" description="New ambiguous matches will appear here when they need review." />
            ) : (
              (candidates.data || []).map((row) => (
                <Card key={row.id} className="bg-white/60 p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="font-semibold text-ink">{row.external_event_id}</p>
                        <Badge tone="pending">{formatStatusLabel(row.status)}</Badge>
                      </div>
                      <p className="mt-2 text-sm text-[#314051]">{row.proposed_entity?.event_display?.display_label || row.proposed_entity_uid || "No proposed entity"}</p>
                      <div className="mt-2 flex flex-wrap gap-2 text-xs text-[#6d7885]">
                        <span>Source #{row.source_id}</span>
                        <span>•</span>
                        <span>Score {row.score?.toFixed(2) ?? "n/a"}</span>
                        <span>•</span>
                        <span>{formatStatusLabel(row.reason_code)}</span>
                      </div>
                    </div>
                    {row.proposed_entity_uid ? (
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => primeRelink({ source_id: row.source_id, external_event_id: row.external_event_id, entity_uid: row.proposed_entity_uid as string })}
                      >
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
          <Card className="p-4">
            <div className="flex items-start justify-between gap-4">
              <div className="max-w-2xl">
                <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Current bindings</p>
                <h3 className="mt-2 text-lg font-semibold">Active links</h3>
                <p className="mt-1 text-sm text-[#596270]">Trusted source-to-entity matches.</p>
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
                        <p className="mt-2 text-sm text-[#314051]">{row.linked_entity?.event_display?.display_label || row.entity_uid}</p>
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

          <Card className="p-4">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Manual repair</p>
                <h3 className="mt-2 text-lg font-semibold">Relink</h3>
                <p className="mt-1 text-sm text-[#596270]">Repair one binding directly.</p>
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

          <Card className="p-4">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Safeguards</p>
                <h3 className="mt-2 text-lg font-semibold">Blocks</h3>
                <p className="mt-1 text-sm text-[#596270]">Keep bad pairings from returning.</p>
              </div>
              <Badge tone="info">{blocks.data?.length ?? 0}</Badge>
            </div>
            <div className="mt-4 space-y-3">
              {(blocks.data || []).length === 0 ? (
                <EmptyState title="No manual blocks" description="Rejected candidates and manual unlink actions can create blocks." />
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
      </div>
    </div>
  );
}
