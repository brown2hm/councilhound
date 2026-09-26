import { bodyDot, bodyLabel } from "@/lib/jurisdiction";

// Body identity dots come from the jurisdiction's palette index
// (lib/jurisdiction.BODY_PALETTE); re-exported so existing importers keep
// working.
export { bodyDot };

export default function BodyTag({
  body,
  className = "",
}: {
  body: string;
  className?: string;
}) {
  return (
    <span className={`inline-flex items-center gap-1.5 whitespace-nowrap ${className}`}>
      <span aria-hidden className={`inline-block h-2 w-2 rounded-full ${bodyDot(body)}`} />
      {bodyLabel(body)}
    </span>
  );
}
