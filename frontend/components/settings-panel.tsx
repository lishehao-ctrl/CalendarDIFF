"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useRef, useState } from "react";
import { Check, ChevronDown, Search } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { EmptyState, ErrorState, LoadingState } from "@/components/data-states";
import { PanelLoadingPlaceholder } from "@/components/panel-loading-placeholder";
import { getSettingsProfile, settingsProfileCacheKey, updateSettingsProfile } from "@/lib/api/settings";
import { getBrowserTimeZone } from "@/lib/browser-timezone";
import { useLocale } from "@/lib/i18n/use-locale";
import { translate } from "@/lib/i18n/runtime";
import { formatTimeZoneLabel, listCommonTimeZones, listSupportedTimeZones, searchTimeZones } from "@/lib/timezones";
import { useApiResource } from "@/lib/use-api-resource";
import type { UserProfile } from "@/lib/types";

const DeferredSettingsMcpAccessCard = dynamic(
  () => import("@/components/settings-mcp-access-card").then((mod) => mod.SettingsMcpAccessCard),
  {
    loading: () => (
      <PanelLoadingPlaceholder
        eyebrow={translate("settings.mcp.eyebrow")}
        title={translate("settings.mcp.title")}
        summary={translate("settings.mcp.summary")}
        rows={2}
      />
    ),
  },
);

