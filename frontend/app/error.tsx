"use client";

import Image from "next/image";
import Link from "next/link";
import { useEffect } from "react";

/** Route-level boundary. Without this a single failed API fetch renders
 * Next's stock error screen — the list pages fetch without catching, so a
 * brief API blip used to take the whole page down. */
export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="mx-auto max-w-[640px] px-4 pb-16 pt-16 sm:px-8">
      <div className="rounded-3xl border border-hairline bg-canvas p-8 text-center">
        <Image
          src="/brand/hound.png"
          alt=""
          width={82}
          height={72}
          className="mx-auto mb-4 h-[72px] w-auto"
        />
        <h1 className="mb-2 text-2xl font-medium tracking-[-0.4px]">The hound lost the scent.</h1>
        <p className="mb-6 text-sm leading-[1.6] text-body">
          This page couldn&apos;t load its data. That usually means the record service is
          briefly unreachable — not that anything is missing from the archive.
        </p>
        <div className="flex flex-wrap justify-center gap-2">
          <button
            onClick={reset}
            className="rounded-xl bg-ink px-5 py-3 text-sm font-semibold leading-none text-white hover:bg-ink-active"
          >
            Try again
          </button>
          <Link
            href="/"
            className="rounded-xl border border-hairline px-5 py-3 text-sm font-semibold leading-none text-muted hover:text-ink"
          >
            Back to the briefing
          </Link>
        </div>
        {error.digest && (
          <p className="mt-5 text-[12px] text-muted-soft">Reference: {error.digest}</p>
        )}
      </div>
    </div>
  );
}
