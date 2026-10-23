"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, Pencil, Trash2, X } from "lucide-react";
import { useId, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  type AnnotationDraft,
  ISSUE_TYPES,
  annotationBody,
  annotationError,
  draftFrom,
  emptyDraft,
  issueLabel,
} from "@/lib/admin/annotation";
import { refreshReview } from "@/lib/admin/cache";
import { ApiError, api, unwrap } from "@/lib/api/client";
import type { Annotation } from "@/lib/api/types";
import { cn } from "@/lib/utils";

import { ExportDialog } from "./export-dialog";

function AnnotationForm({
  initial,
  saving,
  onSave,
  onCancel,
}: {
  initial: AnnotationDraft;
  saving: boolean;
  onSave: (draft: AnnotationDraft) => void;
  onCancel?: () => void;
}) {
  const id = useId();
  const [draft, setDraft] = useState(initial);
  const [tried, setTried] = useState(false);
  const error = annotationError(draft);
  const toggle = (issue: (typeof ISSUE_TYPES)[number], on: boolean) =>
    setDraft((d) => ({
      ...d,
      issueTypes: on ? [...d.issueTypes, issue] : d.issueTypes.filter((i) => i !== issue),
    }));

  return (
    <form
      className="flex flex-col gap-3"
      onSubmit={(event) => {
        event.preventDefault();
        setTried(true);
        if (!error) onSave(draft);
      }}
    >
      <div className="flex gap-2" role="radiogroup" aria-label="Verdict">
        {(["correct", "incorrect"] as const).map((verdict) => (
          <Button
            key={verdict}
            type="button"
            size="sm"
            role="radio"
            aria-checked={draft.verdict === verdict}
            variant={draft.verdict === verdict ? "default" : "outline"}
            onClick={() =>
              setDraft((d) => ({
                ...d,
                verdict,
                issueTypes: verdict === "correct" ? [] : d.issueTypes,
              }))
            }
          >
            {verdict === "correct" ? <Check aria-hidden /> : <X aria-hidden />}
            {verdict === "correct" ? "Correct" : "Incorrect"}
          </Button>
        ))}
      </div>
      {draft.verdict === "incorrect" && (
        <fieldset className="grid grid-cols-2 gap-x-4 gap-y-2">
          <legend className="mb-2 text-sm font-medium">What went wrong</legend>
          {ISSUE_TYPES.map((issue) => (
            <div key={issue} className="flex items-center gap-2">
              <Checkbox
                id={`${id}-${issue}`}
                checked={draft.issueTypes.includes(issue)}
                onCheckedChange={(checked) => toggle(issue, checked === true)}
              />
              <Label htmlFor={`${id}-${issue}`} className="font-normal">
                {issueLabel(issue)}
              </Label>
            </div>
          ))}
        </fieldset>
      )}
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`${id}-expected`}>What it should have said</Label>
        <Textarea
          id={`${id}-expected`}
          rows={3}
          value={draft.expectedResponse}
          onChange={(event) => setDraft((d) => ({ ...d, expectedResponse: event.target.value }))}
        />
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`${id}-notes`}>Notes</Label>
        <Textarea
          id={`${id}-notes`}
          rows={2}
          value={draft.notes}
          onChange={(event) => setDraft((d) => ({ ...d, notes: event.target.value }))}
        />
      </div>
      {tried && error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      <div className="flex gap-2">
        <Button type="submit" size="sm" disabled={saving}>
          Save annotation
        </Button>
        {onCancel && (
          <Button type="button" size="sm" variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
        )}
      </div>
    </form>
  );
}

