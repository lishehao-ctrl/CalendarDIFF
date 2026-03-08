"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { login, register } from "@/lib/api/auth";

export function LoginPageClient({ mode }: { mode: "login" | "register" }) {
  const router = useRouter();
  const [notifyEmail, setNotifyEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    setSubmitting(true);
    setError(null);
    try {
      if (mode === "register" && password !== confirmPassword) {
        throw new Error("Passwords do not match");
      }
      if (mode === "login") {
        await login({ notify_email: notifyEmail, password });
      } else {
        await register({ notify_email: notifyEmail, password });
      }
      router.replace("/");
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : `Unable to ${mode}`);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="min-h-screen bg-transparent px-4 py-8 md:px-8">
      <div className="mx-auto flex min-h-[80vh] max-w-6xl items-center justify-center">
        <div className="grid w-full gap-6 lg:grid-cols-[1.05fr_0.95fr]">
          <Card className="relative overflow-hidden p-8 md:p-10">
            <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(31,94,255,0.16),transparent_42%),radial-gradient(circle_at_80%_20%,rgba(215,90,45,0.12),transparent_30%)]" />
            <div className="relative">
              <p className="text-xs uppercase tracking-[0.24em] text-[#6d7885]">CalendarDIFF</p>
              <h1 className="mt-4 text-4xl font-semibold leading-tight text-ink">Editorial operations for course deadlines, before the queue gets noisy.</h1>
              <p className="mt-5 max-w-xl text-sm leading-7 text-[#596270]">
                Sign in with your workspace notify email to manage sources, review changes, resolve links, and control Gmail intake from one console.
              </p>
            </div>
          </Card>
          <Card className="p-8 md:p-10">
            <p className="text-xs uppercase tracking-[0.24em] text-[#6d7885]">{mode === "login" ? "Welcome back" : "Create account"}</p>
            <h2 className="mt-3 text-3xl font-semibold text-ink">{mode === "login" ? "Sign in" : "Register"}</h2>
            <p className="mt-3 text-sm leading-6 text-[#596270]">
              {mode === "login"
                ? "Use your notify email and password to enter the dashboard."
                : "Create your workspace account with the notify email you want to use for login and notifications."}
            </p>
            {error ? (
              <div className="mt-5 rounded-[1.15rem] border border-[#efc4b5] bg-[#fff3ef] px-4 py-3 text-sm text-[#7f3d2a]">
                {error}
              </div>
            ) : null}
            <div className="mt-6 space-y-4">
              <div>
                <label className="mb-2 block text-xs uppercase tracking-[0.18em] text-[#6d7885]" htmlFor="notify-email-auth">
                  Notify email
                </label>
                <Input id="notify-email-auth" value={notifyEmail} onChange={(event) => setNotifyEmail(event.target.value)} placeholder="notify@example.com" />
              </div>
              <div>
                <label className="mb-2 block text-xs uppercase tracking-[0.18em] text-[#6d7885]" htmlFor="password-auth">
                  Password
                </label>
                <Input id="password-auth" type="password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder="At least 8 characters" />
              </div>
              {mode === "register" ? (
                <div>
                  <label className="mb-2 block text-xs uppercase tracking-[0.18em] text-[#6d7885]" htmlFor="password-confirm-auth">
                    Confirm password
                  </label>
                  <Input id="password-confirm-auth" type="password" value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} placeholder="Repeat your password" />
                </div>
              ) : null}
              <Button className="w-full" disabled={submitting || !notifyEmail || !password || (mode === "register" && !confirmPassword)} onClick={() => void submit()}>
                {submitting ? (mode === "login" ? "Signing in..." : "Creating account...") : (mode === "login" ? "Sign in" : "Create account")}
              </Button>
            </div>
            <div className="mt-6 text-sm text-[#596270]">
              {mode === "login" ? (
                <>
                  Need an account? <Link className="font-medium text-cobalt" href="/register">Register</Link>
                </>
              ) : (
                <>
                  Already registered? <Link className="font-medium text-cobalt" href="/login">Sign in</Link>
                </>
              )}
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}