export function SettingsPanel() {
  const { locale, setLocale } = useLocale();
  const user = useApiResource<UserProfile>(() => getSettingsProfile(), [], null, {
    cacheKey: settingsProfileCacheKey(),
  });

  const [form, setForm] = useState({ timezone_name: "" });
  const [banner, setBanner] = useState<{ tone: "info" | "error"; text: string } | null>(null);
  const [savingUser, setSavingUser] = useState(false);
  const [deviceTimeZone, setDeviceTimeZone] = useState<string | null>(null);
  const [timeZoneOptions, setTimeZoneOptions] = useState<string[]>([]);
  const [timeZonePickerOpen, setTimeZonePickerOpen] = useState(false);
  const [timeZoneQuery, setTimeZoneQuery] = useState("");
  const pickerRef = useRef<HTMLDivElement | null>(null);
  const searchInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    setDeviceTimeZone(getBrowserTimeZone());
    setTimeZoneOptions(listSupportedTimeZones());
  }, []);

  useEffect(() => {
    if (user.data) setForm({ timezone_name: user.data.timezone_name || "" });
  }, [user.data]);

  async function saveUser() {
    setSavingUser(true);
    setBanner(null);
    try {
      await updateSettingsProfile({ timezone_name: form.timezone_name, timezone_source: "manual" });
      setBanner({ tone: "info", text: translate("settings.saved") });
      await user.refresh();
    } catch (err) {
      setBanner({ tone: "error", text: err instanceof Error ? err.message : translate("settings.saveError") });
    } finally {
      setSavingUser(false);
    }
  }

  function applyDeviceTimeZone() {
    if (!deviceTimeZone) return;
    setForm({ timezone_name: deviceTimeZone });
    setBanner(null);
    setTimeZonePickerOpen(false);
    setTimeZoneQuery("");
  }

  const commonTimeZones = useMemo(() => listCommonTimeZones(deviceTimeZone), [deviceTimeZone]);
  const filteredTimeZones = useMemo(() => {
    return searchTimeZones(timeZoneOptions, timeZoneQuery).slice(0, 24);
  }, [timeZoneOptions, timeZoneQuery]);

  function chooseTimeZone(timeZone: string) {
    setForm({ timezone_name: timeZone });
    setBanner(null);
    setTimeZonePickerOpen(false);
    setTimeZoneQuery("");
  }

  useEffect(() => {
    if (!timeZonePickerOpen) {
      return;
    }

    searchInputRef.current?.focus();

    function handlePointerDown(event: MouseEvent) {
      const target = event.target;
      if (!(target instanceof Node)) {
        return;
      }
      if (pickerRef.current?.contains(target)) {
        return;
      }
      setTimeZonePickerOpen(false);
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setTimeZonePickerOpen(false);
      }
    }

    window.addEventListener("mousedown", handlePointerDown);
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("mousedown", handlePointerDown);
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [timeZonePickerOpen]);

  if (user.loading) return <LoadingState label={translate("common.loadingLabels.settings")} />;
  if (user.error) return <ErrorState message={user.error} />;
  if (!user.data) return <EmptyState title={translate("settings.userNotInitializedTitle")} description={translate("settings.userNotInitializedDescription")} />;

  return (
    <div className="space-y-4">
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
        <Card className="p-4">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-[#6d7885]">{translate("settings.account")}</p>
              <h3 className="mt-2 text-lg font-semibold text-ink">{translate("settings.accountTitle")}</h3>
            </div>
            <Badge tone="info">{user.data.timezone_source === "manual" ? translate("settings.manual") : translate("settings.auto")}</Badge>
          </div>
          <div className="mt-4 grid gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)_auto] md:items-end">
            <div>
              <label className="mb-2 block text-xs uppercase tracking-[0.18em] text-[#6d7885]" htmlFor="notify-email-settings">{translate("settings.loginNotifyEmail")}</label>
              <Input id="notify-email-settings" value={user.data.notify_email || ""} disabled />
            </div>
            <div>
              <label className="mb-2 block text-xs uppercase tracking-[0.18em] text-[#6d7885]" htmlFor="account-email-settings">{translate("settings.accountEmail")}</label>
              <Input id="account-email-settings" value={user.data.email || ""} disabled />
            </div>
            <div>
              <label className="mb-2 block text-xs uppercase tracking-[0.18em] text-[#6d7885]" htmlFor="timezone-name">{translate("settings.timezone")}</label>
              <div ref={pickerRef} className="relative">
                <button
                  id="timezone-name"
                  type="button"
                  aria-expanded={timeZonePickerOpen}
                  onClick={() => setTimeZonePickerOpen((current) => !current)}
                  className="flex h-11 w-full items-center justify-between rounded-2xl border border-line bg-white/80 px-4 text-left text-sm text-ink transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[rgba(31,94,255,0.24)] hover:bg-white"
                >
                  <span className={form.timezone_name ? "" : "text-[#7a8593]"}>{form.timezone_name || translate("settings.chooseTimezone")}</span>
                  <ChevronDown className={timeZonePickerOpen ? "h-4 w-4 rotate-180 transition-transform" : "h-4 w-4 transition-transform"} />
                </button>
                {timeZonePickerOpen ? (
                <div className="absolute left-0 right-0 z-20 mt-3 rounded-[1.15rem] border border-line/80 bg-white p-4 shadow-[0_16px_32px_rgba(20,32,44,0.08)]">
                  <div className="relative">
                    <Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-[#7d8794]" />
                    <input
                      ref={searchInputRef}
                      value={timeZoneQuery}
                      onChange={(event) => setTimeZoneQuery(event.target.value)}
                      placeholder={translate("settings.searchTimezone")}
                      className="h-11 w-full rounded-2xl border border-line bg-white/80 pl-11 pr-4 text-sm text-ink outline-none transition focus:border-cobalt focus:bg-white"
                    />
                  </div>
                  <p className="mt-4 text-xs uppercase tracking-[0.16em] text-[#6d7885]">{translate("settings.commonTimeZones")}</p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {commonTimeZones.map((timeZone) => {
                      const active = form.timezone_name === timeZone;
                      const label = formatTimeZoneLabel(timeZone);
                      return (
                        <button
                          key={timeZone}
                          type="button"
                          onClick={() => chooseTimeZone(timeZone)}
                          className={active
                            ? "rounded-full bg-ink px-3 py-1.5 text-sm font-medium text-paper transition"
                            : "rounded-full border border-line/80 bg-white/75 px-3 py-1.5 text-sm font-medium text-[#314051] transition hover:bg-white"}
                        >
                          {label.title}
                        </button>
                      );
                    })}
                  </div>
                  <p className="mt-4 text-xs uppercase tracking-[0.16em] text-[#6d7885]">{translate("settings.allTimeZones")}</p>
                  <div className="mt-3 max-h-64 overflow-y-auto rounded-[1rem] border border-line/80 bg-[#fbf8f3]">
                    {filteredTimeZones.length > 0 ? (
                      filteredTimeZones.map((timeZone) => {
                        const active = form.timezone_name === timeZone;
                        const label = formatTimeZoneLabel(timeZone);
                        return (
                          <button
                            key={timeZone}
                            type="button"
                            onClick={() => chooseTimeZone(timeZone)}
                            className={active
                              ? "flex w-full items-center justify-between border-b border-line/70 bg-[rgba(20,32,44,0.05)] px-4 py-3 text-left text-sm text-ink last:border-b-0"
                              : "flex w-full items-center justify-between border-b border-line/70 px-4 py-3 text-left text-sm text-[#314051] transition hover:bg-white last:border-b-0"}
                          >
                            <span>
                              <span className="block font-medium text-ink">{label.title}</span>
                              <span className="mt-1 block text-xs text-[#6d7885]">{timeZone}</span>
                            </span>
                            {active ? <Check className="h-4 w-4 text-cobalt" /> : null}
                          </button>
                        );
                      })
                    ) : (
                      <div className="px-4 py-3 text-sm text-[#596270]">{translate("settings.noMatchingTimezone")}</div>
                    )}
                  </div>
                </div>
                ) : null}
              </div>
            </div>
            <Button className="md:min-w-[132px]" onClick={() => void saveUser()} disabled={savingUser || !form.timezone_name}>
              {savingUser ? `${translate("common.actions.save")}...` : translate("common.actions.save")}
            </Button>
          </div>
          <div className="mt-4 border-t border-line/80 pt-4">
            <p className="text-xs uppercase tracking-[0.18em] text-[#6d7885]">{translate("common.localeLabel")}</p>
            <div className="mt-3 flex flex-wrap gap-2">
              <Button size="sm" variant={locale === "en" ? "secondary" : "ghost"} onClick={() => setLocale("en")}>
                {translate("common.locales.en")}
              </Button>
              <Button size="sm" variant={locale === "zh-CN" ? "secondary" : "ghost"} onClick={() => setLocale("zh-CN")}>
                {translate("common.locales.zh-CN")}
              </Button>
            </div>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-3 text-xs text-[#596270]">
            <span>{deviceTimeZone ? translate("settings.deviceTimezone", { timezone: deviceTimeZone }) : translate("settings.deviceTimezoneUnavailable")}</span>
            {deviceTimeZone ? (
              <button type="button" className="font-medium text-cobalt transition hover:text-[#1f4fd6]" onClick={applyDeviceTimeZone}>
                {translate("settings.useDeviceTimezone")}
              </button>
            ) : null}
          </div>
        </Card>

      </div>

      {banner ? (
        <Card className={banner.tone === "error" ? "border-[#efc4b5] bg-[#fff3ef] p-4" : "border-[rgba(31,94,255,0.18)] bg-[rgba(31,94,255,0.08)] p-4"}>
          <p className="text-sm text-[#314051]">{banner.text}</p>
        </Card>
      ) : null}

      <DeferredSettingsMcpAccessCard />

    </div>
  );
}
