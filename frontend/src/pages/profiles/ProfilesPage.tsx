import { useQuery } from "@tanstack/react-query";
import { Navigate, useNavigate, useParams } from "react-router-dom";
import { z } from "zod";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  drawerProfilesApi,
  labelStyleProfilesApi,
  magnetProfilesApi,
  materialProfilesApi,
  printerProfilesApi,
} from "@/lib/api";
import { FieldRow, NumberField, TextField } from "@/pages/profiles/fields";
import { ProfileCrudTab } from "@/pages/profiles/ProfileCrudTab";

const TABS = [
  { slug: "printers", label: "Printers" },
  { slug: "magnets", label: "Magnets" },
  { slug: "materials", label: "Materials" },
  { slug: "label-styles", label: "Label Styles" },
  { slug: "drawer-profiles", label: "Drawer Profiles" },
] as const;

// ---------------------------------------------------------------------------
// Printers
// ---------------------------------------------------------------------------

const printerSchema = z.object({
  name: z.string().min(1),
  manufacturer: z.string().optional(),
  model: z.string().optional(),
  build_width_mm: z.coerce.number().positive(),
  build_depth_mm: z.coerce.number().positive(),
  build_height_mm: z.coerce.number().positive(),
  nozzle_diameter_mm: z.coerce.number().positive().default(0.4),
  usable_margin_mm: z.coerce.number().min(0).default(2.0),
});
type PrinterFormValues = z.infer<typeof printerSchema>;

function PrintersTab() {
  return (
    <ProfileCrudTab
      entityLabel="Printer"
      queryKey="profiles-printers"
      api={printerProfilesApi}
      schema={printerSchema}
      defaultValues={
        {
          name: "",
          manufacturer: "",
          model: "",
          build_width_mm: 220,
          build_depth_mm: 220,
          build_height_mm: 250,
          nozzle_diameter_mm: 0.4,
          usable_margin_mm: 2.0,
        } as PrinterFormValues
      }
      columns={[
        { key: "build", label: "Build volume (mm)", format: (r) => `${r.build_width_mm}×${r.build_depth_mm}×${r.build_height_mm}`, mono: true },
        { key: "nozzle_diameter_mm", label: "Nozzle Ø (mm)", mono: true },
      ]}
      renderFields={(form) => (
        <>
          <TextField form={form} name="name" label="Name" />
          <FieldRow>
            <TextField form={form} name="manufacturer" label="Manufacturer" />
            <TextField form={form} name="model" label="Model" />
          </FieldRow>
          <FieldRow>
            <NumberField form={form} name="build_width_mm" label="Build width (mm)" />
            <NumberField form={form} name="build_depth_mm" label="Build depth (mm)" />
          </FieldRow>
          <FieldRow>
            <NumberField form={form} name="build_height_mm" label="Build height (mm)" />
            <NumberField form={form} name="nozzle_diameter_mm" label="Nozzle Ø (mm)" step="0.05" />
          </FieldRow>
          <NumberField form={form} name="usable_margin_mm" label="Usable margin (mm)" step="0.1" />
        </>
      )}
    />
  );
}

// ---------------------------------------------------------------------------
// Magnets
// ---------------------------------------------------------------------------

const magnetSchema = z.object({
  name: z.string().min(1),
  diameter_mm: z.coerce.number().positive(),
  thickness_mm: z.coerce.number().positive(),
  diameter_clearance_mm: z.coerce.number().min(0).default(0.2),
  depth_clearance_mm: z.coerce.number().min(0).default(0.2),
  fit_type: z.string().default("glue"),
});
type MagnetFormValues = z.infer<typeof magnetSchema>;

