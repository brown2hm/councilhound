"""Who is running, from outside the meeting record: each candidate on the
City's official sample ballot, with what their campaign, voter guides,
finance filings, official pages and local news say, pinned by hand with
the date each source was checked (like terms.py, from which the ballot
itself comes).

The record answers what a sitting member did; most candidates have no
record at all, so these sources are how /ask can say anything about them.
Every candidate in a contest is looked up the same way, and what was
looked for and not found is kept too, so an answer can say "no voter-guide
answers were found" instead of describing only the candidates with the
most coverage.

Facts are short neutral paraphrases, each held against the source that
states it; stated positions read as the source's ("The campaign site
lists ..."), never as findings."""
import datetime
import re
import unicodedata
from dataclasses import dataclass

from app import terms

_D = datetime.date

# what each kind of source is, for the prompt and the citation title
KIND_LABEL = {
    "campaign": "campaign site",
    "questionnaire": "voter-guide answers",
    "finance": "campaign finance",
    "official": "official record",
    "news": "news",
    "forum": "candidate forum",
}


@dataclass(frozen=True)
class CandidateSource:
    url: str
    publisher: str
    kind: str                        # a KIND_LABEL key
    title: str
    checked: datetime.date
    facts: tuple[str, ...]
    published: datetime.date | None = None


@dataclass(frozen=True)
class Candidate:
    ballot_name: str                 # exactly as printed on the sample ballot
    contest: str                     # 'mayor' | 'city_council' | 'school_board'
    sources: tuple[CandidateSource, ...] = ()
    aliases: tuple[str, ...] = ()    # nicknames, names without middle names
    incumbent: str | None = None     # the seat they hold now, if any
    not_found: tuple[str, ...] = ()  # looked for and not found, as of CHECKED


CONTESTS = {
    # contest key -> (body whose ballot lists it, the contest as printed)
    "mayor": ("city_council", "Mayor (vote for one)"),
    "city_council": ("city_council", "City Council (vote for not more than six)"),
    "school_board": ("school_board", "School Board (vote for not more than five)"),
}

# the office, in a sentence ("running for City Council")
CONTEST_NAME = {"mayor": "Mayor", "city_council": "City Council", "school_board": "School Board"}

# when every not_found list was last swept (the daily update routine bumps
# it); each source keeps its own date, the day its facts were verified
CHECKED = _D(2026, 10, 9)
# the day the first set of sources was verified page by page
_FIRST_VERIFIED = _D(2026, 10, 5)


def _s(url: str, publisher: str, kind: str, title: str, *facts: str,
       published: datetime.date | None = None,
       checked: datetime.date = _FIRST_VERIFIED) -> CandidateSource:
    return CandidateSource(url, publisher, kind, title, checked, facts, published)


_PATCH = "Patch (Fairfax City)"
_VOTE411 = "League of Women Voters (Vote411)"
_GRANICUS = "City of Fairfax boards and commissions"
_CITY = "City of Fairfax"
_COUNCIL_PAGE = "https://www.fairfaxva.gov/Government/Council/Mayor-and-Council-Members/"
_SCHOOLS = "City of Fairfax Schools"

# ---- sources several candidates share: each candidate's entry repeats only
# what the source says about them

_OFFICIAL_LIST = _s(
    "https://patch.com/virginia/fairfaxcity/official-list-fairfax-city-council-mayor-candidates-november-election-released",
    _PATCH, "news", "Official list of Fairfax City Council and mayoral candidates released",
    "Patch reports the list from the City's Office of Elections: two candidates for Mayor, an open "
    "seat (Kirsten Sides Lockhart; Thomas D. \"Tom\" Peterson, a sitting Councilmember).",
    "Eleven candidates for six at-large Council seats: incumbents Stacy R. Hall, Rachel M McQuillen and "
    "Anthony T. Amos, and eight others (Sandi W. Slappey Brown, Kelly M. O'Brien, Russell A. Jones, "
    "Stephen S. Kim, Susan Hartley Kuiler, María José Padmore, Steve S Chang, Jessica L. Lough).",
    "Five candidates for five School Board seats, all incumbents: Carolyn S. Pitches, Amit Sarah "
    "Hickman, Kristina M. Cecere, Sarah M. Kelsey, Lauren A. Bartelme.",
    published=_D(2026, 6, 18))
_SAMPLE_BALLOTS = _s(
    "https://www.fairfaxva.gov/Government/Elections/Sample-Ballots",
    "City of Fairfax Office of Elections", "official", "Sample ballots, November 3, 2026",
    "The City posts the full sample ballot for the November 3, 2026 general and special elections.",
    "Besides the City offices, the ballot carries three proposed state constitutional amendments and "
    "a City retail sales tax referendum.")
_EARLY_VOTING = _s(
    "https://patch.com/virginia/fairfaxcity/early-voting-begins-2026-election-whats-fairfax-city-ballots",
    _PATCH, "news", "Early voting begins for 2026 election: what's on Fairfax City ballots",
    "Patch reports early voting for City voters runs September 18 through October 31 at City Hall, "
    "10455 Armstrong St.",
    "Election Day is November 3, polls open 6 a.m. to 7 p.m.; the registration deadline is October 23.",
    "The City ballot includes Mayor, City Council (up to six), School Board (up to five) and a "
    "question on a retail sales tax of up to 1% for school construction or public transportation.",
    published=_D(2026, 9, 17))
# when and where to vote, for the election page
VOTING = _EARLY_VOTING
_FFXNOW_PREVIEW = _s(
    "https://www.ffxnow.com/2026/09/17/what-to-expect-as-early-voting-for-the-2026-election-kicks-off-friday-in-fairfax/",
    "FFXnow", "news", "What to expect as early voting for the 2026 election kicks off",
    "FFXnow lists the two mayoral candidates, 11 City Council candidates and 5 School Board "
    "candidates, elected on a non-partisan, at-large basis.",
    "FFXnow says the sales tax referendum would allow up to 1%, raising up to $13.5 million for "
    "school construction and long-term maintenance.",
    published=_D(2026, 9, 17))
_FCT_PREVIEW = _s(
    "https://www.fairfaxtimes.com/articles/early-voting-underway-in-fairfax-county/article_b57e37fb-baf4-47d2-83c6-25c9ead75b17.html",
    "Fairfax County Times", "news", "Early voting underway in Fairfax County",
    "The Times describes the mayoral race as planning commissioner Kirsten Sides Lockhart against "
    "Councilmember Thomas Peterson.",
    "Three Council incumbents (Hall, McQuillen, Amos) seek reelection alongside eight challengers; "
    "voters may choose up to six.",
    "The five School Board members are running unopposed.",
    published=_D(2026, 10, 2))
_FORUM = _s(
    "https://patch.com/virginia/fairfaxcity/fairfax-city-candidates-meet-voters-upcoming-election-event",
    _PATCH, "forum", "Fairfax City candidates to meet voters at upcoming election event",
    "A candidate event on Wednesday, September 30, 2026, 7 p.m., at Katherine Johnson Middle School, "
    "organized by the League of Women Voters of the Fairfax Area and the Central Fairfax Chamber of "
    "Commerce.",
    "Mayoral and Council candidates who accepted were to give two-minute opening statements, then "
    "meet voters. The article does not say which candidates accepted; no recording or recap was found.",
    published=_D(2026, 9, 28))
_VOTE411_INDEX = _s(
    "https://onyourballot.vote411.org/race-index.do?c=35886492",
    _VOTE411, "questionnaire", "Vote411 voter guide: City of Fairfax races",
    "The League of Women Voters guide has pages for the Mayor, City Council and School Board races, "
    "with each candidate's answers where they have responded.")
_EARLY_MONEY = _s(
    "https://patch.com/virginia/fairfaxcity/steve-chang-tops-early-fairfax-city-council-fundraising-lockhart-leads-mayors",
    _PATCH, "finance", "Steve Chang tops early Council fundraising; Lockhart leads mayor's race",
    "Contributions and cash on hand for January 1 to June 30, 2026: Lockhart $4,420.00 / $2,273.13; "
    "Peterson's mayoral committee $750.00 / $750.00 (his separate Council committee reported "
    "$6,303.72 raised, $0 on hand).",
    "Council: Chang $21,100.28 raised with $18,166.87 on hand; Amos $10,355.00 / $12,105.49; Hall "
    "$6,616.39 / $3,940.75; McQuillen $3,190.45 / $3,316.16.",
    published=_D(2026, 7, 20))
