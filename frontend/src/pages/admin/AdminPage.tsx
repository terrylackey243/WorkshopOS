import * as React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import axios from "axios";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { adminApi } from "@/lib/api";

// Fixed, known plan keys (matches backend `Plan.key` seed data / license
// tiers -- see backend/app/models/org.py's FREE_PLAN_ID/PRO_PLAN_ID/
// ENTERPRISE_PLAN_ID, backend/app/services/license.py's VALID_TIERS).
const PLAN_OPTIONS = [
  { key: "free", label: "Free" },
  { key: "pro", label: "Pro" },
  { key: "enterprise", label: "Enterprise" },
] as const;

/**
 * Superadmin-only: manually grant a plan to any organization, bypassing
 * Stripe checkout and self-hosted license keys entirely. Server-side
 * authorization is the only real gate (deps.require_superadmin) -- this
 * page is reachable by anyone, but every request 403s unless the caller's
 * email is in Settings.superadmin_emails.
 */
export function AdminPage() {
  const [search, setSearch] = React.useState("");
  const queryClient = useQueryClient();

  const orgsQuery = useQuery({
    queryKey: ["admin", "organizations", search],
    queryFn: () => adminApi.listOrganizations(search || undefined),
  });

  const setPlanMutation = useMutation({
    mutationFn: ({ organizationId, planKey }: { organizationId: string; planKey: string }) =>
      adminApi.setPlan(organizationId, planKey),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "organizations"] });
    },
  });

  const errorDetail = (error: unknown, fallback: string): string =>
    axios.isAxiosError(error) && typeof error.response?.data?.detail === "string"
      ? error.response.data.detail
      : fallback;

  return (
    <div className="flex flex-col gap-4 p-4">
      <div>
        <h1 className="text-base font-semibold">Admin</h1>
        <p className="text-xs text-muted-foreground">
          Manually grant a plan to any organization — bypasses Stripe and license keys
          entirely. Only visible to superadmin accounts.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Organizations</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <Input
            placeholder="Search by org name, slug, or owner email…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="max-w-sm"
          />

          {orgsQuery.isError && (
            <p className="text-xs text-destructive">
              {errorDetail(orgsQuery.error, "Failed to load organizations.")}
            </p>
          )}
          {setPlanMutation.isError && (
            <p className="text-xs text-destructive">
              {errorDetail(setPlanMutation.error, "Failed to update plan.")}
            </p>
          )}

          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Organization</TableHead>
                <TableHead>Owner</TableHead>
                <TableHead>Plan</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {orgsQuery.data?.map((org) => {
                const isPending =
                  setPlanMutation.isPending && setPlanMutation.variables?.organizationId === org.id;
                return (
                  <TableRow key={org.id}>
                    <TableCell>
                      <div className="flex flex-col">
                        <span>{org.name}</span>
                        <span className="font-mono text-xs text-muted-foreground">{org.slug}</span>
                      </div>
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {org.owner_email ?? "—"}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <Select
                          value={org.plan_key}
                          disabled={isPending}
                          onValueChange={(planKey) =>
                            setPlanMutation.mutate({ organizationId: org.id, planKey })
                          }
                        >
                          <SelectTrigger className="w-36">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            {PLAN_OPTIONS.map((p) => (
                              <SelectItem key={p.key} value={p.key}>
                                {p.label}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                        {isPending && (
                          <Badge variant="secondary" className="text-[10px]">
                            Saving…
                          </Badge>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })}
              {orgsQuery.data?.length === 0 && (
                <TableRow>
                  <TableCell colSpan={3} className="text-center text-sm text-muted-foreground">
                    No organizations match.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