function MagnetsTab() {
  return (
    <ProfileCrudTab
      entityLabel="Magnet"
      queryKey="profiles-magnets"
      api={magnetProfilesApi}
      schema={magnetSchema}
      defaultValues={
        {
          name: "",
          diameter_mm: 6,
          thickness_mm: 2,
          diameter_clearance_mm: 0.2,
          depth_clearance_mm: 0.2,
          fit_type: "glue",
        } as MagnetFormValues
      }
      columns={[
        { key: "size", label: "Size (mm)", format: (r) => `⌀${r.diameter_mm} × ${r.thickness_mm}`, mono: true },
        { key: "fit_type", label: "Fit" },
      ]}
      renderFields={(form) => (
        <>
          <TextField form={form} name="name" label="Name" />
          <FieldRow>
            <NumberField form={form} name="diameter_mm" label="Diameter (mm)" step="0.1" />
            <NumberField form={form} name="thickness_mm" label="Thickness (mm)" step="0.1" />
          </FieldRow>
          <FieldRow>
            <NumberField form={form} name="diameter_clearance_mm" label="Diameter clearance (mm)" step="0.05" />
            <NumberField form={form} name="depth_clearance_mm" label="Depth clearance (mm)" step="0.05" />
          </FieldRow>
          <TextField form={form} name="fit_type" label="Fit type" placeholder="glue" />
        </>
      )}
    />
  );
}

// ---------------------------------------------------------------------------
// Materials
// ---------------------------------------------------------------------------

const materialSchema = z.object({
  name: z.string().min(1),
  material_type: z.string().min(1),
  xy_compensation_mm: z.coerce.number().default(0),
  notes: z.string().optional(),
});
type MaterialFormValues = z.infer<typeof materialSchema>;

function MaterialsTab() {
  return (
    <ProfileCrudTab
      entityLabel="Material"
      queryKey="profiles-materials"
      api={materialProfilesApi}
      schema={materialSchema}
      defaultValues={
        { name: "", material_type: "PLA", xy_compensation_mm: 0, notes: "" } as MaterialFormValues
      }
      columns={[
        { key: "material_type", label: "Type" },
        { key: "xy_compensation_mm", label: "XY comp. (mm)", mono: true },
      ]}
      renderFields={(form) => (
        <>
          <TextField form={form} name="name" label="Name" />
          <TextField form={form} name="material_type" label="Material type" placeholder="PLA" />
          <NumberField form={form} name="xy_compensation_mm" label="XY compensation (mm)" step="0.01" />
          <TextField form={form} name="notes" label="Notes" />
        </>
      )}
    />
  );
}

// ---------------------------------------------------------------------------
// Label styles
// ---------------------------------------------------------------------------

