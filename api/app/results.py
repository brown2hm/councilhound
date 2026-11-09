"""How the November 3, 2026 City election came out: the votes for every
name on the ballot (app.terms holds the ballot itself), pinned by hand from
the Virginia Department of Elections' results site like every other
jurisdiction fact, with the count's status and when it was read.

The count stays marked unofficial until the State Board of Elections
certifies it; re-read the page and update STATUS, AS_OF and the votes when
it does. Winners are the top `seats` vote-getters in each contest, never
written in by hand, so a changed count can't leave a stale winner behind."""
import datetime
from dataclasses import dataclass

_D = datetime.date

SOURCE = "https://enr.elections.virginia.gov/results/public/fairfax-city/elections/2026-November-General"
PUBLISHER = "Virginia Department of Elections"
ELECTION_DAY = _D(2026, 11, 3)

# 'unofficial' (election-night count, canvass under way) | 'certified'
STATUS = "unofficial"
AS_OF = datetime.datetime(2026, 11, 9, 16, 40)   # the page's "Last Updated", City time
STATUS_NOTE = ("Every precinct's election-night count is in, but provisional ballots were not yet "
               "reported and the count is not yet certified.")
BALLOTS_CAST = 11_326
REGISTERED = 19_182


@dataclass(frozen=True)
class ContestResult:
    contest: str                          # an app.candidates.CONTESTS key
    seats: int                            # how many win
    votes: tuple[tuple[str, int], ...]    # ballot name -> votes, in ballot order
    write_in: int = 0

    @property
    def total(self) -> int:
        return sum(v for _, v in self.votes) + self.write_in

    def ranked(self) -> list[tuple[str, int]]:
        return sorted(self.votes, key=lambda nv: -nv[1])

    def winners(self) -> list[str]:
        return [n for n, _ in self.ranked()[: self.seats]]

    def margin(self) -> int:
        """Votes between the last winner and the first runner-up (None-safe:
        0 when every candidate won)."""
        r = self.ranked()
        return r[self.seats - 1][1] - r[self.seats][1] if len(r) > self.seats else 0


RESULTS: dict[str, ContestResult] = {
    "mayor": ContestResult("mayor", 1, (
        ("Kirsten Sides Lockhart", 5_964),
        ('Thomas D. "Tom" Peterson', 4_810),
    ), write_in=62),
    "city_council": ContestResult("city_council", 6, (
        ("Stacy R. Hall", 5_288),
        ("Rachel M McQuillen", 4_792),
        ("Anthony T. Amos", 6_397),
        ("Sandi W. Slappey Brown", 5_555),
        ("Kelly M. O'Brien", 5_957),
        ("Russell A. Jones", 1_737),
        ("Stephen S. Kim", 1_419),
        ("Susan Hartley Kuiler", 3_826),
        ("María José Padmore", 5_394),
        ("Steve S Chang", 4_060),
        ("Jessica L. Lough", 3_773),
    ), write_in=313),
    "school_board": ContestResult("school_board", 5, (
        ("Carolyn S. Pitches", 5_391),
        ("Amit Sarah Hickman", 4_820),
        ("Kristina M. Cecere", 4_973),
        ("Sarah M. Kelsey", 5_072),
        ("Lauren A. Bartelme", 4_716),
    ), write_in=361),
}


@dataclass(frozen=True)
class Referendum:
    key: str
    title: str
    question: str
    yes: int
    no: int

    @property
    def passed(self) -> bool:
        return self.yes > self.no


# the City's own question; the three statewide constitutional amendments
# are left to the state's results
REFERENDA = (
    Referendum(
        "retail_sales_tax", "Retail sales tax",
        # as printed
        "Should the City of Fairfax, Virginia, be authorized to levy a general retail sales tax at a "
        "rate not to exceed one percent (1%), as determined by the City Council, to provide revenue "
        "solely for: (i) capital projects for new construction or renovation of schools serving the "
        "City, including bond and loan financing costs related to such needs; or (ii) public "
        "transportation purposes serving the City, including bond and loan financing costs related "
        "to such needs; or (iii) both capital projects for new construction or renovation of schools "
        "serving the City and public transportation purposes serving the City?",
        yes=6_119, no=4_874),
)


def outcome(ballot_name: str) -> tuple[ContestResult, int, bool] | None:
    """(contest result, votes, won) for a name on the ballot."""
    for r in RESULTS.values():
        for n, v in r.votes:
            if n == ballot_name:
                return r, v, n in r.winners()
    return None


def pct(votes: int, total: int) -> float:
    return round(100 * votes / total, 2) if total else 0.0


def status_line() -> str:
    """'unofficial results as of 2026-11-09 16:40' for prompts and captions."""
    return f"{STATUS} results as of {AS_OF:%Y-%m-%d %H:%M}"
