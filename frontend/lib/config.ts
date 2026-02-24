import { AppConfig } from "@/lib/types";

declare global {
  interface Window {
    __APP_CONFIG__?: AppConfig;
  }
}

export function getRuntimeConfig(): AppConfig {
  if (typeof window === "undefined") {
    return { apiBase: "", apiKey: "" };
  }
  return window.__APP_CONFIG__ ?? { apiBase: "", apiKey: "" };
}
