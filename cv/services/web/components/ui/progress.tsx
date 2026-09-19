"use client";

import { Progress as ProgressPrimitive } from "@base-ui/react/progress";
import type * as React from "react";
import { cn } from "@/lib/utils";

export function Progress({
  className,
  children,
  trackClassName,
  indicatorClassName,
  ...props
}: ProgressPrimitive.Root.Props & {
  trackClassName?: string;
  indicatorClassName?: string;
}): React.ReactElement {
  return (
    <ProgressPrimitive.Root
      className={cn("grid w-full gap-2", className)}
      data-slot="progress"
      {...props}
    >
      {children}
      <ProgressPrimitive.Track
        className={cn(
          "relative h-2 w-full overflow-hidden rounded-full bg-secondary",
          trackClassName,
        )}
        data-slot="progress-track"
      >
        <ProgressPrimitive.Indicator
          className={cn(
            "block h-full rounded-full bg-primary transition-[width] duration-300 ease-out",
            indicatorClassName,
          )}
          data-slot="progress-indicator"
        />
      </ProgressPrimitive.Track>
    </ProgressPrimitive.Root>
  );
}

export function ProgressLabel({
  className,
  ...props
}: ProgressPrimitive.Label.Props): React.ReactElement {
  return (
    <ProgressPrimitive.Label
      className={cn("font-medium text-foreground text-sm", className)}
      data-slot="progress-label"
      {...props}
    />
  );
}

export function ProgressValue({
  className,
  ...props
}: ProgressPrimitive.Value.Props): React.ReactElement {
  return (
    <ProgressPrimitive.Value
      className={cn("text-muted-foreground text-sm tabular-nums", className)}
      data-slot="progress-value"
      {...props}
    />
  );
}

export { ProgressPrimitive };
