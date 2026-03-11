import type { Metadata } from "next";
import { LegalPage } from "@/components/legal-page";

export const metadata: Metadata = {
  title: "Privacy Policy | CalendarDIFF",
  description: "Privacy Policy for CalendarDIFF"
};

const sections = [
  {
    title: "Overview",
    body: [
      "CalendarDIFF is an editorial operations console for course deadlines. This Privacy Policy explains what information the service processes, why it is processed, and how users can control connected data sources.",
      "The service is designed to help operators connect sources such as Canvas ICS and Gmail, review extracted deadline signals, and manage resulting workflow records inside the CalendarDIFF workspace."
    ]
  },
  {
    title: "Information the service processes",
    body: [
      "CalendarDIFF processes account information such as login email, password hash, session state, timezone, and application preferences needed to operate the workspace.",
      "When a user connects external sources, CalendarDIFF processes source metadata, synchronization status, and extracted event or message signals required to build review items and canonical deadline records.",
      "If Gmail is connected, CalendarDIFF requests read-only Gmail access and processes mailbox data needed to identify course-related deadlines. The service is not intended to send, delete, or modify email on the user's behalf."
    ]
  },
  {
    title: "How connected Gmail access is used",
    body: [
      "Gmail access is used to read mailbox data for course and deadline extraction workflows. The configured scope is read-only and is used to support ingestion, parsing, review, and synchronization inside the CalendarDIFF workspace.",
      "OAuth credentials and related connection state may be stored so the service can continue syncing authorized Gmail data until the user disconnects the source or the authorization expires."
    ]
  },
  {
    title: "How data is retained and controlled",
    body: [
      "CalendarDIFF retains operational data needed to provide the console, including review history, source records, synchronization records, and canonical event state produced by the workflow.",
      "Users can disconnect a Gmail source or archive a source from the Sources workspace. Disconnecting or removing a source stops future synchronization for that source, although prior operational records may remain as part of the system's audit and review history."
    ]
  },
  {
    title: "Security and sharing",
    body: [
      "CalendarDIFF uses authenticated sessions, service-to-service credentials, and encrypted secret handling within the application runtime to protect operational data and OAuth-linked credentials.",
      "CalendarDIFF is not intended to sell mailbox data or deadline-derived records. Data is processed to operate the service and its workflow features, and may be shared only with infrastructure or service providers needed to host and run the application."
    ]
  },
  {
    title: "Questions and requests",
    body: [
      "For support, privacy questions, or data-handling requests, use the support channel or support email presented in the CalendarDIFF product surface or OAuth consent screen for this deployment.",
      "If the operator changes how CalendarDIFF handles connected-source data, this page should be updated before those changes are rolled out broadly."
    ]
  }
] as const;

export default function PrivacyPage() {
  return (
    <LegalPage
      eyebrow="Privacy"
      title="Privacy Policy"
      summary="How CalendarDIFF processes account data, connected sources, and Gmail-linked signals for deadline operations."
      updatedAt="March 11, 2026"
      sections={[...sections]}
    />
  );
}
