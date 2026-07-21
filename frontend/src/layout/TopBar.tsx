import { useQuery } from "@tanstack/react-query";
import { ChevronRight, LogOut } from "lucide-react";
import { Link, useParams } from "react-router-dom";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useAuth } from "@/hooks/useAuth";
import { drawersApi, shopsApi, toolboxesApi } from "@/lib/api";

function useBreadcrumb() {
  const { shopId, toolboxId, drawerId } = useParams();

  const shopQuery = useQuery({
    queryKey: ["shops", shopId],
    queryFn: () => shopsApi.get(shopId as string),
    enabled: !!shopId,
  });
  const toolboxQuery = useQuery({
    queryKey: ["toolboxes", toolboxId],
    queryFn: () => toolboxesApi.get(shopId as string, toolboxId as string),
    enabled: !!shopId && !!toolboxId,
  });
  const drawerQuery = useQuery({
    queryKey: ["drawers", drawerId],
    queryFn: () => drawersApi.get(shopId as string, toolboxId as string, drawerId as string),
    enabled: !!shopId && !!toolboxId && !!drawerId,
  });

  const crumbs: { label: string; to: string }[] = [{ label: "Shops", to: "/shops" }];
  if (shopId) {
    crumbs.push({
      label: shopQuery.data?.name ?? "…",
      to: `/shops/${shopId}`,
    });
  }
  if (toolboxId) {
    crumbs.push({
      label: toolboxQuery.data?.name ?? "…",
      to: `/shops/${shopId}/toolboxes/${toolboxId}`,
    });
  }
  if (drawerId) {
    crumbs.push({
      label: drawerQuery.data?.name || drawerQuery.data?.position_label || "…",
      to: `/shops/${shopId}/toolboxes/${toolboxId}/drawers/${drawerId}`,
    });
  }
  return crumbs;
}

export function TopBar() {
  const { user, organizations, activeOrgId, setActiveOrgId, logout } = useAuth();
  const { shopId } = useParams();
  const crumbs = useBreadcrumb();
  const showTreeBreadcrumb = !!shopId;

  return (
    <header className="flex h-11 shrink-0 items-center justify-between border-b border-border bg-card px-3">
      <div className="flex min-w-0 items-center gap-1 text-sm text-muted-foreground">
        {showTreeBreadcrumb ? (
          crumbs.map((crumb, i) => (
            <span key={crumb.to} className="flex items-center gap-1">
              {i > 0 && <ChevronRight className="h-3 w-3" />}
              <Link
                to={crumb.to}
                className="truncate text-foreground hover:underline"
              >
                {crumb.label}
              </Link>
            </span>
          ))
        ) : (
          <span className="text-foreground">WorkshopOS</span>
        )}
      </div>

      <div className="flex items-center gap-2">
        {organizations.length > 1 && (
          <Select
            value={activeOrgId ?? undefined}
            onValueChange={(v) => setActiveOrgId(v)}
          >
            <SelectTrigger className="h-7 w-40 text-xs">
              <SelectValue placeholder="Organization" />
            </SelectTrigger>
            <SelectContent>
              {organizations.map((org) => (
                <SelectItem key={org.id} value={org.id}>
                  {org.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
        <span className="text-xs text-muted-foreground">{user?.email}</span>
        <button
          type="button"
          onClick={logout}
          className="flex h-7 w-7 items-center justify-center rounded-sm text-muted-foreground hover:bg-accent hover:text-foreground"
          title="Log out"
        >
          <LogOut className="h-3.5 w-3.5" />
        </button>
      </div>
    </header>
  );
}
