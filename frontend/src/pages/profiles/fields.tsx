import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

// Loosely typed on purpose: this is a thin layout helper shared across five
// differently-shaped profile forms (Printer/Magnet/Material/DrawerProfile/
// LabelStyle), so pinning it to one form's field-name union would defeat the
// point of sharing it. `UseFormReturn<any>` still fails structural checks in
// some react-hook-form internals (validate callbacks), so we fall all the
// way down to `any` here deliberately.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type AnyForm = any;

export function TextField({
  form,
  name,
  label,
  placeholder,
}: {
  form: AnyForm;
  name: string;
  label: string;
  placeholder?: string;
}) {
  return (
    <div className="flex flex-col gap-1">
      <Label htmlFor={name}>{label}</Label>
      <Input id={name} placeholder={placeholder} {...form.register(name)} />
    </div>
  );
}

export function NumberField({
  form,
  name,
  label,
  step = "any",
}: {
  form: AnyForm;
  name: string;
  label: string;
  step?: string;
}) {
  return (
    <div className="flex flex-col gap-1">
      <Label htmlFor={name}>{label}</Label>
      <Input
        id={name}
        type="number"
        step={step}
        {...form.register(name, { valueAsNumber: true })}
      />
    </div>
  );
}

export function FieldRow({ children }: { children: React.ReactNode }) {
  return <div className="grid grid-cols-2 gap-3">{children}</div>;
}
