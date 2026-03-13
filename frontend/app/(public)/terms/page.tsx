import type { Metadata } from "next";
import { LegalPage } from "@/components/legal-page";

export const metadata: Metadata = {
  title: "Terms of Service | CalendarDIFF",
  description: "Terms of Service for CalendarDIFF"
};

const sections = [
  {
    title: "Using the service",
    body: [
      "CalendarDIFF provides a workspace for connecting sources, reviewing extracted deadline signals, and operating a course-deadline workflow. By using the service, the user agrees to use the product only for lawful, authorized, and work-related purposes.",
      "The user is responsible for ensuring that any connected Gmail mailbox, calendar feed, or other source is one they are authorized to connect and process through the service."
    ]
  },
  {
    title: "Accounts and workspace access",
    body: [
      "Users are responsible for maintaining the confidentiality of their login credentials and for activity performed through their account.",
      "CalendarDIFF may suspend or limit access if use of the service threatens security, violates applicable law, abuses shared infrastructure, or interferes with normal product operations."
    ]
  },
  {
    title: "Connected sources and external providers",
    body: [
      "CalendarDIFF may integrate with third-party services such as Gmail and calendar providers. Those integrations are also subject to the third party's own terms and policies.",
      "CalendarDIFF does not control the availability, content, or policy changes of external providers. If an external provider changes its APIs, scope rules, or authorization requirements, CalendarDIFF may update or suspend the relevant integration."
    ]
  },
  {
    title: "Operational output",
    body: [
      "CalendarDIFF generates review items, approved semantic event records, source health signals, and other workflow artifacts from connected inputs. Users are responsible for reviewing those outputs before relying on them for operational or academic decisions.",
      "The service may surface inferred, normalized, or machine-assisted outputs. Those outputs are intended to support review workflows and are not guaranteed to be complete, final, or error-free without user validation."
    ]
  },
  {
    title: "Availability and changes",
    body: [
      "CalendarDIFF may change, improve, or remove features over time. Maintenance windows, provider outages, schema changes, or operational safeguards may affect availability.",
      "The service may be offered on an as-available basis, and uninterrupted availability is not guaranteed."
    ]
  },
  {
    title: "Contact and updates",
    body: [
      "Questions about these terms should be directed through the support channel or support email shown in the CalendarDIFF product surface or OAuth consent screen for this deployment.",
      "If legal or operational terms materially change, the published Terms of Service page for this deployment should be updated before relying on the new behavior in production."
    ]
  }
] as const;

export default function TermsPage() {
  return (
    <LegalPage
      eyebrow="Legal"
      title="Terms of Service"
      summary="The operating rules, user responsibilities, and service boundaries for using CalendarDIFF."
      updatedAt="March 11, 2026"
      sections={[...sections]}
    />
  );
}
