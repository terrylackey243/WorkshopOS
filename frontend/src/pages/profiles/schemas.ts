import { z } from "zod";

// The 5 profile-type zod schemas + their form default values, shared between
// ProfilesPage's manual create/edit dialogs and the AI Import editable
// preview table (each preview row is its own form validated against the
// matching schema below).

export const printerSchema = z.object({
  name: z.string().min(1),
  manufacturer: z.string().optional(),
  model: z.string().optional(),
  build_width_mm: z.coerce.number().positive(),
  build_depth_mm: z.coerce.number().positive(),
  build_height_mm: z.coerce.number().positive(),
  nozzle_diameter_mm: z.coerce.number().positive().default(0.4),
  usable_margin_mm: z.coerce.number().min(0).default(2.0),
});
export type PrinterFormValues = z.infer<typeof printerSchema>;

export const printerDefaultValues: PrinterFormValues = {
  name: "",
  manufacturer: "",
  model: "",
  build_width_mm: 220,
  build_depth_mm: 220,
  build_height_mm: 250,
  nozzle_diameter_mm: 0.4,
  usable_margin_mm: 2.0,
};

export const magnetSchema = z
  .object({
    name: z.string().min(1),
    diameter_mm: z.coerce.number().positive(),
    thickness_mm: z.coerce.number().positive(),
    diameter_clearance_mm: z.coerce.number().min(0).default(0.2),
    depth_clearance_mm: z.coerce.number().min(0).default(0.2),
    fit_type: z.enum(["press", "glue", "sealed"]).default("glue"),
    // Only meaningful (and only sent to the backend) when fit_type is
    // "sealed" -- see MagnetsTab's fit-type change handler, which clears
    // this back to undefined for "press"/"glue".
    seal_cap_mm: z.coerce.number().positive().optional(),
  })
  .superRefine((values, ctx) => {
    if (values.fit_type === "sealed" && !values.seal_cap_mm) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["seal_cap_mm"],
        message: "Required for a sealed fit",
      });
    }
  });
export type MagnetFormValues = z.infer<typeof magnetSchema>;

export const magnetDefaultValues: MagnetFormValues = {
  name: "",
  diameter_mm: 6,
  thickness_mm: 2,
  diameter_clearance_mm: 0.2,
  depth_clearance_mm: 0.2,
  fit_type: "glue",
  seal_cap_mm: undefined,
};

// Values MagnetsTab writes into diameter_clearance_mm/seal_cap_mm whenever
// the fit_type dropdown changes, so the geometry a fit type implies is
// never left mismatched with stale field values from a previous selection.
export const MAGNET_FIT_TYPE_DEFAULTS: Record<
  MagnetFormValues["fit_type"],
  { diameter_clearance_mm: number; seal_cap_mm: number | undefined }
> = {
  press: { diameter_clearance_mm: 0, seal_cap_mm: undefined },
  glue: { diameter_clearance_mm: 0.2, seal_cap_mm: undefined },
  sealed: { diameter_clearance_mm: 0.2, seal_cap_mm: 0.6 },
};

export const materialSchema = z.object({
  name: z.string().min(1),
  material_type: z.string().min(1),
  xy_compensation_mm: z.coerce.number().default(0),
  notes: z.string().optional(),
});
export type MaterialFormValues = z.infer<typeof materialSchema>;

export const materialDefaultValues: MaterialFormValues = {
  name: "",
  material_type: "PLA",
  xy_compensation_mm: 0,
  notes: "",
};

export const labelStyleSchema = z.object({
  name: z.string().min(1),
  text_height_mm: z.coerce.number().positive().default(15.843),
  body_depth_mm: z.coerce.number().positive().default(4.55),
  outline_offset_mm: z.coerce.number().min(0).default(1.25),
  font_family: z.string().default("DejaVu Sans"),
  font_weight: z.string().default("bold"),
  font_style: z.string().default("italic"),
  horizontal_scale: z.coerce.number().positive().default(1.0),
  minimum_width_mm: z.coerce.number().min(0).default(24.0),
  // An empty `type="number"` input's `valueAsNumber` is `NaN`, not
  // `undefined` -- z.coerce.number().optional() alone rejects `NaN` and
  // fails validation silently (ProfileCrudTab's create mutation has no
  // onError handler), so the dialog just sits there with no visible error
  // the moment this genuinely-optional field is left blank. Preprocess
  // NaN/empty-string to undefined before the number coercion runs.
  fixed_width_mm: z.preprocess(
    (v) => (v === "" || (typeof v === "number" && Number.isNaN(v)) ? undefined : v),
    z.coerce.number().positive().optional(),
  ),
  magnet_count: z.coerce.number().int().min(0).default(2),
  magnet_edge_offset_mm: z.coerce.number().min(0).default(8.0),
  magnet_minimum_bridge_mm: z.coerce.number().min(0).default(0.6),
  magnet_support_extra_mm: z.coerce.number().min(0).default(0.0),
  default_magnet_profile_id: z.string().optional(),
});
export type LabelStyleFormValues = z.infer<typeof labelStyleSchema>;

export const labelStyleDefaultValues: LabelStyleFormValues = {
  name: "",
  text_height_mm: 15.843,
  body_depth_mm: 4.55,
  outline_offset_mm: 1.25,
  font_family: "DejaVu Sans",
  font_weight: "bold",
  font_style: "italic",
  horizontal_scale: 1.0,
  minimum_width_mm: 24.0,
  magnet_count: 2,
  magnet_edge_offset_mm: 8.0,
  magnet_minimum_bridge_mm: 0.6,
  magnet_support_extra_mm: 0.0,
};

export const drawerProfileSchema = z.object({
  name: z.string().min(1),
  inside_width_mm: z.coerce.number().positive(),
  inside_depth_mm: z.coerce.number().positive(),
  inside_height_mm: z.coerce.number().positive(),
  grid_unit_mm: z.coerce.number().positive().default(42),
});
export type DrawerProfileFormValues = z.infer<typeof drawerProfileSchema>;

export const drawerProfileDefaultValues: DrawerProfileFormValues = {
  name: "",
  inside_width_mm: 350,
  inside_depth_mm: 450,
  inside_height_mm: 50,
  grid_unit_mm: 42,
};
