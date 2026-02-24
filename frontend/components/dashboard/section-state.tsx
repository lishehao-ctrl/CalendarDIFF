import { ReactNode } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";

type SectionStateProps = {
  isLoading: boolean;
  error: string | null;
  isEmpty: boolean;
  loadingRows?: number;
  errorTitle: string;
  emptyTitle: string;
  emptyDescription: string;
  children: ReactNode;
};

export function SectionState({
  isLoading,
  error,
  isEmpty,
  loadingRows = 2,
  errorTitle,
  emptyTitle,
  emptyDescription,
  children,
}: SectionStateProps) {
  if (error) {
    return (
      <Alert>
        <AlertTitle>{errorTitle}</AlertTitle>
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    );
  }

  if (isLoading) {
    return (
      <div className="space-y-2">
        {Array.from({ length: Math.max(1, loadingRows) }).map((_, index) => (
          <Skeleton key={index} className="h-20" />
        ))}
      </div>
    );
  }

  if (isEmpty) {
    return (
      <Alert>
        <AlertTitle>{emptyTitle}</AlertTitle>
        <AlertDescription>{emptyDescription}</AlertDescription>
      </Alert>
    );
  }

  return <>{children}</>;
}
