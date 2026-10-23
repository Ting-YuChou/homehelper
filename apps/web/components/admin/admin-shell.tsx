"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ClipboardCheck, LineChart, LogOut } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { api, unwrap } from "@/lib/api/client";
import { adminSessionQuery, queryKeys } from "@/lib/api/queries";
import { cn } from "@/lib/utils";

import { AdminSignIn } from "./admin-sign-in";

const SECTIONS = [
  { href: "/admin/review", label: "Review", icon: ClipboardCheck },
  { href: "/admin/evals", label: "Evals", icon: LineChart },
] as const;

export function AdminShellSkeleton() {
  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 px-4 py-6">
      <Skeleton className="h-8 w-48" />
      <Skeleton className="h-64 w-full" />
    </div>
  );
}

/** Admin pages behind the `hh_admin` session (spec §17.2): sign in first, then review or evals. */
export function AdminShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const queryClient = useQueryClient();
  const session = useQuery(adminSessionQuery);
  const signOut = useMutation({
    mutationFn: () => unwrap(api.DELETE("/v1/admin/session")),
    onSuccess: () => {
      queryClient.removeQueries({ queryKey: queryKeys.admin });
      queryClient.setQueryData(queryKeys.adminSession, false);
    },
  });

  if (session.isPending) return <AdminShellSkeleton />;
  if (session.isError) {
    return (
      <div className="flex flex-1 items-center justify-center p-6 text-center text-muted-foreground">
        Can&apos;t reach the HomeHelper API right now. Please try again in a moment.
      </div>
    );
  }
  if (!session.data) return <AdminSignIn />;

  return (
    <div className="flex min-h-dvh flex-col">
      <header className="sticky top-0 z-10 border-b bg-background/95 backdrop-blur">
        <div className="mx-auto flex h-12 w-full max-w-6xl items-center gap-1 px-4">
          <span className="mr-3 text-sm font-semibold">HomeHelper admin</span>
          <nav className="flex gap-1" aria-label="Admin sections">
            {SECTIONS.map(({ href, label, icon: Icon }) => (
              <Button
                key={href}
                asChild
                variant="ghost"
                size="sm"
                className={cn(pathname.startsWith(href) && "bg-muted")}
              >
                <Link href={href} aria-current={pathname.startsWith(href) ? "page" : undefined}>
                  <Icon data-icon="inline-start" aria-hidden />
                  {label}
                </Link>
              </Button>
            ))}
          </nav>
          <Button
            variant="ghost"
            size="sm"
            className="ml-auto"
            onClick={() => signOut.mutate()}
            disabled={signOut.isPending}
          >
            <LogOut data-icon="inline-start" aria-hidden />
            Sign out
          </Button>
        </div>
      </header>
      <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-4 px-4 py-6">
        {children}
      </main>
    </div>
  );
}
