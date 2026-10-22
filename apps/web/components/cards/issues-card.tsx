import { ListTodo } from "lucide-react";

import { Button } from "@/components/ui/button";
import type {
  IssuesCard as IssuesCardData,
  StructuredAction,
} from "@/lib/api/types";

/** Problems set aside earlier in the conversation (ADR-007): go back to one, or close it. */
export function IssuesCard({
  card,
  interactive,
  onAction,
}: {
  card: IssuesCardData;
  interactive: boolean;
  onAction: (action: StructuredAction) => void;
}) {
  return (
    <section className="flex flex-col gap-3 rounded-xl border p-4">
      <div className="flex items-center gap-2 text-sm font-medium">
        <ListTodo className="size-4 text-muted-foreground" aria-hidden />
        Still open
      </div>
      <ul className="flex flex-col gap-2">
        {card.issues.map((issue) => (
          <li
            key={issue.issue_id}
            className="flex flex-wrap items-center justify-between gap-2"
          >
            <span className="text-sm">{issue.summary}</span>
            {interactive && (
              <span className="flex gap-2">
                <Button
                  size="sm"
                  onClick={() =>
                    onAction({ type: "resume_issue", value: issue.issue_id })
                  }
                >
                  Continue
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() =>
                    onAction({ type: "close_issue", value: issue.issue_id })
                  }
                >
                  Close
                </Button>
              </span>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
