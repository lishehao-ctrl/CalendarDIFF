import { AppShell } from "@/components/app-shell";

const previewSession = {
  user: {
    id: 9001,
    email: "demo@calendardiff.app",
    language_code: "en" as const,
    timezone_name: "America/Los_Angeles",
    timezone_source: "manual" as const,
    created_at: "2026-03-10T18:00:00.000Z",
    onboarding_stage: "ready" as const,
    first_source_id: 1,
  },
};

export default function PreviewLayout({ children }: { children: React.ReactNode }) {
  return <AppShell sessionUser={previewSession.user} basePath="/preview">{children}</AppShell>;
}
