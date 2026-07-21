import * as React from "react";
import { Command } from "cmdk";
import {
  Box,
  Layers,
  Map,
  MapPin,
  Settings,
  SlidersHorizontal,
  Warehouse,
  Wrench,
} from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { toolsApi } from "@/lib/api";

const DESTINATIONS = [
  { to: "/shops", label: "Shops", icon: Warehouse },
  { to: "/tools", label: "Tools", icon: Wrench },
  { to: "/label-designer", label: "Label Designer", icon: Layers },
  { to: "/inserts", label: "Inserts", icon: Box },
  { to: "/profiles", label: "Profiles", icon: SlidersHorizontal },
  { to: "/roadmap", label: "Roadmap", icon: Map },
  { to: "/settings", label: "Settings", icon: Settings },
];

// Below this many typed characters, tool results stay hidden -- otherwise
// opening the palette with an empty/short query would dump the org's entire
// (possibly hundred-plus-item) tool list into the list.
const TOOL_SEARCH_MIN_CHARS = 2;

export function CommandPalette() {
  const [open, setOpen] = React.useState(false);
  const [search, setSearch] = React.useState("");
  const navigate = useNavigate();

  // Same query key `ToolsPage.tsx` uses -- TanStack Query dedupes/reuses
  // that cache, so opening the palette costs nothing extra if the Tools
  // page was already visited this session, and only fetches once otherwise.
  const toolsQuery = useQuery({
    queryKey: ["tools"],
    queryFn: () => toolsApi.list(),
    enabled: open,
  });

  const close = React.useCallback(() => {
    setOpen(false);
    setSearch("");
  }, []);

  React.useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setOpen((v) => !v);
      }
      if (e.key === "Escape") close();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [close]);

  if (!open) return null;

  const tools = toolsQuery.data ?? [];
  const showTools = search.trim().length >= TOOL_SEARCH_MIN_CHARS;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/60 pt-[15vh]"
      onClick={close}
    >
      <Command
        className="w-full max-w-md overflow-hidden rounded-md border border-border bg-popover shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <Command.Input
          autoFocus
          value={search}
          onValueChange={setSearch}
          placeholder="Jump to… or search tools"
          className="w-full border-b border-border bg-transparent px-3 py-2.5 text-sm outline-none placeholder:text-muted-foreground"
        />
        <Command.List className="max-h-72 overflow-auto p-1">
          <Command.Empty className="px-3 py-4 text-center text-xs text-muted-foreground">
            No results.
          </Command.Empty>
          <Command.Group>
            {DESTINATIONS.map(({ to, label, icon: Icon }) => (
              <Command.Item
                key={to}
                value={label}
                onSelect={() => {
                  navigate(to);
                  close();
                }}
                className="flex cursor-pointer items-center gap-2 rounded-sm px-2.5 py-1.5 text-sm text-foreground data-[selected=true]:bg-accent"
              >
                <Icon className="h-3.5 w-3.5 text-muted-foreground" />
                {label}
              </Command.Item>
            ))}
          </Command.Group>
          {showTools && tools.length > 0 && (
            <Command.Group
              heading="Tools"
              className="mt-1 border-t border-border pt-1 [&_[cmdk-group-heading]]:px-2.5 [&_[cmdk-group-heading]]:py-1 [&_[cmdk-group-heading]]:text-[10px] [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-wide [&_[cmdk-group-heading]]:text-muted-foreground"
            >
              {tools.map((tool) => (
                <Command.Item
                  key={tool.id}
                  value={`${tool.name} ${tool.category ?? ""} ${tool.manufacturer ?? ""} ${tool.sku ?? ""}`}
                  onSelect={() => {
                    if (tool.location) {
                      navigate(
                        `/shops/${tool.location.shop_id}/toolboxes/${tool.location.toolbox_id}/drawers/${tool.location.drawer_id}`,
                      );
                    } else {
                      navigate("/tools");
                    }
                    close();
                  }}
                  className="flex cursor-pointer items-center gap-2 rounded-sm px-2.5 py-1.5 text-sm text-foreground data-[selected=true]:bg-accent"
                >
                  <MapPin className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                  <span className="flex min-w-0 flex-1 flex-col">
                    <span className="truncate">{tool.name}</span>
                    <span className="truncate text-xs text-muted-foreground">
                      {tool.location
                        ? `${tool.location.shop_name} / ${tool.location.toolbox_name} / ${tool.location.drawer_label}`
                        : "Unassigned"}
                    </span>
                  </span>
                </Command.Item>
              ))}
            </Command.Group>
          )}
        </Command.List>
      </Command>
    </div>
  );
}
