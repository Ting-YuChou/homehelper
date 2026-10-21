"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronRight, UserRound } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { api, unwrap } from "@/lib/api/client";
import { demoUsersQuery, queryKeys } from "@/lib/api/queries";

function safeNext(next: string | null): string {
  // Only same-app paths, never an open redirect.
  return next?.startsWith("/") && !next.startsWith("//") ? next : "/chat";
}

export function DemoLogin() {
  const router = useRouter();
  const next = safeNext(useSearchParams().get("next"));
  const queryClient = useQueryClient();
  const users = useQuery(demoUsersQuery);
  const login = useMutation({
    mutationFn: (userId: string | null) =>
      unwrap(api.POST("/v1/auth/demo-login", { body: { user_id: userId } })),
    onSuccess: (user) => {
      queryClient.clear();
      queryClient.setQueryData(queryKeys.me, user);
      router.replace(next);
    },
    onError: () => toast.error("Couldn't sign in. Is the API running?"),
  });

  return (
    <div className="flex flex-col gap-3">
      {users.isPending &&
        Array.from({ length: 3 }, (_, i) => <Skeleton key={i} className="h-16 rounded-xl" />)}
      {users.data?.map((user) => (
        <button
          key={user.id}
          type="button"
          disabled={login.isPending}
          onClick={() => login.mutate(user.id)}
          className="flex items-center gap-3 rounded-xl border p-4 text-left transition-colors hover:bg-muted disabled:opacity-50"
        >
          <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-muted font-medium">
            {user.display_name.slice(0, 1)}
          </span>
          <span className="flex min-w-0 flex-1 flex-col">
            <span className="font-medium">{user.display_name}</span>
            {user.description && (
              <span className="truncate text-sm text-muted-foreground">{user.description}</span>
            )}
          </span>
          <ChevronRight className="size-4 text-muted-foreground" aria-hidden />
        </button>
      ))}
      {users.isError && (
        <p className="text-sm text-destructive">Couldn&apos;t load demo users.</p>
      )}
      <Button
        variant="outline"
        size="lg"
        disabled={login.isPending}
        onClick={() => login.mutate(null)}
      >
        <UserRound data-icon="inline-start" aria-hidden />
        Continue as a guest
      </Button>
    </div>
  );
}
