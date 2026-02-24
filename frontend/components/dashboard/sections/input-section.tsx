import { FormEventHandler } from "react";
import { CalendarDays, Loader2, Mail } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";

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
      <div className="stagger-fade grid gap-4 xl:grid-cols-2">
        <Card className="animate-in">
          <CardHeader>
            <CardTitle className="inline-flex items-center gap-2 text-base">
              <CalendarDays className="h-4 w-4 text-accent" />
              Add Calendar Input
            </CardTitle>
            <CardDescription>Paste an ICS URL. Optional term binding is an advanced filter, not required for setup.</CardDescription>
          </CardHeader>
          <CardContent>
            <form className="space-y-4" onSubmit={onCreateCalendarInput}>
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
                <Label htmlFor="source-term">Term (advanced, optional)</Label>
                <Select id="source-term" value={sourceTermId} onChange={(event) => onSourceTermIdChange(event.target.value)}>
                  <option value="">Primary (no term binding)</option>
                  {activeUserTerms.map((term) => (
                    <option key={term.id} value={String(term.id)}>
                      {term.label} ({term.code})
                    </option>
                  ))}
                </Select>
              </div>

              <div className="pt-1">
                <Button type="submit" disabled={createBusy}>
                  {createBusy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                  Create Calendar Input
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>

        <Card className="animate-in">
          <CardHeader>
            <CardTitle className="inline-flex items-center gap-2 text-base">
              <Mail className="h-4 w-4 text-accent" />
              Connect Gmail Input
            </CardTitle>
            <CardDescription>Set optional Gmail filters before redirecting to OAuth authorization.</CardDescription>
          </CardHeader>
          <CardContent>
            <form className="space-y-4" onSubmit={onConnectGmailInput}>
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

              <div className="pt-1">
                <Button type="submit" disabled={createBusy}>
                  {createBusy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                  Connect Gmail
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>
      </div>
    </section>
  );
}
