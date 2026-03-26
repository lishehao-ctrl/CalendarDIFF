import type { Metadata } from "next";
import { LocalizedLegalPage } from "@/components/localized-legal-page";

export const metadata: Metadata = {
  title: "CalendarDIFF",
  description: "CalendarDIFF"
};

export default function TermsPage() {
  return <LocalizedLegalPage kind="terms" />;
}
