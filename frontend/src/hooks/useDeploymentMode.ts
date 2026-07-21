import { useQuery } from "@tanstack/react-query";

import { configApi } from "@/lib/api";

// `deployment_mode` is read from `.env` at process start and never changes
// for a running deployment, so this is safe to cache forever (`staleTime:
// Infinity`) -- there's no invalidation path anywhere in the app, matching
// the plan's explicit reasoning.
export function useDeploymentMode() {
  return useQuery({
    queryKey: ["config"],
    queryFn: configApi.get,
    staleTime: Infinity,
  });
}
