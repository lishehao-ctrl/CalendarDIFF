"use client";

import { useMemo, useState } from "react";
import { Check, Copy, KeyRound, ShieldX } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { EmptyState, ErrorState, LoadingState } from "@/components/data-states";
import { createMcpToken, getMcpTokens, revokeMcpToken, settingsMcpTokensCacheKey } from "@/lib/api/settings";
import { translate } from "@/lib/i18n/runtime";
import { formatDateTime } from "@/lib/presenters";
import { useApiResource } from "@/lib/use-api-resource";
import { workbenchStateSurfaceClassName, workbenchSupportPanelClassName } from "@/lib/workbench-styles";
import type { McpAccessToken, McpAccessTokenCreateResponse } from "@/lib/types";

const expiryOptions = [7, 30, 90, 365] as const;

type Banner = {
  tone: "info" | "error";
  text: string;
} | null;

type RevealPanelState = {
  tokenId: string;
  label: string;
  token: string;
} | null;

function tokenStatus(token: McpAccessToken) {
  if (token.revoked_at) return "revoked" as const;
  if (token.expires_at && new Date(token.expires_at).getTime() < Date.now()) return "expired" as const;
  return "active" as const;
}

function statusTone(status: ReturnType<typeof tokenStatus>) {
  switch (status) {
    case "active":
      return "approved";
    case "expired":
      return "pending";
    case "revoked":
      return "error";
    default:
      return "info";
  }
}

function statusLabel(status: ReturnType<typeof tokenStatus>) {
  switch (status) {
    case "active":
      return translate("settings.mcp.status.active");
    case "expired":
      return translate("settings.mcp.status.expired");
    case "revoked":
      return translate("settings.mcp.status.revoked");
    default:
      return translate("common.labels.unknown");
  }
}

function tokenSort(left: McpAccessToken, right: McpAccessToken) {
  const leftStatus = tokenStatus(left);
  const rightStatus = tokenStatus(right);
  const statusRank = {
    active: 0,
    expired: 1,
    revoked: 2,
  } as const;
  if (statusRank[leftStatus] !== statusRank[rightStatus]) {
    return statusRank[leftStatus] - statusRank[rightStatus];
  }
  const leftActivity = left.last_used_at || left.created_at;
  const rightActivity = right.last_used_at || right.created_at;
  return new Date(rightActivity).getTime() - new Date(leftActivity).getTime();
}

function upsertTokenRow(rows: McpAccessToken[] | null, nextRow: McpAccessToken) {
  const current = rows || [];
  const withoutCurrent = current.filter((row) => row.token_id !== nextRow.token_id);
  return [...withoutCurrent, nextRow].sort(tokenSort);
}

