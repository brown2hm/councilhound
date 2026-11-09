import Link from "next/link";
import ContestTabs from "@/components/ContestTabs";
import ForumCompare from "@/components/ForumCompare";
import QuestionnaireCompare from "@/components/QuestionnaireCompare";
import {
  api,
  formatDate,
  type ElectionCandidate,
  type ContestResult,
  type ElectionContest,
  type ElectionResults,
  type ElectionSource,
} from "@/lib/api";

export const metadata = {
  title: "Election",
  description:
    "The City of Fairfax's November 3, 2026 election: the vote count for Mayor, City Council and School Board, and every candidate with the same sources looked up for each.",
};

export const dynamic = "force-dynamic";

// The order a card lists its sources in, the same for every candidate, so a
// gap shows up as a gap.
const KINDS: [string, string][] = [
  ["campaign", "Campaign site"],
  ["questionnaire", "Voter guides"],
  ["finance", "Campaign finance"],
  ["official", "Official record"],
  ["forum", "Candidate forums"],
  ["news", "News"],
];

const VOTE_FOR = ["", "one", "two", "three", "four", "five", "six", "seven"];

function voteFor(c: ElectionContest) {
  if (!c.vote_for) return c.label;
  return c.vote_for === 1
    ? "Vote for one"
    : `Vote for up to ${VOTE_FOR[c.vote_for] ?? c.vote_for}`;
}

function SourceLink({ s }: { s: ElectionSource }) {
  return (
    <a
      href={s.url}
      target="_blank"
      rel="noopener noreferrer"
      className="underline decoration-hairline underline-offset-2 hover:decoration-ink"
    >
      {s.publisher}
    </a>
  );
}

function Elected() {
  return (
    <span className="inline-flex w-fit shrink-0 rounded-full bg-tint-mint px-2 py-0.5 text-[11px] font-semibold uppercase tracking-[0.6px] text-tint-mint-text">
      Elected
    </span>
  );
}

function asOf(r: ElectionResults) {
  const d = new Date(r.as_of);
  return `${d.toLocaleDateString("en-US", { month: "long", day: "numeric" })}, ${d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" })}`;
}

/** The count for one race, most votes first, a bar per candidate. */
function Result({ r, status }: { r: ContestResult; status: string }) {
  const top = r.candidates[0]?.pct || 1;
  const n = r.candidates.length;
  return (
    <div className="mb-8 rounded-xl border border-hairline bg-canvas p-4 sm:p-5">
      <h3 className="mb-0.5 font-display text-[20px] font-medium tracking-[-0.2px]">
        {status === "certified" ? "Results" : "Unofficial results"}
      </h3>
      <p className="mb-3 text-[13px] text-muted">
        {r.seats === 1 ? "Most votes wins." : `The top ${r.seats} win.`}
        {r.margin === null
          ? ` ${n === r.seats ? `${n} candidates for ${n} seats: all elected.` : ""}`
          : r.seats > 1
            ? ` The last seat was decided by ${r.margin.toLocaleString()} votes.`
            : ` Margin: ${r.margin.toLocaleString()} votes.`}
      </p>
      <ol className="flex flex-col gap-2">
        {r.candidates.map((c, i) => (
          <li key={c.ballot_name}>
            {/* the line between the winners and the rest */}
            {i === r.seats && i < n && (
              <div
                className="mb-2 border-t border-dashed border-hairline"
                aria-hidden
              />
            )}
            <div className="flex flex-wrap items-baseline justify-between gap-x-3">
              <span
                className={`flex items-center gap-2 text-[14px] ${c.won ? "font-semibold text-ink" : "text-body"}`}
              >
                {c.ballot_name}
                {c.won && <Elected />}
              </span>
              <span className="text-[13px] tabular-nums text-muted">
                {c.votes.toLocaleString()} · {c.pct.toFixed(1)}%
              </span>
            </div>
            <div
              className="mt-1 h-1.5 rounded-full bg-hairline-soft"
              aria-hidden
            >
              <div
                className={`h-1.5 rounded-full ${c.won ? "bg-pine" : "bg-muted-soft"}`}
                style={{ width: `${(c.pct / top) * 100}%` }}
              />
            </div>
          </li>
        ))}
      </ol>
      <p className="mt-3 text-[12px] text-muted">
        Write-ins: {r.write_in.toLocaleString()} ({r.write_in_pct.toFixed(1)}%).
        Percentages are of all {r.total.toLocaleString()} votes in the race
        {r.seats > 1 ? `; each voter could choose up to ${r.seats}` : ""}.
      </p>
    </div>
  );
}

