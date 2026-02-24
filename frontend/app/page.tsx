"use client";

import { useEffect } from "react";
import { Loader2 } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export default function UiRootRedirectPage() {
  useEffect(() => {
    const target = new URL("/ui/processing", window.location.origin);
    target.search = window.location.search;
    target.hash = window.location.hash;
    window.location.replace(`${target.pathname}${target.search}${target.hash}`);
  }, []);

  return (
    <div className="container py-6">
      <div className="mx-auto max-w-xl">
        <Card>
          <CardHeader>
            <CardTitle>Redirecting</CardTitle>
            <CardDescription>Opening Processing workspace...</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex items-center text-sm text-muted">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Please wait.
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