export function SettingsMcpAccessCard() {
  const tokens = useApiResource<McpAccessToken[]>(() => getMcpTokens(), [], [], {
    cacheKey: settingsMcpTokensCacheKey(),
  });

  const [createForm, setCreateForm] = useState({
    label: "",
    expiresInDays: String(expiryOptions[1]),
  });
  const [banner, setBanner] = useState<Banner>(null);
  const [creating, setCreating] = useState(false);
  const [revealPanel, setRevealPanel] = useState<RevealPanelState>(null);
  const [copied, setCopied] = useState(false);
  const [revokeConfirmId, setRevokeConfirmId] = useState<string | null>(null);
  const [revokingId, setRevokingId] = useState<string | null>(null);

  const sortedTokens = useMemo(() => [...(tokens.data || [])].sort(tokenSort), [tokens.data]);

  async function reloadTokens() {
    const rows = await getMcpTokens();
    tokens.setData(rows);
    return rows;
  }

  async function handleCreate() {
    const label = createForm.label.trim();
    const expiresInDays = Number(createForm.expiresInDays);
    if (!label || !Number.isFinite(expiresInDays)) {
      return;
    }

    setCreating(true);
    setBanner(null);
    setCopied(false);

    try {
      const created = await createMcpToken({
        label,
        expires_in_days: expiresInDays,
      });
      const { token, ...row } = created;
      tokens.setData((current) => upsertTokenRow(current, row));
      setRevealPanel({
        tokenId: created.token_id,
        label: created.label,
        token: created.token,
      });
      setCreateForm({
        label: "",
        expiresInDays: String(expiryOptions[1]),
      });

      try {
        await reloadTokens();
      } catch {
        setBanner({
          tone: "info",
          text: translate("settings.mcp.refreshWarning"),
        });
      }
    } catch (err) {
      setBanner({
        tone: "error",
        text: err instanceof Error ? err.message : translate("settings.mcp.createFailed"),
      });
    } finally {
      setCreating(false);
    }
  }

  async function handleCopyToken() {
    if (!revealPanel) return;

    try {
      if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(revealPanel.token);
      } else {
        throw new Error("Clipboard unavailable");
      }
      setCopied(true);
    } catch {
      setBanner({
        tone: "error",
        text: translate("settings.mcp.copyFailed"),
      });
    }
  }

  async function handleRevoke(tokenId: string) {
    setRevokingId(tokenId);
    setBanner(null);

    try {
      const revoked = await revokeMcpToken(tokenId);
      tokens.setData((current) => upsertTokenRow(current, revoked));
      setRevokeConfirmId(null);
      try {
        await reloadTokens();
      } catch {
        setBanner({
          tone: "info",
          text: translate("settings.mcp.revokeRefreshWarning"),
        });
      }
    } catch (err) {
      setBanner({
        tone: "error",
        text: err instanceof Error ? err.message : translate("settings.mcp.revokeFailed"),
      });
    } finally {
      setRevokingId(null);
    }
  }

  if (tokens.loading && !tokens.data?.length) {
    return <LoadingState label="mcp access" />;
  }

  if (tokens.error && !tokens.data?.length) {
    return <ErrorState message={tokens.error} />;
  }

  return (
    <Card className="p-5">
      <div className="flex items-start justify-between gap-4">
        <div className="max-w-3xl">
          <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">{translate("settings.mcp.eyebrow")}</p>
          <h3 className="mt-2 text-lg font-semibold text-ink">{translate("settings.mcp.title")}</h3>
          <p className="mt-2 text-sm leading-6 text-[#596270]">{translate("settings.mcp.summary")}</p>
        </div>
        <Badge tone="info">{sortedTokens.length}</Badge>
      </div>

      {banner ? (
        <div className={workbenchStateSurfaceClassName(banner.tone === "error" ? "error" : "info", "mt-5 px-4 py-3 text-sm text-[#314051]")}>
          {banner.text}
        </div>
      ) : null}

      <div className="mt-5 space-y-5">
        <div className="space-y-5">
          <div className={workbenchSupportPanelClassName("default", "p-4")}>
            <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("settings.mcp.createTitle")}</p>
            <div className="mt-4 grid gap-4 md:grid-cols-[minmax(0,1fr)_180px]">
              <div>
                <label className="mb-2 block text-xs uppercase tracking-[0.18em] text-[#6d7885]" htmlFor="settings-mcp-label">
                  {translate("settings.mcp.tokenLabel")}
                </label>
                <Input
                  id="settings-mcp-label"
                  value={createForm.label}
                  onChange={(event) => setCreateForm((current) => ({ ...current, label: event.target.value }))}
                  placeholder={translate("settings.mcp.tokenLabelPlaceholder")}
                />
              </div>
              <div>
                <label className="mb-2 block text-xs uppercase tracking-[0.18em] text-[#6d7885]" htmlFor="settings-mcp-expiry">
                  {translate("settings.mcp.expiresIn")}
                </label>
                <select
                  id="settings-mcp-expiry"
                  className="h-11 w-full rounded-2xl border border-line bg-white/80 px-4 text-sm text-ink outline-none transition focus:border-cobalt focus:bg-white"
                  value={createForm.expiresInDays}
                  onChange={(event) => setCreateForm((current) => ({ ...current, expiresInDays: event.target.value }))}
                >
                  {expiryOptions.map((days) => (
                    <option key={days} value={days}>
                      {translate("settings.mcp.expiresInDays", { days })}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <div className="mt-4 flex flex-wrap gap-3">
              <Button onClick={() => void handleCreate()} disabled={creating || !createForm.label.trim()}>
                <KeyRound className="mr-2 h-4 w-4" />
                {creating ? translate("settings.mcp.creating") : translate("settings.mcp.createToken")}
              </Button>
            </div>
          </div>

          {revealPanel ? (
            <div className={workbenchStateSurfaceClassName("info", "p-4")}>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("settings.mcp.oneTimeRevealEyebrow")}</p>
                  <p className="mt-2 text-sm font-medium text-ink">{revealPanel.label}</p>
                </div>
                <Button size="sm" variant="ghost" onClick={() => setRevealPanel(null)}>
                  {translate("common.actions.close")}
                </Button>
              </div>
              <div className={workbenchSupportPanelClassName("quiet", "mt-4 p-4")}>
                <code className="block break-all text-sm text-ink">{revealPanel.token}</code>
              </div>
              <div className="mt-4 flex flex-wrap gap-3">
                <Button size="sm" variant="soft" onClick={() => void handleCopyToken()}>
                  {copied ? <Check className="mr-2 h-4 w-4" /> : <Copy className="mr-2 h-4 w-4" />}
                  {copied ? translate("settings.mcp.copied") : translate("settings.mcp.copyToken")}
                </Button>
              </div>
              <p className="mt-4 text-sm leading-6 text-[#596270]">{translate("settings.mcp.oneTimeRevealWarning")}</p>
            </div>
          ) : null}
        </div>

        <div className={workbenchSupportPanelClassName("default", "p-4")}>
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("settings.mcp.listEyebrow")}</p>
              <h4 className="mt-2 text-base font-semibold text-ink">{translate("settings.mcp.listTitle")}</h4>
            </div>
            {tokens.loading ? <Badge tone="info">{translate("common.labels.loading", { label: translate("settings.mcp.eyebrow").toLowerCase() })}</Badge> : null}
          </div>

          <div className="mt-4 space-y-3">
            {sortedTokens.length === 0 ? (
              <EmptyState title={translate("settings.mcp.emptyTitle")} description={translate("settings.mcp.emptyDescription")} />
            ) : (
              sortedTokens.map((token) => {
                const status = tokenStatus(token);
                const scopesSummary = token.scopes.length > 0 ? token.scopes.join(", ") : translate("common.labels.notAvailable");

                return (
                  <div key={token.token_id} className={workbenchSupportPanelClassName("quiet", "p-4")}>
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <p className="text-sm font-medium text-ink">{token.label || translate("common.labels.notAvailable")}</p>
                          <Badge tone={statusTone(status)}>{statusLabel(status)}</Badge>
                        </div>
                        <div className="mt-3 grid gap-2 text-sm text-[#596270] md:grid-cols-2">
                          <p>{translate("settings.mcp.createdAt")}: {formatDateTime(token.created_at)}</p>
                          <p>{translate("settings.mcp.expiresAt")}: {formatDateTime(token.expires_at, translate("common.labels.notAvailable"))}</p>
                          <p>{translate("settings.mcp.lastUsedAt")}: {formatDateTime(token.last_used_at, translate("common.labels.notAvailable"))}</p>
                          <p>{translate("settings.mcp.scopes")}: {scopesSummary}</p>
                        </div>
                      </div>
                      {status === "active" ? (
                        <Button size="sm" variant="ghost" onClick={() => setRevokeConfirmId((current) => (current === token.token_id ? null : token.token_id))}>
                          <ShieldX className="mr-2 h-4 w-4" />
                          {translate("settings.mcp.revoke")}
                        </Button>
                      ) : null}
                    </div>

                    {revokeConfirmId === token.token_id ? (
                      <div className={workbenchStateSurfaceClassName("error", "mt-4 p-4")}>
                        <p className="text-sm font-medium text-ink">{translate("settings.mcp.revokeConfirmTitle")}</p>
                        <p className="mt-2 text-sm leading-6 text-[#596270]">{translate("settings.mcp.revokeConfirmBody")}</p>
                        <div className="mt-4 flex flex-wrap gap-3">
                          <Button
                            size="sm"
                            variant="danger"
                            onClick={() => void handleRevoke(token.token_id)}
                            disabled={revokingId === token.token_id}
                          >
                            {revokingId === token.token_id ? translate("settings.mcp.revoking") : translate("settings.mcp.confirmRevoke")}
                          </Button>
                          <Button size="sm" variant="ghost" onClick={() => setRevokeConfirmId(null)} disabled={revokingId === token.token_id}>
                            {translate("common.actions.cancel")}
                          </Button>
                        </div>
                      </div>
                    ) : null}
                  </div>
                );
              })
            )}
          </div>

          <div className="mt-5 rounded-[1rem] border border-line/80 bg-[#fbf8f3] p-4">
            <p className="text-xs uppercase tracking-[0.16em] text-[#6d7885]">{translate("settings.mcp.usageEyebrow")}</p>
            <p className="mt-2 text-sm leading-6 text-[#596270]">{translate("settings.mcp.usageHint")}</p>
          </div>
        </div>
      </div>
    </Card>
  );
}
