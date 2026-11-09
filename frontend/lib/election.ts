// Until polls close the election page is a ballot guide, with a nav entry,
// a front-page link and an Ask starter question. After that it shows the
// results (api/app/results.py): the starter question comes down, and the
// nav entry and front-page link stay up until the new terms begin.
export const ELECTION_DAY = "2026-11-03";
export const RESULTS_UNTIL = "2026-12-31";

/** Whether `today` (YYYY-MM-DD) is on or before Election Day. */
export const electionAhead = (today: string) => today <= ELECTION_DAY;

/** The same, for right now in the City's time zone. */
export const electionAheadNow = () =>
  electionAhead(new Date().toLocaleDateString("en-CA", { timeZone: "America/New_York" }));

/** Whether the election page belongs in the nav and on the front page. */
export const electionInNews = (today: string) => today <= RESULTS_UNTIL;

export const electionInNewsNow = () =>
  electionInNews(new Date().toLocaleDateString("en-CA", { timeZone: "America/New_York" }));

/** A starter question for /ask while the election is ahead. */
export const ELECTION_QUESTION = "Who is running for City Council on November 3?";
