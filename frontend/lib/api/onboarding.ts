import { apiGet, apiPost } from "@/lib/api/client";
import type { OnboardingStatus } from "@/lib/types";

export async function getOnboardingStatus() {
  return apiGet<OnboardingStatus>("/onboarding/status");
}

export async function saveOnboardingCanvasIcs(payload: { url: string }) {
  return apiPost<OnboardingStatus>("/onboarding/canvas-ics", payload);
}

export async function startOnboardingGmailOAuth(payload?: { label_id?: string | null; return_to?: "onboarding" | "sources" }) {
  return apiPost<{ source_id: number; provider: "gmail"; authorization_url: string; expires_at: string }>(
    "/onboarding/gmail/oauth-sessions",
    payload || {},
  );
}

export async function skipOnboardingGmail() {
  return apiPost<OnboardingStatus>("/onboarding/gmail-skip", {});
}

export async function saveOnboardingTermBinding(payload: {
  term_key?: string | null;
  term_from: string;
  term_to: string;
}) {
  return apiPost<OnboardingStatus>("/onboarding/term-binding", payload);
}
