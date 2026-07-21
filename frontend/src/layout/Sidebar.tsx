import {
  Box,
  LayoutDashboard,
  Layers,
  Map,
  Settings,
  SlidersHorizontal,
  Warehouse,
  Wrench,
} from "lucide-react";
import { NavLink } from "react-router-dom";

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

export function Sidebar() {
  return (
    <aside className="flex h-full w-44 shrink-0 flex-col border-r border-border bg-card">
      <div className="flex h-11 shrink-0 items-center gap-1.5 border-b border-border px-3">
        <div className="flex h-5 w-5 items-center justify-center rounded-sm bg-primary text-[10px] font-bold text-primary-foreground">
          W
        </div>
        <span className="text-sm font-semibold tracking-tight">WorkshopOS</span>
      </div>
      <nav className="flex flex-col gap-0.5 p-2">
        {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === "/"}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-2 rounded-sm px-2 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground",
                isActive && "bg-accent text-foreground",
              )
            }
          >
            <Icon className="h-3.5 w-3.5 shrink-0" />
            <span className="truncate">{label}</span>
          </NavLink>
        ))}
      </nav>
    </aside>
  );
}
