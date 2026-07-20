"use client";

import { useEffect, useState } from "react";
import { LOADING_GIFS, pickRandomLoadingGif } from "../../lib/loadingGifs";
import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";

export default function LoadingGif({
  message = "Working…",
  alt = "Loading",
  className = "",
}) {
  const [src, setSrc] = useState(LOADING_GIFS[0] || null);

  useEffect(() => {
    setSrc(pickRandomLoadingGif());
    if (typeof window === "undefined") return undefined;
    const preloaders = LOADING_GIFS.map((gif) => {
      const image = new window.Image();
      image.src = gif;
      return image;
    });
    return () => {
      preloaders.forEach((image) => {
        image.src = "";
      });
    };
  }, []);

  return (
    <div
      className={cn(
        "flex shrink-0 flex-col items-center gap-3",
        className,
      )}
    >
      {src ? (
        <div className="flex items-center justify-center">
          <img
            src={src}
            alt={alt}
            width={160}
            height={160}
            className="size-40 rounded-2xl border border-primary/35 bg-gradient-to-br from-primary/12 to-pink-400/8 object-contain p-3 shadow-[0_18px_45px_rgba(255,20,147,0.18)] max-md:size-32"
          />
        </div>
      ) : (
        <Spinner className="size-10 text-primary" />
      )}
      {message ? (
        <p className="m-0 max-w-[260px] text-center text-sm leading-snug text-foreground/90">
          {message}
        </p>
      ) : null}
      <div className="flex gap-2 text-primary" aria-hidden="true">
        <span className="animate-[pulse_1.4s_ease-in-out_infinite] text-2xl leading-none">
          •
        </span>
        <span className="animate-[pulse_1.4s_ease-in-out_0.2s_infinite] text-2xl leading-none">
          •
        </span>
        <span className="animate-[pulse_1.4s_ease-in-out_0.4s_infinite] text-2xl leading-none">
          •
        </span>
      </div>
    </div>
  );
}
