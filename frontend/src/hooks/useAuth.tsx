import * as React from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import {
  authApi,
  type LoginPayload,
  type RegisterPayload,
} from "@/lib/api";
import {
  clearToken,
  getActiveOrgId,
  getToken,
  isAuthenticated,
  onAuthChange,
  setActiveOrgId as persistActiveOrgId,
  setToken,
} from "@/lib/auth";
import type { OrganizationSummary, User } from "@/lib/types";

interface AuthContextValue {
  user: User | undefined;
  organizations: OrganizationSummary[];
  isLoading: boolean;
  isAuthed: boolean;
  activeOrgId: string | null;
  setActiveOrgId: (id: string) => void;
  login: (payload: LoginPayload) => Promise<void>;
  register: (payload: RegisterPayload) => Promise<void>;
  logout: () => void;
}

const AuthContext = React.createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const queryClient = useQueryClient();
  const [authed, setAuthed] = React.useState(isAuthenticated());
  const [activeOrgId, setActiveOrgIdState] = React.useState<string | null>(
    getActiveOrgId(),
  );

  React.useEffect(() => onAuthChange(() => setAuthed(isAuthenticated())), []);

  const meQuery = useQuery({
    queryKey: ["auth", "me"],
    queryFn: authApi.me,
    enabled: authed,
    retry: false,
  });

  // Default the active org to the first membership once `me` resolves.
  React.useEffect(() => {
    if (!activeOrgId && meQuery.data?.organizations?.length) {
      const first = meQuery.data.organizations[0].id;
      persistActiveOrgId(first);
      setActiveOrgIdState(first);
    }
  }, [activeOrgId, meQuery.data]);

  const login = React.useCallback(
    async (payload: LoginPayload) => {
      const res = await authApi.login(payload);
      setToken(res.access_token);
      setAuthed(true);
      await queryClient.invalidateQueries({ queryKey: ["auth", "me"] });
    },
    [queryClient],
  );

  const register = React.useCallback(
    async (payload: RegisterPayload) => {
      const res = await authApi.register(payload);
      setToken(res.access_token);
      setAuthed(true);
      // The org just created is unambiguous -- set it directly rather than
      // waiting on the `me` query round-trip (avoids a race where the first
      // authenticated render happens before `organizations` has resolved).
      persistActiveOrgId(res.organization_id);
      setActiveOrgIdState(res.organization_id);
      await queryClient.invalidateQueries({ queryKey: ["auth", "me"] });
    },
    [queryClient],
  );

  const logout = React.useCallback(() => {
    clearToken();
    setAuthed(false);
    queryClient.clear();
  }, [queryClient]);

  const setActiveOrgId = React.useCallback((id: string) => {
    persistActiveOrgId(id);
    setActiveOrgIdState(id);
  }, []);

  const value: AuthContextValue = {
    user: meQuery.data?.user,
    organizations: meQuery.data?.organizations ?? [],
    isLoading: authed && meQuery.isLoading,
    isAuthed: authed,
    activeOrgId,
    setActiveOrgId,
    login,
    register,
    logout,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = React.useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}

export { getToken };
