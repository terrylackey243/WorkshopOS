import * as React from "react";
import { useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { onPlanLimitExceeded } from "@/lib/billing";

/**
 * Global 402 ("plan limit exceeded") handler -- mounted once in AppShell.tsx
 * alongside <CommandPalette />, mirroring how a cross-cutting HTTP-status
 * side effect is surfaced without touching any of the four existing
 * create-mutation call sites (shops/toolboxes/drawers/tools). Subscribes to
 * lib/billing.ts's pub/sub, which api.ts's response interceptor publishes to
 * on any 402 response.
 */
export function UpgradeDialog() {
  const navigate = useNavigate();
  const [open, setOpen] = React.useState(false);
  const [message, setMessage] = React.useState<string>("");

  React.useEffect(() => {
    return onPlanLimitExceeded((msg) => {
      setMessage(msg);
      setOpen(true);
    });
  }, []);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Plan limit reached</DialogTitle>
          <DialogDescription>{message}</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" size="sm" onClick={() => setOpen(false)}>
            Dismiss
          </Button>
          <Button
            size="sm"
            onClick={() => {
              setOpen(false);
              navigate("/settings");
            }}
          >
            View plans
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
