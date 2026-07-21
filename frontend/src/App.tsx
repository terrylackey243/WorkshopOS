import { createBrowserRouter, Navigate, RouterProvider } from "react-router-dom";

import { AppShell } from "@/layout/AppShell";
import { Dashboard } from "@/pages/Dashboard";
import { DrawerDetail } from "@/pages/drawers/DrawerDetail";
import { InsertDetail } from "@/pages/inserts/InsertDetail";
import { InsertsEmptyState } from "@/pages/inserts/InsertsPage";
import { InsertsSection } from "@/pages/inserts/InsertsSection";
import { DesignDetail } from "@/pages/label-designer/DesignDetail";
import { LabelDesignerEmptyState } from "@/pages/label-designer/LabelDesignerPage";
import { LabelDesignerSection } from "@/pages/label-designer/LabelDesignerSection";
import { LoginPage } from "@/pages/auth/LoginPage";
import { RegisterPage } from "@/pages/auth/RegisterPage";
import { ProfilesPage } from "@/pages/profiles/ProfilesPage";
import { RoadmapPage } from "@/pages/roadmap/RoadmapPage";
import { SettingsPage } from "@/pages/settings/SettingsPage";
import { ShopDetail } from "@/pages/shops/ShopDetail";
import { ShopNew } from "@/pages/shops/ShopNew";
import { ShopsIndex } from "@/pages/shops/ShopsIndex";
import { ShopsSection } from "@/pages/shops/ShopsSection";
import { ToolboxDetail } from "@/pages/toolboxes/ToolboxDetail";
import { ToolDetail } from "@/pages/tools/ToolDetail";
import { ToolsPage } from "@/pages/tools/ToolsPage";

const router = createBrowserRouter([
  { path: "/login", element: <LoginPage /> },
  { path: "/register", element: <RegisterPage /> },
  {
    path: "/",
    element: <AppShell />,
    children: [
      { index: true, element: <Dashboard /> },
      {
        path: "shops",
        element: <ShopsSection />,
        children: [
          { index: true, element: <ShopsIndex /> },
          { path: "new", element: <ShopNew /> },
          { path: ":shopId", element: <ShopDetail /> },
          { path: ":shopId/toolboxes/:toolboxId", element: <ToolboxDetail /> },
          {
            path: ":shopId/toolboxes/:toolboxId/drawers/:drawerId",
            element: <DrawerDetail />,
          },
        ],
      },
      { path: "tools", element: <ToolsPage /> },
      { path: "tools/:toolId", element: <ToolDetail /> },
      {
        path: "label-designer",
        element: <LabelDesignerSection />,
        children: [
          { index: true, element: <LabelDesignerEmptyState /> },
          { path: ":designId", element: <DesignDetail /> },
        ],
      },
      {
        path: "inserts",
        element: <InsertsSection />,
        children: [
          { index: true, element: <InsertsEmptyState /> },
          { path: ":insertDesignId", element: <InsertDetail /> },
        ],
      },
      { path: "profiles", element: <ProfilesPage /> },
      { path: "profiles/:tab", element: <ProfilesPage /> },
      { path: "roadmap", element: <RoadmapPage /> },
      { path: "settings", element: <SettingsPage /> },
      { path: "*", element: <Navigate to="/shops" replace /> },
    ],
  },
  { path: "*", element: <Navigate to="/login" replace /> },
]);

export function App() {
  return <RouterProvider router={router} />;
}
