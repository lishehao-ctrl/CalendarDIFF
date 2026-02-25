import { FormEventHandler } from "react";
import { Loader2, Mail } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

type InputSectionProps = {
  sourceEmailLabel: string;
  sourceEmailFromContains: string;
  sourceEmailSubjectKeywords: string;
  createBusy: boolean;
  onSourceEmailLabelChange: (value: string) => void;
  onSourceEmailFromContainsChange: (value: string) => void;
  onSourceEmailSubjectKeywordsChange: (value: string) => void;
  onConnectGmailInput: FormEventHandler<HTMLFormElement>;
};

export function InputSection({
  sourceEmailLabel,
  sourceEmailFromContains,
  sourceEmailSubjectKeywords,
  createBusy,
  onSourceEmailLabelChange,
  onSourceEmailFromContainsChange,
  onSourceEmailSubjectKeywordsChange,
  onConnectGmailInput,
}: InputSectionProps) {
  return (
    <section id="input" className="section-anchor">
      <div className="stagger-fade grid gap-4">
        <Card className="animate-in">
          <CardHeader>
            <CardTitle className="inline-flex items-center gap-2 text-base">
              <Mail className="h-4 w-4 text-accent" />
              Connect Gmail Input
            </CardTitle>
            <CardDescription>
              ICS is managed in onboarding. Use this page to connect Gmail filters and OAuth authorization.
            </CardDescription>
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
