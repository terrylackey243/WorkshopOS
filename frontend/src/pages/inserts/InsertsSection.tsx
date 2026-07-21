import { Outlet } from "react-router-dom";
import { Panel, PanelGroup, PanelResizeHandle } from "react-resizable-panels";

import { InsertsList } from "@/pages/inserts/InsertsList";

// Master/detail layout shell mirroring LabelDesignerSection: a list panel on
// the left (every InsertDesign in the org -- generated bins and uploaded
// STLs alike -- plus the two creation entry points) and the routed detail
// panel (empty state or a specific insert) on the right via <Outlet/>.
export function InsertsSection() {
  return (
    <PanelGroup direction="horizontal" className="h-full">
      <Panel defaultSize={32} minSize={22} maxSize={50} className="h-full">
        <InsertsList />
      </Panel>
      <PanelResizeHandle className="w-px bg-border transition-colors hover:bg-ring" />
      <Panel minSize={40} className="h-full overflow-auto scrollbar-thin">
        <Outlet />
      </Panel>
    </PanelGroup>
  );
}
