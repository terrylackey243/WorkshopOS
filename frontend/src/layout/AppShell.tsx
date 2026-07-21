import { Navigate, Outlet } from "react-router-dom";

import { CommandPalette } from "@/components/CommandPalette";
import { JobFailureToast } from "@/components/JobFailureToast";
import { UpgradeDialog } from "@/components/UpgradeDialog";
import { useAuth } from "@/hooks/useAuth";
import { Sidebar } from "@/layout/Sidebar";
import { TopBar } from "@/layout/TopBar";

export function AppShell() {
  const { isAuthed, isLoading } = useAuth();

  if (!isAuthed) {
    return <Navigate to="/login" replace />;
  }

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-background text-sm text-muted-foreground">
        Loading WorkshopOS…
      </div>
    );
  }

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-background text-foreground">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar />
        <main className="min-h-0 flex-1 overflow-hidden">
          <Outlet />
        </main>
      </div>
      <CommandPalette />
      <UpgradeDialog />
      <JobFailureToast />
    </div>
  );
}
