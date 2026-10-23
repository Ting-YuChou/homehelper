"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, api, unwrap } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/queries";
import { signInMessage } from "@/lib/admin/session";

/** Exchanges the admin token for the httpOnly `hh_admin` cookie; the token isn't kept here. */
export function AdminSignIn() {
  const queryClient = useQueryClient();
  const [token, setToken] = useState("");
  const signIn = useMutation({
    mutationFn: (value: string) =>
      unwrap(api.POST("/v1/admin/session", { body: { token: value } })),
    onSuccess: () => {
      setToken("");
      queryClient.setQueryData(queryKeys.adminSession, true);
    },
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (token.trim()) signIn.mutate(token.trim());
  };
  const error =
    signIn.error instanceof ApiError
      ? signInMessage(signIn.error.status)
      : signIn.error
        ? signInMessage(0)
        : null;

  return (
    <main className="mx-auto flex w-full max-w-sm flex-1 flex-col justify-center gap-6 px-4 py-12">
      <div className="flex flex-col gap-2">
        <h1 className="text-2xl font-semibold tracking-tight">Admin sign-in</h1>
        <p className="text-sm text-muted-foreground">
          Review conversations and eval reports. Enter the API&apos;s admin token.
        </p>
      </div>
      <form className="flex flex-col gap-3" onSubmit={submit}>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="admin-token">Admin token</Label>
          <Input
            id="admin-token"
            type="password"
            autoComplete="current-password"
            value={token}
            onChange={(event) => setToken(event.target.value)}
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? "admin-token-error" : undefined}
          />
          {error && (
            <p id="admin-token-error" role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
        </div>
        <Button type="submit" disabled={!token.trim() || signIn.isPending}>
          Sign in
        </Button>
      </form>
    </main>
  );
}