_COUNCIL_MONEY = _s(
    "https://patch.com/virginia/fairfaxcity/chang-leads-fairfax-city-council-fundraising-candidates-raise-more-98k",
    _PATCH, "finance", "Chang leads Fairfax City Council fundraising as candidates raise more than $98K",
    "Patch's roundup of Council candidates' 2026 contributions through August 31, 2026, from state "
    "campaign finance reports: Chang first ($23,180), Padmore third ($17,394), Kuiler $9,283.71 "
    "across two committees, Lough $3,270.74.",
    published=_D(2026, 10, 5))
_DEMOCRATS = _s(
    "https://patch.com/virginia/fairfaxcity/fairfax-city-democrats-recommend-lockhart-mayor-four-council-candidates",
    _PATCH, "news", "Fairfax City Democrats recommend Lockhart for Mayor, four Council candidates",
    "The Fairfax City Democratic Committee recommended Kirsten Lockhart for Mayor and Council "
    "candidates Anthony Amos, Sandi Slappey Brown, María José Padmore and Kelly O'Brien.",
    "The committee said it evaluated candidates on publicly stated positions, records in office and "
    "alignment with Democratic values; scores were not released.",
    "All candidates appear on the ballot as independents.",
    published=_D(2026, 8, 19))
_COMMON_GROUND = _s(
    "https://patch.com/virginia/fairfaxcity/fairfax-city-candidates-launch-common-ground-campaign-ahead-november-election",
    _PATCH, "news", "Fairfax City candidates launch 'Common Ground' campaign",
    "A 'Common Ground' group of independent candidates: mayoral candidate Tom Peterson and Council "
    "candidates Stacy R. Hall, Rachel McQuillen, Susan Hartley Kuiler, Jessica L. Lough and Steve S. Chang.",
    "Patch says they run individual campaigns but share resources; shared themes include accountable "
    "local government, safe neighborhoods, schools, local businesses, affordability, taxes and the "
    "effects of growth.",
    published=_D(2026, 8, 20))
_FOUR_RECORDS = _s(
    "https://patch.com/virginia/fairfaxcity/how-four-fairfax-candidates-voted-taxes-trails-housing-willard-sherwood",
    _PATCH, "news", "How four Fairfax candidates voted on taxes, trails, housing and Willard-Sherwood",
    "Meals tax increase from 4% to 4.5% (May 2026): Amos and Peterson yes; Hall and McQuillen no.",
    "Willard-Sherwood land-use approvals (October 2025): Amos supported all; Hall and Peterson opposed "
    "all; McQuillen opposed five of six. All four voted for the April 2026 construction authorization.",
    "An added $4.6 million for the George Snyder Trail (January 2026): Amos supported; Hall, "
    "McQuillen and Peterson opposed.",
    "Accessory dwelling unit ordinance (July 2026) and Highlands at Mantua rezoning (September 2026): "
    "Amos and Peterson yes; Hall and McQuillen no.",
    published=_D(2026, 9, 24))
_SB_ABOUT = _s(
    "https://www.cityoffairfaxschools.org/apps/pages/index.jsp?uREC_ID=1663433&type=d&pREC_ID=1812348",
    _SCHOOLS, "official", "About the School Board",
    "The five at-large School Board members are all elected together in even-numbered years; the "
    "next election is November 2026.")
_SB_BIOS = "https://www.cityoffairfaxschools.org/apps/pages/index.jsp?uREC_ID=1663433&type=d&pREC_ID=1812351"
_SB_2024 = _s(
    "https://patch.com/virginia/fairfaxcity/fairfax-city-school-board-election-results-polls-close",
    _PATCH, "news", "5 win 5 seats on Fairfax City School Board; school bond passes",
    "In the November 5, 2024 election all five candidates for the five seats won: Pitches 2,224 votes "
    "(22.13%), Kelsey 2,085 (20.75%), Cecere 1,948 (19.38%), Bartelme 1,829 (18.20%), Hickman 1,805 "
    "(17.96%).",
    published=_D(2024, 11, 5))
_SB_SWORN = _s(
    "https://patch.com/virginia/fairfaxcity/new-fairfax-city-school-board-officially-sworn-city-hall",
    _PATCH, "news", "Fairfax City School Board members sworn in",
    "Bartelme, Cecere, Hickman, Kelsey and Pitches were sworn in at City Hall to serve two-year terms "
    "after the November 2024 election.",
    published=_D(2025, 1, 14))
_DANIELS_RUN = "https://www.ffxnow.com/2026/04/15/fairfax-city-school-board-daniels-run-renovations-wary-of-cost/"

# sources about a whole race rather than one candidate
RACE_SOURCES: dict[str, tuple[CandidateSource, ...]] = {
    "mayor": (_OFFICIAL_LIST, _SAMPLE_BALLOTS, _EARLY_VOTING, _FFXNOW_PREVIEW, _FCT_PREVIEW, _FORUM,
              _VOTE411_INDEX, _EARLY_MONEY, _DEMOCRATS, _COMMON_GROUND, _FOUR_RECORDS),
    "city_council": (_OFFICIAL_LIST, _SAMPLE_BALLOTS, _EARLY_VOTING, _FFXNOW_PREVIEW, _FCT_PREVIEW,
                     _FORUM, _VOTE411_INDEX, _EARLY_MONEY, _COUNCIL_MONEY, _DEMOCRATS, _COMMON_GROUND,
                     _FOUR_RECORDS),
    "school_board": (_OFFICIAL_LIST, _SAMPLE_BALLOTS, _EARLY_VOTING, _FCT_PREVIEW, _FORUM, _VOTE411_INDEX,
                     _SB_ABOUT, _SB_2024, _SB_SWORN),
}

# the same checklist for everyone, so a gap reads as a gap and not as silence
_NO_VOTE411 = "Vote411 (League of Women Voters) answers: listed, not yet responded"
_NO_FORUM = "a recording or recap of the September 30 candidate forum"
_NO_VPAP = "VPAP's campaign finance pages (they could not be read)"
_NO_2026_FINANCE = ("a dated 2026 campaign finance report (VPAP's race page lists small totals but "
                    "could not be read directly; Patch's finance coverage covered Council only)")

