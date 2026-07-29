"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardPanel, CardTitle } from "@/components/ui/card";
import { getAgentApiBase } from "../../lib/agentApi";

/**
 * Live JPEG preview from the apply agent (polls /preview/latest).
 */
export default function BrowserPreview({
  active = false,
  pageUrl = null,
  uiMode = null,
}) {
  const [src, setSrc] = useState(null);
  const [expanded, setExpanded] = useState(false);
  const [hasFrame, setHasFrame] = useState(false);

  useEffect(() => {
    if (!active) {
      setSrc(null);
      setHasFrame(false);
      return undefined;
    }

    let cancelled = false;
    let timer;

    async function tick() {
      try {
        const res = await fetch(
          `${getAgentApiBase()}/preview/latest?t=${Date.now()}`,
          { cache: "no-store" }
        );
        if (!res.ok) {
          if (!cancelled) setHasFrame(false);
        } else {
          const blob = await res.blob();
          const url = URL.createObjectURL(blob);
          if (cancelled) {
            URL.revokeObjectURL(url);
            return;
          }
          setSrc((prev) => {
            if (prev) URL.revokeObjectURL(prev);
            return url;
          });
          setHasFrame(true);
        }
      } catch {
        if (!cancelled) setHasFrame(false);
      }
      if (!cancelled) timer = setTimeout(tick, 400);
    }

    tick();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
      setSrc((prev) => {
        if (prev) URL.revokeObjectURL(prev);
        return null;
      });
    };
  }, [active]);

  useEffect(() => {
    if (!expanded) return undefined;
    function onKey(e) {
      if (e.key === "Escape") setExpanded(false);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [expanded]);

  const caption =
    [uiMode, pageUrl].filter(Boolean).join(" · ") ||
    (active ? "Waiting for first frame…" : "Start a run to see the browser");

  return (
    <>
      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-2 space-y-0">
          <CardTitle>Browser</CardTitle>
          <Button
            size="sm"
            variant="secondary"
            disabled={!hasFrame}
            onClick={() => setExpanded(true)}
          >
            Expand
          </Button>
        </CardHeader>
        <CardPanel className="space-y-2">
          <div className="relative aspect-video overflow-hidden rounded-lg border border-border bg-black/80">
            {src ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={src}
                alt="Agent browser preview"
                className="h-full w-full object-contain object-top"
              />
            ) : (
              <div className="flex h-full min-h-[180px] items-center justify-center px-4 text-center text-sm text-muted-foreground">
                {active
                  ? "Connecting to live preview…"
                  : "Start a run to see the browser"}
              </div>
            )}
          </div>
          <p className="m-0 truncate text-xs text-muted-foreground" title={caption}>
            {caption}
          </p>
        </CardPanel>
      </Card>

      {expanded ? (
        <div
          className="fixed inset-0 z-50 flex flex-col bg-black/95 p-3 sm:p-5"
          role="dialog"
          aria-modal="true"
          aria-label="Expanded browser preview"
        >
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <p className="m-0 max-w-[80%] truncate text-sm text-muted-foreground">
              {caption}
            </p>
            <Button size="sm" variant="secondary" onClick={() => setExpanded(false)}>
              Close
            </Button>
          </div>
          <div className="min-h-0 flex-1 overflow-auto rounded-lg border border-border bg-black">
            {src ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={src}
                alt="Expanded agent browser preview"
                className="mx-auto h-auto max-h-full w-full object-contain"
              />
            ) : null}
          </div>
        </div>
      ) : null}
    </>
  );
}
