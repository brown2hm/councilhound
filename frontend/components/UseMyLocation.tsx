"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

/** Browser geolocation → /nearby?lat&lng. Nothing is stored anywhere. */
export default function UseMyLocation({ radius }: { radius: number }) {
  const router = useRouter();
  const [state, setState] = useState<"idle" | "locating" | "denied" | "unsupported">("idle");

  function locate() {
    if (typeof navigator === "undefined" || !navigator.geolocation) {
      setState("unsupported");
      return;
    }
    setState("locating");
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const lat = pos.coords.latitude.toFixed(5);
        const lng = pos.coords.longitude.toFixed(5);
        router.push(`/nearby?lat=${lat}&lng=${lng}&r=${radius}&q=${encodeURIComponent("my location")}`);
      },
      () => setState("denied"),
      { enableHighAccuracy: false, timeout: 10000, maximumAge: 300000 },
    );
  }

  return (
    <span className="inline-flex items-center gap-2">
      <button
        type="button"
        onClick={locate}
        disabled={state === "locating"}
        className="rounded-xl border border-hairline bg-canvas px-4 py-[11px] text-sm font-semibold leading-none hover:border-ink disabled:opacity-60"
      >
        {state === "locating" ? "Locating…" : "📍 Use my location"}
      </button>
      {state === "denied" && (
        <span className="text-[12px] text-muted">Location blocked — type an address instead.</span>
      )}
      {state === "unsupported" && (
        <span className="text-[12px] text-muted">Your browser can&apos;t share location.</span>
      )}
    </span>
  );
}
