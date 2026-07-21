// Domain types mirroring the WorkshopOS backend schema (plan §2).
// IDs are UUID strings; timestamps are ISO-8601 strings.

export type Role = "owner" | "admin" | "member";

export interface Plan {
  id: string;
  key: string;
  name: string;
  max_shops: number | null;
  max_toolboxes: number | null;
  max_drawers: number | null;
  max_tools: number | null;
  max_users: number | null;
}

// Matches backend `OrganizationRead` (no timestamps -- the backend doesn't
// send them for this entity). `OrganizationDetail` matches
// `OrganizationDetailRead`, returned only by `GET /organizations/{id}`.
export interface Organization {
  id: string;
  name: string;
  slug: string;
  plan_id: string;
}

export interface OrganizationDetail extends Organization {
  plan: Plan;
  // Populated only once a self-hosted license key has been activated (billing
  // milestone) -- both null on a fresh org, or on a SaaS org that upgraded via
  // Stripe instead of a license key.
  license_tier: string | null;
  license_activated_at: string | null;
}

// `GET /config` -- unauthenticated, top-level (not org-scoped), read before
// any auth state exists so the frontend knows whether to render the
// self-hosted license-key panel or the SaaS Stripe upgrade buttons.
export interface DeploymentConfig {
  deployment_mode: "saas" | "self_hosted";
}

// Matches backend `OrganizationSummary` embedded in `GET /auth/me`'s
// response -- a flattened org+role view, not a raw Membership row.
export interface OrganizationSummary {
  id: string;
  name: string;
  slug: string;
  plan_key: string;
  role: Role;
}

export interface User {
  id: string;
  email: string;
  display_name: string | null;
  is_active: boolean;
}

export interface Shop {
  id: string;
  organization_id: string;
  name: string;
  slug: string;
  location: string | null;
  created_at: string;
  updated_at: string;
}

