import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import axios from "axios";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useAuth } from "@/hooks/useAuth";
import { useDeploymentMode } from "@/hooks/useDeploymentMode";
import { aiImportApi, billingApi, exportOrganization, organizationsApi, triggerBlobDownload } from "@/lib/api";

const licenseSchema = z.object({
  license_key: z.string().min(1, "Required"),
});
type LicenseFormValues = z.infer<typeof licenseSchema>;

const aiSettingsSchema = z.object({
  anthropic_api_key: z.string().min(1, "Required"),
});
type AiSettingsFormValues = z.infer<typeof aiSettingsSchema>;

export function SettingsPage() {
  const { user, organizations, activeOrgId } = useAuth();
  const queryClient = useQueryClient();
  const deploymentModeQuery = useDeploymentMode();

  const orgQueryKey = ["organizations", activeOrgId];
  const orgQuery = useQuery({
    queryKey: orgQueryKey,
    queryFn: () => organizationsApi.get(activeOrgId as string),
    enabled: !!activeOrgId,
  });

  const activeOrgSummary = organizations.find((org) => org.id === activeOrgId);

  const exportMutation = useMutation({
    mutationFn: () => exportOrganization(),
    onSuccess: (blob) => {
      const slug = activeOrgSummary?.slug ?? "org";
      const date = new Date().toISOString().slice(0, 10);
      triggerBlobDownload(blob, `workshopos-export-${slug}-${date}.zip`);
    },
  });

  const planLimits = [
    ["Shops", orgQuery.data?.plan?.max_shops],
    ["Toolboxes", orgQuery.data?.plan?.max_toolboxes],
    ["Drawers", orgQuery.data?.plan?.max_drawers],
    ["Tools", orgQuery.data?.plan?.max_tools],
    ["Users", orgQuery.data?.plan?.max_users],
  ] as const;

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors: licenseErrors },
  } = useForm<LicenseFormValues>({
    resolver: zodResolver(licenseSchema),
  });

  const activateLicenseMutation = useMutation({
    mutationFn: (values: LicenseFormValues) =>
      billingApi.activateLicense(values.license_key),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: orgQueryKey });
      reset();
    },
  });

  const {
    register: registerAiSettings,
    handleSubmit: handleAiSettingsSubmit,
    reset: resetAiSettings,
    formState: { errors: aiSettingsErrors },
  } = useForm<AiSettingsFormValues>({
    resolver: zodResolver(aiSettingsSchema),
  });

  const setApiKeyMutation = useMutation({
    mutationFn: (values: AiSettingsFormValues) => aiImportApi.setApiKey(values.anthropic_api_key),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: orgQueryKey });
      resetAiSettings();
    },
  });

  const clearApiKeyMutation = useMutation({
    mutationFn: () => aiImportApi.clearApiKey(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: orgQueryKey });
    },
  });

  const aiSettingsError = setApiKeyMutation.isError
    ? axios.isAxiosError(setApiKeyMutation.error) &&
      typeof setApiKeyMutation.error.response?.data?.detail === "string"
      ? setApiKeyMutation.error.response.data.detail
      : "Failed to save API key."
    : null;

  const checkoutMutation = useMutation({
    mutationFn: (tier: "pro" | "enterprise") => billingApi.checkout(tier),
    onSuccess: (data) => {
      window.location.assign(data.checkout_url);
    },
  });

  const portalMutation = useMutation({
    mutationFn: () => billingApi.portal(),
    onSuccess: (data) => {
      window.location.assign(data.portal_url);
    },
  });

  const licenseActivationError = activateLicenseMutation.isError
    ? axios.isAxiosError(activateLicenseMutation.error) &&
      typeof activateLicenseMutation.error.response?.data?.detail === "string"
      ? activateLicenseMutation.error.response.data.detail
      : "Failed to activate license key."
    : null;

  const deploymentMode = deploymentModeQuery.data?.deployment_mode;
  const isPaidPlan = orgQuery.data?.plan?.key !== "free" && !!orgQuery.data?.plan;

  return (
    <div className="flex h-full flex-col gap-4 overflow-auto scrollbar-thin p-4">
      <div>
        <h1 className="text-base font-semibold">Settings</h1>
        <p className="text-xs text-muted-foreground">
          Organization details, members, and plan.
        </p>
      </div>

      <Card className="max-w-xl">
        <CardHeader>
          <CardTitle>Organization</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-2 text-sm">
          <div className="flex justify-between">
            <span className="text-muted-foreground">Name</span>
            <span>{orgQuery.data?.name ?? "…"}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">Slug</span>
            <span className="font-mono text-xs">{orgQuery.data?.slug ?? "…"}</span>
          </div>
        </CardContent>
      </Card>

      <Card className="max-w-xl">
        <CardHeader>
          <CardTitle>Plan</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-2 text-sm">
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">Current plan</span>
            <Badge variant="secondary">
              {orgQuery.data?.plan?.name ?? orgQuery.data?.plan?.key ?? "—"}
            </Badge>
          </div>
          <div className="mt-1 grid grid-cols-2 gap-x-6 gap-y-1 text-xs text-muted-foreground">
            {planLimits.map(([label, limit]) => (
              <div key={label} className="flex justify-between">
                <span>{label}</span>
                <span className="font-mono text-foreground">
                  {limit === null || limit === undefined ? "Unlimited" : limit}
                </span>
              </div>
            ))}
          </div>

          {orgQuery.data?.license_tier && (
            <div className="mt-2 flex flex-col gap-1 border-t border-border pt-2 text-xs">
              <div className="flex justify-between">
                <span className="text-muted-foreground">Licensed tier</span>
                <span className="font-mono text-foreground capitalize">
                  {orgQuery.data.license_tier}
                </span>
              </div>
              {orgQuery.data.license_activated_at && (
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Activated</span>
                  <span className="font-mono text-foreground">
                    {new Date(orgQuery.data.license_activated_at).toLocaleString()}
                  </span>
                </div>
              )}
            </div>
          )}

          {deploymentMode === "self_hosted" && (
            <form
              onSubmit={handleSubmit((v) => activateLicenseMutation.mutate(v))}
              className="mt-3 flex flex-col gap-2 border-t border-border pt-3"
            >
              <Label htmlFor="license_key">License key</Label>
              <Textarea
                id="license_key"
                rows={3}
                placeholder="Paste your license key here"
                className="font-mono text-xs"
                {...register("license_key")}
              />
              {licenseErrors.license_key && (
                <p className="text-xs text-destructive">
                  {licenseErrors.license_key.message}
                </p>
              )}
              {licenseActivationError && (
                <p className="text-xs text-destructive">{licenseActivationError}</p>
              )}
              <Button
                type="submit"
                size="sm"
                className="w-fit"
                disabled={activateLicenseMutation.isPending}
              >
                {activateLicenseMutation.isPending ? "Activating…" : "Activate"}
              </Button>
            </form>
          )}

          {deploymentMode === "saas" && (
            <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-border pt-3">
              <Button
                size="sm"
                variant="outline"
                disabled={checkoutMutation.isPending}
                onClick={() => checkoutMutation.mutate("pro")}
              >
                Upgrade to Pro
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={checkoutMutation.isPending}
                onClick={() => checkoutMutation.mutate("enterprise")}
              >
                Upgrade to Enterprise
              </Button>
              {isPaidPlan && (
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={portalMutation.isPending}
                  onClick={() => portalMutation.mutate()}
                >
                  Manage billing
                </Button>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      <Card className="max-w-xl" id="anthropic-api-key">
        <CardHeader>
          <CardTitle>AI Import</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-2 text-sm">
          <p className="text-muted-foreground">
            Bring your own Anthropic API key to enable AI Import (turning a free-text description
            into a batch of profile presets, reviewable before anything is created). WorkshopOS
            never sees or bills for your usage -- get a key from{" "}
            <span className="font-mono text-xs">console.anthropic.com</span>.
          </p>
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">Status</span>
            <Badge variant={orgQuery.data?.anthropic_api_key_configured ? "default" : "secondary"}>
              {orgQuery.data?.anthropic_api_key_configured ? "Configured" : "Not configured"}
            </Badge>
          </div>
          <form
            onSubmit={handleAiSettingsSubmit((v) => setApiKeyMutation.mutate(v))}
            className="mt-1 flex flex-col gap-2 border-t border-border pt-3"
          >
            <Label htmlFor="anthropic_api_key">Anthropic API key</Label>
            <Input
              id="anthropic_api_key"
              type="password"
              placeholder="sk-ant-..."
              className="font-mono text-xs"
              {...registerAiSettings("anthropic_api_key")}
            />
            {aiSettingsErrors.anthropic_api_key && (
              <p className="text-xs text-destructive">{aiSettingsErrors.anthropic_api_key.message}</p>
            )}
            {aiSettingsError && <p className="text-xs text-destructive">{aiSettingsError}</p>}
            <div className="flex gap-2">
              <Button type="submit" size="sm" className="w-fit" disabled={setApiKeyMutation.isPending}>
                {setApiKeyMutation.isPending ? "Saving…" : "Save key"}
              </Button>
              {orgQuery.data?.anthropic_api_key_configured && (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="w-fit"
                  disabled={clearApiKeyMutation.isPending}
                  onClick={() => clearApiKeyMutation.mutate()}
                >
                  {clearApiKeyMutation.isPending ? "Removing…" : "Remove key"}
                </Button>
              )}
            </div>
          </form>
        </CardContent>
      </Card>

      <Card className="max-w-xl">
        <CardHeader>
          <CardTitle>Members</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Email</TableHead>
                <TableHead>Role</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow>
                <TableCell>{user?.email}</TableCell>
                <TableCell className="capitalize">
                  {activeOrgSummary?.role ?? "owner"}
                </TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Card className="max-w-xl">
        <CardHeader>
          <CardTitle>Backup</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-2 text-sm">
          <p className="text-muted-foreground">
            Download a full snapshot of this organization's data (shops, tools, designs, inserts,
            layouts, profiles) and generated files as a ZIP -- useful independent of Docker volume
            backups, especially for self-hosted deployments.
          </p>
          <Button
            size="sm"
            className="w-fit"
            disabled={exportMutation.isPending}
            onClick={() => exportMutation.mutate()}
          >
            {exportMutation.isPending ? "Exporting…" : "Export organization data"}
          </Button>
          {exportMutation.isError && (
            <p className="text-xs text-destructive">Export failed. Please try again.</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
