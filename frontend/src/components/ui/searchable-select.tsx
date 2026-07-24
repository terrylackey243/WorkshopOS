import * as React from "react";
import { Command } from "cmdk";
import { Check, ChevronDown } from "lucide-react";

import { cn } from "@/lib/utils";

export interface SearchableSelectOption {
  value: string;
  label: string;
  // Extra terms cmdk's fuzzy matcher should search against, in addition to
  // the label -- e.g. a profile's dimensions, so "406" matches even though
  // it's not in the visible label text.
  searchText?: string;
}

interface SearchableSelectProps {
  id?: string;
  options: SearchableSelectOption[];
  value?: string;
  onValueChange: (value: string) => void;
  placeholder?: string;
  searchPlaceholder?: string;
}

/**
 * A `<Select>` drop-in for option lists too long to scan visually --
 * type-to-filter via cmdk (already a dependency for `CommandPalette.tsx`),
 * styled to match `select.tsx`'s trigger/content/item classes so it reads as
 * the same control, not a bolted-on widget. No `@radix-ui/react-popover`
 * dependency added -- a plain absolutely-positioned panel + outside-click
 * listener is enough for a single inline dropdown.
 */
export function SearchableSelect({
  id,
  options,
  value,
  onValueChange,
  placeholder,
  searchPlaceholder,
}: SearchableSelectProps) {
  const [open, setOpen] = React.useState(false);
  const containerRef = React.useRef<HTMLDivElement>(null);
  const selected = options.find((o) => o.value === value);

  React.useEffect(() => {
    if (!open) return;
    const handlePointerDown = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handlePointerDown);
    return () => document.removeEventListener("mousedown", handlePointerDown);
  }, [open]);

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        id={id}
        onClick={() => setOpen((v) => !v)}
        className="flex h-8 w-full items-center justify-between rounded-sm border border-input bg-background px-2.5 py-1 text-sm shadow-sm focus:outline-none focus:ring-1 focus:ring-ring"
      >
        <span className={cn("line-clamp-1", !selected && "text-muted-foreground")}>
          {selected ? selected.label : (placeholder ?? "Select…")}
        </span>
        <ChevronDown className="h-3.5 w-3.5 shrink-0 opacity-50" />
      </button>

      {open && (
        <Command
          className="absolute z-50 mt-1 w-full overflow-hidden rounded-sm border border-border bg-popover text-popover-foreground shadow-md"
          filter={(itemValue, search) =>
            itemValue.toLowerCase().includes(search.toLowerCase()) ? 1 : 0
          }
        >
          <Command.Input
            autoFocus
            placeholder={searchPlaceholder ?? "Search…"}
            className="w-full border-b border-border bg-transparent px-2.5 py-1.5 text-sm outline-none placeholder:text-muted-foreground"
          />
          <Command.List className="max-h-60 overflow-auto p-1">
            <Command.Empty className="px-2.5 py-3 text-center text-xs text-muted-foreground">
              No matches.
            </Command.Empty>
            {options.map((option) => (
              <Command.Item
                key={option.value}
                value={`${option.label} ${option.searchText ?? ""}`}
                onSelect={() => {
                  onValueChange(option.value);
                  setOpen(false);
                }}
                className="relative flex w-full cursor-pointer select-none items-center rounded-sm py-1.5 pl-7 pr-2 text-sm outline-none data-[selected=true]:bg-accent data-[selected=true]:text-accent-foreground"
              >
                <span className="absolute left-2 flex h-3.5 w-3.5 items-center justify-center">
                  {option.value === value && <Check className="h-3.5 w-3.5" />}
                </span>
                {option.label}
              </Command.Item>
            ))}
          </Command.List>
        </Command>
      )}
    </div>
  );
}
