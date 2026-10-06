// The election page is up until polls close; after that the nav entry, the
// front-page link and the Ask suggestions come down with the ballot data
// (api/app/candidates.py).
export const ELECTION_DAY = "2026-11-03";

/** Whether `today` (YYYY-MM-DD) is on or before Election Day. */
export const electionAhead = (today: string) => today <= ELECTION_DAY;

/** The same, for right now in the City's time zone. */
export const electionAheadNow = () =>
  electionAhead(new Date().toLocaleDateString("en-CA", { timeZone: "America/New_York" }));

/** A starter question for /ask while the election is ahead. */
export const ELECTION_QUESTION = "Who is running for City Council on November 3?";