CANDIDATES: tuple[Candidate, ...] = (
    # ---------------------------------------------------------------- Mayor
    Candidate(
        "Kirsten Sides Lockhart", "mayor",
        aliases=("Kirsten Lockhart", "Kirsten S. Lockhart"),
        incumbent="Vice Chair of the Planning Commission (appointed by Council)",
        sources=(
            _s("https://lockhartforfairfax.com/", "Lockhart for Fairfax", "campaign",
               "Kirsten Lockhart for Mayor",
               "The campaign site's tagline is \"Leadership with H(e)art\"; it says the City needs "
               "government that engages the community and makes transparent, fact-driven decisions."),
            _s("https://onyourballot.vote411.org/race-detail.do?id=29000195", _VOTE411, "questionnaire",
               "Vote411: Fairfax City Mayor",
               "Her Vote411 bio says she grew up in Fairfax County, worked as a management consultant at "
               "Booz Allen Hamilton, moved to the City in 2017 and was appointed to the Planning "
               "Commission in 2021.",
               "She lists as priorities sustainable budgeting; development in Activity Centers with "
               "transparent review; more resident participation in planning; attracting City staff; and "
               "ties with George Mason University and neighboring jurisdictions.",
               "She lists as qualifications Planning Commission Vice Chair, delegate to the Facade and "
               "Interior Improvement Grant committee, and 20+ years of strategy consulting.",
               "She names as most urgent improving communication between residents and City government "
               "on taxes, homelessness, traffic and immigration."),
            _s("https://patch.com/virginia/fairfaxcity/kirsten-lockhart-puts-communication-center-fairfax-city-mayor-bid",
               _PATCH, "questionnaire", "Kirsten Lockhart puts communication at center of mayor bid",
               "In Patch's questionnaire she says she has worked in management and strategy consulting, "
               "mainly for federal and defense clients, since 2006, and has been a Planning Commissioner "
               "since March 2021.",
               "Education listed: Thomas Jefferson High School for Science and Technology; University of "
               "Virginia.",
               "She names communication as the most pressing issue, between residents and City government "
               "and among residents on development and spending.",
               "She says development decisions should be data-driven, guided by existing planning "
               "documents, and include varied housing types, including affordable units.",
               "She says she has no party affiliation and did not seek endorsements.",
               published=_D(2026, 9, 17)),
            _s("https://fairfax.granicus.com/boards/w/85f2b8dc41dad80d/boards/17650", _GRANICUS, "official",
               "Planning Commission members",
               "The City's roster lists Kirsten S. Lockhart as Planning Commission Vice Chair, term from "
               "March 23, 2021 to December 21, 2029 (as listed)."),
            _s("https://patch.com/virginia/fairfaxcity/how-kirsten-lockhart-voted-seven-fairfax-city-projects-plans",
               _PATCH, "news", "How Kirsten Lockhart voted on seven Fairfax City projects and plans",
               "Patch reviews her Planning Commission votes: for the FY2025-29 capital plan including the "
               "George Snyder Trail (January 2024, 6-0); to recommend denial of the Breezeway Motel / "
               "Fairfax Gardens rezoning (November 2021, 7-0; Council approved it 4-3).",
               "For the Kamp Washington small area plan (October 2022); to recommend approval of the "
               "Fairfax Presbyterian Church plan with 10 affordable townhouses (October 2022); to "
               "recommend WillowWood Phase I with conditions (April 2024, 4-1).",
               "To recommend denial of the Davies Property as not conforming to the comprehensive plan "
               "(June 2025, 4-2; Council approved it 4-3); to recommend the Urban Forest Master Plan "
               "draft (February 2026, 5-0).",
               published=_D(2026, 9, 28)),
            _s("https://patch.com/virginia/fairfaxcity/lockhart-leads-peterson-fairfax-city-mayor-s-race-fundraising-after-30-000",
               _PATCH, "finance", "Lockhart leads Peterson in mayor's race fundraising after $30,000 donation",
               "Through August 31, 2026: $38,535.80 in 2026 contributions, $4,728.79 spent, "
               "$33,807.01 cash on hand.",
               "A $30,000 contribution from one individual donor on August 11 made up about 78% of her "
               "total; other donors named include Fairfax County Supervisor Dalia Palchik and James "
               "Feather ($500 each).",
               published=_D(2026, 9, 29)),
            _s(_DEMOCRATS.url, _PATCH, "news", _DEMOCRATS.title,
               "The Fairfax City Democratic Committee recommended her for Mayor.",
               published=_DEMOCRATS.published),
        ),
        not_found=(_NO_FORUM, "an announcement story or profile outside Patch"),
    ),
    Candidate(
        'Thomas D. "Tom" Peterson', "mayor",
        aliases=("Tom Peterson", "Thomas Peterson", "Thomas D. Peterson"),
        incumbent="City Councilmember (term ends December 31, 2026; not running for reelection to Council)",
        sources=(
            _s("https://tom4fairfax.org/", "Tom Peterson for Mayor", "campaign", "Tom Peterson for Mayor",
               "The campaign site's slogan is \"Caring for Our Community, Creating Confidence in Our Future.\"",
               "The campaign site lists priority areas: cost of living, quality of life and land use, public "
               "safety, sustainability, schools, community engagement and ethics."),
            _s(_COUNCIL_PAGE + "Councilmember-Thomas-D-Peterson", _CITY, "official", "Councilmember Thomas D. Peterson",
               "The City's profile lists him as a Councilmember in his first term; it says he has lived in the City "
               "since 2002 and chaired the Environmental Sustainability Committee from 2022-24.",
               "It says he is founder, president and CEO of the Center for Climate Strategies and an adjunct "
               "professor at Johns Hopkins University and George Mason University.",
               checked=_D(2026, 10, 5)),
            _s("https://tom4fairfax.org/about", "Tom Peterson for Mayor", "campaign", "About Tom",
               "The site says he has lived in the City since 2002, founded and runs a national nonprofit, "
               "and also runs a historic tourist home business.",
               "It says he chaired the City's Environmental Sustainability Committee for three years before "
               "joining Council, and represents the City on several regional planning bodies."),
            _s("https://patch.com/virginia/fairfaxcity/tom-peterson-puts-cost-living-center-fairfax-city-mayor-bid",
               _PATCH, "questionnaire", "Tom Peterson puts cost of living at center of mayor bid",
               "In Patch's questionnaire he gives his age as 67 and says he has lived in the City 24 years "
               "and is a native of Fairfax County.",
               "He lists President and CEO of The Center for Climate Strategies since 2004, and 44 years in "
               "government, business, nonprofit and academic roles including 10 at the EPA.",
               "Education listed: B.S. in biology (William & Mary), a Duke master's in economics and policy, "
               "an MBA (University of Texas at Austin).",
               "He names cost of living and fiscal responsibility as the top issue: closer review of spending, "
               "avoiding excessive debt and unnecessary tax increases.",
               "He supports redevelopment that widens the commercial tax base and housing at various income "
               "levels, and voices concern about the height, density and pace of recent proposals.",
               "As Council results he cites budget reductions, hiring a new City Manager, cutting the "
               "Willard-Sherwood cost to taxpayers by over 55%, and advancing a sales-tax option for school "
               "capital needs.",
               "He says he is unaffiliated and working with other unaffiliated candidates.",
               published=_D(2026, 9, 17)),
            _s(_FOUR_RECORDS.url, _PATCH, "news", _FOUR_RECORDS.title,
               "Patch reports he voted for the meals-tax increase, the accessory dwelling unit ordinance and "
               "the Highlands at Mantua rezoning; opposed all October 2025 Willard-Sherwood approvals but "
               "voted for the April 2026 construction authorization; and opposed the added $4.6 million for "
               "the George Snyder Trail.",
               published=_FOUR_RECORDS.published),
            _s("https://patch.com/virginia/fairfaxcity/lockhart-leads-peterson-fairfax-city-mayor-s-race-fundraising-after-30-000",
               _PATCH, "finance", "Lockhart leads Peterson in mayor's race fundraising after $30,000 donation",
               "His mayoral committee through August 31, 2026: $11,303.10 in contributions, $4,245.45 spent, "
               "$7,057.65 cash on hand. He also has a separate City Council committee, not included.",
               "Donors named include Council candidate Steve Chang and attorney Chap Petersen ($1,000 each).",
               published=_D(2026, 9, 29)),
            _s(_COMMON_GROUND.url, _PATCH, "news", _COMMON_GROUND.title,
               "He is the mayoral candidate in the 'Common Ground' group of independent candidates.",
               published=_COMMON_GROUND.published),
        ),
        not_found=(_NO_VOTE411, _NO_FORUM),
    ),
    # ---------------------------------------------------------------- City Council
    Candidate(
        "Stacy R. Hall", "city_council",
        aliases=("Stacy Hall", "Stacy Renee Hall"),
        incumbent="City Councilmember (term ends December 31, 2026)",
        sources=(
            _s("https://stacyforfairfax.com/", "Stacy for Fairfax", "campaign", "Stacy Hall for City Council",
               "The campaign site says she is a controller for an animal health company, spent nine years as "
               "a public accountant, runs her own accounting and tax business, and has lived in the City "
               "since 2011.",
               "It lists civic roles: City Council (since 2025), School Board (2023-2024), Providence "
               "Elementary PTA president (2019-2022), Environmental Sustainability Committee (2023-2024), "
               "Cobbdale Civic Association treasurer.",
               "The campaign site lists priorities: public safety; environment and green spaces; fiscal "
               "responsibility; transparency; City schools; housing affordability; walkability; small "
               "business support; non-partisan leadership."),
            _s(_COUNCIL_PAGE + "Councilmember-Stacy-R-Hall", _CITY, "official", "Councilmember Stacy R. Hall",
               "The City's profile lists her as a Councilmember in her first term; it says she has lived in the City "
               "since 2011 and served on the School Board from 2023-24, representing it on the Environmental "
               "Sustainability Committee.",
               "It says she works as a controller at ACI Biosciences and has been treasurer of the Cobbdale Civic "
               "Association since 2022.",
               checked=_D(2026, 10, 5)),
            _s("https://onyourballot.vote411.org/race-detail.do?id=4143051", _VOTE411, "questionnaire",
               "Vote411: Fairfax City Council",
               "Her Vote411 bio lists a finance degree, 15+ years as a controller, nine years of PTA "
               "leadership, and service on Council and, before that, the School Board.",
               "She lists as priorities strong schools, safe neighborhoods, reliable services, financial "
               "sustainability and development that fits.",
               "She names rising costs and affordability as most urgent, proposing transparent budgeting, "
               "debt limits, a stronger commercial tax base and appropriately scaled development."),
            _s("https://patch.com/virginia/fairfaxcity/stacy-hall-s-fairfax-city-council-voting-record-taxes-trails-housing-willard",
               _PATCH, "news", "Stacy Hall's Council voting record: taxes, trails, housing and Willard-Sherwood",
               "Patch reports she voted for the FY2025 and FY2027 budgets and against the meals-tax increase "
               "(passed 4-2), saying she understood it was needed to balance the budget.",
               "She supported the July 2026 sales-tax referendum request; opposed all six October 2025 "
               "Willard-Sherwood approvals and supported the April 2026 construction authorization.",
               "She opposed the added $4.6 million for the George Snyder Trail and supported cancelling it; "
               "she opposed the accessory dwelling unit ordinance, the Davies rezoning and Highlands at Mantua.",
               published=_D(2026, 9, 24)),
            _s("https://patch.com/virginia/fairfaxcity/1k-ox-hill-contribution-among-donations-stacy-halls-fairfax-city-council",
               _PATCH, "finance", "$1K Ox Hill contribution among donations to Stacy Hall's campaign",
               "Through August 31, 2026: $7,204.58 in 2026 contributions, $3,259.30 cash on hand, $744.56 "
               "unpaid debt.",
               "Donors named include a $1,000 contribution tied to Ox Hill Companies, former Mayor Steve "
               "Stombres and Council candidate Steve Chang ($500).",
               published=_D(2026, 10, 5)),
            _s(_COMMON_GROUND.url, _PATCH, "news", _COMMON_GROUND.title,
               "She is a Council candidate in the 'Common Ground' group.", published=_COMMON_GROUND.published),
        ),
        not_found=("a 2026 Patch candidate questionnaire", _NO_FORUM),
    ),
    Candidate(
        "Rachel M McQuillen", "city_council",
        aliases=("Rachel McQuillen", "Rachel M. McQuillen"),
        incumbent="City Councilmember (term ends December 31, 2026)",
        sources=(
            _s("https://rachelforfairfax.com/", "Rachel for Fairfax", "campaign", "Rachel McQuillen for City Council",
               "The campaign site lists priorities: affordability and responsible spending; smart, sustainable "
               "growth; resident engagement.",
               "The site shows an endorsement from Moms Demand Action."),
            _s(_COUNCIL_PAGE + "Councilmember-Rachel-M-McQuillen", _CITY, "official", "Councilmember Rachel M. McQuillen",
               "The City's profile lists her as a Councilmember in her first term; it describes her as a 14-year "
               "City resident who served on the School Board from 2023-24, representing it on the Parks and "
               "Recreation Advisory Board.",
               "It says she worked in accounting and finance before launching a dog training and pet care service "
               "in 2018, and holds officer roles in the Rotary Club of Fairfax.",
               checked=_D(2026, 10, 5)),
            _s("https://onyourballot.vote411.org/race-detail.do?id=4143051", _VOTE411, "questionnaire",
               "Vote411: Fairfax City Council",
               "She lists as priorities affordability and responsible spending, schools and public safety, the "
               "local economy, housing and redevelopment, safer transportation and the environment.",
               "She lists as qualifications small-business ownership, past School Board and current Council "
               "service, 10 years with the Providence PTA and more than a decade in accounting and finance.",
               "She names the City becoming more expensive to live in as most urgent, citing the citywide "
               "efficiency audit she pushed for, a stronger commercial tax base, attainable housing and closer "
               "scrutiny of major projects' lifetime cost.",
               checked=_D(2026, 10, 5)),
            _s("https://patch.com/virginia/fairfaxcity/rachel-mcquillen-puts-growth-rising-costs-center-fairfax-city-council",
               _PATCH, "questionnaire", "Rachel McQuillen puts growth, rising costs at center of reelection bid",
               "In Patch's questionnaire she gives her age as 45 and says she has lived in the City since 2010.",
               "Education listed: A.S. in business administration (NOVA); B.S. in marketing (George Mason). "
               "She owns a dog training and pet care business and lists 10+ years in accounting and finance.",
               "She lists City Council since January 2025, past School Board service, past Parks and Recreation "
               "Advisory Board service, and the Move Fairfax City steering committee.",
               "She names managing growth and rising costs as the central issue, proposing a citywide "
               "efficiency audit, cost transparency, long-term financial planning, faster permitting, "
               "down-payment assistance and workforce housing.",
               "She says she has never sought or received a party endorsement.",
               published=_D(2026, 9, 16)),
            _s(_FOUR_RECORDS.url, _PATCH, "news", _FOUR_RECORDS.title,
               "Patch reports she voted against the meals-tax increase, the accessory dwelling unit ordinance "
               "and Highlands at Mantua; opposed five of six October 2025 Willard-Sherwood approvals and voted "
               "for the April 2026 construction authorization; and opposed the added $4.6 million for the "
               "George Snyder Trail.",
               published=_FOUR_RECORDS.published),
            _s("https://patch.com/virginia/fairfaxcity/mcquillen-raises-4-6k-2026-fairfax-city-council-campaign",
               _PATCH, "finance", "McQuillen raises $4.6K in 2026 Council campaign",
               "January 1 to August 31, 2026: $4,640.45 in contributions, $2,448.71 cash on hand, no debts.",
               "Donors named include former Mayor Steve Stombres and Council candidate Steve Chang ($500 each).",
               "Patch reports she spent $750 on ads in a paper owned by Council candidate Steve Chang.",
               published=_D(2026, 10, 5)),
            _s(_COMMON_GROUND.url, _PATCH, "news", _COMMON_GROUND.title,
               "She is a Council candidate in the 'Common Ground' group.", published=_COMMON_GROUND.published),
        ),
        not_found=(_NO_FORUM,),
    ),
    Candidate(
        "Anthony T. Amos", "city_council",
        aliases=("Anthony Amos",),
        incumbent="City Councilmember (term ends December 31, 2026)",
        sources=(
            _s("https://www.anthonytamos.org/", "Friends of Anthony Amos", "campaign",
               "Anthony Amos for City Council",
               "The campaign site's slogan is \"Keeping Fairfax Moving Forward\"; the home page describes his "
               "military-family background and has accomplishments and issues sections."),
            _s(_COUNCIL_PAGE + "Councilmember-Anthony-T-Amos", _CITY, "official", "Councilmember Anthony T. Amos",
               "The City's profile lists him as a Councilmember in his first term; it says he was the City's "
               "representative on the Fairfax Campus and Community Advisory Board in 2024.",
               "It says he is a Development Associate with the Michaels Organization and previously worked as a "
               "legislative and community outreach aide for the Fairfax County Board of Supervisors.",
               checked=_D(2026, 10, 5)),
            _s("https://onyourballot.vote411.org/race-detail.do?id=4143051", _VOTE411, "questionnaire",
               "Vote411: Fairfax City Council",
               "His Vote411 bio says he grew up in a military family, raised in Germany, Missouri and Hawaii.",
               "He lists as qualifications City Council, co-leading the Move Fairfax steering committee, "
               "representing the City on finance, water and air quality committees, and a master's in "
               "public policy from George Mason.",
               "He names affordability in housing, taxes and jobs as most urgent, proposing dedicated housing "
               "trust fund revenue, home-sharing guidelines, childcare coordination and job upskilling."),
            _s("https://patch.com/virginia/fairfaxcity/anthony-amos-favors-case-case-development-reviews-fairfax-city-council-bid",
               _PATCH, "questionnaire", "Anthony Amos favors case-by-case development reviews",
               "In Patch's questionnaire he gives his age as 28 and says he is the first African American man "
               "elected to the Council in over 50 years.",
               "He has worked for The Michaels Organization (affordable housing development) since January "
               "2025; he lists a master's in public policy (George Mason) and bachelor's degrees in political "
               "science and sociology.",
               "He lists a state appointment to the Charitable Gaming Board and regional committee seats.",
               "He favors case-by-case review of development proposals and public-private investment, and "
               "lists affordability, business development, childcare and public safety among priorities.",
               published=_D(2026, 9, 9)),
            _s(_FOUR_RECORDS.url, _PATCH, "news", _FOUR_RECORDS.title,
               "Patch reports he voted for the meals-tax increase, the accessory dwelling unit ordinance and "
               "Highlands at Mantua; supported all October 2025 Willard-Sherwood approvals and the April 2026 "
               "construction authorization; and supported the added $4.6 million for the George Snyder Trail "
               "and opposed cancelling it.",
               published=_FOUR_RECORDS.published),
            _s("https://patch.com/virginia/fairfaxcity/5k-donation-helps-amos-raise-nearly-21k-2026-fairfax-city-council-campaign",
               _PATCH, "finance", "$5K donation helps Amos raise nearly $21K in 2026",
               "January 1 to August 31, 2026: $20,912.50 in contributions, $5,286.96 spent, $20,136.67 cash "
               "on hand, no loans or debts.",
               "The largest was a $5,000 contribution from an individual donor; business donors named include "
               "Landmark Atlantic Holdings and Great American Restaurants ($1,000 each).",
               published=_D(2026, 10, 5)),
            _s(_DEMOCRATS.url, _PATCH, "news", _DEMOCRATS.title,
               "He is one of four Council candidates the Fairfax City Democratic Committee recommended.",
               published=_DEMOCRATS.published),
        ),
        not_found=(_NO_FORUM,),
    ),
    Candidate(
        "Sandi W. Slappey Brown", "city_council",
        aliases=("Sandi Slappey Brown", "Sandra Slappey Brown", "Sandi Brown"),
        sources=(
            _s("https://www.ssb4ffx.com/meet-sandi", "Sandi Slappey Brown for Fairfax", "campaign", "Meet Sandi",
               "The campaign site says she moved to the City in 2018 and grew up overseas, in seven countries.",
               "It describes her as a social worker whose work has included child welfare, mental health, "
               "homeless services and juvenile justice, mostly in local government, plus seven years with a "
               "social services consulting firm.",
               "It lists a B.S.W. (George Mason), an M.S.W. (Catholic University), a master's in "
               "industrial/organizational psychology (George Mason) and PMP certification."),
            _s("https://www.ssb4ffx.com/my-priorities", "Sandi Slappey Brown for Fairfax", "campaign",
               "My Priorities",
               "The campaign site lists an Old Town priority: replacing parking with businesses, adding public "
               "art and pedestrian space, possibly closing some streets to cars.",
               "It lists timely completion of the Willard-Sherwood health and recreation center.",
               "It lists more diverse and affordable housing options, including accessory dwelling units.",
               "It lists moving to staggered, longer terms for the six Council seats."),
            _s("https://onyourballot.vote411.org/race-detail.do?id=4143051", _VOTE411, "questionnaire",
               "Vote411: Fairfax City Council",
               "In her Vote411 answers she lists as priorities redevelopment of aging sites into mixed-use "
               "spaces, housing across income levels, and building trust in government, including possible "
               "charter changes to Council term length and mayoral authority.",
               "She names development as most urgent and proposes zoning ordinance amendments to state City "
               "requirements and developer incentives up front."),
            _s("https://patch.com/virginia/fairfaxcity/sandi-slappey-brown-sees-taxes-city-services-key-fairfax-city-council",
               _PATCH, "questionnaire", "Sandi Slappey Brown sees taxes, City services as key Council challenges",
               "In Patch's questionnaire she gives her age as 59 and her occupation as a social work manager "
               "with 38 years in the field, mostly in local government.",
               "She says rising taxes and the cost of City services are among the biggest challenges, and calls "
               "for widening the commercial tax base to rely less on real estate taxes.",
               "She supports a mix of market-rate, attainable and affordable housing.",
               "Patch lists her service as a chief or assistant chief election officer (2006-2026) and as the "
               "City's representative to the Fairfax-Falls Church Community Services Board (2020-2023).",
               published=_D(2026, 9, 14)),
            _s("https://fairfax.granicus.com/boards/w/85f2b8dc41dad80d/members/1581957", _GRANICUS, "official",
               "Member record: Sandra Slappey Brown",
               "The City's boards record lists Sandra Slappey Brown on the Fairfax-Falls Church Community "
               "Services Board from September 8, 2020 to September 8, 2023."),
            _s("https://patch.com/virginia/fairfaxcity/slappey-brown-raises-more-8k-fairfax-city-council-campaign",
               _PATCH, "finance", "Slappey Brown raises more than $8K in Council campaign",
               "Through August 31, 2026: $8,173 in contributions plus $3,450 in loans, $6,030.44 spent, "
               "$4,142.56 cash on hand.",
               "Donors named include former Councilmember Janice Miller.",
               published=_D(2026, 10, 5)),
            _s(_DEMOCRATS.url, _PATCH, "news", _DEMOCRATS.title,
               "She is one of four Council candidates the Fairfax City Democratic Committee recommended.",
               published=_DEMOCRATS.published),
        ),
        not_found=(_NO_FORUM, "any earlier run for office"),
    ),
    Candidate(
        "Kelly M. O'Brien", "city_council",
        aliases=("Kelly O'Brien", "Kelly OBrien"),
        sources=(
            _s("https://www.kellyobrienforfairfax.com", "Kelly O'Brien for Fairfax", "campaign",
               "Kelly O'Brien for City Council",
               "The campaign site says she is a planner with 20+ years in local government, spent seven years "
               "in the City's planning department, and is Deputy Director of Planning and Zoning for the Town "
               "of Vienna.",
               "It lists Vice Chair of the Parks and Recreation Advisory Board, the Old Town Fairfax Business "
               "Association board, organizing Asian Festival on Main, and creating Fairfax411.",
               "The campaign site lists three priorities: smart growth and responsible planning; good "
               "governance and listening to the community; supporting local businesses.",
               "In the site's Q&A she says zoning should align with the adopted Small Area Plans, read as "
               "long-range guides rather than quotas, and supports more housing choices including accessory "
               "dwelling units, townhomes and condos in appropriate places.",
               "She supports keeping the CUE bus fare-free while monitoring it, and says she would review new "
               "initiatives before raising taxes."),
            _s("https://onyourballot.vote411.org/race-detail.do?id=4143051", _VOTE411, "questionnaire",
               "Vote411: Fairfax City Council",
               "Her Vote411 bio lists a master's in city and regional planning (Rutgers), AICP certification "
               "and the Certified Zoning Administrator credential.",
               "She lists as priorities planning for growth, local businesses, infrastructure that keeps pace "
               "with development, and more transparent government.",
               "She names as most urgent building trust among Council members and between City government "
               "and the community."),
            _s("https://patch.com/virginia/fairfaxcity/kelly-o-brien-targets-development-uncertainty-fairfax-city-council-bid",
               _PATCH, "questionnaire", "Kelly O'Brien seeks more predictable development",
               "In Patch's questionnaire she gives her age as 47, says this is her first run for office and "
               "that she has lived in the City 15+ years.",
               "She names uncertainty over growth and development as the most pressing issue, proposing to "
               "align the zoning ordinance with adopted Small Area Plans.",
               "She says special exceptions should be exceptional rather than routine, with redevelopment "
               "concentrated in designated growth areas.",
               published=_D(2026, 9, 14)),
            _s("https://fairfax.granicus.com/boards/w/85f2b8dc41dad80d/boards/17648", _GRANICUS, "official",
               "Park and Recreation Advisory Board",
               "The City's roster lists Kelly M. O'Brien as a member in her second term, March 22, 2022 to "
               "March 22, 2028, appointed by Council."),
            _s("https://patch.com/virginia/fairfaxcity/kelly-o-brien-raises-8-4k-fairfax-city-council-campaign",
               _PATCH, "finance", "Kelly O'Brien raises $8.4K in Council campaign",
               "Through August 31, 2026: $8,417.21 in contributions (including $2,036.69 in-kind), $7,996.55 "
               "spent, $425.66 cash on hand, no loans or debts.",
               "Donors named include Mayor Catherine Read and Councilmember Stacey Hardy-Chandler ($105.75 "
               "each) and former Councilmember Janice Miller ($250).",
               published=_D(2026, 10, 5)),
            _s("https://m.connectionnewspapers.com/news/2024/apr/10/honoring-fairfax-city-women-making-a-difference/",
               "Connection Newspapers", "news", "Honoring Fairfax City women making a difference",
               "Connection reports she received a 2024 Women of Influence award from the City's Commission for "
               "Women, and worked on the 'Mason to Metro' bicycle plan as a City planner.",
               published=_D(2024, 4, 10)),
            _s(_DEMOCRATS.url, _PATCH, "news", _DEMOCRATS.title,
               "She is one of four Council candidates the Fairfax City Democratic Committee recommended.",
               published=_DEMOCRATS.published),
        ),
        not_found=(_NO_FORUM,),
    ),
    Candidate(
        "Russell A. Jones", "city_council",
        aliases=("Russell Jones", "Russ Jones"),
        sources=(
            _s("https://jones4fairfax.com", "Russell Jones for City Council", "campaign",
               "Russell Jones for City Council",
               "The campaign site describes him as a business owner with 20+ years in contracting and "
               "government work.",
               "It lists tax reduction, budget transparency and cutting wasteful spending, citing a 100% "
               "property tax increase over six years and a projected 75% rise by 2030."),
            _s("https://jones4fairfax.com/meet_russell", "Russell Jones for City Council", "campaign", "Meet Russell",
               "The site says he has lived in the City over 40 years, owns a home and a small business, and "
               "serves on the Board of Zoning Appeals."),
            _s("https://jones4fairfax.com/issues", "Russell Jones for City Council", "campaign", "Issues",
               "The site lists concern about tax increases for long-time residents on fixed incomes and about "
               "rising population density.",
               "It says \"We need to stop spending\" and that budget cuts are feasible.",
               "It lists homelessness as a concern and says funding alone will not resolve it."),
            _s("https://patch.com/virginia/fairfaxcity/russell-jones-puts-tax-increases-center-fairfax-city-council-bid",
               _PATCH, "questionnaire", "Russell Jones puts fighting tax increases at center of Council bid",
               "In Patch's questionnaire he gives his age as 64 and describes himself as a 40-year City "
               "resident, a retired government employee and remodeling contractor, and a Board of Zoning "
               "Appeals member.",
               "He calls tax increases the most pressing issue and says spending should stay within the budget.",
               "He urges caution on new development and redevelopment.",
               published=_D(2026, 9, 14)),
            _s("https://fairfax.granicus.com/boards/w/85f2b8dc41dad80d/boards/17627", _GRANICUS, "official",
               "Board of Zoning Appeals",
               "The City's roster lists Russell A. Jones as a member in his second term, May 25, 2021 to May 25, "
               "2030, appointed by the Court."),
            _s("https://patch.com/virginia/fairfaxcity/russell-jones-reports-no-contributions-fairfax-city-council-campaign-through",
               _PATCH, "finance", "Russell Jones reports no contributions through August",
               "His committee reported $0 in contributions and loans from January 23 to August 31, 2026, with "
               "$89.50 cash on hand.",
               published=_D(2026, 10, 5)),
        ),
        not_found=(_NO_VOTE411, _NO_FORUM, "any earlier run for office"),
    ),
    Candidate(
        "Stephen S. Kim", "city_council",
        aliases=("Stephen Kim", "Steve Kim"),
        sources=(
            _s("https://patch.com/virginia/fairfaxcity/stephen-kim-reports-no-contributions-fairfax-city-council-campaign",
               _PATCH, "finance", "Stephen Kim reports no contributions in Council campaign",
               "Patch reports his committee, Friends of Stephen Kim, was set up in February 2026 for an "
               "independent run for City Council.",
               "Through August 31, 2026: $0 in contributions, $300 in loans from the candidate, $66 spent on "
               "voter data lists, $234 cash on hand.",
               published=_D(2026, 10, 5)),
        ),
        not_found=(
            "a campaign website",
            "a Patch candidate questionnaire",
            _NO_VOTE411,
            "any City board or commission service",
            "any stated occupation, years in the City or biography",
            _NO_FORUM,
        ),
    ),
    Candidate(
        "Susan Hartley Kuiler", "city_council",
        aliases=("Susan Kuiler", "Susan H. Kuiler"),
        sources=(
            _s("https://kuiler4fairfax.com/", "Kuiler for Fairfax City Council", "campaign", "Susan Hartley Kuiler",
               "The campaign site describes her as an independent candidate and lists accountable leadership, "
               "transparent governance, fiscal responsibility and community-informed decisions."),
            _s("https://kuiler4fairfax.com/about/", "Kuiler for Fairfax City Council", "campaign", "About Susan",
               "The site says she has lived in the City for more than 39 years.",
               "It says she worked about 40 years in software development, program management and capital "
               "planning, including disaster response and recovery systems for FEMA.",
               "It lists president of the Cambridge Station Homeowners Association, the board of Friends of "
               "Accotink Creek, the Fairfax Rotary Club, and the Parks and Recreation Advisory Board."),
            _s("https://kuiler4fairfax.com/priorities/", "Kuiler for Fairfax City Council", "campaign", "Priorities",
               "The campaign site lists seven priorities: vibrant community; safe and connected; responsible "
               "growth; collaborative government; economic growth; environmental stewardship; excellent schools.",
               "It says development decisions should weigh infrastructure capacity and community input, and "
               "residents should be engaged before plans are final."),
            _s("https://patch.com/virginia/fairfaxcity/susan-hartley-kuiler-targets-growth-small-town-character-fairfax-council-bid",
               _PATCH, "questionnaire", "Susan Hartley Kuiler targets growth, small-town character in Council bid",
               "In Patch's questionnaire she says the biggest challenge is managing population and economic "
               "growth without losing the City's natural resources and small-town character.",
               "She favors targeted redevelopment, faster approvals, flexible mixed-use policies, small business "
               "support and infrastructure investment.",
               "Education listed: B.A. (Oakland University), PMP certification, a graduate certificate in "
               "software engineering administration (Central Michigan University).",
               published=_D(2026, 9, 15)),
            _s("https://fairfax.granicus.com/boards/w/85f2b8dc41dad80d/boards/17648", _GRANICUS, "official",
               "Park and Recreation Advisory Board",
               "The City's roster lists Susan H. Kuiler as a member in her first term, June 10, 2025 to June 10, "
               "2028, appointed by Council."),
            _s("https://patch.com/virginia/fairfaxcity/fairfax-city-elections-2-council-candidates-tied-read-re-elected",
               _PATCH, "news", "Fairfax City elections: Read re-elected",
               "In the November 2024 mayoral election Patch reports Mayor Catherine Read was re-elected with "
               "7,710 votes (57.06%) and challenger Susan Hartley Kuiler received 5,175 (42.12%).",
               published=_D(2024, 11, 6)),
            _s("https://patch.com/virginia/fairfaxcity/susan-hartley-kuiler-reports-4-465-raised-fairfax-city-council-campaign",
               _PATCH, "finance", "Chang, Petersen among donors to Kuiler's Council campaign",
               "Her Council committee raised $4,465 through August 31, 2026, with $2,016.93 cash on hand and "
               "no debt.",
               "Patch says an earlier committee registered for a mayoral run took $4,818.71 of her own money in "
               "early 2026, repaid $6,000 in loans and closed with no money and no debt; she then formed the "
               "Council committee.",
               "Donors named include Council candidate Steve Chang and his committee ($1,500 combined) and "
               "former state Senator Chap Petersen ($800).",
               published=_D(2026, 10, 5)),
            _s(_COMMON_GROUND.url, _PATCH, "news", _COMMON_GROUND.title,
               "She is a Council candidate in the 'Common Ground' group.", published=_COMMON_GROUND.published),
        ),
        not_found=(_NO_VOTE411, _NO_FORUM),
    ),
    Candidate(
        "María José Padmore", "city_council",
        aliases=("Maria Jose Padmore", "Maria Padmore", "María Padmore"),
        sources=(
            _s("https://www.mariajosepadmore.com/", "Friends of María José Padmore", "campaign",
               "María José Padmore for City Council",
               "The bilingual campaign site describes her as a multicultural, multilingual community leader who "
               "came to the United States in 1990 and settled in Fairfax City in 2002.",
               "It says her career has bridged communities and public systems, including people facing "
               "language barriers, and that she advocates for equitable access to services, opportunities and "
               "representation.",
               "The site has no separate issues page and does not name an occupation or employer."),
            _s("https://www.mariajosepadmore.com/endorsements", "Friends of María José Padmore", "campaign",
               "Endorsements",
               "The endorsements page lists SEIU and current and former officials including Michelle "
               "Maldonado, Elizabeth Guzman, and Fairfax County Supervisors Andres Jimenez and Walter "
               "Alcorn."),
            _s("https://patch.com/virginia/fairfaxcity/democratic-officials-among-donors-padmore-raises-17-4k-fairfax-city-council",
               _PATCH, "finance", "Democratic officials among donors as Padmore raises $17.4K",
               "Through August 31, 2026: $17,394 in contributions, $14,027.65 cash on hand, $500 unpaid debt.",
               "Donors named include SEIU Virginia 512 ($5,000), Michelle Maldonado ($1,750) and Mason "
               "District Supervisor Andres Jimenez ($1,000).",
               published=_D(2026, 10, 5)),
            _s(_DEMOCRATS.url, _PATCH, "news", _DEMOCRATS.title,
               "She is one of four Council candidates the Fairfax City Democratic Committee recommended.",
               published=_DEMOCRATS.published),
        ),
        not_found=(
            "a Patch candidate questionnaire",
            _NO_VOTE411,
            "any stated occupation or education",
            "any City board or commission service",
            _NO_FORUM,
        ),
    ),
    Candidate(
        "Steve S Chang", "city_council",
        aliases=("Steve Chang", "Steve S. Chang", "Steven Chang"),
        sources=(
            _s("https://chang4fairfax.com/about/", "Chang4Fairfax", "campaign", "About Steve Chang",
               "The campaign site says he and his family have been part of the City community for more than "
               "seven years.",
               "It says he pursued doctoral studies in theoretical particle physics at the University of "
               "Maryland and later studied at Southeastern Baptist Theological Seminary.",
               "It says he started businesses including a jewelry store and an IT company, founded Global "
               "Mission Church of Virginia, and is majority owner and CEO of The Independent News Press."),
            _s("https://chang4fairfax.com/priorities/", "Chang4Fairfax", "campaign", "Priorities",
               "The campaign site lists five priorities: community-driven leadership; fiscal responsibility "
               "and effective government; local businesses and economic growth; the environment and quality "
               "of life; safe neighborhoods."),
            _s("https://patch.com/virginia/fairfaxcity/fairfax-city-council-candidate-steve-chang-calls-greater-fiscal-discipline",
               _PATCH, "questionnaire", "Steve Chang calls for greater fiscal discipline",
               "In Patch's questionnaire he gives his age as 67 and says he has held no prior office.",
               "He names keeping the City's finances healthy while holding living costs and local taxes "
               "manageable as the biggest challenge.",
               "He calls for closer scrutiny of major capital projects, budget transparency and efficiency "
               "before raising taxes or fees, and development aligned with the Comprehensive Plan.",
               published=_D(2026, 9, 16)),
            _s("https://patch.com/virginia/fairfaxcity/20k-construction-company-donation-drives-changs-fairfax-city-council",
               _PATCH, "finance", "$20K construction company donation drives Chang's fundraising",
               "Through August 31, 2026: $23,180 raised and $17,304.82 cash on hand.",
               "Solid Construction Inc. of Fairfax gave $20,000 on April 7, about 86% of his contributions; "
               "former state Senator Chap Petersen is among other donors named.",
               "Patch reports his campaign paid The Independent News Press, which he owns, $2,000 for advertising.",
               published=_D(2026, 10, 5)),
            _s(_COMMON_GROUND.url, _PATCH, "news", _COMMON_GROUND.title,
               "He is a Council candidate in the 'Common Ground' group.", published=_COMMON_GROUND.published),
        ),
        not_found=(_NO_VOTE411, "any City board or commission service", _NO_FORUM),
    ),
    Candidate(
        "Jessica L. Lough", "city_council",
        aliases=("Jessica Lough",),
        sources=(
            _s("https://jessicaforfairfax.com/", "Lough for Fairfax", "campaign", "Jessica for Fairfax",
               "The campaign site lists evidence-based, non-partisan governance; fiscal responsibility; "
               "environmental action (including phasing out gas leaf blowers); middle-income housing and small "
               "business support; a binding Council code of ethics; and engaging renters, young adults and "
               "long-time residents."),
            _s("https://jessicaforfairfax.com/aboutjessica", "Lough for Fairfax", "campaign", "About Jessica",
               "The site says she and her family have lived in the City since 2020.",
               "It says she holds bachelor's and master's degrees in atmospheric sciences from the University "
               "of Michigan and has spent 20 years in the U.S. government and in program and leadership roles "
               "at Fortune 50 companies.",
               "It says she serves on the board of Earth League International, a nonprofit focused on "
               "endangered species."),
            _s("https://patch.com/virginia/fairfaxcity/jessica-lough-targets-fiscal-management-fairfax-city-council-bid",
               _PATCH, "questionnaire", "Jessica Lough targets taxes, spending in Council bid",
               "In Patch's questionnaire she gives her age as 43 and her occupation as a strategy and global "
               "operations leader, with 20+ years at companies including Amazon, Meta and Google; this is her "
               "first run for office.",
               "She names responsible fiscal management as the most pressing issue, saying the City should show "
               "it uses existing resources well before asking taxpayers for more.",
               "She proposes a 10-year plan with accountability metrics, reviewing whether programs produce "
               "results, and widening the commercial tax base.",
               published=_D(2026, 9, 15)),
            _s("https://patch.com/virginia/fairfaxcity/jessica-lough-raises-3-3k-fairfax-city-council-campaign",
               _PATCH, "finance", "Jessica Lough raises $3.3K in Council campaign",
               "June 12 to August 31, 2026: $3,270.74 in contributions, $2,717.54 spent, $769.09 cash on hand, "
               "$215.89 owed on loans from the candidate.",
               "Donors named include Council candidate Steve Chang and former Mayor Steve Stombres ($500 each).",
               published=_D(2026, 10, 5)),
            _s(_COMMON_GROUND.url, _PATCH, "news", _COMMON_GROUND.title,
               "She is a Council candidate in the 'Common Ground' group.", published=_COMMON_GROUND.published),
        ),
        not_found=(_NO_VOTE411, "any City board or commission service", _NO_FORUM),
    ),
    # ---------------------------------------------------------------- School Board
    # all five are incumbents running unopposed for the five seats; little has
    # been published for 2026, so their 2024 answers are kept and labelled
    Candidate(
        "Carolyn S. Pitches", "school_board",
        aliases=("Carolyn Pitches",),
        incumbent="School Board Chair",
        sources=(
            _s(_SB_BIOS, _SCHOOLS, "official", "School Board bios",
               "The School Board's bio lists her as Chair, in her eighth term, chair since 2018 after six years "
               "as vice chair.",
               "It says she is a math specialist at Flint Hill School with 28 years of teaching, holds degrees "
               "from Virginia Tech and George Mason, and has lived in the City since 1999.",
               "It lists her as the board's representative to the Washington Area Boards of Education."),
            _s("https://patch.com/virginia/fairfaxcity/carolyn-pitches-runs-fairfax-city-school-board-candidate-profile",
               _PATCH, "questionnaire", "Carolyn Pitches runs for School Board (2024 candidate profile)",
               "In Patch's 2024 questionnaire (the previous election) she said she does not align with a "
               "political party and education should not be politicized.",
               "Her 2024 priorities: facility modernization and security, learning loss and student wellness, "
               "elementary school renovations and the high school roof replacement.",
               published=_D(2024, 8, 30)),
            _s(_DANIELS_RUN, "FFXnow", "news", "School Board weighs adding to Daniels Run renovations",
               "FFXnow reports she voiced reservations about the Daniels Run Elementary renovation as planned, "
               "citing HVAC and space, and proposed exploring a larger addition.",
               published=_D(2026, 4, 15)),
        ),
        not_found=("a 2026 campaign website", _NO_VOTE411, "a 2026 news questionnaire", _NO_2026_FINANCE),
    ),
    Candidate(
        "Amit Sarah Hickman", "school_board",
        aliases=("Amit Hickman", "Amit S. Hickman"),
        incumbent="School Board member",
        sources=(
            _s(_SB_BIOS, _SCHOOLS, "official", "School Board bios",
               "The School Board's bio page lists her as Vice Chair in her second term (the board's May 2026 "
               "minutes name Kristina Cecere as Vice Chair).",
               "It says she is education director for a local non-profit early childhood program and an "
               "outpatient mental health clinician, with master's degrees in education and social work from "
               "George Mason.",
               "It lists past Daniels Run Elementary PTA leadership and membership of the City Neighborhood "
               "Readiness Team."),
            _s("https://onyourballot.vote411.org/race-detail.do?id=68964635", _VOTE411, "questionnaire",
               "Vote411: Fairfax City School Board",
               "Her Vote411 bio describes her as a parent of three, longtime educator and clinical social "
               "worker in the City.",
               "She lists as priorities schools where every student is known, supported and challenged, and "
               "responsible planning for the future.",
               "She cites 20+ years working with children and families and master's degrees in early "
               "childhood education and social work from George Mason.",
               "She names as most urgent planning thoughtfully for students' immediate and long-term needs."),
            _s("https://patch.com/virginia/fairfaxcity/amit-hickman-running-fairfax-city-school-board-candidate-profile",
               _PATCH, "questionnaire", "Amit Hickman runs for School Board (2024 candidate profile)",
               "In Patch's 2024 questionnaire (the previous election) she called elementary school renovation "
               "her single most pressing issue and supported the 2024 bond referendum.",
               published=_D(2024, 8, 30)),
            _s(_DANIELS_RUN, "FFXnow", "news", "School Board weighs adding to Daniels Run renovations",
               "FFXnow reports she supported continuing the superintendent's Daniels Run renovation plan while "
               "acknowledging possible added expense.",
               published=_D(2026, 4, 15)),
        ),
        not_found=("a 2026 campaign website (a campaign Facebook page is linked from Vote411)",
                   "a 2026 news questionnaire", _NO_2026_FINANCE),
    ),
    Candidate(
        "Kristina M. Cecere", "school_board",
        aliases=("Kristina Cecere",),
        incumbent="School Board Vice Chair (per the board's May 2026 minutes)",
        sources=(
            _s("https://www.cecere4fairfax.com", "Cecere for School Board", "campaign", "Cecere for School Board",
               "The campaign site says she is running for a second term, is a former Fairfax High School "
               "teacher with two children in City schools, and was the first in her family to graduate "
               "from college."),
            _s("https://www.cecere4fairfax.com/priorities", "Cecere for School Board", "campaign", "Priorities",
               "The campaign site lists three priorities: a safe and secure learning environment; a stronger "
               "school-community relationship; the teacher pipeline and retention, including partnering with "
               "local colleges."),
            _s(_SB_BIOS, _SCHOOLS, "official", "School Board bios",
               "The School Board's bio lists her in her first term; she is an evaluation specialist with "
               "Arlington Public Schools and taught math at Fairfax High School for over a decade.",
               "It lists a master's in education (George Mason) and a Master of Public Policy and education "
               "finance certificate (Georgetown)."),
        ),
        not_found=(_NO_VOTE411, "a 2026 news questionnaire", _NO_2026_FINANCE),
    ),
    Candidate(
        "Sarah M. Kelsey", "school_board",
        aliases=("Sarah Kelsey",),
        incumbent="School Board member",
        sources=(
            _s(_SB_BIOS, _SCHOOLS, "official", "School Board bios",
               "The School Board's bio lists her in her second term; she is a preschool teacher who previously "
               "taught elementary and special education for ten years in Kansas City, Missouri.",
               "It lists degrees from Northwest Missouri State and the University of Kansas, and past roles with "
               "the Mosby Woods Community Association and Providence Elementary PTA."),
            _s("https://patch.com/virginia/fairfaxcity/2022-candidate-profile-sarah-kelsey-fairfax-city-school-board",
               _PATCH, "questionnaire", "Sarah Kelsey for School Board (2022 candidate profile)",
               "In Patch's 2022 questionnaire she named timely completion of school improvement projects as her "
               "primary concern.",
               published=_D(2022, 10, 17)),
            _s(_DANIELS_RUN, "FFXnow", "news", "School Board weighs adding to Daniels Run renovations",
               "FFXnow quotes her calling the renovation designs a 'Band-Aid' that would need fixing later.",
               published=_D(2026, 4, 15)),
        ),
        not_found=("a 2026 campaign website", _NO_VOTE411, "a 2026 news questionnaire", _NO_2026_FINANCE),
    ),
    Candidate(
        "Lauren A. Bartelme", "school_board",
        aliases=("Lauren Bartelme",),
        incumbent="School Board member",
        sources=(
            _s(_SB_BIOS, _SCHOOLS, "official", "School Board bios",
               "The School Board's bio lists her in her first term, with a background in science and math "
               "teaching in Baltimore and Fairfax County and as a Teach for America member.",
               "It lists a B.S. in physics (UNC Chapel Hill) and a master's in teaching (Johns Hopkins), "
               "and says she has lived in the City since 2009."),
            _s("https://patch.com/virginia/fairfaxcity/lauren-bartelme-runs-fairfax-city-school-board-candidate-profile",
               _PATCH, "questionnaire", "Lauren Bartelme runs for School Board (2024 candidate profile)",
               "In Patch's 2024 questionnaire (the previous election) she named teacher recruitment and "
               "retention as the most pressing issue for the schools.",
               "She supported the 2024 bond referendum and pledged to advocate for special education, English "
               "learners and twice-exceptional students.",
               published=_D(2024, 9, 10)),
        ),
        not_found=("a campaign website", _NO_VOTE411, "a 2026 news questionnaire", _NO_2026_FINANCE,
                   "2026 news coverage beyond candidate lists"),
    ),
)


