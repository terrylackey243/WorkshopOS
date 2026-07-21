import { Outlet } from "react-router-dom";
import { Panel, PanelGroup, PanelResizeHandle } from "react-resizable-panels";

import { DesignsList } from "@/pages/label-designer/DesignsList";

// Master/detail layout shell mirroring ShopsSection: a list panel on the
// left (all designs + "New design") and the routed detail panel (empty
// state or a specific design) on the right via <Outlet/>.
export function LabelDesignerSection() {
  return (
    <PanelGroup direction="horizontal" className="h-full">
      <Panel defaultSize={32} minSize={22} maxSize={50} className="h-full">
        <DesignsList />
      </Panel>
      <PanelResizeHandle className="w-px bg-border transition-colors hover:bg-ring" />
      <Panel minSize={40} className="h-full overflow-auto scrollbar-thin">
        <Outlet />
      </Panel>
    </PanelGroup>
  );
}
