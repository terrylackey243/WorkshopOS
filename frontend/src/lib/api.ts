import axios, { type AxiosInstance } from "axios";
import { getActiveOrgId, getToken, handleUnauthorized } from "@/lib/auth";
import { handlePlanLimitExceeded } from "@/lib/billing";
import type {
  AdminOrganization,
  AiExtractedRow,
  AiExtractPayload,
  AiToolExtractedRow,
  Dashboard,
  Design,
  DeploymentConfig,
  DrawerLayout,
  DrawerProfile,
  Drawer,
  FailedJob,
  InsertDesign,
  LabelStyleProfile,
  MagnetProfile,
  MaterialProfile,
  Organization,
  OrganizationDetail,
  OrganizationSummary,
  PrinterProfile,
  RoadmapItem,
  Shop,
  Tool,
  Toolbox,
  User,
} from "@/lib/types";

// Relative base — nginx proxies `/api/` (and `/health`) to the FastAPI
// backend container in production, and vite's dev-server proxy does the
// same locally (see vite.config.ts). Never hardcode a host here.
export const API_BASE = "/api";

export const http: AxiosInstance = axios.create({
  baseURL: API_BASE,
});

http.interceptors.request.use((config) => {
  const token = getToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

http.interceptors.response.use(
  (response) => response,
  (error) => {
    if (axios.isAxiosError(error) && error.response?.status === 401) {
      handleUnauthorized();
    }
    if (axios.isAxiosError(error) && error.response?.status === 402) {
      const detail = error.response.data?.detail;
      handlePlanLimitExceeded(
        typeof detail === "string" ? detail : "Plan limit exceeded.",
      );
    }
    return Promise.reject(error);
  },
);

// Org-scoped resources are nested under `/organizations/{organization_id}/...`
// server-side (validated against a real Membership row -- never trusted from
// the client, see plan §3). The one piece of client state legitimately
// needed is *which* of the user's orgs is "active" (for the TopBar org
// switcher on multi-org accounts); we splice that into the path per call so
// switching orgs immediately changes what every query fetches.
function orgPath(suffix: string): string {
  const orgId = getActiveOrgId();
  if (!orgId) {
    throw new Error("No active organization selected.");
  }
  return `/organizations/${orgId}${suffix}`;
}

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

export interface RegisterPayload {
  organization_name: string;
  email: string;
  password: string;
  display_name?: string;
}

export interface LoginPayload {
  email: string;
  password: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export interface RegisterResponse extends TokenResponse {
  user: User;
  organization_id: string;
  organization_slug: string;
}

export interface MeResponse {
  user: User;
  organizations: OrganizationSummary[];
  is_superadmin: boolean;
}

export const authApi = {
  register: (payload: RegisterPayload) =>
    http.post<RegisterResponse>("/auth/register", payload).then((r) => r.data),
  login: (payload: LoginPayload) =>
    http.post<TokenResponse>("/auth/login", payload).then((r) => r.data),
  me: () => http.get<MeResponse>("/auth/me").then((r) => r.data),
};

// ---------------------------------------------------------------------------
// Organizations (the route itself is not nested under organization_id)
// ---------------------------------------------------------------------------

export const organizationsApi = {
  list: () => http.get<Organization[]>("/organizations").then((r) => r.data),
  get: (id: string) =>
    http.get<OrganizationDetail>(`/organizations/${id}`).then((r) => r.data),
};

// ---------------------------------------------------------------------------
// Admin (superadmin-only -- manual plan grants, bypassing Stripe/license
// entirely). Not org-scoped: acts across every organization, gated
// server-side on the caller's email (see deps.require_superadmin).
// ---------------------------------------------------------------------------

export const adminApi = {
  listOrganizations: (search?: string) =>
    http
      .get<AdminOrganization[]>("/admin/organizations", {
        params: search ? { search } : undefined,
      })
      .then((r) => r.data),
  setPlan: (organizationId: string, planKey: string) =>
    http
      .post<AdminOrganization>(`/admin/organizations/${organizationId}/plan`, {
        plan_key: planKey,
      })
      .then((r) => r.data),
};

// ---------------------------------------------------------------------------
// Billing / plan enforcement (self-hosted license keys + SaaS Stripe
// Checkout/portal) -- org-scoped via `orgPath()`, same as every other
// mutation. See lib/billing.ts for the paired 402 pub/sub.
// ---------------------------------------------------------------------------

export interface CheckoutResponse {
  checkout_url: string;
}

export interface PortalResponse {
  portal_url: string;
}

export const billingApi = {
  activateLicense: (licenseKey: string) =>
    http
      .post<OrganizationDetail>(orgPath("/license"), { license_key: licenseKey })
      .then((r) => r.data),
  checkout: (tier: "pro" | "enterprise") =>
    http
      .post<CheckoutResponse>(orgPath("/billing/checkout"), { tier })
      .then((r) => r.data),
  portal: () =>
    http.post<PortalResponse>(orgPath("/billing/portal")).then((r) => r.data),
};

// ---------------------------------------------------------------------------
// AI Import: BYOK Anthropic-key storage + prompt-to-preview extraction.
// Org-scoped via `orgPath()`, same as `billingApi` above. Not a CRUD
// resource, so this is a bespoke object rather than `makeCrud`/`makeProfileCrud`.
// ---------------------------------------------------------------------------

export const aiImportApi = {
  setApiKey: (apiKey: string) =>
    http
      .post<OrganizationDetail>(orgPath("/ai-settings"), { anthropic_api_key: apiKey })
      .then((r) => r.data),
  clearApiKey: () =>
    http.delete<OrganizationDetail>(orgPath("/ai-settings")).then((r) => r.data),
  extract: (payload: AiExtractPayload) =>
    http
      .post<{ rows: AiExtractedRow[] }>(orgPath("/ai-import/extract"), payload)
      .then((r) => r.data.rows),
};

/**
 * AI Add Tool: identifies tools in a reference-sheet photo. Multipart like
 * `uploadToolPhoto`/`importTools` (no manual Content-Type -- axios infers
 * the multipart boundary from the `FormData` body). Unlike `aiImportApi.extract`,
 * the photo is never persisted server-side -- it's used once for this call
 * and discarded.
 */
export function extractToolsFromPhoto(file: File): Promise<AiToolExtractedRow[]> {
  const formData = new FormData();
  formData.append("file", file);
  return http
    .post<{ rows: AiToolExtractedRow[] }>(orgPath("/tools/ai-import/extract"), formData)
    .then((r) => r.data.rows);
}

// ---------------------------------------------------------------------------
// Deployment config: unauthenticated, top-level route (like `/health`), not
// under `/api`'s org-scoped convention -- read before any auth state exists
// to decide whether Settings renders the license panel or Stripe buttons.
// ---------------------------------------------------------------------------

export const configApi = {
  get: () => http.get<DeploymentConfig>("/config").then((r) => r.data),
};

// ---------------------------------------------------------------------------
// Generic org-scoped CRUD + profile CRUD factories (flat resources: shops,
// tools, and the 5 profile types all live directly under /organizations/{id}/...)
// ---------------------------------------------------------------------------

function makeCrud<T, TCreate = Partial<T>, TUpdate = Partial<T>>(suffix: string) {
  return {
    list: () => http.get<T[]>(orgPath(suffix)).then((r) => r.data),
    get: (id: string) => http.get<T>(orgPath(`${suffix}/${id}`)).then((r) => r.data),
    create: (payload: TCreate) =>
      http.post<T>(orgPath(suffix), payload).then((r) => r.data),
    update: (id: string, payload: TUpdate) =>
      http.patch<T>(orgPath(`${suffix}/${id}`), payload).then((r) => r.data),
    remove: (id: string) =>
      http.delete<void>(orgPath(`${suffix}/${id}`)).then(() => undefined),
  };
}

function makeProfileCrud<T, TCreate = Partial<T>, TUpdate = Partial<T>>(suffix: string) {
  return {
    ...makeCrud<T, TCreate, TUpdate>(suffix),
    setDefault: (id: string) =>
      http.post<T>(orgPath(`${suffix}/${id}/default`)).then((r) => r.data),
  };
}

export const shopsApi = makeCrud<Shop>("/shops");
export const toolsApi = makeCrud<Tool>("/tools");

export interface ToolImportRowError {
  row: number | null;
  message: string;
}

export interface ToolImportResult {
  imported: number;
  tools: Tool[];
}

/**
 * Bulk tool creation from a CSV, alongside `toolsApi`'s single-tool `create`.
 * Multipart like `uploadInsertDesign` -- a FormData body, no manual
 * Content-Type (axios infers the multipart boundary from the body itself).
 * On a 422 the response body is `{detail, errors: ToolImportRowError[]}`,
 * not the single-string `{detail}` shape most endpoints use -- callers
 * should read `error.response.data.errors` for the per-row list.
 */
export function importTools(file: File): Promise<ToolImportResult> {
  const formData = new FormData();
  formData.append("file", file);
  return http
    .post<ToolImportResult>(orgPath("/tools/import"), formData)
    .then((r) => r.data);
}

/** Replace semantics -- one photo per tool, uploading again overwrites it. */
export function uploadToolPhoto(toolId: string, file: File): Promise<Tool> {
  const formData = new FormData();
  formData.append("file", file);
  return http
    .post<Tool>(orgPath(`/tools/${toolId}/photo`), formData)
    .then((r) => r.data);
}

export function deleteToolPhoto(toolId: string): Promise<Tool> {
  return http.delete<Tool>(orgPath(`/tools/${toolId}/photo`)).then((r) => r.data);
}

/**
 * Photo downloads require the same Bearer auth as every other route, so a
 * plain `<img src>` won't work -- fetch as a blob and hand the caller an
 * object URL to render, same pattern as `fetchInsertDesignFile`.
 */
export function fetchToolPhoto(toolId: string): Promise<Blob> {
  return http
    .get<Blob>(orgPath(`/tools/${toolId}/photo`), { responseType: "blob" })
    .then((r) => r.data);
}

export interface ToolCheckoutPayload {
  checked_out_to: string;
  checkout_due_at?: string;
}

export function checkoutTool(toolId: string, payload: ToolCheckoutPayload): Promise<Tool> {
  return http.post<Tool>(orgPath(`/tools/${toolId}/checkout`), payload).then((r) => r.data);
}

export function returnTool(toolId: string): Promise<Tool> {
  return http.post<Tool>(orgPath(`/tools/${toolId}/return`)).then((r) => r.data);
}

export function markMaintenanceDone(toolId: string): Promise<Tool> {
  return http.post<Tool>(orgPath(`/tools/${toolId}/maintenance/mark-done`)).then((r) => r.data);
}

export const dashboardApi = {
  get: () => http.get<Dashboard>(orgPath("/dashboard")).then((r) => r.data),
};

/** Same authenticated-blob pattern as `fetchToolPhoto`/`fetchDesignFile` --
 * the export endpoint requires the same Bearer auth as every other route. */
export function exportOrganization(): Promise<Blob> {
  return http.get<Blob>(orgPath("/export"), { responseType: "blob" }).then((r) => r.data);
}

export function fetchFailedJobs(): Promise<FailedJob[]> {
  return http.get<FailedJob[]>(orgPath("/failed-jobs")).then((r) => r.data);
}

export const printerProfilesApi = makeProfileCrud<PrinterProfile>("/profiles/printers");
export const magnetProfilesApi = makeProfileCrud<MagnetProfile>("/profiles/magnets");
export const materialProfilesApi = makeProfileCrud<MaterialProfile>("/profiles/materials");
export const drawerProfilesApi = makeProfileCrud<DrawerProfile>("/profiles/drawer-profiles");
export const labelStyleProfilesApi = makeProfileCrud<LabelStyleProfile>("/profiles/label-styles");

// ---------------------------------------------------------------------------
// Nested tenancy tree: toolboxes require a shopId, drawers require a
// shopId + toolboxId. These can't use the flat `makeCrud` factory above.
// ---------------------------------------------------------------------------

export const toolboxesApi = {
  list: (shopId: string) =>
    http.get<Toolbox[]>(orgPath(`/shops/${shopId}/toolboxes`)).then((r) => r.data),
  get: (shopId: string, toolboxId: string) =>
    http
      .get<Toolbox>(orgPath(`/shops/${shopId}/toolboxes/${toolboxId}`))
      .then((r) => r.data),
  create: (shopId: string, payload: Partial<Toolbox>) =>
    http
      .post<Toolbox>(orgPath(`/shops/${shopId}/toolboxes`), payload)
      .then((r) => r.data),
  update: (shopId: string, toolboxId: string, payload: Partial<Toolbox>) =>
    http
      .patch<Toolbox>(orgPath(`/shops/${shopId}/toolboxes/${toolboxId}`), payload)
      .then((r) => r.data),
  remove: (shopId: string, toolboxId: string) =>
    http
      .delete<void>(orgPath(`/shops/${shopId}/toolboxes/${toolboxId}`))
      .then(() => undefined),
};

// ---------------------------------------------------------------------------
// Designs (Label Designer): flat org-scoped resource like shops/tools.
// `parameters_json` is a frozen snapshot from creation -- editing the label
// style/magnet profile a design uses doesn't retroactively change it, so
// `regenerate` re-derives it from the profiles' *current* values and
// re-enqueues generation. `magnet_profile_id` omitted on create falls back
// server-side to the label style's default.
// ---------------------------------------------------------------------------

export interface DesignCreatePayload {
  name: string;
  text: string;
  label_style_profile_id: string;
  magnet_profile_id?: string;
  shop_id?: string;
  // Optional -- links this label to a Tool so generation also produces a
  // QR-code body deep-linking to that tool's page.
  tool_id?: string;
}

export const designsApi = {
  list: () => http.get<Design[]>(orgPath("/designs")).then((r) => r.data),
  get: (id: string) => http.get<Design>(orgPath(`/designs/${id}`)).then((r) => r.data),
  create: (payload: DesignCreatePayload) =>
    http.post<Design>(orgPath("/designs"), payload).then((r) => r.data),
  update: (id: string, payload: DesignCreatePayload) =>
    http.patch<Design>(orgPath(`/designs/${id}`), payload).then((r) => r.data),
  regenerate: (id: string) =>
    http.post<Design>(orgPath(`/designs/${id}/regenerate`)).then((r) => r.data),
  remove: (id: string) =>
    http.delete<void>(orgPath(`/designs/${id}`)).then(() => undefined),
};

/**
 * STL downloads require the same Bearer auth as every other route, so a
 * plain `<a href>` won't work -- fetch as a blob through the authenticated
 * `http` client instead (see plan §"Downloads are authenticated blobs").
 *
 * `contentHash` is appended as a cache-busting query param -- this URL is
 * otherwise stable across regenerations (same design_id/kind) while the
 * file it points at is overwritten in place, so any HTTP cache that keys
 * purely on URL (a browser's local disk cache, a CDN, an intermediate
 * proxy) can end up serving bytes from before the latest regeneration
 * indefinitely, regardless of the origin's own Cache-Control header --
 * that header only governs *future* responses, not one a client already
 * cached under the old (no-Cache-Control) response before this fix shipped.
 * Varying the URL itself sidesteps every such cache at once.
 */
export function fetchDesignFile(
  designId: string,
  kind: "outline" | "text" | "qr",
  contentHash?: string,
): Promise<Blob> {
  return http
    .get<Blob>(orgPath(`/designs/${designId}/files/${kind}`), {
      responseType: "blob",
      params: contentHash ? { v: contentHash } : undefined,
    })
    .then((r) => r.data);
}

/** Triggers a browser download of an in-memory blob via a temporary anchor. */
export function triggerBlobDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
}

// ---------------------------------------------------------------------------
// Insert Designs (Gridfinity Bin Generator + STL Import, Milestone 3 Phases
// 1-2): flat org-scoped resource mirroring Designs above -- immutable once
// created, no `update`. Two creation routes feed the same unified list:
// `POST .../generate-bin` (source="generated", Phase 1) and
// `POST .../insert-designs/upload` (source="upload", Phase 2, see
// `uploadInsertDesign` below) rather than a single generic
// `POST .../insert-designs`, since the two paths take entirely different
// payload shapes (JSON params vs. multipart file).
// ---------------------------------------------------------------------------

export interface InsertDesignCreatePayload {
  name: string;
  grid_width_units: number;
  grid_depth_units: number;
  height_units: number;
  compartments_x?: number;
  compartments_y?: number;
  include_stacking_lip?: boolean;
  magnet_profile_id?: string;
}

export const insertDesignsApi = {
  list: () => http.get<InsertDesign[]>(orgPath("/insert-designs")).then((r) => r.data),
  get: (id: string) =>
    http.get<InsertDesign>(orgPath(`/insert-designs/${id}`)).then((r) => r.data),
  create: (payload: InsertDesignCreatePayload) =>
    http
      .post<InsertDesign>(orgPath("/insert-designs/generate-bin"), payload)
      .then((r) => r.data),
  remove: (id: string) =>
    http.delete<void>(orgPath(`/insert-designs/${id}`)).then(() => undefined),
};

/**
 * Bin STL downloads require the same Bearer auth as every other route, so a
 * plain `<a href>` won't work -- fetch as a blob through the authenticated
 * `http` client instead, same pattern as `fetchDesignFile`. Bins are a single
 * printable body (unlike labels' two-body outline+text split), so the
 * endpoint is singular `/file`, not `/files/{kind}`.
 */
export function fetchInsertDesignFile(insertDesignId: string): Promise<Blob> {
  return http
    .get<Blob>(orgPath(`/insert-designs/${insertDesignId}/file`), {
      responseType: "blob",
    })
    .then((r) => r.data);
}

export interface UploadInsertDesignPayload {
  name: string;
  file: File;
  source_reference?: string;
}

/**
 * Second `InsertDesign` creation path (Milestone 3 Phase 2): uploads an
 * arbitrary STL the user already has (community download, tooltrace.ai
 * export, etc.) instead of generating one. Multipart, not JSON -- build a
 * `FormData` and let axios infer `Content-Type: multipart/form-data` (with
 * the required boundary parameter) from the body itself. Setting the header
 * manually here would pin it to a boundary-less value and break parsing
 * server-side.
 */
export function uploadInsertDesign(
  payload: UploadInsertDesignPayload,
): Promise<InsertDesign> {
  const formData = new FormData();
  formData.append("name", payload.name);
  formData.append("file", payload.file);
  if (payload.source_reference) {
    formData.append("source_reference", payload.source_reference);
  }
  return http
    .post<InsertDesign>(orgPath("/insert-designs/upload"), formData)
    .then((r) => r.data);
}

export const drawersApi = {
  list: (shopId: string, toolboxId: string) =>
    http
      .get<Drawer[]>(orgPath(`/shops/${shopId}/toolboxes/${toolboxId}/drawers`))
      .then((r) => r.data),
  get: (shopId: string, toolboxId: string, drawerId: string) =>
    http
      .get<Drawer>(
        orgPath(`/shops/${shopId}/toolboxes/${toolboxId}/drawers/${drawerId}`),
      )
      .then((r) => r.data),
  create: (shopId: string, toolboxId: string, payload: Partial<Drawer>) =>
    http
      .post<Drawer>(
        orgPath(`/shops/${shopId}/toolboxes/${toolboxId}/drawers`),
        payload,
      )
      .then((r) => r.data),
  update: (
    shopId: string,
    toolboxId: string,
    drawerId: string,
    payload: Partial<Drawer>,
  ) =>
    http
      .patch<Drawer>(
        orgPath(`/shops/${shopId}/toolboxes/${toolboxId}/drawers/${drawerId}`),
        payload,
      )
      .then((r) => r.data),
  remove: (shopId: string, toolboxId: string, drawerId: string) =>
    http
      .delete<void>(
        orgPath(`/shops/${shopId}/toolboxes/${toolboxId}/drawers/${drawerId}`),
      )
      .then(() => undefined),
  moveLeft: (shopId: string, toolboxId: string, drawerId: string) =>
    http
      .post<Drawer>(
        orgPath(`/shops/${shopId}/toolboxes/${toolboxId}/drawers/${drawerId}/move-left`),
      )
      .then((r) => r.data),
  moveRight: (shopId: string, toolboxId: string, drawerId: string) =>
    http
      .post<Drawer>(
        orgPath(`/shops/${shopId}/toolboxes/${toolboxId}/drawers/${drawerId}/move-right`),
      )
      .then((r) => r.data),
};

// ---------------------------------------------------------------------------
// Drawer Layouts (Milestone 3 Phase 3, drawer auto-layout / bin-packing):
// nested one level deeper than `drawersApi` (shopId, toolboxId, drawerId).
// `generate()` creates a NEW immutable `DrawerLayout` snapshot from whatever
// tools currently have `drawer_id` = this drawer AND a linked
// `insert_design_id` -- it does not update an existing layout in place, so
// `list()` returns the full generation history, newest first. Both are POST
// (`generate`) / GET with no body needed.
// ---------------------------------------------------------------------------

export const drawerLayoutsApi = {
  list: (shopId: string, toolboxId: string, drawerId: string) =>
    http
      .get<DrawerLayout[]>(
        orgPath(`/shops/${shopId}/toolboxes/${toolboxId}/drawers/${drawerId}/layouts`),
      )
      .then((r) => r.data),
  get: (shopId: string, toolboxId: string, drawerId: string, layoutId: string) =>
    http
      .get<DrawerLayout>(
        orgPath(
          `/shops/${shopId}/toolboxes/${toolboxId}/drawers/${drawerId}/layouts/${layoutId}`,
        ),
      )
      .then((r) => r.data),
  generate: (shopId: string, toolboxId: string, drawerId: string) =>
    http
      .post<DrawerLayout>(
        orgPath(`/shops/${shopId}/toolboxes/${toolboxId}/drawers/${drawerId}/layouts`),
      )
      .then((r) => r.data),
  merge: (shopId: string, toolboxId: string, drawerId: string, layoutId: string) =>
    http
      .post<DrawerLayout>(
        orgPath(
          `/shops/${shopId}/toolboxes/${toolboxId}/drawers/${drawerId}/layouts/${layoutId}/merge`,
        ),
      )
      .then((r) => r.data),
  // Milestone 3 Phase 5 (print-bed panelization): buckets the given layout's
  // already-placed bins onto N printer-bed-sized plates and enqueues one
  // background STL-generation job per plate -- same immutable-snapshot
  // pattern as `merge()`, just with a required body.
  export: (
    shopId: string,
    toolboxId: string,
    drawerId: string,
    layoutId: string,
    printerProfileId: string,
  ) =>
    http
      .post<DrawerLayout>(
        orgPath(
          `/shops/${shopId}/toolboxes/${toolboxId}/drawers/${drawerId}/layouts/${layoutId}/export`,
        ),
        { printer_profile_id: printerProfileId },
      )
      .then((r) => r.data),
};

export interface DrawerOption {
  id: string;
  label: string;
}

/**
 * Flattened `"Shop / Toolbox / Drawer"` list across every drawer in the org
 * -- an N (shops) x M (toolboxes) x K (drawers) fan-out of the nested
 * `toolboxesApi`/`drawersApi` list calls, collapsed into one array for a
 * single-`<Select>` drawer picker. Shared by `ToolsPage.tsx`'s manual "New
 * tool" form and the AI Add Tool preview rows' per-row drawer override --
 * originally lived only in `ToolsPage.tsx` before being lifted here.
 */
export async function fetchAllDrawerOptions(): Promise<DrawerOption[]> {
  const shops = await shopsApi.list();
  const toolboxesByShop = await Promise.all(
    shops.map((shop) => toolboxesApi.list(shop.id)),
  );
  const toolboxes = toolboxesByShop.flatMap((list, i) =>
    list.map((toolbox) => ({ toolbox, shop: shops[i] })),
  );
  const drawersByToolbox = await Promise.all(
    toolboxes.map(({ toolbox, shop }) => drawersApi.list(shop.id, toolbox.id)),
  );
  return drawersByToolbox.flatMap((list, i) => {
    const { toolbox, shop } = toolboxes[i];
    return list.map((drawer) => ({
      id: drawer.id,
      label: `${shop.name} / ${toolbox.name} / ${
        drawer.name || drawer.position_label || "Drawer"
      }`,
    }));
  });
}

/**
 * Plate STL downloads require the same Bearer auth as every other route, so
 * a plain `<a href>` won't work -- fetch as a blob through the authenticated
 * `http` client instead, same pattern as `fetchInsertDesignFile`. One plate
 * is one combined multi-body STL (already merged server-side), so the
 * endpoint takes a `plateIndex`, not a per-body `kind`.
 */
export function fetchPlateFile(
  shopId: string,
  toolboxId: string,
  drawerId: string,
  layoutId: string,
  plateIndex: number,
): Promise<Blob> {
  return http
    .get<Blob>(
      orgPath(
        `/shops/${shopId}/toolboxes/${toolboxId}/drawers/${drawerId}/layouts/${layoutId}/plates/${plateIndex}/file`,
      ),
      { responseType: "blob" },
    )
    .then((r) => r.data);
}

// ---------------------------------------------------------------------------
// Roadmap: deliberately NOT org-scoped (no orgPath()) -- this is a shared
// product roadmap, not per-tenant data, so every authenticated user sees
// and manages the same list. See lib/types.ts's RoadmapItem doc comment.
// ---------------------------------------------------------------------------

export interface RoadmapItemCreatePayload {
  title: string;
  description?: string;
  status?: RoadmapItem["status"];
}

export interface RoadmapItemUpdatePayload {
  title?: string;
  description?: string | null;
  status?: RoadmapItem["status"];
}

export const roadmapApi = {
  list: () => http.get<RoadmapItem[]>("/roadmap").then((r) => r.data),
  create: (payload: RoadmapItemCreatePayload) =>
    http.post<RoadmapItem>("/roadmap", payload).then((r) => r.data),
  update: (id: string, payload: RoadmapItemUpdatePayload) =>
    http.patch<RoadmapItem>(`/roadmap/${id}`, payload).then((r) => r.data),
  remove: (id: string) => http.delete<void>(`/roadmap/${id}`).then(() => undefined),
  moveUp: (id: string) => http.post<RoadmapItem>(`/roadmap/${id}/move-up`).then((r) => r.data),
  moveDown: (id: string) => http.post<RoadmapItem>(`/roadmap/${id}/move-down`).then((r) => r.data),
};
