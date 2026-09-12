import Image from "next/image";
import Link from "next/link";

export const metadata = { title: "Not found" };

const ELSEWHERE = [
  { href: "/topics", label: "Projects & topics" },
  { href: "/meetings", label: "Meetings" },
  { href: "/nearby", label: "Near me" },
  { href: "/ask", label: "Ask the hound" },
];

export default function NotFound() {
  return (
    <div className="mx-auto max-w-[640px] px-4 pb-16 pt-16 sm:px-8">
      <div className="rounded-3xl border border-hairline bg-canvas p-8 text-center">
        <Image
          src="/brand/fox.png"
          alt=""
          width={610}
          height={409}
          className="mx-auto mb-4 h-[72px] w-auto"
        />
        <h1 className="mb-2 text-2xl font-medium tracking-[-0.4px]">Nothing at this address.</h1>
        <p className="mb-6 text-sm leading-[1.6] text-body">
          The page may have moved, or a topic may have been merged into a related one as the
          record grew. Try searching the archive, or start from one of these.
        </p>
        <div className="mb-6 flex flex-wrap justify-center gap-2">
          {ELSEWHERE.map((l) => (
            <Link
              key={l.href}
              href={l.href}
              className="rounded-full border border-hairline px-4 py-2 text-sm font-medium text-muted hover:text-ink"
            >
              {l.label}
            </Link>
          ))}
        </div>
        <form action="/search" className="flex items-center gap-2 rounded-xl border border-hairline bg-canvas p-1.5 pl-4">
          <input
            name="q"
            placeholder="Search the meeting record..."
            className="min-w-0 flex-1 bg-transparent text-[15px] text-ink outline-none placeholder:text-muted-soft"
          />
          <button className="shrink-0 rounded-lg bg-ink px-5 py-2.5 text-sm font-semibold text-white hover:bg-ink-active">
            Search
          </button>
        </form>
      </div>
    </div>
  );
}
