import { FormEventHandler } from "react";
import { CalendarDays, Loader2, Mail } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

type TermOption = {
  id: number;
  code: string;
  label: string;
  starts_on: string;
  ends_on: string;
  is_active: boolean;
};

type InputSectionProps = {
  sourceUrl: string;
  sourceTermId: string;
  sourceEmailLabel: string;
  sourceEmailFromContains: string;
  sourceEmailSubjectKeywords: string;
  activeUserTerms: TermOption[];
  createBusy: boolean;
  onSourceUrlChange: (value: string) => void;
  onSourceTermIdChange: (value: string) => void;
  onSourceEmailLabelChange: (value: string) => void;
  onSourceEmailFromContainsChange: (value: string) => void;
  onSourceEmailSubjectKeywordsChange: (value: string) => void;
  onCreateCalendarInput: FormEventHandler<HTMLFormElement>;
  onConnectGmailInput: FormEventHandler<HTMLFormElement>;
};

export function InputSection({
  sourceUrl,
  sourceTermId,
  sourceEmailLabel,
  sourceEmailFromContains,
  sourceEmailSubjectKeywords,
  activeUserTerms,
  createBusy,
  onSourceUrlChange,
  onSourceTermIdChange,
  onSourceEmailLabelChange,
  onSourceEmailFromContainsChange,
  onSourceEmailSubjectKeywordsChange,
  onCreateCalendarInput,
  onConnectGmailInput,
}: InputSectionProps) {
  return (
    <section id="input" className="section-anchor">
      <Card className="animate-fade-in">
        <CardHeader>
          <CardTitle>Input Layer: Add Inputs One by One</CardTitle>
          <CardDescription>
            Calendar and Gmail are independent inputs. Add either one first, and add the other only when needed.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 lg:grid-cols-2">
          <Card className="rounded-2xl">
            <CardHeader>
              <CardTitle className="text-base">
                <span className="inline-flex items-center gap-2">
                  <CalendarDays className="h-4 w-4" />
                  Add Calendar Input
                </span>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <form className="grid gap-4" onSubmit={onCreateCalendarInput}>
                <div className="space-y-2">
                  <Label htmlFor="source-url">ICS URL</Label>
                  <Input
                    id="source-url"
                    type="url"
                    value={sourceUrl}
                    onChange={(event) => onSourceUrlChange(event.target.value)}
                    placeholder="https://..."
                    required
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="source-term">Semester (optional)</Label>
                  <select
                    id="source-term"
                    className="h-10 w-full rounded-md border border-line bg-white px-3 py-2 text-sm"
                    value={sourceTermId}
                    onChange={(event) => onSourceTermIdChange(event.target.value)}
                  >
                    <option value="">Unassigned</option>
                    {activeUserTerms.map((term) => (
                      <option key={term.id} value={String(term.id)}>
                        {term.label} ({term.code})
                      </option>
                    ))}
                  </select>
                </div>
                <Button type="submit" disabled={createBusy}>
                  {createBusy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                  Create Calendar Input
                </Button>
              </form>
            </CardContent>
          </Card>

          <Card className="rounded-2xl">
            <CardHeader>
              <CardTitle className="text-base">
                <span className="inline-flex items-center gap-2">
                  <Mail className="h-4 w-4" />
                  Connect Gmail Input
                </span>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <form className="grid gap-4" onSubmit={onConnectGmailInput}>
                <div className="space-y-2">
                  <Label htmlFor="source-email-label">Gmail Label (optional)</Label>
                  <Input
                    id="source-email-label"
                    value={sourceEmailLabel}
                    onChange={(event) => onSourceEmailLabelChange(event.target.value)}
                    maxLength={255}
                    placeholder="INBOX"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="source-email-from">From Contains (optional)</Label>
                  <Input
                    id="source-email-from"
                    value={sourceEmailFromContains}
                    onChange={(event) => onSourceEmailFromContainsChange(event.target.value)}
                    maxLength={255}
                    placeholder="instructor@school.edu"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="source-email-subject">Subject Keywords (comma separated)</Label>
                  <Input
                    id="source-email-subject"
                    value={sourceEmailSubjectKeywords}
                    onChange={(event) => onSourceEmailSubjectKeywordsChange(event.target.value)}
                    placeholder="assignment, quiz, deadline"
                  />
                </div>
                <Button type="submit" disabled={createBusy}>
                  {createBusy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                  Connect Gmail
                </Button>
              </form>
            </CardContent>
          </Card>
        </CardContent>
      </Card>
    </section>
  );
}
