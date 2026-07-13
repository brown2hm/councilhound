import { BODY_LABELS } from "@/lib/api";

// Body identity colors: City Council = deep teal, Planning Commission =
// ochre. Dots (not filled badges) so they never read as status badges.
export const BODY_DOTS: Record<string, string> = {
  city_council: "bg-teal",
  planning_commission: "bg-ochre",
};

export default function BodyTag({
  body,
  className = "",
}: {
  body: string;
  className?: string;
}) {
  return (
    <span className={`inline-flex items-center gap-1.5 whitespace-nowrap ${className}`}>
      <span
        aria-hidden
        className={`inline-block h-2 w-2 rounded-full ${BODY_DOTS[body] ?? "bg-muted-soft"}`}
      />
      {BODY_LABELS[body] ?? body}
    </span>
  );
}