export interface Toolbox {
  id: string;
  shop_id: string;
  name: string;
  kind: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface DrawerProfile {
  id: string;
  organization_id: string;
  name: string;
  inside_width_mm: number;
  inside_depth_mm: number;
  inside_height_mm: number;
  grid_unit_mm: number;
  is_default: boolean;
  created_at: string;
  updated_at: string;
}

export interface Drawer {
  id: string;
  toolbox_id: string;
  drawer_profile_id: string;
  name: string | null;
  position_label: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

// A tool's shop/toolbox/drawer breadcrumb, derived server-side from
// `Tool.drawer_id` (not a real column) -- null when the tool isn't assigned
// to a drawer. `drawer_label` mirrors the same `name || position_label ||
// "Drawer"` fallback this app already uses client-side elsewhere.
export interface ToolLocation {
  shop_id: string;
  shop_name: string;
  toolbox_id: string;
  toolbox_name: string;
  drawer_id: string;
  drawer_label: string;
}

export interface Tool {
  id: string;
  organization_id: string;
  name: string;
  category: string | null;
  manufacturer: string | null;
  sku: string | null;
  notes: string | null;
  drawer_id: string | null;
  quantity: number;
  insert_design_id: string | null;
  // Meaningful only when `insert_design_id` is set: how many of this tool's
  // owned `quantity` should get a packed slot in a generated drawer layout.
  // Defaults server-side to 1 when an insert is linked; NULL otherwise.
  insert_quantity: number | null;
  location: ToolLocation | null;
  has_photo: boolean;
  checked_out_to: string | null;
  checked_out_at: string | null;
  checkout_due_at: string | null;
  maintenance_interval_days: number | null;
  last_maintained_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface PrinterProfile {
  id: string;
  organization_id: string;
  name: string;
  manufacturer: string | null;
  model: string | null;
  build_width_mm: number;
  build_depth_mm: number;
  build_height_mm: number;
  nozzle_diameter_mm: number;
  usable_margin_mm: number;
  is_default: boolean;
  created_at: string;
  updated_at: string;
}

export interface MagnetProfile {
  id: string;
  organization_id: string;
  name: string;
  diameter_mm: number;
  thickness_mm: number;
  diameter_clearance_mm: number;
  depth_clearance_mm: number;
  fit_type: string;
  is_default: boolean;
  created_at: string;
  updated_at: string;
}

export interface MaterialProfile {
  id: string;
  organization_id: string;
  name: string;
  material_type: string;
  xy_compensation_mm: number;
  notes: string | null;
  is_default: boolean;
  created_at: string;
  updated_at: string;
}

export interface LabelStyleProfile {
  id: string;
  organization_id: string;
  name: string;
  text_height_mm: number;
  body_depth_mm: number;
  outline_offset_mm: number;
  font_family: string;
  font_weight: string;
  font_style: string;
  horizontal_scale: number;
  minimum_width_mm: number;
  fixed_width_mm: number | null;
  magnet_count: number;
  magnet_edge_offset_mm: number;
  magnet_minimum_bridge_mm: number;
  magnet_support_extra_mm: number;
  default_magnet_profile_id: string | null;
  is_default: boolean;
  created_at: string;
  updated_at: string;
}

export type DesignStatus = "queued" | "generated" | "failed" | "draft";

// Shared with InsertDesign below -- both the label-design and bin-generation
// pipelines use the identical draft -> queued -> generated|failed lifecycle.
export type InsertDesignStatus = DesignStatus;

// Matches backend `DesignRead`. `parameters_json` is the immutable
// generation snapshot (already JSON-safe -- Decimal fields inside it are
// plain numbers, not the string-serialized Decimals other profile entities
// use); it's opaque to the frontend, which never reads its shape directly.
export interface Design {
  id: string;
  organization_id: string;
  shop_id: string | null;
  // Optional link to a Tool -- when set, generation also produces a
  // qr_stl_path body encoding a deep link to that tool's page.
  tool_id: string | null;
  name: string;
  text: string;
  label_style_profile_id: string;
  magnet_profile_id: string | null;
  parameters_json: Record<string, unknown>;
  engine_version: string;
  content_hash: string;
  status: DesignStatus;
  outline_stl_path: string | null;
  text_stl_path: string | null;
  qr_stl_path: string | null;
  generated_at: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

// Matches backend `InsertDesignRead` (Gridfinity bin generator, Milestone 3
// Phase 1). Unlike `Design`, bins are a single printable body -- one STL, no
// outline/text split -- and `source` distinguishes generation from future
// upload/tooltrace import paths, only "generated" is produced by the current
// `POST .../generate-bin` endpoint. `parameters_json` (the full generation
// snapshot) and `bounds_json` (computed `{width_mm, depth_mm, height_mm}`
// footprint metadata) are both opaque here, same as `Design.parameters_json`.
export interface InsertDesign {
  id: string;
  organization_id: string;
  name: string;
  source: "generated" | "upload" | "tooltrace";
  source_reference: string | null;
  stl_path: string | null;
  bounds_json: Record<string, unknown> | null;
  status: InsertDesignStatus;
  parameters_json: Record<string, unknown> | null;
  engine_version: string | null;
  content_hash: string | null;
  error_message: string | null;
  generated_at: string | null;
  created_at: string;
  updated_at: string;
}

// Matches backend `InsertPlacementRead` (Milestone 3 Phase 3, drawer
// auto-layout). Coordinates are real millimeters, origin at one corner of
// the drawer's usable interior (`DrawerProfile.inside_width_mm` x
// `inside_depth_mm`). `rotation_deg` is 0 or 90 -- when 90, the placed
// rectangle's on-screen footprint is the insert's depth x width (swapped),
// not width x depth.
export interface InsertPlacement {
  id: string;
  insert_design_id: string;
  x_mm: number;
  y_mm: number;
  rotation_deg: number;
}

// One entry in `DrawerLayout.layout_json.unplaced` -- an eligible
// tool-copy the packer couldn't fit, kept visible rather than silently
// dropped (see plan's explicit callout of Milestone 2's profile-form
// silent-failure UX bug). The three "exceeds printer bed"/"exceeds max plate
// count"/"insert not yet generated" reasons are only produced by
// `POST .../export` (Milestone 3 Phase 5, panelization); they render through
// this SAME list, not a separate panel -- see DrawerDetail.tsx.
//
// `tool_id` vs `placement_id` is genuinely EITHER/OR, confirmed live: a
// generate/merge-produced entry has `tool_id` (a tool that never got a
// placement at all), while an export/panelize-produced entry has
// `placement_id` instead (an already-placed bin that couldn't be
// re-bucketed onto a plate) and OMITS `tool_id` entirely -- there is no
// tool-choice concept left once a placement already exists. Both are
// optional here rather than assuming the plan's implied uniform shape.
export interface UnplacedInsert {
  tool_id?: string;
  placement_id?: string;
  insert_design_id: string;
  reason:
    | "no space"
    | "exceeds drawer height"
    | "exceeds printer bed"
    | "exceeds max plate count"
    | "insert not yet generated";
}

// The opaque-elsewhere JSONB blob typed concretely here because the
// frontend actually reads `unplaced` and `utilization_pct` out of it to
// render them (unlike `Design.parameters_json`/`InsertDesign.bounds_json`,
// which stay `Record<string, unknown>`).
// One entry in `DrawerLayoutJson.merges` -- Milestone 3 Phase 4 (bin
// merging). Populated only on a layout returned by `POST .../merge`; empty
// on a freshly-generated (pre-merge) layout.
export interface MergedBin {
  merged_insert_design_id: string;
  grid_width_units: number;
  grid_depth_units: number;
  source_placement_count: number;
}

// One placed insert on a plate, in `DrawerLayoutJson.plates[i].assignments`
// (Milestone 3 Phase 5, print-bed panelization at export). Coordinates are
// plate-local millimeters (a fresh origin per plate, NOT the drawer-space
// origin `InsertPlacement.x_mm/y_mm` use). Per the plan, `plates` lives
// inside the `layout_json` JSONB blob rather than behind Numeric columns, so
// these numeric fields are expected to arrive as real JSON numbers already
// -- unlike `InsertPlacement.x_mm/y_mm/rotation_deg`, which are Numeric
// columns and DO serialize as strings (see `drawerLayoutGeometry.ts`'s
// `effectiveFootprintMm` doc comment). Still coerce with `Number(...)`
// before any arithmetic on these fields, per that same established
// defensive habit, rather than trusting the JSONB assumption blindly.
export interface PlateAssignment {
  placement_id: string;
  insert_design_id: string;
  x_mm: number;
  y_mm: number;
  rotation_deg: number;
}

export type PlateStatus = "queued" | "generated" | "failed";

// One printer-bed-sized plate produced by `POST .../export`. `stl_path` is
// server-side only (opaque here, download goes through `fetchPlateFile`);
// `error_message` is set only when `status === "failed"`.
export interface Plate {
  plate_index: number;
  status: PlateStatus;
  stl_path: string | null;
  error_message: string | null;
  bin_count: number;
  assignments: PlateAssignment[];
}

export interface DrawerLayoutJson {
  unplaced: UnplacedInsert[];
  utilization_pct: number;
  merges: MergedBin[];
  // Populated only on a layout returned by `POST .../export` (Milestone 3
  // Phase 5). Optional, not just an empty array -- confirmed live during
  // verification that a freshly-generated or merged (pre-export) layout's
  // `layout_json` omits the `plates` key entirely rather than sending `[]`,
  // so callers must guard with `?? []` (see DrawerDetail.tsx), not assume
  // presence the way the plan's non-optional spec implied.
  plates?: Plate[];
}

export type DrawerLayoutStatus = "draft" | "computed" | "exported";

// Matches backend `DrawerLayoutRead`. Each "Generate layout" call creates a
// NEW row (immutable snapshot, same pattern as `Design`/`InsertDesign`)
// rather than updating one in place -- `GET .../layouts` returns the full
// history, newest first.
export interface DrawerLayout {
  id: string;
  drawer_id: string;
  status: DrawerLayoutStatus;
  layout_json: DrawerLayoutJson;
  // Set only on a layout produced by `POST .../export` (Milestone 3 Phase
  // 5); null on generate/merge-produced layouts.
  printer_profile_id: string | null;
  created_at: string;
  updated_at: string;
  placements: InsertPlacement[];
}

export type RoadmapStatus = "planned" | "in_progress" | "done";

// Matches backend `RoadmapItemRead`. Deliberately NOT organization-scoped --
// this tracks WorkshopOS's own development progress (a shared product
// roadmap), not per-tenant user data, so `api.ts`'s `roadmapApi` calls plain
// `/roadmap` routes rather than going through `orgPath()`.
export interface RoadmapItem {
  id: string;
  title: string;
  description: string | null;
  status: RoadmapStatus;
  position: number;
  created_at: string;
  updated_at: string;
}

export interface Dashboard {
  overdue_checkouts: Tool[];
  active_checkouts: Tool[];
  maintenance_due: Tool[];
}

export type FailedJobKind = "label" | "insert" | "plate";

export interface FailedJob {
  kind: FailedJobKind;
  id: string;
  name: string;
  error_message: string | null;
  failed_at: string | null;
  link: string | null;
}
