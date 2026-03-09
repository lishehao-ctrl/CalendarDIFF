"use client";

import { useEffect, useMemo, useState } from "react";
import { Clock3, Mail, Plus, RefreshCw, ShieldCheck, Tags, Trash2, X } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { EmptyState, ErrorState, LoadingState } from "@/components/data-states";
import {
  createWorkItemKindMapping,
  deleteWorkItemKindMapping,
  getCurrentUser,
  getWorkItemKindMappingStatus,
  listWorkItemKindMappings,
  updateCurrentUser,
  updateWorkItemKindMapping,
} from "@/lib/api/users";
import { useApiResource } from "@/lib/use-api-resource";
import { formatDateTime } from "@/lib/presenters";
import type { UserProfile, WorkItemKindMapping, WorkItemKindMappingStatus } from "@/lib/types";

export function SettingsPanel() {
  const user = useApiResource<UserProfile>(() => getCurrentUser(), []);
  const mappings = useApiResource<WorkItemKindMapping[]>(() => listWorkItemKindMappings(), []);
  const mappingStatus = useApiResource<WorkItemKindMappingStatus>(() => getWorkItemKindMappingStatus(), []);
  const [form, setForm] = useState({ timezone_name: "" });
  const [saving, setSaving] = useState(false);
  const [mappingBusy, setMappingBusy] = useState<number | "new" | null>(null);
  const [banner, setBanner] = useState<{ tone: "info" | "error"; text: string } | null>(null);
  const [newMappingName, setNewMappingName] = useState("");
  const [draftNames, setDraftNames] = useState<Record<number, string>>({});
  const [draftAliases, setDraftAliases] = useState<Record<number, string[]>>({});
  const [aliasInputs, setAliasInputs] = useState<Record<number, string>>({});

  useEffect(() => {
    if (!user.data) {
      return;
    }
    setForm({ timezone_name: user.data.timezone_name || "" });
  }, [user.data]);

  useEffect(() => {
    if (!mappings.data) {
      return;
    }
    const names: Record<number, string> = {};
    const aliases: Record<number, string[]> = {};
    for (const row of mappings.data) {
      names[row.id] = row.name;
      aliases[row.id] = [...row.aliases];
    }
    setDraftNames(names);
    setDraftAliases(aliases);
  }, [mappings.data]);

  const mappingRows = useMemo(() => mappings.data || [], [mappings.data]);

  async function saveUserSettings() {
    setSaving(true);
    setBanner(null);
    try {
      await updateCurrentUser({ timezone_name: form.timezone_name });
      setBanner({ tone: "info", text: "Settings saved." });
      await user.refresh();
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : "Unable to save settings" });
    } finally {
      setSaving(false);
    }
  }

  async function refreshMappings() {
    await Promise.all([mappings.refresh(), mappingStatus.refresh()]);
  }

  async function createMapping() {
    const normalizedName = newMappingName.trim();
    if (!normalizedName) return;
    setMappingBusy("new");
    setBanner(null);
    try {
      await createWorkItemKindMapping({ name: normalizedName, aliases: [] });
      setNewMappingName("");
      setBanner({ tone: "info", text: `Created mapping “${normalizedName}”.` });
      await refreshMappings();
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : "Unable to create mapping" });
    } finally {
      setMappingBusy(null);
    }
  }

  async function saveMapping(mappingId: number) {
    const name = (draftNames[mappingId] || "").trim();
    const aliases = draftAliases[mappingId] || [];
    if (!name) return;
    setMappingBusy(mappingId);
    setBanner(null);
    try {
      await updateWorkItemKindMapping(mappingId, { name, aliases });
      setBanner({ tone: "info", text: `Updated “${name}”.` });
      await refreshMappings();
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : "Unable to update mapping" });
    } finally {
      setMappingBusy(null);
    }
  }

  async function removeMapping(mappingId: number) {
    const confirmed = window.confirm("Delete this work item mapping and all of its aliases?");
    if (!confirmed) return;
    setMappingBusy(mappingId);
    setBanner(null);
    try {
      await deleteWorkItemKindMapping(mappingId);
      setBanner({ tone: "info", text: "Mapping deleted." });
      await refreshMappings();
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : "Unable to delete mapping" });
    } finally {
      setMappingBusy(null);
    }
  }

  function addAlias(mappingId: number) {
    const nextAlias = (aliasInputs[mappingId] || "").trim();
    if (!nextAlias) return;
    setDraftAliases((prev) => ({
      ...prev,
      [mappingId]: [...(prev[mappingId] || []), nextAlias],
    }));
    setAliasInputs((prev) => ({ ...prev, [mappingId]: "" }));
  }

  function removeAlias(mappingId: number, alias: string) {
    setDraftAliases((prev) => ({
      ...prev,
      [mappingId]: (prev[mappingId] || []).filter((value) => value !== alias),
    }));
  }

  if (user.loading || mappings.loading || mappingStatus.loading) return <LoadingState label="settings" />;
  if (user.error) return <ErrorState message={user.error} />;
  if (mappings.error) return <ErrorState message={mappings.error} />;
  if (mappingStatus.error) return <ErrorState message={mappingStatus.error} />;
  if (!user.data) return <EmptyState title="User not initialized" description="Complete registration before editing settings." />;

  return (
    <div className="grid gap-5 xl:grid-cols-[1fr_0.9fr]">
      <div className="space-y-5">
        <Card className="p-6 md:p-7">
          <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Editable settings</p>
          <h3 className="mt-3 text-2xl font-semibold">Workspace identity</h3>
          <p className="mt-2 text-sm leading-6 text-[#596270]">
            Login email is managed by auth. This page edits stable runtime preferences and work-item mapping rules.
          </p>

          {banner ? (
            <div className={banner.tone === "error" ? "mt-5 rounded-[1.15rem] border border-[#efc4b5] bg-[#fff3ef] px-4 py-3 text-sm text-[#7f3d2a]" : "mt-5 rounded-[1.15rem] border border-[rgba(31,94,255,0.18)] bg-[rgba(31,94,255,0.08)] px-4 py-3 text-sm text-[#314051]"}>
              {banner.text}
            </div>
          ) : null}

          <div className="mt-6 space-y-4">
            <div>
              <label className="mb-2 block text-xs uppercase tracking-[0.18em] text-[#6d7885]" htmlFor="notify-email-settings">
                Login / notify email
              </label>
              <Input id="notify-email-settings" value={user.data.notify_email || ""} disabled />
            </div>
            <div>
              <label className="mb-2 block text-xs uppercase tracking-[0.18em] text-[#6d7885]" htmlFor="timezone-name">
                Timezone name
              </label>
              <Input id="timezone-name" value={form.timezone_name} onChange={(event) => setForm({ timezone_name: event.target.value })} placeholder="America/Los_Angeles" />
            </div>
            <Button onClick={() => void saveUserSettings()} disabled={saving || !form.timezone_name}>
              {saving ? "Saving settings..." : "Save settings"}
            </Button>
          </div>
        </Card>

        <Card className="p-6 md:p-7">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Work item mappings</p>
              <h3 className="mt-3 text-2xl font-semibold">Name + alias resolution</h3>
              <p className="mt-2 text-sm leading-6 text-[#596270]">
                Define the canonical work-item names your workspace uses and the aliases that should resolve to them.
              </p>
            </div>
            <div className="rounded-[1.15rem] border border-line/80 bg-white/70 px-4 py-3 text-sm text-[#314051]">
              <p className="font-medium text-ink">Rebuild status</p>
              <p className="mt-1">State: {mappingStatus.data?.state || "idle"}</p>
              <p className="mt-1">Last rebuilt: {formatDateTime(mappingStatus.data?.last_rebuilt_at, "Never")}</p>
              {mappingStatus.data?.last_error ? <p className="mt-1 text-[#7f3d2a]">{mappingStatus.data.last_error}</p> : null}
            </div>
          </div>

          <div className="mt-6 rounded-[1.15rem] border border-line/80 bg-white/70 p-4">
            <label className="mb-2 block text-xs uppercase tracking-[0.18em] text-[#6d7885]" htmlFor="new-work-item-mapping">
              Add canonical work item name
            </label>
            <div className="flex flex-wrap gap-3">
              <Input
                id="new-work-item-mapping"
                value={newMappingName}
                onChange={(event) => setNewMappingName(event.target.value)}
                placeholder="Homework"
                className="max-w-md"
              />
              <Button onClick={() => void createMapping()} disabled={mappingBusy === "new" || !newMappingName.trim()}>
                <Plus className="mr-2 h-4 w-4" />
                {mappingBusy === "new" ? "Creating..." : "Add mapping"}
              </Button>
            </div>
          </div>

          <div className="mt-5 space-y-4">
            {mappingRows.length === 0 ? (
              <EmptyState title="No mappings yet" description="Create a canonical work-item name, then attach aliases such as HW or PA." />
            ) : (
              mappingRows.map((mapping) => (
                <Card key={mapping.id} className="bg-white/60 p-5">
                  <div className="flex flex-wrap items-start justify-between gap-4">
                    <div className="min-w-0 flex-1 space-y-4">
                      <div>
                        <label className="mb-2 block text-xs uppercase tracking-[0.18em] text-[#6d7885]">Canonical name</label>
                        <Input
                          value={draftNames[mapping.id] || ""}
                          onChange={(event) => setDraftNames((prev) => ({ ...prev, [mapping.id]: event.target.value }))}
                          placeholder="Homework"
                        />
                      </div>
                      <div>
                        <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Aliases</p>
                        <div className="mt-3 flex flex-wrap gap-2">
                          {(draftAliases[mapping.id] || []).map((alias) => (
                            <span key={`${mapping.id}-${alias}`} className="inline-flex items-center gap-2 rounded-full border border-line/80 bg-white/80 px-3 py-1 text-sm text-[#314051]">
                              {alias}
                              <button type="button" aria-label={`Remove alias ${alias}`} onClick={() => removeAlias(mapping.id, alias)}>
                                <X className="h-3.5 w-3.5" />
                              </button>
                            </span>
                          ))}
                        </div>
                        <div className="mt-3 flex flex-wrap gap-3">
                          <Input
                            value={aliasInputs[mapping.id] || ""}
                            onChange={(event) => setAliasInputs((prev) => ({ ...prev, [mapping.id]: event.target.value }))}
                            placeholder="hw"
                            className="max-w-sm"
                          />
                          <Button variant="ghost" onClick={() => addAlias(mapping.id)} disabled={!(aliasInputs[mapping.id] || "").trim()}>
                            <Plus className="mr-2 h-4 w-4" />
                            Add alias
                          </Button>
                        </div>
                      </div>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <Button onClick={() => void saveMapping(mapping.id)} disabled={mappingBusy === mapping.id}>
                        {mappingBusy === mapping.id ? "Saving..." : "Save"}
                      </Button>
                      <Button variant="ghost" onClick={() => void removeMapping(mapping.id)} disabled={mappingBusy === mapping.id}>
                        <Trash2 className="mr-2 h-4 w-4" />
                        Delete
                      </Button>
                    </div>
                  </div>
                </Card>
              ))
            )}
          </div>
        </Card>
      </div>

      <div className="space-y-5">
        <Card className="p-6">
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-[rgba(31,94,255,0.1)] text-cobalt">
              <Mail className="h-5 w-5" />
            </div>
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Identity snapshot</p>
              <h3 className="mt-1 text-xl font-semibold">Current profile</h3>
            </div>
          </div>
          <div className="mt-5 space-y-3 text-sm text-[#314051]">
            <div className="rounded-[1.15rem] border border-line/80 bg-white/60 p-4">
              <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Login / notify email</p>
              <p className="mt-2 font-medium">{user.data.notify_email || "Not set"}</p>
              <p className="mt-2 text-xs text-[#596270]">This identifier is managed by auth and intentionally stays read-only inside the app.</p>
            </div>
            <div className="rounded-[1.15rem] border border-line/80 bg-white/60 p-4">
              <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">Created</p>
              <p className="mt-2 font-medium">{formatDateTime(user.data.created_at, "Not available")}</p>
            </div>
          </div>
        </Card>

        <Card className="p-6">
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-[rgba(47,143,91,0.12)] text-moss">
              <Clock3 className="h-5 w-5" />
            </div>
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Timing defaults</p>
              <h3 className="mt-1 text-xl font-semibold">Operational timing</h3>
            </div>
          </div>
          <div className="mt-5 rounded-[1.15rem] border border-line/80 bg-white/60 p-4 text-sm text-[#314051]">
            <p>Timezone: {user.data.timezone_name}</p>
            <p className="mt-2">Calendar delay seconds: {user.data.calendar_delay_seconds}</p>
          </div>
          <div className="mt-4 rounded-[1.15rem] border border-line/80 bg-white/60 p-4 text-sm text-[#596270]">
            Authentication is session-based. Work item mappings let you teach the system how your course uses names like HW, PA, or Lab Paper.
          </div>
        </Card>

        <Card className="p-6">
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-[rgba(20,32,44,0.08)] text-ink">
              <Tags className="h-5 w-5" />
            </div>
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">Mapping summary</p>
              <h3 className="mt-1 text-xl font-semibold">Resolution coverage</h3>
            </div>
          </div>
          <div className="mt-5 rounded-[1.15rem] border border-line/80 bg-white/60 p-4 text-sm text-[#314051]">
            <p>Canonical names: {mappingRows.length}</p>
            <p className="mt-2">Aliases: {mappingRows.reduce((count, row) => count + row.aliases.length, 0)}</p>
            <p className="mt-2">Last rebuild: {formatDateTime(mappingStatus.data?.last_rebuilt_at, "Never")}</p>
          </div>
        </Card>
      </div>
    </div>
  );
}
