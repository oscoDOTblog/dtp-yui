"use client";

import { useEffect, useState } from "react";
import { LOADING_GIFS, pickRandomLoadingGif } from "../../lib/loadingGifs";
import styles from "./LoadingGif.module.css";

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
    <div className={`${styles.container} ${className}`.trim()}>
      {src ? (
        <div className={styles.gifWrap}>
          <img
            src={src}
            alt={alt}
            width={160}
            height={160}
            className={styles.gifImage}
          />
        </div>
      ) : (
        <div className={styles.spinner} aria-hidden="true" />
      )}
      {message ? <p className={styles.caption}>{message}</p> : null}
      <div className={styles.dots} aria-hidden="true">
        <span className={styles.dot}>•</span>
        <span className={styles.dot}>•</span>
        <span className={styles.dot}>•</span>
      </div>
    </div>
  );
}
