"use client";

import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectItem,
  SelectPopup,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";

const FIT_OPTIONS = [
  { value: "strong", label: "Strength", className: "text-success-foreground" },
  { value: "warning", label: "Warning", className: "text-warning-foreground" },
  { value: "gap", label: "Gap", className: "text-destructive-foreground" },
];

function areaName(item) {
  return (item?.requirement || item?.skill || "").trim();
}

function resolveFit(item, bucket) {
  const raw = (item?.fit || "").toLowerCase();
  if (raw === "strong" || raw === "strength") return "strong";
  if (raw === "warning" || raw === "warn") return "warning";
  if (raw === "gap") return "gap";
  return bucket;
}

function notesFor(item, fit) {
  if (fit === "strong") {
    return item.evidenceLevel || item.reason || "verified evidence";
  }
  return item.reason || "";
}

function flattenRows(match) {
  const rows = [];
  for (const item of match?.strongMatches || []) {
    rows.push({ item, fit: resolveFit(item, "strong") });
  }
  for (const item of match?.warnings || []) {
    rows.push({ item, fit: resolveFit(item, "warning") });
  }
  for (const item of match?.meaningfulGaps || []) {
    rows.push({ item, fit: resolveFit(item, "gap") });
  }
  return rows;
}

function fitOptionClass(fit) {
  return FIT_OPTIONS.find((opt) => opt.value === fit)?.className || "";
}

/**
 * Fit assessment table with Strength / Warning / Gap dropdowns.
 * onChangeFit(requirement, fit) should persist + refresh match.
 */
export default function FitAssessmentTable({
  match,
  busy = false,
  busyRequirement = "",
  onChangeFit,
}) {
  const rows = flattenRows(match);

  if (!rows.length) {
    return (
      <p className="m-0 text-sm text-muted-foreground">
        No fit rows yet — run Analyze first.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-border bg-card">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Area</TableHead>
            <TableHead className="w-[9.5rem]">Your fit</TableHead>
            <TableHead>Notes</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map(({ item, fit }, idx) => {
            const requirement = areaName(item);
            const rowBusy =
              busy &&
              (!busyRequirement ||
                busyRequirement.toLowerCase() === requirement.toLowerCase());
            return (
              <TableRow key={`${fit}-${requirement}-${idx}`}>
                <TableCell>
                  <div className="flex flex-wrap items-center gap-2">
                    <span>{requirement || "—"}</span>
                    {item.fitOverridden ? (
                      <Badge variant="outline" className="text-[10px] uppercase">
                        Override
                      </Badge>
                    ) : null}
                  </div>
                </TableCell>
                <TableCell>
                  <Select
                    value={fit}
                    disabled={busy || !requirement || !onChangeFit}
                    onValueChange={(value) => {
                      if (!value || value === fit || !requirement) return;
                      onChangeFit?.(requirement, value);
                    }}
                  >
                    <SelectTrigger
                      size="sm"
                      className={cn(
                        "min-w-[7.5rem] font-bold",
                        fitOptionClass(fit),
                        rowBusy && "opacity-70",
                      )}
                      aria-label={`Fit for ${requirement || "requirement"}`}
                    >
                      <SelectValue />
                    </SelectTrigger>
                    <SelectPopup>
                      {FIT_OPTIONS.map((opt) => (
                        <SelectItem
                          key={opt.value}
                          value={opt.value}
                          className={opt.className}
                        >
                          {opt.label}
                        </SelectItem>
                      ))}
                    </SelectPopup>
                  </Select>
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {notesFor(item, fit)}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}
