"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileOutput } from "lucide-react";
import { useId, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import {
  type ExportForm,
  type ExportRequest,
  OUTCOMES,
  type Outcome,
  exportBody,
  formFromCase,
  hasChecks,
} from "@/lib/admin/export";
import { api, unwrap } from "@/lib/api/client";
import { adminManualsQuery, queryKeys } from "@/lib/api/queries";

const NO_MANUAL = "none";
const OUTCOME_LABELS: Record<Outcome, string> = {
  resolved: "Resolved",
  escalated: "Escalated to a technician",
  abandoned: "Abandoned",
  out_of_scope: "Out of scope",
};

function exportCall(annotationId: string, body: ExportRequest, dryRun: boolean) {
  return unwrap(
    api.POST("/v1/admin/annotations/{annotation_id}/export", {
      params: { path: { annotation_id: annotationId }, query: { dry_run: dryRun } },
      body,
    }),
  );
}

function ExportFields({
  form,
  onChange,
}: {
  form: ExportForm;
  onChange: (form: ExportForm) => void;
}) {
  const id = useId();
  const manuals = useQuery(adminManualsQuery);
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`${id}-behavior`}>The last reply should</Label>
        <Textarea
          id={`${id}-behavior`}
          rows={3}
          value={form.expectedBehavior}
          onChange={(event) => onChange({ ...form, expectedBehavior: event.target.value })}
          placeholder="Judged by the LLM judge, e.g. “Gives one step and waits for the result.”"
        />
      </div>
      <div className="flex flex-wrap gap-4">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`${id}-outcome`}>Outcome after the reply</Label>
          <Select
            value={form.outcome}
            onValueChange={(value) =>
              onChange({ ...form, outcome: value as ExportForm["outcome"] })
            }
          >
            <SelectTrigger id={`${id}-outcome`} className="w-56">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="any">Not checked</SelectItem>
              {OUTCOMES.map((outcome) => (
                <SelectItem key={outcome} value={outcome}>
                  {OUTCOME_LABELS[outcome]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`${id}-manual`}>Must cite</Label>
          <Select
            value={form.docId ?? NO_MANUAL}
            onValueChange={(value) =>
              onChange({ ...form, docId: value === NO_MANUAL ? null : value })
            }
          >
            <SelectTrigger id={`${id}-manual`} className="w-64">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NO_MANUAL}>Any manual</SelectItem>
              {(manuals.data ?? []).map((manual) => (
                <SelectItem key={manual.doc_id} value={manual.doc_id}>
                  {manual.title}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
      <div className="flex flex-col gap-2">
        <div className="flex items-center gap-2">
          <Checkbox
            id={`${id}-no-steps`}
            checked={form.forbidStepCards}
            onCheckedChange={(checked) => onChange({ ...form, forbidStepCards: checked === true })}
          />
          <Label htmlFor={`${id}-no-steps`} className="font-normal">
            No repair steps at all
          </Label>
        </div>
        <div className="flex items-center gap-2">
          <Checkbox
            id={`${id}-one-step`}
            checked={form.oneStepPerReply}
            onCheckedChange={(checked) => onChange({ ...form, oneStepPerReply: checked === true })}
          />
          <Label htmlFor={`${id}-one-step`} className="font-normal">
            At most one step card per reply
          </Label>
        </div>
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`${id}-forbidden`}>Must never say (one phrase per line)</Label>
        <Textarea
          id={`${id}-forbidden`}
          rows={2}
          value={form.forbiddenText}
          onChange={(event) => onChange({ ...form, forbiddenText: event.target.value })}
        />
      </div>
    </div>
  );
}

/** Export an annotation as a regression case: preview the suggested checks, adjust, export. */
export function ExportDialog({
  annotationId,
  conversationId,
}: {
  annotationId: string;
  conversationId: string;
}) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<ExportForm | null>(null);
  const [yaml, setYaml] = useState<string | null>(null);

  const preview = useMutation({
    mutationFn: (body: ExportRequest) => exportCall(annotationId, body, true),
    onSuccess: (result) => {
      setForm((current) => current ?? formFromCase(result.case));
      setYaml(result.yaml);
    },
    onError: (error) => toast.error(error.message || "Couldn't preview the case."),
  });
  const save = useMutation({
    mutationFn: (body: ExportRequest) => exportCall(annotationId, body, false),
    onSuccess: (result) => {
      setOpen(false);
      toast.success(`Exported ${result.case.id}. Run “uv run evals regression pull” to add it.`);
      void queryClient.invalidateQueries({
        queryKey: queryKeys.adminConversation(conversationId),
      });
    },
    onError: (error) => toast.error(error.message || "Couldn't export the case."),
  });

  const openChange = (next: boolean) => {
    setOpen(next);
    if (next && !form) preview.mutate({});
  };

  return (
    <Dialog open={open} onOpenChange={openChange}>
      <DialogTrigger asChild>
        <Button size="xs" variant="ghost">
          <FileOutput data-icon="inline-start" aria-hidden />
          Export as regression case
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Export as a regression case</DialogTitle>
          <DialogDescription>
            The case replays every customer message before this reply, then checks the reply the
            agent gives now. Exporting freezes the annotation.
          </DialogDescription>
        </DialogHeader>
        {form ? (
          <ExportFields form={form} onChange={setForm} />
        ) : (
          <Skeleton className="h-64 w-full" />
        )}
        {yaml && (
          <details className="rounded-lg border bg-muted/30 p-3 text-xs">
            <summary className="cursor-pointer text-sm">Case file preview</summary>
            <pre className="mt-2 overflow-x-auto whitespace-pre-wrap">{yaml}</pre>
          </details>
        )}
        {form && !hasChecks(form) && (
          <p role="alert" className="text-sm text-destructive">
            Add at least one check.
          </p>
        )}
        <DialogFooter>
          <Button
            variant="outline"
            disabled={!form || preview.isPending}
            onClick={() => form && preview.mutate(exportBody(form))}
          >
            Update preview
          </Button>
          <Button
            disabled={!form || !hasChecks(form) || save.isPending}
            onClick={() => form && save.mutate(exportBody(form))}
          >
            Export
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
