import { Outlet } from "react-router-dom";
import { Panel, PanelGroup, PanelResizeHandle } from "react-resizable-panels";

import { TreeNav } from "@/components/tree/TreeNav";

export function ShopsSection() {
  return (
    <PanelGroup direction="horizontal" className="h-full">
      <Panel defaultSize={22} minSize={16} maxSize={40} className="h-full">
        <TreeNav />
      </Panel>
      <PanelResizeHandle className="w-px bg-border transition-colors hover:bg-ring" />
      <Panel minSize={40} className="h-full overflow-auto scrollbar-thin">
        <Outlet />
      </Panel>
    </PanelGroup>
  );
}
