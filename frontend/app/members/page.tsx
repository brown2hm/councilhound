import Link from "next/link";
import { api } from "@/lib/api";

export const dynamic = "force-dynamic";

const ROLE_TINTS: Record<string, string> = {
  Mayor: "bg-tint-lavender text-tint-lavender-text",
  Councilmember: "bg-tint-mint text-tint-mint-text",
  Chair: "bg-tint-ochre text-tint-ochre-text",
  "Vice-Chair": "bg-tint-ochre text-tint-ochre-text",
  Commissioner: "bg-card text-body",
};

export default async function MembersPage() {
  const members = await api.members();
  const council = members.filter((m) => m.roles.some((r) => r === "Mayor" || r === "Councilmember"));
  const commission = members.filter((m) => !council.includes(m));

  const Grid = ({ list }: { list: typeof members }) => (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {list.map((m) => (
        <Link
          key={m.slug}
          href={`/members/${m.slug}`}
          className={`rounded-2xl border border-hairline p-4 px-5 hover:border-ink ${
            m.is_current ? "bg-canvas" : "bg-soft opacity-75 hover:opacity-100"
          }`}
        >
          <div className="mb-1.5 font-semibold">{m.name}</div>
          <div className="mb-2 flex flex-wrap gap-1.5">
            {m.roles.map((r) => (
              <span key={r} className={`rounded-full px-2 py-[3px] text-xs font-semibold ${ROLE_TINTS[r] ?? "bg-card text-body"}`}>
                {r}
              </span>
            ))}
            {!m.is_current && (
              <span className="rounded-full bg-strong px-2 py-[3px] text-xs font-semibold text-muted">
                Former
              </span>
            )}
          </div>
          <div className="text-[13px] text-muted">
            {m.votes_cast > 0 ? `${m.votes_cast} recorded votes` : "No recorded votes yet"}
          </div>
        </Link>
      ))}
    </div>
  );

  return (
    <div className="mx-auto max-w-[1100px] px-8 pb-16 pt-8">
      <h1 className="mb-1 text-[32px] font-medium tracking-[-0.5px]">Members</h1>
      <p className="mb-8 text-sm text-muted">
        Voting records and recorded positions, parsed from meeting minutes and rosters.
      </p>
      <h2 className="mb-3 flex items-center gap-2 text-lg font-semibold">
        <span className="h-2.5 w-2.5 rounded-full bg-teal" /> City Council
      </h2>
      <Grid list={council} />
      <h2 className="mb-3 mt-9 flex items-center gap-2 text-lg font-semibold">
        <span className="h-2.5 w-2.5 rounded-full bg-ochre" /> Planning Commission & boards
      </h2>
      <Grid list={commission} />
    </div>
  );
}
