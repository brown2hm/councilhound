"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useJurisdiction } from "@/components/JurisdictionProvider";

const STATUSES = ["proposed", "in_progress", "approved", "denied", "deferred", "completed", "withdrawn"];

/** One "kind" control covers both primary facets: `official=true` for the
 * city's own project records, `type=` for everything the meetings named. */
const KINDS = [
  { value: "", label: "Any kind" },
  { value: "official", label: "Official projects" },
  { value: "project", label: "Projects" },
  { value: "topic", label: "Plans & programs" },
  { value: "ordinance", label: "Ordinances" },
  { value: "resolution", label: "Resolutions" },
  { value: "case_number", label: "Cases" },
  { value: "location", label: "Places" },
  { value: "person", label: "People" },
];

const RECENCY = [
  { value: "", label: "Any time" },
  { value: "30", label: "Last 30 days" },
  { value: "90", label: "Last 90 days" },
  { value: "365", label: "Last 12 months" },
];

const SORTS = [
  { value: "", label: "Most activity" },
  { value: "recent", label: "Recently updated" },
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
    <label className="inline-flex items-center gap-1.5 rounded-xl border border-hairline bg-white py-1.5 pl-3 pr-1 text-[13px] text-muted">
      {label}
      <select
        name={name}
        value={value}
        onChange={(e) => onChange(name, e.target.value)}
        className="bg-transparent pr-1 text-[13px] font-semibold text-ink outline-none"
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

/** The directory's one filter row: name, kind, status, body, recency, sort,
 * and the recurring-only switch (on unless the URL says `active=0`). Every
 * control writes to the URL so views are shareable and the server component
 * re-renders. */
export default function DirectoryFilters() {
  const { bodies: BODIES, identity } = useJurisdiction();
  const kinds = KINDS.map((k) => (k.value === "official" ? { ...k, label: `Official ${identity.noun} projects` } : k));
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();

  function apply(patch: Record<string, string>) {
    const next = new URLSearchParams(params.toString());
    for (const [name, value] of Object.entries(patch)) {
      if (value) next.set(name, value);
      else next.delete(name);
    }
    next.delete("page");
    const qs = next.toString();
    router.push(qs ? `${pathname}?${qs}` : pathname);
  }
  const set = (name: string, value: string) => apply({ [name]: value });

  const kind = params.get("official") === "true" ? "official" : (params.get("type") ?? "");
  const recurring = params.get("active") !== "0";

  return (
    <form
      action={pathname}
      onSubmit={(e) => {
        e.preventDefault();
        set("q", (new FormData(e.currentTarget).get("q") as string) ?? "");
      }}
      className="flex flex-wrap items-center gap-2"
    >
      <input
        name="q"
        defaultValue={params.get("q") ?? ""}
        placeholder="Filter by name…"
        aria-label="Filter by name"
        className="min-w-[200px] flex-1 rounded-xl border border-hairline bg-white px-3.5 py-2 text-[13px] outline-none placeholder:text-muted-soft focus:border-ink"
      />
      <Select
        name="kind"
        label="Kind"
        value={kind}
        onChange={(_, v) =>
          apply(v === "official" ? { official: "true", type: "" } : { official: "", type: v })
        }
        options={kinds}
      />
      <Select
        name="status"
        label="Status"
        value={params.get("status") ?? ""}
        onChange={set}
        options={[{ value: "", label: "Any" }, ...STATUSES.map((s) => ({ value: s, label: s.replace("_", " ") }))]}
      />
      <Select
        name="body"
        label="Body"
        value={params.get("body") ?? ""}
        onChange={set}
        options={[{ value: "", label: "Any" }, ...BODIES.map((b) => ({ value: b.key, label: b.label }))]}
      />
      <Select name="days" label="Seen" value={params.get("days") ?? ""} onChange={set} options={RECENCY} />
      <Select name="sort" label="Sort" value={params.get("sort") ?? ""} onChange={set} options={SORTS} />
      <button
        type="button"
        role="switch"
        aria-checked={recurring}
        onClick={() => set("active", recurring ? "0" : "")}
        title="Hide topics with a single tracked update"
        className="inline-flex items-center gap-2 pl-1 text-[13px] font-medium text-body"
      >
        <span
          aria-hidden
          className={`relative inline-block h-[18px] w-[30px] rounded-full transition-colors ${recurring ? "bg-teal" : "bg-strong"}`}
        >
          <span
            className={`absolute top-[2px] h-[14px] w-[14px] rounded-full bg-canvas transition-[left] ${recurring ? "left-[14px]" : "left-[2px] border border-hairline"}`}
          />
        </span>
        Recurring only
      </button>
      {/* hidden mirrors keep the other facets when the name filter submits */}
      {["type", "official", "view", "status", "body", "days", "sort", "active"].map((k) =>
        params.get(k) ? <input key={k} type="hidden" name={k} value={params.get(k)!} /> : null,
      )}
    </form>
  );
}
