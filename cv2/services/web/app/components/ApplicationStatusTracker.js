"use client";

import { APPLICATION_REJECTED, APPLICATION_TRACK } from "../../lib/applicationStatus";
import { cn } from "@/lib/utils";

/**
 * Interview-rail status tracker.
 * Signature: connected stage stations on a hot-pink progress rail;
 * Rejected is a separate terminal exit, not another station on the track.
 */
export default function ApplicationStatusTracker({
  value = null,
  onChange,
  disabled = false,
  updatedAt = null,
  className,
}) {
  const isRejected = value === APPLICATION_REJECTED.id;
  const currentIdx = APPLICATION_TRACK.findIndex((s) => s.id === value);
  const progressRatio =
    !isRejected && currentIdx >= 0
      ? currentIdx / Math.max(APPLICATION_TRACK.length - 1, 1)
      : 0;

  let updatedLabel = "";
  if (updatedAt) {
    try {
      updatedLabel = new Date(updatedAt).toLocaleString();
    } catch {
      updatedLabel = String(updatedAt);
    }
  }

  return (
    <section
      className={cn(
        "rounded-xl border border-border/80 bg-gradient-to-b from-primary/[0.07] to-transparent p-4 sm:p-5",
        className,
      )}
      aria-label="Application status"
    >
      <div className="mb-4 flex flex-wrap items-end justify-between gap-2">
        <div>
          <p className="m-0 text-[0.65rem] font-semibold uppercase tracking-[0.18em] text-primary">
            Application track
          </p>
          <p className="m-0 mt-1 text-sm text-muted-foreground">
            {isRejected
              ? "Closed — marked rejected"
              : currentIdx >= 0
                ? `Current stage: ${APPLICATION_TRACK[currentIdx].label}`
                : "Set where this role sits in your pipeline"}
          </p>
        </div>
        {updatedLabel ? (
          <p className="m-0 text-xs text-muted-foreground/80">
            Updated {updatedLabel}
          </p>
        ) : null}
      </div>

      <div className="flex flex-col gap-4 lg:flex-row lg:items-stretch lg:gap-5">
        <div className="min-w-0 flex-1 overflow-x-auto pb-1 [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          <div
            className="relative mx-auto min-w-[28rem] px-1 pt-2 sm:min-w-0"
            role="group"
            aria-label="Interview stages"
          >
            {/* Rail */}
            <div
              className="pointer-events-none absolute top-[1.35rem] right-4 left-4 h-0.5 rounded-full bg-border/80"
              aria-hidden
            />
            <div
              className={cn(
                "pointer-events-none absolute top-[1.35rem] left-4 h-0.5 rounded-full bg-primary transition-[width] duration-500 ease-out",
                isRejected && "opacity-40",
              )}
              style={{
                width:
                  currentIdx < 0 || isRejected
                    ? "0%"
                    : `calc(${progressRatio * 100}% - 0px)`,
                maxWidth: "calc(100% - 2rem)",
              }}
              aria-hidden
            />

            <ol className="relative m-0 flex list-none items-start justify-between gap-1 p-0">
              {APPLICATION_TRACK.map((stage, idx) => {
                const selected = !isRejected && value === stage.id;
                const passed = !isRejected && currentIdx > idx;
                return (
                  <li key={stage.id} className="flex min-w-0 flex-1 flex-col items-center">
                    <button
                      type="button"
                      disabled={disabled}
                      aria-pressed={selected}
                      aria-label={`Set status to ${stage.label}`}
                      title={stage.label}
                      onClick={() => onChange?.(stage.id)}
                      className={cn(
                        "group relative z-[1] flex size-7 items-center justify-center rounded-full border-2 transition-all duration-200",
                        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 focus-visible:ring-offset-background",
                        "disabled:cursor-not-allowed disabled:opacity-50",
                        selected &&
                          "border-primary bg-primary text-primary-foreground shadow-[0_0_0_4px_rgba(255,20,147,0.22),0_0_24px_rgba(255,20,147,0.35)] scale-110",
                        passed &&
                          !selected &&
                          "border-primary/80 bg-primary/25 text-primary",
                        !selected &&
                          !passed &&
                          "border-border bg-background text-muted-foreground hover:border-primary/55 hover:text-foreground",
                      )}
                    >
                      <span
                        className={cn(
                          "size-2 rounded-full bg-current transition-transform",
                          selected && "scale-125",
                          !selected && !passed && "opacity-50 group-hover:opacity-90",
                        )}
                      />
                    </button>
                    <span
                      className={cn(
                        "mt-2 max-w-[4.5rem] text-center text-[0.7rem] leading-tight font-medium sm:max-w-none sm:text-xs",
                        selected && "font-semibold text-primary",
                        passed && !selected && "text-foreground/85",
                        !selected && !passed && "text-muted-foreground",
                      )}
                    >
                      <span className="sm:hidden">{stage.short}</span>
                      <span className="hidden sm:inline">{stage.label}</span>
                    </span>
                  </li>
                );
              })}
            </ol>
          </div>
        </div>

        <div className="flex shrink-0 items-center justify-center lg:border-l lg:border-border/70 lg:pl-5">
          <button
            type="button"
            disabled={disabled}
            aria-pressed={isRejected}
            aria-label="Set status to Rejected"
            onClick={() => onChange?.(APPLICATION_REJECTED.id)}
            className={cn(
              "inline-flex min-h-11 items-center justify-center rounded-lg border px-4 py-2 text-sm font-semibold tracking-wide transition-all",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-destructive focus-visible:ring-offset-2 focus-visible:ring-offset-background",
              "disabled:cursor-not-allowed disabled:opacity-50",
              isRejected
                ? "border-destructive bg-destructive/20 text-destructive-foreground shadow-[0_0_0_1px_rgba(239,68,68,0.35)]"
                : "border-border/90 bg-background/60 text-muted-foreground hover:border-destructive/60 hover:text-destructive-foreground",
            )}
          >
            {APPLICATION_REJECTED.label}
          </button>
        </div>
      </div>
    </section>
  );
}
