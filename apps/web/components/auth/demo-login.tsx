"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronRight, UserRound } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { api, unwrap } from "@/lib/api/client";
import { demoUsersQuery, metaQuery, queryKeys } from "@/lib/api/queries";
import { isWrongCode, loginMessage } from "@/lib/auth/login";
import { safeNext } from "@/lib/safe-next";

export function DemoLogin() {
  const router = useRouter();
  const next = useSearchParams().get("next");
  const queryClient = useQueryClient();
  const users = useQuery(demoUsersQuery);
  // A deployed demo can require an access code, so that only people given it start LLM turns.
  const meta = useQuery(metaQuery);
  const codeRequired = meta.data?.access_code_required ?? false;
  const [code, setCode] = useState("");
  const login = useMutation({
    mutationFn: (userId: string | null) =>
      unwrap(
        api.POST("/v1/auth/demo-login", {
          body: { user_id: userId, access_code: codeRequired ? code.trim() : null },
        }),
      ),
    onSuccess: (user) => {
      queryClient.clear();
      queryClient.setQueryData(queryKeys.me, user);
      router.replace(safeNext(next, window.location.origin));
    },
    onError: (error) => {
      if (!isWrongCode(error)) toast.error(loginMessage(error));
    },
  });
  const wrongCode = isWrongCode(login.error);
  // Without /v1/meta it isn't known whether a code is needed, so nobody can sign in yet.
  const disabled =
    login.isPending || !meta.isSuccess || (codeRequired && !code.trim());

  return (
    <div className="flex flex-col gap-3">
      {codeRequired && (
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="access-code">Access code</Label>
          <Input
            id="access-code"
            type="password"
            autoComplete="off"
            value={code}
            onChange={(event) => setCode(event.target.value)}
            aria-invalid={wrongCode ? true : undefined}
            aria-describedby={wrongCode ? "access-code-error" : "access-code-hint"}
          />
          {wrongCode ? (
            <p id="access-code-error" role="alert" className="text-sm text-destructive">
              {loginMessage(login.error)}
            </p>
          ) : (
            <p id="access-code-hint" className="text-sm text-muted-foreground">
              This demo is private. Ask its owner for the code.
            </p>
          )}
        </div>
      )}
      {users.isPending &&
        Array.from({ length: 3 }, (_, i) => <Skeleton key={i} className="h-16 rounded-xl" />)}
      {users.data?.map((user) => (
        <button
          key={user.id}
          type="button"
          disabled={disabled}
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
      {meta.isError && (
        <p className="text-sm text-destructive">Can&apos;t reach the HomeHelper API right now.</p>
      )}
      {users.isError && (
        <p className="text-sm text-destructive">Couldn&apos;t load demo users.</p>
      )}
      <Button variant="outline" size="lg" disabled={disabled} onClick={() => login.mutate(null)}>
        <UserRound data-icon="inline-start" aria-hidden />
        Continue as a guest
      </Button>
    </div>
  );
}
