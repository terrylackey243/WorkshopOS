import { forwardRef, useImperativeHandle } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
// eslint-disable-next-line @typescript-eslint/no-explicit-any -- form is shared across 5 differently-shaped schemas, same rationale as fields.tsx's AnyForm
import { useForm } from "react-hook-form";

import { NumberField, TextField } from "@/pages/profiles/fields";
import type { AiExtractedRow, AiProfileTypeKey } from "@/lib/types";

import { PROFILE_TYPE_CONFIG } from "./profileTypeConfig";

export interface PreviewRowHandle {
  // Runs this row's own zod validation; returns the validated values ready
  // to hand to `*ProfilesApi.create()`, or null if this row has errors (its
  // own error messages are already visible in the row -- nothing more to
  // report to the caller).
  getValidatedValues: () => Promise<Record<string, unknown> | null>;
}

interface PreviewRowProps {
  profileType: AiProfileTypeKey;
  row: AiExtractedRow;
  // Names known to already exist for this org+profile-type -- every row the
  // extract endpoint flagged `name_conflict` on contributes its own name to
  // this set, so renaming a row here can be re-checked without another
  // network round-trip.
  existingNames: Set<string>;
  onRemove: () => void;
}

export const PreviewRow = forwardRef<PreviewRowHandle, PreviewRowProps>(function PreviewRow(
  { profileType, row, existingNames, onRemove }: PreviewRowProps,
  ref,
) {
  const config = PROFILE_TYPE_CONFIG[profileType];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const form = useForm<any>({
    resolver: zodResolver(config.schema),
    defaultValues: { ...config.defaultValues, ...row.fields, name: row.name ?? "" },
  });

  useImperativeHandle(ref, () => ({
    getValidatedValues: async () => {
      const valid = await form.trigger();
      return valid ? form.getValues() : null;
    },
  }));

  const name: string | undefined = form.watch("name");
  const nameMissing = !name || !name.trim();
  const nameConflict = !nameMissing && existingNames.has(name.trim());

  return (
    <div className="flex flex-col gap-2 rounded-sm border border-border p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="max-w-xs flex-1">
          <TextField form={form} name="name" label="Name" />
          {nameMissing && <p className="mt-1 text-xs text-destructive">Name required</p>}
          {nameConflict && <p className="mt-1 text-xs text-destructive">This name already exists</p>}
        </div>
        <button
          type="button"
          onClick={onRemove}
          className="mt-5 shrink-0 text-xs text-muted-foreground hover:text-destructive"
        >
          Remove
        </button>
      </div>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {config.fields.map((f) =>
          f.kind === "number" ? (
            <NumberField key={f.name} form={form} name={f.name} label={f.label} step={f.step} />
          ) : (
            <TextField key={f.name} form={form} name={f.name} label={f.label} />
          ),
        )}
      </div>
    </div>
  );
});
