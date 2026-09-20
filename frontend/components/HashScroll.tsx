"use client";

import { useEffect } from "react";

/**
 * Scroll to the URL hash once the page has rendered. A streamed page's
 * anchor (a dated heading deep inside a wiki history) is not in the document
 * when the browser does its own hash scroll on load, so the jump from a
 * meeting page to "this meeting in the wiki" would land at the top.
 */
export default function HashScroll() {
  useEffect(() => {
    const id = decodeURIComponent(window.location.hash.slice(1));
    if (!id) return;
    const el = document.getElementById(id);
    if (el) el.scrollIntoView({ block: "start" });
  }, []);
  return null;
}
