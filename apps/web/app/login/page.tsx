import type { Metadata } from "next";
import { Suspense } from "react";

import { DemoLogin } from "@/components/auth/demo-login";

export const metadata: Metadata = { title: "Sign in" };

export default function LoginPage() {
  return (
    <main className="mx-auto flex w-full max-w-md flex-1 flex-col justify-center gap-6 px-4 py-12">
      <div className="flex flex-col gap-2">
        <h1 className="text-2xl font-semibold tracking-tight">Pick a demo user</h1>
        <p className="text-sm text-muted-foreground">
          Demo users come with appliances and repair history. Guests get the same help, without
          personalization.
        </p>
      </div>
      {/* useSearchParams reads the request, so it renders below a Suspense boundary. */}
      <Suspense>
        <DemoLogin />
      </Suspense>
    </main>
  );
}
