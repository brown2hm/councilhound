// The election page is up until polls close; after that the nav entry and the
// front-page link come down with the ballot data (api/app/candidates.py).
export const ELECTION_DAY = "2026-11-03";

/** Whether `today` (YYYY-MM-DD, local) is on or before Election Day. */
export const electionAhead = (today: string) => today <= ELECTION_DAY;
