import type { z } from "zod";

import {
  drawerProfileDefaultValues,
  drawerProfileSchema,
  labelStyleDefaultValues,
  labelStyleSchema,
  magnetDefaultValues,
  magnetSchema,
  materialDefaultValues,
  materialSchema,
  printerDefaultValues,
  printerSchema,
} from "@/pages/profiles/schemas";
import {
  drawerProfilesApi,
  labelStyleProfilesApi,
  magnetProfilesApi,
  materialProfilesApi,
  printerProfilesApi,
} from "@/lib/api";
import type { AiProfileTypeKey } from "@/lib/types";

// One entry per profile type AI Import supports -- mirrors the backend's
// PROFILE_TYPE_SPECS (app/services/ai_profile_extraction.py). `fields` lists
// only the fields the extractor actually populates (everything else keeps
// the schema's own default), matching the approved per-type placeholder copy.
interface PreviewFieldConfig {
  name: string;
  label: string;
  kind: "text" | "number";
  step?: string;
}

interface ProfileTypeConfig {
  label: string;
  schema: z.ZodTypeAny;
  defaultValues: Record<string, unknown>;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- shared across 5 differently-shaped profile APIs, same rationale as fields.tsx's AnyForm
  api: { create: (payload: any) => Promise<unknown> };
  fields: PreviewFieldConfig[];
  placeholder: string;
}

export const PROFILE_TYPE_CONFIG: Record<AiProfileTypeKey, ProfileTypeConfig> = {
  printer: {
    label: "Printer",
    schema: printerSchema,
    defaultValues: printerDefaultValues,
    api: printerProfilesApi,
    fields: [
      { name: "build_width_mm", label: "Build width (mm)", kind: "number" },
      { name: "build_depth_mm", label: "Build depth (mm)", kind: "number" },
      { name: "build_height_mm", label: "Build height (mm)", kind: "number" },
      { name: "nozzle_diameter_mm", label: "Nozzle Ø (mm)", kind: "number", step: "0.05" },
      { name: "usable_margin_mm", label: "Usable margin (mm)", kind: "number", step: "0.1" },
      { name: "manufacturer", label: "Manufacturer", kind: "text" },
      { name: "model", label: "Model", kind: "text" },
    ],
    placeholder:
      "One line per printer — name, build width × depth × height. Optional: manufacturer, model, nozzle diameter (default 0.4mm), usable margin (default 2mm).\ne.g. Bambu X1C — build 256 x 256 x 256 — nozzle 0.4mm",
  },
  magnet: {
    label: "Magnet",
    schema: magnetSchema,
    defaultValues: magnetDefaultValues,
    api: magnetProfilesApi,
    fields: [
      { name: "diameter_mm", label: "Diameter (mm)", kind: "number", step: "0.1" },
      { name: "thickness_mm", label: "Thickness (mm)", kind: "number", step: "0.1" },
      { name: "diameter_clearance_mm", label: "Diameter clearance (mm)", kind: "number", step: "0.05" },
      { name: "depth_clearance_mm", label: "Depth clearance (mm)", kind: "number", step: "0.05" },
      { name: "fit_type", label: "Fit type", kind: "text" },
    ],
    placeholder:
      "One line per magnet — name, diameter × thickness. Optional: clearance, fit type (press/snug/glue/loose, default glue).\ne.g. 6x2 press-fit — 6mm diameter x 2mm thick — press fit",
  },
  material: {
    label: "Material",
    schema: materialSchema,
    defaultValues: materialDefaultValues,
    api: materialProfilesApi,
    fields: [
      { name: "material_type", label: "Material type", kind: "text" },
      { name: "xy_compensation_mm", label: "XY compensation (mm)", kind: "number", step: "0.01" },
      { name: "notes", label: "Notes", kind: "text" },
    ],
    placeholder:
      "One line per material — name, material type. Optional: XY compensation, notes.\ne.g. Standard PLA — material type PLA",
  },
  drawer_profile: {
    label: "Drawer Profile",
    schema: drawerProfileSchema,
    defaultValues: drawerProfileDefaultValues,
    api: drawerProfilesApi,
    fields: [
      { name: "inside_width_mm", label: "Inside width (mm)", kind: "number" },
      { name: "inside_depth_mm", label: "Inside depth (mm)", kind: "number" },
      { name: "inside_height_mm", label: "Inside height (mm)", kind: "number" },
      { name: "grid_unit_mm", label: "Grid unit (mm)", kind: "number", step: "1" },
    ],
    placeholder:
      "One line per drawer — name, inside width × depth × height. Optional: grid unit (default 42mm).\ne.g. Shallow 22x14.5 — W22 x D14.5 x H2 — grid 42mm",
  },
  label_style: {
    label: "Label Style",
    schema: labelStyleSchema,
    defaultValues: labelStyleDefaultValues,
    api: labelStyleProfilesApi,
    fields: [
      { name: "minimum_width_mm", label: "Minimum width (mm)", kind: "number", step: "0.1" },
      { name: "magnet_count", label: "Magnet count", kind: "number", step: "1" },
    ],
    placeholder:
      "One line per label style — name required, everything else optional (falls back to defaults unless you say otherwise).\ne.g. Wide labels — minimum width 40mm, magnet count 3",
  },
};

export const PROFILE_TYPE_OPTIONS: { value: AiProfileTypeKey; label: string }[] = (
  Object.keys(PROFILE_TYPE_CONFIG) as AiProfileTypeKey[]
).map((value) => ({ value, label: PROFILE_TYPE_CONFIG[value].label }));
