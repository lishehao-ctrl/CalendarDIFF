import { AppShell } from "@/components/app-shell";
import { requireServerSession } from "@/lib/server-auth";

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const session = await requireServerSession();
  return <AppShell sessionUser={session.user}>{children}</AppShell>;
}
