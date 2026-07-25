import { useMemo, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import axios from "axios";
import { Camera } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  AI_TOOL_PHOTO_MAX_BYTES,
  extractToolsFromPhoto,
  fetchAllDrawerOptions,
  shopsApi,
  toolboxesApi,
  toolsApi,
  drawersApi,
} from "@/lib/api";
import type { AiToolExtractedRow } from "@/lib/types";

import { ToolPreviewRow, type PreviewRowHandle } from "./ToolPreviewRow";

function extractErrorMessage(error: unknown, fallback: string): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === "string") return detail;
  }
  return fallback;
}

interface PreviewRowState {
  key: string;
  row: AiToolExtractedRow;
}

interface CommitSummary {
  created: number;
  failed: { name: string; message: string }[];
}

export function AiAddToolPage() {
  const [shopId, setShopId] = useState<string | undefined>();
  const [toolboxId, setToolboxId] = useState<string | undefined>();
  const [drawerId, setDrawerId] = useState<string | undefined>();
  const [rows, setRows] = useState<PreviewRowState[]>([]);
  const [summary, setSummary] = useState<CommitSummary | null>(null);
  const [isCommitting, setIsCommitting] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const [fileError, setFileError] = useState<string | null>(null);
  const rowRefs = useRef(new Map<string, PreviewRowHandle | null>());
  const fileInputRef = useRef<HTMLInputElement>(null);
  const cameraInputRef = useRef<HTMLInputElement>(null);

  const shopsQuery = useQuery({ queryKey: ["shops"], queryFn: () => shopsApi.list() });
  const toolboxesQuery = useQuery({
    queryKey: ["toolboxes", shopId],
    queryFn: () => toolboxesApi.list(shopId as string),
    enabled: !!shopId,
  });
  const drawersQuery = useQuery({
    queryKey: ["drawers", shopId, toolboxId],
    queryFn: () => drawersApi.list(shopId as string, toolboxId as string),
    enabled: !!shopId && !!toolboxId,
  });
  // Same query key ToolsPage.tsx uses for its flattened drawer picker, so
  // this shares its cache rather than firing a redundant N x M x K fan-out.
  const drawerOptionsQuery = useQuery({
    queryKey: ["drawers", "all-with-path"],
    queryFn: fetchAllDrawerOptions,
  });

  const extractMutation = useMutation({
    mutationFn: (file: File) => extractToolsFromPhoto(file),
    onSuccess: (extractedRows) => {
      setRows(extractedRows.map((row) => ({ key: crypto.randomUUID(), row })));
      setSummary(null);
    },
  });

  function handleFile(file: File) {
    if (file.size > AI_TOOL_PHOTO_MAX_BYTES) {
      // Reject client-side before ever starting the upload -- found by hand
      // when a 39MB file's upload stalled on a slow connection and got
      // dropped mid-transfer with no HTTP response at all, leaving the page
      // stuck on "Identifying tools..." forever (see extractToolsFromPhoto's
      // timeout for the other half of that fix). The server would reject
      // this file anyway once fully uploaded, so there's no reason to make
      // the user wait through the upload first.
      setFileError(
        `Photo exceeds the ${AI_TOOL_PHOTO_MAX_BYTES / (1024 * 1024)}MB upload limit ` +
          `(this one is ${(file.size / (1024 * 1024)).toFixed(1)}MB). Try a smaller export/JPEG.`,
      );
      return;
    }
    setFileError(null);
    extractMutation.mutate(file);
  }

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
        await toolsApi.create({
          name: values.name,
          category: values.category || null,
          manufacturer: values.manufacturer || null,
          notes: values.notes || null,
          quantity: values.quantity,
          drawer_id: values.drawer_id || null,
        });
        created.push(key);
      } catch (error) {
        failed.push({
          name: values.name || row.name || "(unnamed)",
          message: extractErrorMessage(error, "Failed to create."),
        });
      }
    }

    setRows((prev) => prev.filter((r) => !created.includes(r.key)));
    setSummary({ created: created.length, failed });
    setIsCommitting(false);
  }

  function handleRejectAll() {
    setRows([]);
    setSummary(null);
  }

  const drawerOptions = useMemo(() => drawerOptionsQuery.data ?? [], [drawerOptionsQuery.data]);
  const canUpload = !!drawerId;

  return (
    <div className="flex h-full flex-col overflow-auto scrollbar-thin p-4">
      <div className="mb-3">
        <h1 className="text-base font-semibold">AI Add Tool</h1>
        <p className="text-xs text-muted-foreground">
          Pick a drawer, then drop in a photo of one or more tools laid on a sheet of paper --
          Claude identifies each one for you to review before anything is created. Uses the
          Anthropic API key configured in Settings.
        </p>
      </div>

      <div className="flex max-w-3xl flex-col gap-3">
        <div className="grid grid-cols-3 gap-3">
          <div className="flex flex-col gap-1">
            <Label>Shop</Label>
            <Select
              value={shopId}
              onValueChange={(v) => {
                setShopId(v);
                setToolboxId(undefined);
                setDrawerId(undefined);
              }}
            >
              <SelectTrigger>
                <SelectValue placeholder="Select a shop" />
              </SelectTrigger>
              <SelectContent>
                {(shopsQuery.data ?? []).map((shop) => (
                  <SelectItem key={shop.id} value={shop.id}>
                    {shop.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-1">
            <Label>Toolbox</Label>
            <Select
              value={toolboxId}
              onValueChange={(v) => {
                setToolboxId(v);
                setDrawerId(undefined);
              }}
              disabled={!shopId}
            >
              <SelectTrigger>
                <SelectValue placeholder={shopId ? "Select a toolbox" : "Select a shop first"} />
              </SelectTrigger>
              <SelectContent>
                {(toolboxesQuery.data ?? []).map((toolbox) => (
                  <SelectItem key={toolbox.id} value={toolbox.id}>
                    {toolbox.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-1">
            <Label>Drawer</Label>
            <Select value={drawerId} onValueChange={setDrawerId} disabled={!toolboxId}>
              <SelectTrigger>
                <SelectValue placeholder={toolboxId ? "Select a drawer" : "Select a toolbox first"} />
              </SelectTrigger>
              <SelectContent>
                {(drawersQuery.data ?? []).map((drawer) => (
                  <SelectItem key={drawer.id} value={drawer.id}>
                    {drawer.name || drawer.position_label || "Drawer"}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        <div className="flex flex-col gap-1">
          <Label>Photo</Label>
          <div
            onDragOver={(e) => {
              if (!canUpload) return;
              e.preventDefault();
              setIsDragging(true);
            }}
            onDragLeave={() => setIsDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setIsDragging(false);
              if (!canUpload) return;
              const file = e.dataTransfer.files?.[0];
              if (file) handleFile(file);
            }}
            onClick={() => canUpload && fileInputRef.current?.click()}
            className={`flex flex-col items-center justify-center gap-1 rounded-sm border border-dashed p-6 text-center text-sm transition-colors ${
              canUpload
                ? `cursor-pointer border-border text-muted-foreground hover:bg-accent ${isDragging ? "bg-accent" : ""}`
                : "cursor-not-allowed border-border/50 text-muted-foreground/50"
            }`}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept="image/*"
              className="hidden"
              disabled={!canUpload}
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) handleFile(file);
                e.target.value = "";
              }}
            />
            {/* `capture="environment"` sends a mobile browser straight into
                the rear camera instead of the OS's Photo Library/Take
                Photo/Browse chooser -- ignored on desktop, where this input
                just behaves like the one above. Separate input (not reused)
                because an input can't switch `capture` on and off live. */}
            <input
              ref={cameraInputRef}
              type="file"
              accept="image/*"
              capture="environment"
              className="hidden"
              disabled={!canUpload}
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) handleFile(file);
                e.target.value = "";
              }}
            />
            <p>
              {canUpload
                ? "Drop a photo here, or click to browse"
                : "Select a shop, toolbox, and drawer first"}
            </p>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={!canUpload}
              onClick={(e) => {
                e.stopPropagation();
                cameraInputRef.current?.click();
              }}
            >
              <Camera className="h-3.5 w-3.5" />
              Take Photo
            </Button>
            {extractMutation.isPending && <p className="text-xs">Identifying tools…</p>}
          </div>
          {fileError && <p className="text-xs text-destructive">{fileError}</p>}
          {!fileError && extractMutation.isError && (
            <p className="text-xs text-destructive">
              {extractErrorMessage(
                extractMutation.error,
                "Failed to identify tools in this photo. The connection may have dropped mid-upload -- try again.",
              )}
            </p>
          )}
        </div>
      </div>

      {rows.length > 0 && (
        <div className="mt-6 flex max-w-3xl flex-col gap-3">
          <h2 className="text-sm font-semibold">
            Preview -- {rows.length} row{rows.length === 1 ? "" : "s"}
          </h2>
          {rows.map(({ key, row }) => (
            <ToolPreviewRow
              key={key}
              ref={(handle) => {
                rowRefs.current.set(key, handle);
              }}
              row={row}
              drawerOptions={drawerOptions}
              defaultDrawerId={drawerId}
              onRemove={() => setRows((prev) => prev.filter((r) => r.key !== key))}
            />
          ))}
          <div className="flex items-center gap-2">
            <Button className="w-fit" disabled={isCommitting} onClick={handleCommit}>
              {isCommitting ? "Creating…" : `Create ${rows.length} tool${rows.length === 1 ? "" : "s"}`}
            </Button>
            <Button
              className="w-fit"
              variant="outline"
              disabled={isCommitting}
              onClick={handleRejectAll}
            >
              Reject All
            </Button>
          </div>
        </div>
      )}

      {summary && (
        <div className="mt-4 max-w-3xl rounded-sm border border-border p-3 text-sm">
          {summary.created > 0 && <p>Created {summary.created} tool(s).</p>}
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
