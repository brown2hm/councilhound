"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";
import StatusBadge from "@/components/StatusBadge";
import type { EntitySuggestion } from "@/lib/api";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** Site-wide search: typeahead over tracked topics and members, Enter
 * falls through to the full-text search page. */
export default function SearchBox({
  autoFocus = false,
  className = "",
  placeholder = "Search topics, members, transcripts…",
}: {
  autoFocus?: boolean;
  className?: string;
  placeholder?: string;
}) {
  const router = useRouter();
  const listId = useId();
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<EntitySuggestion[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const boxRef = useRef<HTMLFormElement>(null);

  useEffect(() => {
    const term = q.trim();
    if (term.length < 2) {
      setHits([]);
      return;
    }
    const ctrl = new AbortController();
    const t = setTimeout(async () => {
      try {
        const resp = await fetch(`${API}/entities/suggest?q=${encodeURIComponent(term)}`, {
          signal: ctrl.signal,
        });
        if (resp.ok) {
          setHits(await resp.json());
          setOpen(true);
          setActive(-1);
        }
      } catch {
        // aborted or offline: keep whatever is showing
      }
    }, 150);
    return () => {
      clearTimeout(t);
      ctrl.abort();
    };
  }, [q]);

  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  function go(href: string) {
    setOpen(false);
    setQ("");
    router.push(href);
  }

  function onKey(e: React.KeyboardEvent<HTMLInputElement>) {
    if (!open || hits.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => (a + 1) % hits.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => (a <= 0 ? hits.length - 1 : a - 1));
    } else if (e.key === "Enter" && active >= 0) {
      e.preventDefault();
      go(hits[active].href);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  }

  return (
    <form
      ref={boxRef}
      role="search"
      action="/search"
      method="get"
      onSubmit={(e) => {
        if (!q.trim()) e.preventDefault();
        else setOpen(false);
      }}
      className={`relative ${className}`}
    >
      <input
        name="q"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        onFocus={() => hits.length > 0 && setOpen(true)}
        onKeyDown={onKey}
        autoFocus={autoFocus}
        autoComplete="off"
        placeholder={placeholder}
        aria-label="Search"
        aria-autocomplete="list"
        aria-controls={listId}
        aria-expanded={open && hits.length > 0}
        className="w-full rounded-full border border-hairline bg-canvas py-2 pl-9 pr-4 text-sm outline-none placeholder:text-muted-soft focus:border-ink"
      />
      <svg
        aria-hidden="true"
        width="14"
        height="14"
        viewBox="0 0 16 16"
        className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-muted"
      >
        <circle cx="6.5" cy="6.5" r="5" fill="none" stroke="currentColor" strokeWidth="1.8" />
        <path d="M10.5 10.5L15 15" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      </svg>
      {open && hits.length > 0 && (
        <ul
          id={listId}
          role="listbox"
          className="absolute left-0 right-0 top-full z-30 mt-1.5 overflow-hidden rounded-2xl border border-hairline bg-canvas shadow-lg"
        >
          {hits.map((h, i) => (
            <li key={`${h.kind}-${h.slug}`} role="option" aria-selected={i === active}>
              <Link
                href={h.href}
                onClick={() => go(h.href)}
                onMouseEnter={() => setActive(i)}
                className={`flex items-center justify-between gap-3 px-4 py-2.5 text-sm ${
                  i === active ? "bg-soft" : ""
                }`}
              >
                <span className="min-w-0">
                  <span className="block truncate font-semibold">{h.name}</span>
                  <span className="block text-[12px] text-muted">
                    {h.kind === "member"
                      ? "member"
                      : `${h.entity_type.replace("_", " ")} · ${h.update_count} update${h.update_count === 1 ? "" : "s"}`}
                  </span>
                </span>
                {h.kind === "topic" && <StatusBadge status={h.current_status} />}
              </Link>
            </li>
          ))}
          <li className="border-t border-hairline-soft px-4 py-2 text-[12px] text-muted">
            Press Enter to search every transcript and agenda for “{q.trim()}”
          </li>
        </ul>
      )}
    </form>
  );
}