const labelStyleSchema = z.object({
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
type LabelStyleFormValues = z.infer<typeof labelStyleSchema>;

function LabelStylesTab() {
  const magnetProfilesQuery = useQuery({
    queryKey: ["profiles-magnets"],
    queryFn: () => magnetProfilesApi.list(),
  });

  return (
    <ProfileCrudTab
      entityLabel="Label style"
      queryKey="profiles-label-styles"
      api={labelStyleProfilesApi}
      schema={labelStyleSchema}
      defaultValues={
        {
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
        } as LabelStyleFormValues
      }
      columns={[
        { key: "font_family", label: "Font", format: (r) => `${r.font_family} (${r.font_weight}/${r.font_style})` },
        { key: "text_height_mm", label: "Text height (mm)", mono: true },
        { key: "magnet_count", label: "Magnets", mono: true },
      ]}
      renderFields={(form) => (
        <>
          <TextField form={form} name="name" label="Name" />
          <FieldRow>
            <NumberField form={form} name="text_height_mm" label="Text height (mm)" step="0.001" />
            <NumberField form={form} name="body_depth_mm" label="Body depth (mm)" step="0.01" />
          </FieldRow>
          <FieldRow>
            <NumberField form={form} name="outline_offset_mm" label="Outline offset (mm)" step="0.01" />
            <NumberField form={form} name="horizontal_scale" label="Horizontal scale" step="0.01" />
          </FieldRow>
          <FieldRow>
            <TextField form={form} name="font_family" label="Font family" />
            <TextField form={form} name="font_weight" label="Font weight" />
          </FieldRow>
          <FieldRow>
            <TextField form={form} name="font_style" label="Font style" />
            <NumberField form={form} name="minimum_width_mm" label="Minimum width (mm)" step="0.1" />
          </FieldRow>
          <NumberField form={form} name="fixed_width_mm" label="Fixed width (mm, optional)" step="0.1" />
          <FieldRow>
            <NumberField form={form} name="magnet_count" label="Magnet count" step="1" />
            <NumberField form={form} name="magnet_edge_offset_mm" label="Magnet edge offset (mm)" step="0.1" />
          </FieldRow>
          <FieldRow>
            <NumberField form={form} name="magnet_minimum_bridge_mm" label="Magnet min. bridge (mm)" step="0.05" />
            <NumberField form={form} name="magnet_support_extra_mm" label="Magnet support extra (mm)" step="0.05" />
          </FieldRow>
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-muted-foreground">
              Default magnet profile
            </label>
            <Select
              value={form.watch("default_magnet_profile_id")}
              onValueChange={(v) => form.setValue("default_magnet_profile_id", v)}
            >
              <SelectTrigger>
                <SelectValue placeholder="None" />
              </SelectTrigger>
              <SelectContent>
                {(magnetProfilesQuery.data ?? []).map((m) => (
                  <SelectItem key={m.id} value={m.id}>
                    {m.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </>
      )}
    />
  );
}

// ---------------------------------------------------------------------------
// Drawer profiles
// ---------------------------------------------------------------------------

const drawerProfileSchema = z.object({
  name: z.string().min(1),
  inside_width_mm: z.coerce.number().positive(),
  inside_depth_mm: z.coerce.number().positive(),
  inside_height_mm: z.coerce.number().positive(),
  grid_unit_mm: z.coerce.number().positive().default(42),
});
type DrawerProfileFormValues = z.infer<typeof drawerProfileSchema>;

function DrawerProfilesTab() {
  return (
    <ProfileCrudTab
      entityLabel="Drawer profile"
      queryKey="profiles-drawer-profiles"
      api={drawerProfilesApi}
      schema={drawerProfileSchema}
      defaultValues={
        {
          name: "",
          inside_width_mm: 350,
          inside_depth_mm: 450,
          inside_height_mm: 50,
          grid_unit_mm: 42,
        } as DrawerProfileFormValues
      }
      columns={[
        { key: "inside", label: "Inside (mm)", format: (r) => `${r.inside_width_mm}×${r.inside_depth_mm}×${r.inside_height_mm}`, mono: true },
        { key: "grid_unit_mm", label: "Grid unit (mm)", mono: true },
      ]}
      renderFields={(form) => (
        <>
          <TextField form={form} name="name" label="Name" />
          <FieldRow>
            <NumberField form={form} name="inside_width_mm" label="Inside width (mm)" />
            <NumberField form={form} name="inside_depth_mm" label="Inside depth (mm)" />
          </FieldRow>
          <FieldRow>
            <NumberField form={form} name="inside_height_mm" label="Inside height (mm)" />
            <NumberField form={form} name="grid_unit_mm" label="Grid unit (mm)" step="1" />
          </FieldRow>
        </>
      )}
    />
  );
}

// ---------------------------------------------------------------------------
// Page shell
// ---------------------------------------------------------------------------

export function ProfilesPage() {
  const { tab } = useParams();
  const navigate = useNavigate();

  if (!tab) return <Navigate to="/profiles/printers" replace />;

  return (
    <div className="p-4">
      <div className="mb-3">
        <h1 className="text-base font-semibold">Profiles</h1>
        <p className="text-xs text-muted-foreground">
          Reusable presets for printers, magnets, materials, label styles, and drawer
          dimensions.
        </p>
      </div>
      <Tabs value={tab} onValueChange={(v) => navigate(`/profiles/${v}`)}>
        <TabsList>
          {TABS.map((t) => (
            <TabsTrigger key={t.slug} value={t.slug}>
              {t.label}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>
      <div className="mt-4">
        {tab === "printers" && <PrintersTab />}
        {tab === "magnets" && <MagnetsTab />}
        {tab === "materials" && <MaterialsTab />}
        {tab === "label-styles" && <LabelStylesTab />}
        {tab === "drawer-profiles" && <DrawerProfilesTab />}
      </div>
    </div>
  );
}
