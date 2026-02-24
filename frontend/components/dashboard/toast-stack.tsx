import { cn } from "@/lib/utils";

type DashboardToast = {
  id: number;
  message: string;
  tone: "success" | "error" | "info";
};

export function DashboardToastStack({ toasts }: { toasts: DashboardToast[] }) {
  if (!toasts.length) {
    return null;
  }

  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-50 space-y-2">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className={cn(
            "pointer-events-auto max-w-[420px] rounded-2xl border px-4 py-3 text-sm text-white shadow-elevated",
            toast.tone === "success" && "border-emerald-800 bg-emerald-700",
            toast.tone === "error" && "border-rose-800 bg-rose-700",
            toast.tone === "info" && "border-slate-900 bg-slate-800"
          )}
        >
          {toast.message}
        </div>
      ))}
    </div>
  );
}
