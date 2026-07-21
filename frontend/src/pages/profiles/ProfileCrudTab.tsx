import * as React from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import axios from "axios";
import { Plus, Star, Trash2 } from "lucide-react";
import { useForm, type UseFormReturn } from "react-hook-form";
import type { ZodType } from "zod";

import { FormDialog } from "@/components/FormDialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

function extractErrorMessage(error: unknown, fallback: string): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === "string") return detail;
  }
  return fallback;
}

interface ProfileBase {
  id: string;
  name: string;
  is_default: boolean;
}

interface ProfileApi<T> {
  list: () => Promise<T[]>;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  create: (payload: any) => Promise<T>;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  update: (id: string, payload: any) => Promise<T>;
  remove: (id: string) => Promise<void>;
  setDefault: (id: string) => Promise<T>;
}

interface Column<T> {
  key: string;
  label: string;
  format?: (row: T) => React.ReactNode;
  mono?: boolean;
}

interface ProfileCrudTabProps<T extends ProfileBase, TForm extends Record<string, unknown>> {
  entityLabel: string;
  queryKey: string;
  api: ProfileApi<T>;
  columns: Column<T>[];
  schema: ZodType<TForm>;
  defaultValues: TForm;
  renderFields: (form: UseFormReturn<TForm>) => React.ReactNode;
  toEditValues?: (row: T) => TForm;
}

export function ProfileCrudTab<T extends ProfileBase, TForm extends Record<string, unknown>>({
  entityLabel,
  queryKey,
  api,
  columns,
  schema,
  defaultValues,
  renderFields,
  toEditValues,
}: ProfileCrudTabProps<T, TForm>) {
  const qc = useQueryClient();
  const [createOpen, setCreateOpen] = React.useState(false);
  const [editRow, setEditRow] = React.useState<T | null>(null);
  const [createError, setCreateError] = React.useState<string | null>(null);
  const [editError, setEditError] = React.useState<string | null>(null);

  const listQuery = useQuery({ queryKey: [queryKey], queryFn: api.list });

  const createForm = useForm<TForm>({ resolver: zodResolver(schema), defaultValues: defaultValues as never });
  const editForm = useForm<TForm>({ resolver: zodResolver(schema), defaultValues: defaultValues as never });

  React.useEffect(() => {
    if (editRow) {
      editForm.reset((toEditValues ? toEditValues(editRow) : (editRow as unknown as TForm)));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editRow]);

  const createMutation = useMutation({
    mutationFn: (values: TForm) => api.create(values),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: [queryKey] });
      setCreateOpen(false);
      setCreateError(null);
      createForm.reset(defaultValues as never);
    },
    onError: (error: unknown) => {
      setCreateError(extractErrorMessage(error, `Failed to create ${entityLabel.toLowerCase()}. Please try again.`));
    },
  });

  const updateMutation = useMutation({
    mutationFn: (values: TForm) => api.update(editRow!.id, values),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: [queryKey] });
      setEditRow(null);
      setEditError(null);
    },
    onError: (error: unknown) => {
      setEditError(extractErrorMessage(error, `Failed to save ${entityLabel.toLowerCase()}. Please try again.`));
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.remove(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: [queryKey] }),
  });

  const setDefaultMutation = useMutation({
    mutationFn: (id: string) => api.setDefault(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: [queryKey] }),
  });

  return (
    <div>
      <div className="mb-3 flex items-center justify-between">
        <p className="text-xs text-muted-foreground">
          {(listQuery.data ?? []).length} {entityLabel.toLowerCase()}
          {(listQuery.data ?? []).length === 1 ? "" : "s"}
        </p>
        <FormDialog
          open={createOpen}
          onOpenChange={(o) => {
            setCreateOpen(o);
            if (!o) setCreateError(null);
          }}
          trigger={
            <Button size="sm">
              <Plus />
              New {entityLabel.toLowerCase()}
            </Button>
          }
          title={`New ${entityLabel.toLowerCase()}`}
          formId={`create-${queryKey}`}
          submitting={createMutation.isPending}
        >
          <form
            id={`create-${queryKey}`}
            onSubmit={createForm.handleSubmit(
              (v) => {
                setCreateError(null);
                createMutation.mutate(v);
              },
              () => setCreateError(`Check the highlighted fields for ${entityLabel.toLowerCase()} — one or more values are invalid.`),
            )}
            className="flex flex-col gap-3"
          >
            {renderFields(createForm)}
            {createError && (
              <p className="rounded-sm border border-destructive/30 bg-destructive/10 px-2.5 py-1.5 text-xs text-destructive">
                {createError}
              </p>
            )}
          </form>
        </FormDialog>
      </div>

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            {columns.map((c) => (
              <TableHead key={c.key}>{c.label}</TableHead>
            ))}
            <TableHead>Default</TableHead>
            <TableHead />
          </TableRow>
        </TableHeader>
        <TableBody>
          {(listQuery.data ?? []).map((row) => (
            <TableRow key={row.id}>
              <TableCell>
                <button
                  type="button"
                  className="font-medium hover:underline"
                  onClick={() => setEditRow(row)}
                >
                  {row.name}
                </button>
              </TableCell>
              {columns.map((c) => (
                <TableCell
                  key={c.key}
                  className={c.mono ? "font-mono text-muted-foreground" : "text-muted-foreground"}
                >
                  {c.format ? c.format(row) : String((row as Record<string, unknown>)[c.key] ?? "—")}
                </TableCell>
              ))}
              <TableCell>
                {row.is_default ? (
                  <Badge>
                    <Star className="mr-1 h-2.5 w-2.5 fill-current" />
                    Default
                  </Badge>
                ) : (
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-6 px-1.5 text-xs"
                    onClick={() => setDefaultMutation.mutate(row.id)}
                  >
                    Make default
                  </Button>
                )}
              </TableCell>
              <TableCell>
                <Button
                  size="icon"
                  variant="ghost"
                  onClick={() => {
                    if (confirm(`Delete "${row.name}"?`)) deleteMutation.mutate(row.id);
                  }}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </TableCell>
            </TableRow>
          ))}
          {listQuery.isSuccess && listQuery.data.length === 0 && (
            <TableRow>
              <TableCell colSpan={columns.length + 3} className="py-6 text-center text-muted-foreground">
                No {entityLabel.toLowerCase()}s yet.
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>

      <FormDialog
        open={!!editRow}
        onOpenChange={(o) => {
          if (!o) {
            setEditRow(null);
            setEditError(null);
          }
        }}
        trigger={<span />}
        title={`Edit ${entityLabel.toLowerCase()}`}
        formId={`edit-${queryKey}`}
        submitting={updateMutation.isPending}
      >
        <form
          id={`edit-${queryKey}`}
          onSubmit={editForm.handleSubmit(
            (v) => {
              setEditError(null);
              updateMutation.mutate(v);
            },
            () => setEditError(`Check the highlighted fields for ${entityLabel.toLowerCase()} — one or more values are invalid.`),
          )}
          className="flex flex-col gap-3"
        >
          {renderFields(editForm)}
          {editError && (
            <p className="rounded-sm border border-destructive/30 bg-destructive/10 px-2.5 py-1.5 text-xs text-destructive">
              {editError}
            </p>
          )}
        </form>
      </FormDialog>
    </div>
  );
}