function AnnotationSummary({
  annotation,
  conversationId,
  onEdit,
  onDelete,
  busy,
}: {
  annotation: Annotation;
  conversationId: string;
  onEdit: () => void;
  onDelete: () => void;
  busy: boolean;
}) {
  const exported = annotation.exported_case_id !== null;
  const [confirming, setConfirming] = useState(false);
  return (
    <div className="flex flex-col gap-2 text-sm">
      <div className="flex flex-wrap items-center gap-1.5">
        <Badge
          variant="secondary"
          className={cn(
            annotation.verdict === "correct"
              ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200"
              : "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-200",
          )}
        >
          {annotation.verdict === "correct" ? "Correct" : "Incorrect"}
        </Badge>
        {annotation.issue_types.map((issue) => (
          <Badge key={issue} variant="outline">
            {issueLabel(issue)}
          </Badge>
        ))}
        {exported && (
          <Badge variant="secondary" title="Exported as a regression case">
            Case <span className="font-mono">{annotation.exported_case_id}</span>
          </Badge>
        )}
      </div>
      {annotation.expected_response && (
        <p>
          <span className="text-muted-foreground">Should say: </span>
          {annotation.expected_response}
        </p>
      )}
      {annotation.notes && <p className="text-muted-foreground">{annotation.notes}</p>}
      {!exported &&
        (confirming ? (
          <div className="flex items-center gap-1" role="group" aria-label="Confirm delete">
            <span className="text-sm">Delete this annotation?</span>
            <Button size="xs" variant="destructive" onClick={onDelete} disabled={busy}>
              Delete
            </Button>
            <Button size="xs" variant="ghost" onClick={() => setConfirming(false)}>
              Keep
            </Button>
          </div>
        ) : (
          <div className="flex gap-1">
            <Button size="xs" variant="ghost" onClick={onEdit} disabled={busy}>
              <Pencil data-icon="inline-start" aria-hidden />
              Edit
            </Button>
            <Button size="xs" variant="ghost" onClick={() => setConfirming(true)} disabled={busy}>
              <Trash2 data-icon="inline-start" aria-hidden />
              Delete
            </Button>
            <ExportDialog annotationId={annotation.id} conversationId={conversationId} />
          </div>
        ))}
    </div>
  );
}

/** Annotations on one assistant reply (spec §17.2): add, edit or delete until exported. */
export function AnnotationPanel({
  conversationId,
  messageId,
  annotations,
}: {
  conversationId: string;
  messageId: string;
  annotations: Annotation[];
}) {
  const queryClient = useQueryClient();
  // An annotation id being edited, "new" for the add form, or null.
  const [editing, setEditing] = useState<string | null>(null);
  const refresh = (delta: number) => refreshReview(queryClient, conversationId, delta);
  const failed = (error: Error) =>
    toast.error(
      error instanceof ApiError && error.status === 409
        ? "This annotation was exported and can't change."
        : "Couldn't save the annotation.",
    );

  const create = useMutation({
    mutationFn: (draft: AnnotationDraft & { verdict: "correct" | "incorrect" }) =>
      unwrap(
        api.POST("/v1/admin/annotations", {
          body: { message_id: messageId, ...annotationBody(draft) },
        }),
      ),
    onSuccess: () => {
      setEditing(null);
      refresh(1);
    },
    onError: failed,
  });
  const update = useMutation({
    mutationFn: ({
      id,
      draft,
    }: {
      id: string;
      draft: AnnotationDraft & { verdict: "correct" | "incorrect" };
    }) =>
      unwrap(
        api.PUT("/v1/admin/annotations/{annotation_id}", {
          params: { path: { annotation_id: id } },
          body: annotationBody(draft),
        }),
      ),
    onSuccess: () => {
      setEditing(null);
      refresh(0);
    },
    onError: failed,
  });
  const remove = useMutation({
    mutationFn: (id: string) =>
      unwrap(
        api.DELETE("/v1/admin/annotations/{annotation_id}", {
          params: { path: { annotation_id: id } },
        }),
      ),
    onSuccess: () => refresh(-1),
    onError: failed,
  });
  const busy = create.isPending || update.isPending || remove.isPending;

  return (
    <section
      aria-label="Annotations"
      className="flex flex-col gap-3 rounded-lg border bg-muted/30 p-3"
    >
      {annotations.map((annotation) =>
        editing === annotation.id ? (
          <AnnotationForm
            key={annotation.id}
            initial={draftFrom(annotation)}
            saving={busy}
            onCancel={() => setEditing(null)}
            onSave={(draft) =>
              draft.verdict &&
              update.mutate({ id: annotation.id, draft: { ...draft, verdict: draft.verdict } })
            }
          />
        ) : (
          <AnnotationSummary
            key={annotation.id}
            annotation={annotation}
            conversationId={conversationId}
            // While a form is open, other annotations wait (its draft isn't thrown away).
            busy={busy || editing !== null}
            onEdit={() => setEditing(annotation.id)}
            onDelete={() => remove.mutate(annotation.id)}
          />
        ),
      )}
      {editing === "new" ? (
        <AnnotationForm
          initial={emptyDraft()}
          saving={busy}
          onCancel={() => setEditing(null)}
          onSave={(draft) => draft.verdict && create.mutate({ ...draft, verdict: draft.verdict })}
        />
      ) : (
        <Button
          size="sm"
          variant="outline"
          className="self-start"
          onClick={() => setEditing("new")}
          disabled={busy || editing !== null}
        >
          Annotate this reply
        </Button>
      )}
    </section>
  );
}
