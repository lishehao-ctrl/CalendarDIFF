import { requireReadyServerSession } from "@/lib/server-auth";

export default async function FamilyLayout({ children }: { children: React.ReactNode }) {
  await requireReadyServerSession();

  return children;
}
