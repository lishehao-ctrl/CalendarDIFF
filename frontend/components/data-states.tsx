import { Card } from "@/components/ui/card";

export function LoadingState({ label }: { label: string }) {
  return (
    <Card className="p-6">
      <div className="space-y-4 animate-pulse">
        <div className="h-3 w-24 rounded-full bg-[rgba(20,32,44,0.08)]" />
        <div className="h-9 w-2/5 rounded-2xl bg-[rgba(20,32,44,0.08)]" />
        <div className="grid gap-3 md:grid-cols-2">
          <div className="h-24 rounded-[1.2rem] bg-[rgba(20,32,44,0.08)]" />
          <div className="h-24 rounded-[1.2rem] bg-[rgba(20,32,44,0.08)]" />
        </div>
      </div>
      <p className="mt-4 text-sm text-[#596270]">Loading {label}...</p>
    </Card>
  );
}

export function ErrorState({ message }: { message: string }) {
  return (
    <Card className="border-[#e9b9ab] bg-[#fff3ef] p-6">
      <p className="text-xs uppercase tracking-[0.18em] text-ember">Request error</p>
      <p className="mt-3 text-sm text-[#7f3d2a]">{message}</p>
    </Card>
  );
}

export function EmptyState({ title, description }: { title: string; description: string }) {
  return (
    <Card className="border-dashed bg-white/40 p-8">
      <h3 className="text-lg font-semibold text-ink">{title}</h3>
      <p className="mt-2 max-w-xl text-sm text-[#596270]">{description}</p>
    </Card>
  );
}
