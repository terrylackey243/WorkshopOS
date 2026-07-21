import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { ChevronRight, Package, Plus, Warehouse, Wrench } from "lucide-react";

import { drawersApi, shopsApi, toolboxesApi } from "@/lib/api";
import type { Drawer, Shop, Toolbox } from "@/lib/types";
import { cn } from "@/lib/utils";

function Row({
  depth,
  icon,
  label,
  sub,
  active,
  expanded,
  onToggle,
  to,
}: {
  depth: number;
  icon: React.ReactNode;
  label: string;
  sub?: string;
  active: boolean;
  expanded?: boolean;
  onToggle?: () => void;
  to: string;
}) {
  return (
    <div
      className={cn(
        "group flex items-center gap-1 rounded-sm py-1 pr-2 text-sm hover:bg-accent",
        active && "bg-accent text-accent-foreground",
      )}
      style={{ paddingLeft: 8 + depth * 14 }}
    >
      <button
        type="button"
        onClick={onToggle}
        className={cn(
          "flex h-4 w-4 shrink-0 items-center justify-center text-muted-foreground",
          onToggle ? "visible" : "invisible",
        )}
      >
        <ChevronRight
          className={cn("h-3 w-3 transition-transform", expanded && "rotate-90")}
        />
      </button>
      <Link to={to} className="flex min-w-0 flex-1 items-center gap-1.5">
        <span className="shrink-0 text-muted-foreground">{icon}</span>
        <span className="truncate">{label}</span>
        {sub && (
          <span className="shrink-0 truncate text-xs text-muted-foreground">
            {sub}
          </span>
        )}
      </Link>
    </div>
  );
}

function ToolboxNode({ toolbox, shopId }: { toolbox: Toolbox; shopId: string }) {
  const { toolboxId: activeToolboxId, drawerId: activeDrawerId } = useParams();
  const [expanded, setExpanded] = React.useState(
    activeToolboxId === toolbox.id,
  );

  const drawersQuery = useQuery({
    queryKey: ["drawers", { toolbox_id: toolbox.id }],
    queryFn: () => drawersApi.list(shopId, toolbox.id),
    enabled: expanded,
  });

  return (
    <div>
      <Row
        depth={1}
        icon={<Package className="h-3.5 w-3.5" />}
        label={toolbox.name}
        active={activeToolboxId === toolbox.id && !activeDrawerId}
        expanded={expanded}
        onToggle={() => setExpanded((v) => !v)}
        to={`/shops/${shopId}/toolboxes/${toolbox.id}`}
      />
      {expanded && (
        <div>
          {(drawersQuery.data ?? []).map((drawer: Drawer) => (
            <Row
              key={drawer.id}
              depth={2}
              icon={<Wrench className="h-3.5 w-3.5" />}
              label={drawer.name || drawer.position_label || "Drawer"}
              active={activeDrawerId === drawer.id}
              to={`/shops/${shopId}/toolboxes/${toolbox.id}/drawers/${drawer.id}`}
            />
          ))}
          {drawersQuery.isSuccess && drawersQuery.data.length === 0 && (
            <p className="pl-11 py-1 text-xs text-muted-foreground">
              No drawers yet
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function ShopNode({ shop }: { shop: Shop }) {
  const { shopId: activeShopId, toolboxId: activeToolboxId } = useParams();
  const [expanded, setExpanded] = React.useState(activeShopId === shop.id);

  const toolboxesQuery = useQuery({
    queryKey: ["toolboxes", { shop_id: shop.id }],
    queryFn: () => toolboxesApi.list(shop.id),
    enabled: expanded,
  });

  return (
    <div>
      <Row
        depth={0}
        icon={<Warehouse className="h-3.5 w-3.5" />}
        label={shop.name}
        active={activeShopId === shop.id && !activeToolboxId}
        expanded={expanded}
        onToggle={() => setExpanded((v) => !v)}
        to={`/shops/${shop.id}`}
      />
      {expanded && (
        <div>
          {(toolboxesQuery.data ?? []).map((toolbox: Toolbox) => (
            <ToolboxNode key={toolbox.id} toolbox={toolbox} shopId={shop.id} />
          ))}
          {toolboxesQuery.isSuccess && toolboxesQuery.data.length === 0 && (
            <p className="pl-8 py-1 text-xs text-muted-foreground">
              No toolboxes yet
            </p>
          )}
        </div>
      )}
    </div>
  );
}

export function TreeNav() {
  const shopsQuery = useQuery({ queryKey: ["shops"], queryFn: () => shopsApi.list() });

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-border px-2 py-1.5">
        <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Shops
        </span>
        <Link
          to="/shops/new"
          className="flex h-5 w-5 items-center justify-center rounded-sm text-muted-foreground hover:bg-accent hover:text-foreground"
          title="New shop"
        >
          <Plus className="h-3.5 w-3.5" />
        </Link>
      </div>
      <div className="flex-1 overflow-auto scrollbar-thin py-1">
        {shopsQuery.isLoading && (
          <p className="px-2 py-1 text-xs text-muted-foreground">Loading…</p>
        )}
        {shopsQuery.isSuccess && shopsQuery.data.length === 0 && (
          <p className="px-2 py-1 text-xs text-muted-foreground">
            No shops yet — create one to get started.
          </p>
        )}
        {(shopsQuery.data ?? []).map((shop) => (
          <ShopNode key={shop.id} shop={shop} />
        ))}
      </div>
    </div>
  );
}
