import type { Metadata } from "next";
import { LocalizedLegalPage } from "@/components/localized-legal-page";

export const metadata: Metadata = {
  title: "CalendarDIFF",
  description: "CalendarDIFF"
};

export default function PrivacyPage() {
  return <LocalizedLegalPage kind="privacy" />;
}