function CandidateCard({ c }: { c: ElectionCandidate }) {
  const byKind = (kind: string) => c.sources.filter((s) => s.kind === kind);
  return (
    <article className="flex flex-col rounded-xl border border-hairline bg-canvas p-4">
      <h3 className="flex flex-wrap items-center gap-2 text-[17px] font-semibold leading-snug text-ink">
        {c.ballot_name}
        {c.won && <Elected />}
      </h3>
      {c.incumbent && (
        <p className="mt-0.5 text-[12px] leading-snug text-muted">
          Now: {c.incumbent}
        </p>
      )}
      {c.member && (
        <Link
          href={`/members/${c.member.slug}`}
          className="mt-2 inline-flex w-fit items-center gap-1 rounded-full bg-tint-mint px-2.5 py-0.5 text-[12px] font-semibold text-tint-mint-text hover:bg-mint"
        >
          Voting record on CouncilHound →
        </Link>
      )}

      <dl className="mt-3 flex flex-col text-[13px]">
        {KINDS.map(([kind, label]) => {
          const found = byKind(kind);
          // a voting record parsed from the minutes is an official record too
          const record = kind === "official" ? c.member : null;
          return (
            <div
              key={kind}
              className="grid grid-cols-[120px_1fr] gap-2 border-t border-hairline-soft py-1.5"
            >
              <dt className="text-muted">{label}</dt>
              <dd className="text-body">
                {found.length || record ? (
                  <ul className="flex flex-col gap-1">
                    {record && (
                      <li className="leading-snug">
                        <Link
                          href={`/members/${record.slug}`}
                          className="underline decoration-hairline underline-offset-2 hover:decoration-ink"
                        >
                          Voting record
                        </Link>
                        <span className="text-[12px] text-muted">
                          {" "}
                          · CouncilHound, from meeting minutes
                        </span>
                      </li>
                    )}
                    {found.map((s) => (
                      <li key={s.url} className="leading-snug">
                        <a
                          href={s.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="underline decoration-hairline underline-offset-2 hover:decoration-ink"
                        >
                          {s.title}
                        </a>
                        <span className="text-[12px] text-muted">
                          {" "}
                          · {s.publisher}
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <span className="text-muted-soft">none found</span>
                )}
              </dd>
            </div>
          );
        })}
      </dl>

      {c.not_found.length > 0 && (
        <p className="mt-2 text-[12px] leading-snug text-muted">
          <span className="font-semibold">Looked for, not found:</span>{" "}
          {c.not_found.join("; ")}.
        </p>
      )}

      {c.sources.length > 0 && (
        <details className="group mt-3 border-t border-hairline pt-2">
          <summary className="cursor-pointer text-[13px] font-semibold text-body-strong marker:text-muted">
            What the sources say ({c.sources.length})
          </summary>
          <ul className="mt-2 flex flex-col gap-3">
            {c.sources.map((s) => (
              <li key={s.url} className="text-[13px] leading-relaxed text-body">
                <div className="text-[12px] text-muted">
                  <SourceLink s={s} /> · {s.kind_label}
                  {s.published
                    ? ` · ${formatDate(s.published)}`
                    : ` · checked ${formatDate(s.checked)}`}
                </div>
                <ul className="mt-0.5 list-disc pl-4">
                  {s.facts.map((f) => (
                    <li key={f}>{f}</li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        </details>
      )}

      <Link
        href={`/ask?q=${encodeURIComponent(`What do we know about ${c.ballot_name}, candidate in the November 3 election?`)}`}
        className="mt-auto pt-3 text-[13px] font-semibold text-hound hover:underline"
      >
        Ask about this candidate →
      </Link>
    </article>
  );
}

function Contest({ c, status }: { c: ElectionContest; status: string | null }) {
  const n = c.candidates.length;
  return (
    <section>
      {/* the selected tab names the race; the heading stays for screen readers and the outline */}
      <h2 className="sr-only">{c.name}</h2>
      {c.result && status && <Result r={c.result} status={status} />}
      {c.result && (
        <h3 className="mb-2 font-display text-[20px] font-medium tracking-[-0.2px]">
          The candidates
        </h3>
      )}
      <p className="mb-3 text-[13px] font-semibold text-muted">
        {voteFor(c)} · {n} candidate{n === 1 ? "" : "s"}
        {c.vote_for && c.vote_for > 1 ? ` for ${c.vote_for} seats` : ""}
      </p>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {c.candidates.map((cand) => (
          <CandidateCard key={cand.ballot_name} c={cand} />
        ))}
      </div>

      {c.questionnaires.length > 0 && (
        <div className="mt-8">
          <h3 className="mb-2 font-display text-[20px] font-medium tracking-[-0.2px]">
            Same questions, side by side
          </h3>
          <QuestionnaireCompare questionnaires={c.questionnaires} />
        </div>
      )}

      {c.forums.length > 0 && (
        <div className="mt-8">
          <h3 className="mb-2 font-display text-[20px] font-medium tracking-[-0.2px]">
            At the forums, in their own words
          </h3>
          <ForumCompare forums={c.forums} />
        </div>
      )}

      {c.race_sources.length > 0 && (
        <details className="mt-6 rounded-lg bg-soft px-4 py-3">
          <summary className="cursor-pointer text-[13px] font-semibold text-body-strong">
            Coverage of the whole race ({c.race_sources.length})
          </summary>
          <ul className="mt-2 flex flex-col gap-3">
            {c.race_sources.map((s) => (
              <li key={s.url} className="text-[13px] leading-relaxed text-body">
                <a
                  href={s.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="font-semibold underline-offset-2 hover:underline"
                >
                  {s.title}
                </a>
                <span className="text-[12px] text-muted">
                  {" "}
                  · {s.publisher}
                  {s.published ? `, ${formatDate(s.published)}` : ""}
                </span>
                <ul className="mt-0.5 list-disc pl-4">
                  {s.facts.map((f) => (
                    <li key={f}>{f}</li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}

export default async function ElectionPage() {
  const e = await api.election();
  const day = e.contests[0]?.election_date;
  const r = e.results;

  return (
    <div className="mx-auto max-w-[1180px] px-4 pb-16 pt-8 sm:px-8">
      <h1 className="mb-1 font-display text-[34px] font-medium tracking-[-0.5px]">
        {day
          ? `${new Date(day + "T00:00:00").toLocaleDateString("en-US", { month: "long", day: "numeric" })} City election`
          : "City election"}
        {r ? " results" : ""}
      </h1>
      {r && (
        <section
          className={`mb-6 rounded-xl px-4 py-3 text-[13px] leading-relaxed sm:px-5 ${r.status === "certified" ? "bg-tint-mint text-tint-mint-text" : "bg-tint-ochre text-tint-ochre-text"}`}
        >
          <p className="font-semibold">
            {r.status === "certified"
              ? "Certified results"
              : "Unofficial results"}{" "}
            as of {asOf(r)}
          </p>
          <p className="max-w-[90ch]">
            {r.note} {r.ballots_cast.toLocaleString()} ballots cast of{" "}
            {r.registered.toLocaleString()} registered voters (
            {Math.round((100 * r.ballots_cast) / r.registered)}%). From the{" "}
            <a
              href={r.source}
              target="_blank"
              rel="noopener noreferrer"
              className="underline underline-offset-2"
            >
              {r.publisher}
            </a>
            . The newly elected take office January 1, 2027; until then the
            sitting members hold their seats.
          </p>
        </section>
      )}
      <p className="mb-5 max-w-[78ch] text-[15px] leading-relaxed text-body">
        Every candidate on the City&apos;s{" "}
        <a
          href={e.ballot_url}
          target="_blank"
          rel="noopener noreferrer"
          className="underline underline-offset-2"
        >
          official sample ballot
        </a>
        , in ballot order, with the same sources looked up for each one. City
        elections are non-partisan: every candidate appears on the ballot as an
        independent.
      </p>

      <aside className="mb-6 rounded-xl border border-hairline bg-callout px-4 py-3 text-[13px] leading-relaxed text-body sm:px-5">
        <p className="mb-1 font-semibold text-ink">
          Outside the meeting record
        </p>
        <p className="max-w-[90ch]">
          Many candidates have never voted at a meeting CouncilHound indexes, so
          this page draws on campaign sites, voter guides, campaign finance
          reports, City rosters and local news for everyone alike. Each source
          carries the date it was checked; what was looked for and not found is
          listed too. Nothing here is a recommendation. Candidates who already
          hold office link to their voting record.
        </p>
      </aside>

      {!r && (
        <section className="mb-8 rounded-xl bg-pine px-4 py-4 text-white sm:px-5">
          <h2 className="mb-1.5 text-[15px] font-semibold">How to vote</h2>
          <ul className="list-disc pl-5 text-[14px] leading-relaxed text-white/90">
            {e.voting.facts.map((f) => (
              <li key={f}>{f}</li>
            ))}
          </ul>
          <p className="mt-1.5 text-[12px] text-white/65">
            From{" "}
            <a
              href={e.voting.url}
              target="_blank"
              rel="noopener noreferrer"
              className="underline"
            >
              {e.voting.publisher}
            </a>
            {e.voting.published ? `, ${formatDate(e.voting.published)}` : ""}.
            Confirm details with the City&apos;s Office of Elections.
          </p>
        </section>
      )}

      <ContestTabs
        tabs={e.contests.map((c) => ({
          key: c.key,
          name: c.name,
          count: c.result
            ? `${c.result.seats} elected of ${c.candidates.length}`
            : `${c.candidates.length} candidate${c.candidates.length === 1 ? "" : "s"}`,
          rule: voteFor(c).toLowerCase(),
        }))}
      >
        {e.contests.map((c) => (
          <Contest key={c.key} c={c} status={r?.status ?? null} />
        ))}
      </ContestTabs>

      {r && r.referenda.length > 0 && (
        <section className="mt-10">
          <h2 className="mb-2 font-display text-[22px] font-medium tracking-[-0.2px]">
            Also on the City ballot
          </h2>
          {r.referenda.map((q) => (
            <div
              key={q.key}
              className="rounded-xl border border-hairline bg-canvas p-4 sm:p-5"
            >
              <p className="flex flex-wrap items-center gap-2 text-[15px] font-semibold text-ink">
                {q.title}
                <span
                  className={`rounded-full px-2 py-0.5 text-[11px] uppercase tracking-[0.6px] ${q.passed ? "bg-tint-mint text-tint-mint-text" : "bg-tint-coral text-tint-coral-text"}`}
                >
                  {q.passed ? "Passed" : "Failed"}
                </span>
              </p>
              <p className="mt-1 text-[13px] tabular-nums text-body">
                Yes {q.yes.toLocaleString()} ({q.yes_pct.toFixed(1)}%) · No{" "}
                {q.no.toLocaleString()} ({(100 - q.yes_pct).toFixed(1)}%)
              </p>
              <details className="mt-2">
                <summary className="cursor-pointer text-[13px] font-semibold text-body-strong">
                  The question as printed
                </summary>
                <p className="mt-1 max-w-[90ch] text-[13px] leading-relaxed text-body">
                  {q.question}
                </p>
              </details>
            </div>
          ))}
        </section>
      )}

      <p className="mt-12 text-[12px] text-muted">
        Candidate sources last swept {formatDate(e.checked)}. Something missing
        or wrong? Every fact links to the page it came from.
      </p>
    </div>
  );
}