# ---------------------------------------------------------------- lookups

def election_date(contest: str) -> datetime.date | None:
    body, _ = CONTESTS[contest]
    return terms.TERMS[body].next_election


def contest_label(contest: str) -> str:
    return CONTESTS[contest][1]


def _norm(text: str) -> list[str]:
    """Lowercased words without accents, quotes or single-letter initials:
    'María José Padmore' -> ['maria', 'jose', 'padmore']."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    words = re.findall(r"[a-z]+(?:'[a-z]+)?", text.lower())
    return [w for w in words if len(w) > 1]


_TITLES = re.compile(r"^(mayor|councilmember|council member|commissioner|candidate|"
                     r"school board (member|candidate)|mr|mrs|ms|dr)\.?\s+")


def match(name: str) -> list[Candidate]:
    """The candidates a name refers to: every word of it among a ballot
    name's or alias's words ('Tom Peterson', 'Padmore', 'Maria Padmore');
    failing that, the last word as a last name, with the first initial
    breaking ties ('Kristen Lockhart')."""
    needle = _norm(_TITLES.sub("", (name or "").strip().lower()))
    if not needle:
        return []
    hits = []
    for c in CANDIDATES:
        for form in (c.ballot_name, *c.aliases):
            if set(needle) <= set(_norm(form)):
                hits.append(c)
                break
    if hits:
        return hits
    last = [c for c in CANDIDATES if _norm(c.ballot_name)[-1:] == needle[-1:]]
    if len(last) > 1 and len(needle) > 1:
        last = [c for c in last if _norm(c.ballot_name)[0][0] == needle[0][0]] or last
    return last


def in_contest(contest: str) -> list[Candidate]:
    return [c for c in CANDIDATES if c.contest == contest]


# last names that are also everyday words or common elsewhere: only a
# first-and-last-name mention counts ("City Hall" is not Stacy Hall)
_COMMON_LAST = {"hall", "brown", "jones", "kim", "chang", "amos"}


def named_in(question: str) -> list[Candidate]:
    """Candidates the question names outright: first and last name, or a
    distinctive last name alone."""
    words = set(_norm(question))
    out = []
    for c in CANDIDATES:
        for form in (c.ballot_name, *c.aliases):
            parts = _norm(form)
            last = parts[-1]
            if last in words and (parts[0] in words or last not in _COMMON_LAST):
                out.append(c)
                break
    return out
