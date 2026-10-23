import type { Metadata } from "next";
import { Suspense } from "react";

import { AdminShell, AdminShellSkeleton } from "@/components/admin/admin-shell";

export const metadata: Metadata = {
  title: { template: "%s · HomeHelper admin", default: "HomeHelper admin" },
  robots: { index: false, follow: false },
};

// The shell reads the pathname for its navigation, so it renders below a Suspense boundary.
export default function AdminLayout({ children }: LayoutProps<"/admin">) {
  return (
    <Suspense fallback={<AdminShellSkeleton />}>
      <AdminShell>{children}</AdminShell>
    </Suspense>
  );
}
