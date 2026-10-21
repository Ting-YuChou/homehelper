import { BookOpenCheck, ShieldAlert, Wrench } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";

const FEATURES = [
  {
    icon: Wrench,
    title: "One step at a time",
    body: "A guided troubleshooting plan: try a step, tell it whether that fixed it, get the next one.",
  },
  {
    icon: BookOpenCheck,
    title: "Grounded in the manual",
    body: "Every instruction cites the manufacturer's manual, down to the page.",
  },
  {
    icon: ShieldAlert,
    title: "Safety first",
    body: "Gas, smoke or sparks stop the troubleshooting and hand you over to a technician.",
  },
];

export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-4xl flex-1 flex-col justify-center gap-12 px-6 py-16">
      <section className="flex flex-col gap-5">
        <p className="text-sm font-medium tracking-wide text-muted-foreground uppercase">
          Portfolio project · appliance repair support agent
        </p>
        <h1 className="text-4xl font-semibold tracking-tight sm:text-5xl">HomeHelper</h1>
        <p className="max-w-2xl text-lg text-muted-foreground">
          Describe what&apos;s wrong with your dishwasher, washer or fridge and get step-by-step
          help, grounded in the manufacturer&apos;s manual.
        </p>
        <div>
          <Button asChild size="lg">
            <Link href="/login">Start the demo</Link>
          </Button>
        </div>
      </section>
      <section className="grid gap-4 sm:grid-cols-3">
        {FEATURES.map(({ icon: Icon, title, body }) => (
          <div key={title} className="flex flex-col gap-2 rounded-xl border p-5">
            <Icon className="size-5 text-muted-foreground" aria-hidden />
            <h2 className="font-medium">{title}</h2>
            <p className="text-sm text-muted-foreground">{body}</p>
          </div>
        ))}
      </section>
    </main>
  );
}
