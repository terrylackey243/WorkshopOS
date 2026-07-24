import { useMemo, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import axios from "axios";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { aiImportApi } from "@/lib/api";
import type { AiExtractedRow, AiProfileTypeKey } from "@/lib/types";

import { PreviewRow, type PreviewRowHandle } from "./PreviewRow";
import { PROFILE_TYPE_CONFIG, PROFILE_TYPE_OPTIONS } from "./profileTypeConfig";

function extractErrorMessage(error: unknown, fallback: string): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === "string") return detail;
  }
  return fallback;
}

interface PreviewRowState {
  key: string;
  row: AiExtractedRow;
}

interface CommitSummary {
  created: number;
  failed: { name: string; message: string }[];
}

export function AiImportPage() {
  const [profileType, setProfileType] = useState<AiProfileTypeKey>("drawer_profile");
  const [unit, setUnit] = useState<"in" | "mm">("in");
  const [prompt, setPrompt] = useState("");
  const [rows, setRows] = useState<PreviewRowState[]>([]);
  const [summary, setSummary] = useState<CommitSummary | null>(null);
  const rowRefs = useRef(new Map<string, PreviewRowHandle | null>());

  const config = PROFILE_TYPE_CONFIG[profileType];

  const existingNames = useMemo(
    () => new Set(rows.filter((r) => r.row.name_conflict && r.row.name).map((r) => r.row.name as string)),
    [rows],
  );

  const extractMutation = useMutation({
    mutationFn: () => aiImportApi.extract({ profile_type: profileType, unit, prompt }),
    onSuccess: (extractedRows) => {
      setRows(extractedRows.map((row) => ({ key: crypto.randomUUID(), row })));
      setSummary(null);
    },
  });

  const [isCommitting, setIsCommitting] = useState(false);

  async function handleCommit() {
    setIsCommitting(true);
    const created: string[] = [];
    const failed: { name: string; message: string }[] = [];

    for (const { key, row } of rows) {
      const handle = rowRefs.current.get(key);
      const values = await handle?.getValidatedValues();
      if (!values) {
        failed.push({ name: row.name ?? "(unnamed)", message: "Fix the highlighted fields above." });
        continue;
      }
      try {
        await config.api.create(values);
        created.push(key);
      } catch (error) {
        failed.push({
          name: String(values.name ?? row.name ?? "(unnamed)"),
          message: extractErrorMessage(error, "Failed to create."),
        });
      }
    }

    setRows((prev) => prev.filter((r) => !created.includes(r.key)));
    setSummary({ created: created.length, failed });
    setIsCommitting(false);
  }

  return (
    <div className="p-4">
      <div className="mb-3">
        <h1 className="text-base font-semibold">AI Import</h1>
        <p className="text-xs text-muted-foreground">
          Describe a batch of profiles in plain text and review a preview before anything is
          created. Uses the Anthropic API key configured in Settings.
        </p>
      </div>

      <div className="flex max-w-2xl flex-col gap-3">
        <div className="grid grid-cols-2 gap-3">
          <div className="flex flex-col gap-1">
            <Label>Profile type</Label>
            <Select
              value={profileType}
              onValueChange={(v) => {
                setProfileType(v as AiProfileTypeKey);
                setRows([]);
                setSummary(null);
              }}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {PROFILE_TYPE_OPTIONS.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-1">
            <Label>Unit</Label>
            <Select value={unit} onValueChange={(v) => setUnit(v as "in" | "mm")}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="in">Inches</SelectItem>
                <SelectItem value="mm">Millimeters</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>

        <div className="flex flex-col gap-1">
          <Label htmlFor="ai-import-prompt">Prompt</Label>
          <Textarea
            id="ai-import-prompt"
            rows={6}
            placeholder={config.placeholder}
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
          />
        </div>

        {extractMutation.isError && (
          <p className="text-xs text-destructive">
            {extractErrorMessage(extractMutation.error, "Failed to generate preview.")}
          </p>
        )}

        <Button
          className="w-fit"
          disabled={!prompt.trim() || extractMutation.isPending}
          onClick={() => extractMutation.mutate()}
        >
          {extractMutation.isPending ? "Generating…" : "Generate preview"}
        </Button>
      </div>

      {rows.length > 0 && (
        <div className="mt-6 flex max-w-2xl flex-col gap-3">
          <h2 className="text-sm font-semibold">
            Preview -- {rows.length} row{rows.length === 1 ? "" : "s"}
          </h2>
          {rows.map(({ key, row }) => (
            <PreviewRow
              key={key}
              ref={(handle) => {
                rowRefs.current.set(key, handle);
              }}
              profileType={profileType}
              row={row}
              existingNames={existingNames}
              onRemove={() => setRows((prev) => prev.filter((r) => r.key !== key))}
            />
          ))}
          <Button className="w-fit" disabled={isCommitting} onClick={handleCommit}>
            {isCommitting ? "Creating…" : `Create ${rows.length} profile${rows.length === 1 ? "" : "s"}`}
          </Button>
        </div>
      )}

      {summary && (
        <div className="mt-4 max-w-2xl rounded-sm border border-border p-3 text-sm">
          {summary.created > 0 && <p>Created {summary.created} profile(s).</p>}
          {summary.failed.length > 0 && (
            <div className="mt-1 text-destructive">
              <p>{summary.failed.length} row(s) need attention:</p>
              <ul className="ml-4 list-disc">
                {summary.failed.map((f, i) => (
                  <li key={i}>
                    {f.name}: {f.message}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
