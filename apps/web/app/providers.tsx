"use client";

import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";

import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ApiError } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/queries";

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(() => {
    // An expired admin session (401 on an admin call) sends the reviewer back to sign-in.
    const adminSessionEnded = (error: Error, admin: boolean) => {
      if (admin && error instanceof ApiError && error.status === 401) {
        client.setQueryData(queryKeys.adminSession, false);
      }
    };
    const client: QueryClient = new QueryClient({
      queryCache: new QueryCache({
        onError: (error, query) =>
          adminSessionEnded(
            error,
            query.queryKey[0] === "admin" && query.queryKey[1] !== "session",
          ),
      }),
      mutationCache: new MutationCache({
        onError: (error) => adminSessionEnded(error, window.location.pathname.startsWith("/admin")),
      }),
      defaultOptions: { queries: { staleTime: 30_000, refetchOnWindowFocus: false } },
    });
    return client;
  });
  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>{children}</TooltipProvider>
      <Toaster position="top-center" />
    </QueryClientProvider>
  );
}
