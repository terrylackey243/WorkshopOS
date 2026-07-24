import {
  Box,
  LayoutDashboard,
  Layers,
  Map,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Warehouse,
  Wrench,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { Link, NavLink } from "react-router-dom";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useAuth } from "@/hooks/useAuth";
import { organizationsApi } from "@/lib/api";
import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard },
  { to: "/shops", label: "Shops", icon: Warehouse },
  { to: "/tools", label: "Tools", icon: Wrench },
  { to: "/label-designer", label: "Label Designer", icon: Layers },
  { to: "/inserts", label: "Inserts", icon: Box },
  { to: "/profiles", label: "Profiles", icon: SlidersHorizontal },
  { to: "/roadmap", label: "Roadmap", icon: Map },
  { to: "/settings", label: "Settings", icon: Settings },
];

const navLinkClass = ({ isActive }: { isActive: boolean }) =>
  cn(
    "flex items-center gap-2 rounded-sm px-2 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground",
    isActive && "bg-accent text-foreground",
  );

export function Sidebar() {
  const { isSuperadmin, activeOrgId } = useAuth();
  const navItems = isSuperadmin
    ? [...NAV_ITEMS, { to: "/admin", label: "Admin", icon: ShieldCheck }]
    : NAV_ITEMS;

  // Same query key SettingsPage uses for the org detail query, so this
  // shares its cache rather than firing a redundant request.
  const orgQuery = useQuery({
    queryKey: ["organizations", activeOrgId],
    queryFn: () => organizationsApi.get(activeOrgId as string),
    enabled: !!activeOrgId,
  });
  const aiImportEnabled = orgQuery.data?.anthropic_api_key_configured ?? false;

  return (
    <aside className="flex h-full w-44 shrink-0 flex-col border-r border-border bg-card">
      <div className="flex h-11 shrink-0 items-center gap-1.5 border-b border-border px-3">
        <div className="flex h-5 w-5 items-center justify-center rounded-sm bg-primary text-[10px] font-bold text-primary-foreground">
          W
        </div>
        <span className="text-sm font-semibold tracking-tight">WorkshopOS</span>
      </div>
      <nav className="flex flex-col gap-0.5 p-2">
        {navItems.map(({ to, label, icon: Icon }) => (
          <NavLink key={to} to={to} end={to === "/"} className={navLinkClass}>
            <Icon className="h-3.5 w-3.5 shrink-0" />
            <span className="truncate">{label}</span>
          </NavLink>
        ))}
        {aiImportEnabled ? (
          <NavLink to="/ai-import" className={navLinkClass}>
            <Sparkles className="h-3.5 w-3.5 shrink-0" />
            <span className="truncate">AI Import</span>
          </NavLink>
        ) : (
          <Tooltip>
            <TooltipTrigger asChild>
              <Link
                to="/settings#anthropic-api-key"
                className="flex items-center gap-2 rounded-sm px-2 py-1.5 text-sm text-muted-foreground/50 transition-colors hover:bg-accent hover:text-muted-foreground"
              >
                <Sparkles className="h-3.5 w-3.5 shrink-0" />
                <span className="truncate">AI Import</span>
              </Link>
            </TooltipTrigger>
            <TooltipContent side="right">Add an Anthropic API key in Settings to enable</TooltipContent>
          </Tooltip>
        )}
      </nav>
    </aside>
  );
}
