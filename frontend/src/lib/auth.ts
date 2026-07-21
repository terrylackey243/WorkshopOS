// Token storage + simple pub/sub so the API client can force a logout on 401
// without importing React or the router (keeps lib/ dependency-free of UI).

const TOKEN_KEY = "workshopos.token";
const ACTIVE_ORG_KEY = "workshopos.activeOrgId";

type Listener = () => void;
const listeners = new Set<Listener>();

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
  listeners.forEach((l) => l());
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(ACTIVE_ORG_KEY);
  listeners.forEach((l) => l());
}

export function isAuthenticated(): boolean {
  return !!getToken();
}

export function onAuthChange(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function getActiveOrgId(): string | null {
  return localStorage.getItem(ACTIVE_ORG_KEY);
}

export function setActiveOrgId(orgId: string): void {
  localStorage.setItem(ACTIVE_ORG_KEY, orgId);
}

/** Called by the api client on a 401 response. */
export function handleUnauthorized(): void {
  clearToken();
  if (window.location.pathname !== "/login") {
    window.location.assign("/login");
  }
}
