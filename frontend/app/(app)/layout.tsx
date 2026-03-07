import { AppShell } from "@/components/app-shell";
import { requireServerSession } from "@/lib/server-auth";

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  await requireServerSession();
  return <AppShell>{children}</AppShell>;
}
