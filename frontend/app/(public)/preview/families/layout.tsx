import { FamilySubnav } from "@/components/family-subnav";

export default function PreviewFamilyLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="space-y-4">
      <div className="px-1">
        <p className="text-xs uppercase tracking-[0.22em] text-[#6d7885]">Families</p>
        <h1 className="mt-1 text-2xl font-semibold text-ink">Families governance</h1>
      </div>
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <FamilySubnav basePath="/preview" />
      </div>
      {children}
    </div>
  );
}
