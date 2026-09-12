"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";

const STATUSES = ["proposed", "in_progress", "approved", "denied", "deferred", "completed", "withdrawn"];

const RECENCY = [
  { value: "", label: "Any time" },
  { value: "30", label: "Last 30 days" },
  { value: "90", label: "Last 90 days" },
  { value: "365", label: "Last year" },
];

const SORTS = [
  { value: "recent", label: "Recently updated" },
  { value: "active", label: "Most activity" },
  { value: "name", label: "A to Z" },
];

function Select({
  name,
  value,
  options,
  onChange,
  label,
}: {
  name: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (name: string, value: string) => void;
  label: string;
}) {
  return (
    <label className="flex items-center gap-1.5 text-[13px] text-muted">
      <span className="sr-only">{label}</span>
      <select
        name={name}
        value={value}
        onChange={(e) => onChange(name, e.target.value)}
        className="rounded-full border border-hairline bg-canvas px-3 py-1.5 text-[13px] font-medium text-body outline-none focus:border-ink"
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}

/** The secondary facets of the directory: status, body, recency, activity,
 * sort, and name search. Every control writes to the URL so views are
 * shareable and the server component re-renders. */
export default function DirectoryFilters() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();

  function set(name: string, value: string) {
    const next = new URLSearchParams(params.toString());
    if (value) next.set(name, value);
    else next.delete(name);
    next.delete("page");
    router.push(`${pathname}?${next.toString()}`);
  }

  const active = params.get("active") === "1";

  return (
    <form
      action={pathname}
      onSubmit={(e) => {
        e.preventDefault();
        set("q", (new FormData(e.currentTarget).get("q") as string) ?? "");
      }}
      className="flex flex-wrap items-center gap-2"
    >
      <Select
        name="status"
        label="Status"
        value={params.get("status") ?? ""}
        onChange={set}
        options={[{ value: "", label: "Any status" }, ...STATUSES.map((s) => ({ value: s, label: s.replace("_", " ") }))]}
      />
      <Select
        name="body"
        label="Body"
        value={params.get("body") ?? ""}
        onChange={set}
        options={[
          { value: "", label: "Either body" },
          { value: "city_council", label: "City Council" },
          { value: "planning_commission", label: "Planning Commission" },
        ]}
      />
      <Select name="days" label="Recency" value={params.get("days") ?? ""} onChange={set} options={RECENCY} />
      <Select name="sort" label="Sort" value={params.get("sort") ?? "recent"} onChange={set} options={SORTS} />
      <button
        type="button"
        onClick={() => set("active", active ? "" : "1")}
        aria-pressed={active}
        title="Hide topics with a single tracked update"
        className={`rounded-full px-3 py-1.5 text-[13px] font-medium ${
          active ? "bg-ink text-canvas" : "border border-hairline bg-canvas text-muted hover:text-ink"
        }`}
      >
        Recurring only
      </button>
      {/* hidden mirrors keep the primary facets when the search submits */}
      {["type", "official", "view"].map((k) =>
        params.get(k) ? <input key={k} type="hidden" name={k} value={params.get(k)!} /> : null,
      )}
      <input
        name="q"
        defaultValue={params.get("q") ?? ""}
        placeholder="Filter by name…"
        aria-label="Filter by name"
        className="w-full rounded-full border border-hairline bg-canvas px-4 py-1.5 text-[13px] outline-none placeholder:text-muted-soft focus:border-ink sm:ml-auto sm:w-[200px]"
      />
    </form>
  );
}
