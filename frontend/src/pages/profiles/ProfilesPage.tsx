import { useQuery } from "@tanstack/react-query";
import { Navigate, useNavigate, useParams } from "react-router-dom";

import { Label } from "@/components/ui/label";
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
import {
  drawerProfileDefaultValues,
  drawerProfileSchema,
  labelStyleDefaultValues,
  labelStyleSchema,
  MAGNET_FIT_TYPE_DEFAULTS,
  magnetDefaultValues,
  magnetSchema,
  type MagnetFormValues,
  materialDefaultValues,
  materialSchema,
  printerDefaultValues,
  printerSchema,
} from "@/pages/profiles/schemas";

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

function PrintersTab() {
  return (
    <ProfileCrudTab
      entityLabel="Printer"
      queryKey="profiles-printers"
      api={printerProfilesApi}
      schema={printerSchema}
      defaultValues={printerDefaultValues}
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

const FIT_TYPE_LABELS: Record<MagnetFormValues["fit_type"], string> = {
  press: "Press-fit (tighter)",
  glue: "Glue (open recess)",
  sealed: "Sealed (print-in-place)",
};

function MagnetsTab() {
  return (
    <ProfileCrudTab
      entityLabel="Magnet"
      queryKey="profiles-magnets"
      api={magnetProfilesApi}
      schema={magnetSchema}
      defaultValues={magnetDefaultValues}
      toEditValues={(row) => ({
        name: row.name,
        diameter_mm: row.diameter_mm,
        thickness_mm: row.thickness_mm,
        diameter_clearance_mm: row.diameter_clearance_mm,
        depth_clearance_mm: row.depth_clearance_mm,
        fit_type: row.fit_type as MagnetFormValues["fit_type"],
        seal_cap_mm: row.seal_cap_mm ?? undefined,
      })}
      columns={[
        { key: "size", label: "Size (mm)", format: (r) => `⌀${r.diameter_mm} × ${r.thickness_mm}`, mono: true },
        { key: "fit_type", label: "Fit", format: (r) => FIT_TYPE_LABELS[r.fit_type as MagnetFormValues["fit_type"]] ?? r.fit_type },
      ]}
      renderFields={(form) => {
        const fitType = form.watch("fit_type") as MagnetFormValues["fit_type"];
        return (
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
            <div className="flex flex-col gap-1">
              <Label>Fit type</Label>
              <Select
                value={fitType}
                onValueChange={(v) => {
                  const fit = v as MagnetFormValues["fit_type"];
                  const defaults = MAGNET_FIT_TYPE_DEFAULTS[fit];
                  form.setValue("fit_type", fit, { shouldValidate: true });
                  form.setValue("diameter_clearance_mm", defaults.diameter_clearance_mm, { shouldValidate: true });
                  form.setValue("seal_cap_mm", defaults.seal_cap_mm, { shouldValidate: true });
                }}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {(Object.keys(FIT_TYPE_LABELS) as MagnetFormValues["fit_type"][]).map((fit) => (
                    <SelectItem key={fit} value={fit}>
                      {FIT_TYPE_LABELS[fit]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            {fitType === "sealed" && (
              <NumberField
                form={form}
                name="seal_cap_mm"
                label="Seal cap thickness (mm) — printed over the magnet after it's inserted mid-print"
                step="0.1"
              />
            )}
          </>
        );
      }}
    />
  );
}

// ---------------------------------------------------------------------------
// Materials
// ---------------------------------------------------------------------------

function MaterialsTab() {
  return (
    <ProfileCrudTab
      entityLabel="Material"
      queryKey="profiles-materials"
      api={materialProfilesApi}
      schema={materialSchema}
      defaultValues={materialDefaultValues}
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
      defaultValues={labelStyleDefaultValues}
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

function DrawerProfilesTab() {
  return (
    <ProfileCrudTab
      entityLabel="Drawer profile"
      queryKey="profiles-drawer-profiles"
      api={drawerProfilesApi}
      schema={drawerProfileSchema}
      defaultValues={drawerProfileDefaultValues}
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
    <div className="flex h-full flex-col overflow-auto scrollbar-thin p-4">
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
