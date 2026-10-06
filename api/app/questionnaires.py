"""The same questions put to everyone in a race: the 2026 voter-guide
questionnaires (League of Women Voters' Vote411, Patch's candidate
questionnaire), kept answer by answer so the election page can set the
candidates' answers to one question side by side.

Only questions every candidate in the race was asked are kept (no
challenger-only question, no family details); each answer is a short
paraphrase of what the candidate wrote, never longer than the answer
itself, checked against the published text. A candidate with no row
did not respond; an answer of None is a question they left blank.

Pinned by hand like app.candidates, and retired with it after the
election."""
import datetime
from dataclasses import dataclass

_D = datetime.date

VOTE411 = "League of Women Voters (Vote411)"
PATCH = "Patch (Fairfax City)"


@dataclass(frozen=True)
class Response:
    candidate: str                               # ballot name, as in app.candidates
    answers: tuple[tuple[str, str | None], ...]  # (question key, paraphrase or None if left blank)
    url: str | None = None                       # the candidate's own page, when it has one
    published: datetime.date | None = None


@dataclass(frozen=True)
class Questionnaire:
    key: str
    contest: str                                 # an app.candidates.CONTESTS key
    publisher: str
    title: str
    url: str
    checked: datetime.date                       # when the answers were last read
    questions: tuple[tuple[str, str], ...]       # (key, the question as printed)
    responses: tuple[Response, ...]
    note: str | None = None                      # what was left out, and why


def _r(candidate: str, *answers: tuple[str, str | None], url: str | None = None,
       published: datetime.date | None = None) -> Response:
    return Response(candidate, answers, url, published)


QUESTIONNAIRES: tuple[Questionnaire, ...] = (
    Questionnaire(
        'vote411_mayor', 'mayor', VOTE411, 'League of Women Voters Vote411 voter guide, Mayor',
        'https://onyourballot.vote411.org/race-detail.do?id=29000195',
        checked=_D(2026, 10, 5),
        questions=(
            ('priorities', 'What are your priorities for Fairfax City?'),
            ('qualifications', 'What qualifications do you have for this position?'),
            ('urgent', "What do you see as the most urgent issue facing Fairfax City and what solutions do"
                       " you propose?"),
        ),
        responses=(
            _r('Kirsten Sides Lockhart',
               ('priorities', "Five priorities: a sustainable long-term budget from holistic planning; "
                              "integrated development in Activity Centers with transparent, repeatable "
                              "review and small-business space; more resident participation; quality staff"
                              " and a culture of respect; stronger GMU and regional ties."),
               ('qualifications', "Cites Planning Commission service since March 2021, now Vice Chair and "
                                  "delegate to the FIIG committee; 20+ years as a strategy consultant, "
                                  "mostly federal, in infrastructure and change management; City parks and"
                                  " rec participant, PTA member and volunteer."),
               ('urgent', "Campaign-trail concerns include taxes, homelessness, traffic and immigration; "
                          "the common thread is communication between residents and government. Lower "
                          "taxes need a community conversation on acceptable cuts; leadership should set a"
                          " standard of accessible communication.")),
        ),
        note="Vote411's biography field is left out; backgrounds are on each candidate's card.",
    ),
    Questionnaire(
        'vote411_city_council', 'city_council', VOTE411, 'League of Women Voters Vote411 voter guide, City Council',
        'https://onyourballot.vote411.org/race-detail.do?id=4143051',
        checked=_D(2026, 10, 5),
        questions=(
            ('priorities', 'What are your priorities for Fairfax City?'),
            ('qualifications', 'What qualifications do you have for this position?'),
            ('urgent', "What do you see as the most urgent issue facing Fairfax City and what solutions do"
                       " you propose?"),
        ),
        responses=(
            _r('Anthony T. Amos',
               ('priorities', "Affordability (housing, taxes), small business, financial education, "
                              "homelessness, education and childcare, community building, environment, "
                              "safety. Proposes a Capital Acquisition and Land Preservation Fund, "
                              "green/accessible home-upgrade rebates, delayed-permit fee refunds."),
               ('qualifications', "Cites current Council service; co-leading the Move Fairfax Steering "
                                  "Committee; City representative on Finance and Water and Air Quality "
                                  "committees with COG and VML; a public policy master's from George "
                                  "Mason; work for Fairfax County and as an affordable housing developer."),
               ('urgent', "Affordability: housing, taxes, cost of living and jobs, all correlated. Working"
                          " on dedicated housing trust fund revenue (incl. workforce housing for educators"
                          " and public safety), a Home Sharing Program, childcare during public meetings "
                          "and events, and trade-skill upskilling.")),
            _r('Stacy R. Hall',
               ('priorities', "Strong schools, safe neighborhoods, reliable services and a financially "
                              "sustainable future. Appropriately scaled development that weighs traffic, "
                              "infrastructure, green space and neighborhood character. Support small "
                              "businesses; transparent, responsive government."),
               ('qualifications', "Cites service on the School Board and City Council, giving knowledge of"
                                  " operations, budgeting, education, land use and infrastructure; a "
                                  "finance degree with minors in economics and biology; 15+ years as a "
                                  "controller; nine years in PTA leadership, three as president."),
               ('urgent', "Keeping affordability and services as costs, tuition, debt and capital needs "
                          "rise. Separate needs from wants; weigh long-term costs. Backs multiyear "
                          "budgets, debt limits, core services first, program reviews, a stronger "
                          "commercial tax base, filling vacancies, scaled development.")),
            _r('Rachel M McQuillen',
               ('priorities', "Wants the next generation to afford to live in the City. Priorities: "
                              "affordability and responsible spending; schools and public safety; a strong"
                              " local economy; thoughtful housing and redevelopment; safer transportation;"
                              " the environment. Residents need a voice before decisions."),
               ('qualifications', "Cites being a homeowner, small-business owner, former School Board "
                                  "member and current Council member; 10 years with the Providence PTA; "
                                  "more than a decade in accounting and finance. Describes doing homework,"
                                  " asking hard questions and listening to different viewpoints."),
               ('urgent', "The City is getting more expensive; neither taxes nor cuts alone solve it. "
                          "Cites pushing for a citywide efficiency audit; urges a stronger commercial tax "
                          "base, local business support, attainable housing, redevelopment with lasting "
                          "value and scrutiny of projects' lifetime cost.")),
            _r("Kelly M. O'Brien",
               ('priorities', "Planning for the future while keeping what makes the community special: "
                              "thoughtful growth, support for local businesses and commercial areas, "
                              "infrastructure and services that keep pace, and City government that is "
                              "easier to understand, with residents given a meaningful voice."),
               ('qualifications', "Cites a career in local government: complex issues, project management,"
                                  " engagement with residents and businesses, presenting to boards and "
                                  "elected officials. Says City experience means usually knowing who to "
                                  "ask; emphasizes listening, doing homework and thoughtful decisions."),
               ('urgent', "Among the most urgent: building trust, among Council members and between City "
                          "government and the community. Proposes clear, accessible communication, "
                          "meaningful engagement and more transparency, so growth, housing, transportation"
                          " and finances can be tackled together.")),
            _r('Sandi W. Slappey Brown',
               ('priorities', "A path for development, replacing aging buildings and parking lots with "
                              "commercial and residential space true to the City's character; housing for "
                              "varied incomes; trust in government; exploring charter changes for "
                              "staggered, possibly longer Council terms and the Mayor's role."),
               ('qualifications', "Cites 30+ years as a social worker, mostly in local government; "
                                  "master's degrees in social work and organizational psychology; PMP "
                                  "certification; 20 years as a chief or assistant chief election officer."),
               ('urgent', "Among the biggest challenges, development: cites 24 major projects underway, "
                          "many seeking special exceptions. Interested in clearer upfront expectations and"
                          " a faster process; backs zoning amendments trading height or density for green "
                          "space or transportation gains.")),
        ),
        note="Vote411's biography field is left out; backgrounds are on each candidate's card.",
    ),
    Questionnaire(
        'vote411_school_board', 'school_board', VOTE411, 'League of Women Voters Vote411 voter guide, School Board',
        'https://onyourballot.vote411.org/race-detail.do?id=68964635',
        checked=_D(2026, 10, 5),
        questions=(
            ('priorities', 'What are your priorities if elected to the School Board?'),
            ('qualifications', 'What qualifications do you have for this position?'),
            ('urgent', "What do you see as the most urgent issue facing our local public schools and what "
                       "solutions do you propose?"),
        ),
        responses=(
            _r('Amit Sarah Hickman',
               ('priorities', "Schools where every student is known, supported and challenged; thoughtful,"
                              " innovative designs for the upcoming elementary school renovations; "
                              "communication with families; stewardship of public funds; support for "
                              "educators; and continued collaboration with FCPS."),
               ('qualifications', "Cites 20+ years working with children and families; a master's in early"
                                  " childhood education and an MSW from George Mason; work as an educator "
                                  "and clinical social worker; and current School Board service."),
               ('urgent', "Among the most urgent: planning for students' immediate and long-term needs. "
                          "Sees renovations as a chance for flexible, inclusive spaces, alongside "
                          "academic, social-emotional and staffing needs. Would prioritize renovation "
                          "oversight, FCPS collaboration, family communication.")),
        ),
        note="Vote411's biography field is left out; backgrounds are on each candidate's card.",
    ),
    Questionnaire(
        'patch_mayor', 'mayor', PATCH, "Patch's 2026 candidate questionnaire, Mayor",
        'https://patch.com/virginia/fairfaxcity',
        checked=_D(2026, 10, 5),
        questions=(
            ('slate', "Have you been endorsed by a political party or aligned yourself with a group of "
                      "candidates in the 2026 Fairfax City elections? Select the answer that best "
                      "describes your campaign. If both apply, select Other and explain."),
            ('differing_views', "How would you work with City Council members and residents whose "
                                "political views differ from yours?"),
            ('why', 'Why are you running for mayor of Fairfax City?'),
            ('role', 'What do you see as the primary role of the Mayor? How will you achieve that goal?'),
            ('pressing', "The single most pressing issue facing voters is _______, and this is what I "
                         "intend to do about it."),
            ('platform', 'Describe the other issues that define your campaign platform.'),
            ('done_well', "What has the current mayor and City Council done well, and what would you "
                          "change? Please give specific examples."),
            ('differences', "What are the critical differences between you and the other candidate seeking"
                            " this post?"),
            ('development', "What approach should Fairfax City take to new development and redevelopment? "
                            "What types of projects would you support or oppose, and how would you balance"
                            " housing needs and economic growth with concerns about traffic, "
                            "infrastructure and neighborhood character?"),
            ('accomplishments', "What accomplishments in your past would you cite as evidence you can "
                                "handle this job?"),
        ),
        responses=(
            _r('Kirsten Sides Lockhart',
               ('slate', 'Named a "recommended" candidate by the City of Fairfax Democratic Committee; did'
                         ' not seek any endorsement or alignment'),
               ('differing_views', "Full ideological agreement isn't needed to weigh projects on data and "
                                   "public engagement. Hopes elected officials work together respectfully "
                                   "and productively, and that residents feel heard and engage "
                                   "respectfully in return."),
               ('why', "Cites dismay, over five-plus years on the Planning Commission, at the caliber of "
                       "elected officials' discourse. Wants analytic rigor in decisions, to restore "
                       "respectful working relationships with staff, boards and residents, and residents "
                       "heard; a public servant, not a politician."),
               ('role', "Top priority is representing the City on regional bodies such as COG, NVTC, NVTA "
                        "and the Northern Virginia Regional Commission. Success depends on Council and "
                        "staff working together, so a key goal is a productive, goal-aligned team across "
                        "City stakeholders."),
               ('pressing', "Communication: accessible ways for residents to reach government, government "
                            "pursuing every avenue to reach them, and better ways for residents to talk "
                            "with each other. Much consensus-building could happen in neighborhoods if the"
                            " City removes barriers to participation."),
               ('platform', None),
               ('done_well', None),
               ('differences', "Asks readers to visit both campaign websites and examine City government "
                               "voting records to draw their own conclusions."),
               ('development', "Data-driven, risk-informed, guided by the Comprehensive, Small Area and "
                               "Master Plans, with clear, repeatable evaluation; collect data on traffic, "
                               "stormwater and vacancies. Hopes for mixed housing incl. affordable units, "
                               "small-business space, and parks, trees and walkability."),
               ('accomplishments', None),
               url='https://patch.com/virginia/fairfaxcity/kirsten-lockhart-puts-communication-center-fairfax-city-mayor-bid', published=_D(2026, 9, 17)),
            _r('Thomas D. "Tom" Peterson',
               ('slate', 'Unaffiliated and cooperating with candidates who are unaffiliated'),
               ('differing_views', "Welcomes different perspectives; cites a 44-year career bringing "
                                   "together people with conflicting views to reach practical agreements. "
                                   "Will work with everyone regardless of affiliation: listen, understand "
                                   "interests, establish facts and find areas of agreement."),
               ('why', "Cites 24 years as a resident and Council service. Says the City needs experienced,"
                       " collaborative leadership on cost of living, development, taxes and other choices;"
                       " wants to move Fairfax forward while protecting its qualities and giving residents"
                       " a meaningful voice."),
               ('role', "Presiding over Council and helping it function, plus representing Fairfax "
                        "regionally. Would act as a collaborative facilitator, bridge residents, Council "
                        "and staff with early participation, draw on service on eight regional boards, and"
                        " set a civil, constructive tone."),
               ('pressing', "Cost of living, economic security and fiscal responsibility. Manage resources"
                            " responsibly, scrutinize spending and major investments, avoid excessive debt"
                            " and unnecessary tax increases, maintain essential services, and ease "
                            "housing, transportation and energy cost pressures."),
               ('platform', "Cost of living, economic security and fiscal responsibility; schools; public "
                            "safety and City services; transportation and infrastructure; local "
                            "businesses; environment and community health; open government; and carefully "
                            "balanced growth that doesn't overwhelm the city."),
               ('done_well', "Cites budgets that substantially cut proposed tax rates, a new City Manager,"
                             " a 55%+ cut in Willard-Sherwood's taxpayer cost, a school sales-tax option "
                             "and a firearms ban at City events. Would add earlier, more rigorous review "
                             "of major decisions and earlier public input."),
               ('differences', "Campaign is focused solely on the City: listening to residents and "
                               "bringing people together for practical solutions that serve the entire "
                               "community."),
               ('development', "More balanced growth. Supports redevelopment that strengthens the "
                               "commercial tax base and meets demonstrated housing needs, but has "
                               "significant concerns on height, density, scale and pace of some proposals;"
                               " Small Area Plans' ~4,700 units (~45% of stock) need full analysis first."),
               ('accomplishments', "Cites current Council service and prior chairing of the Environmental "
                                   "Sustainability Committee; 24 years in the City; a 44-year career "
                                   "including 20+ stakeholder-based state climate, energy and economic "
                                   "plans, White House and Senate assignments, and 10 years at EPA."),
               url='https://patch.com/virginia/fairfaxcity/tom-peterson-puts-cost-living-center-fairfax-city-mayor-bid', published=_D(2026, 9, 17)),
        ),
        note=("Questions on age, family, education, occupation, advice and anything else are left out "
              "(backgrounds are on each candidate's card), as is the follow-up on party status."),
    ),
    Questionnaire(
        'patch_city_council', 'city_council', PATCH, "Patch's 2026 candidate questionnaire, City Council",
        'https://patch.com/virginia/fairfaxcity',
        checked=_D(2026, 10, 5),
        questions=(
            ('slate', "City elections are traditionally non-partisan and candidates must run as "
                      "independents, according to both the city charter and the Code of Virginia. No party"
                      " affiliation or \"mark\" will appear next to any of the candidates' names on the "
                      "November 2026 ballot. Have you been endorsed by a recognized political party or "
                      "have you aligned yourself with a group of candidates representing themselves as "
                      "independent, non-partisan candidates, including candidates running in other city "
                      "races? Please check the answer that is most appropriate."),
            ('why', 'Why are you seeking elective office?'),
            ('pressing', "The single most pressing issue facing voters is _______, and this is what I "
                         "intend to do about it."),
            ('development', "What approach should Fairfax City take to new development and redevelopment? "
                            "What types of projects would you support or oppose, and how would you balance"
                            " housing needs and economic growth with concerns about traffic, "
                            "infrastructure and neighborhood character?"),
            ('differences', "What are the critical differences between you and the other candidates "
                            "seeking this post?"),
            ('platform', 'Describe the other issues that define your campaign platform.'),
            ('accomplishments', "What accomplishments in your past would you cite as evidence you can "
                                "handle this job?"),
        ),
        responses=(
            _r('Rachel M McQuillen',
               ('slate', 'Aligned with a group of independent, nonpartisan candidates'),
               ('why', "Seeking reelection after PTA, School Board and Council service. Says City Hall "
                       "decisions are deeply personal; still asks overlooked questions and challenges "
                       "assumptions; wants to protect what people love while keeping the City affordable, "
                       "welcoming and worthy of trust."),
               ('pressing', "Managing growth and rising costs without losing quality of life. Will pursue "
                            "more efficient operations, responsible redevelopment, economic growth and "
                            "long-term planning so residents aren't priced out or overwhelmed by traffic "
                            "and infrastructure demands."),
               ('development', "Welcome development that adds housing choices, revitalizes underused sites"
                               " and grows the tax base; supports adaptive reuse and mixed use. Strengthen"
                               " the Renaissance Housing Program, speed permitting; oppose projects with "
                               "unresolved infrastructure or safety concerns or poor scale."),
               ('differences', "Cites School Board and Council service, a decade-plus in accounting and "
                               "finance, and building a small business. Points to challenging costly "
                               "projects, defending resident participation, backing ethics standards and "
                               "evidence-based investments; answers to residents, not a party."),
               ('platform', "Responsible spending (finish the efficiency audit, long-term financial "
                            "plans); home reinvestment and workforce housing; faster permitting; "
                            "thoughtful growth; traffic safety via Move Fairfax City; schools and public "
                            "safety; environment; childcare; resident trust."),
               ('accomplishments', "Cites School Board legislative chair work building support for "
                                   "facility investments; on Council, advancing the efficiency audit, "
                                   "backing Willard-Sherwood after its projected tax impact fell from 9.7 "
                                   "to 4.33 cents, voting against the meals-tax increase, stronger ethics "
                                   "standards."),
               url='https://patch.com/virginia/fairfaxcity/rachel-mcquillen-puts-growth-rising-costs-center-fairfax-city-council', published=_D(2026, 9, 16)),
            _r('Anthony T. Amos',
               ('slate', 'Recommended for reelection by a political party'),
               ('why', "Seeking reelection to see investments through, guide the City through a "
                       "challenging economy and housing crisis, and strengthen its regional position; "
                       "wants an idea-focused, solution-oriented approach rather than an inconsistent "
                       "vision for the future."),
               ('pressing', "Affordability, housing and taxes. Working on dedicated housing trust fund "
                            "revenue (incl. workforce housing for educators and public safety), a Home "
                            "Sharing Program, childcare during public meetings and events, and trade-skill"
                            " upskilling."),
               ('development', "Small area plans and zoning set guidelines, but judge each project on its "
                               "merits, e.g. whether housing adds road connections that ease congestion. "
                               "Cites Willard-Sherwood as a key investment; urges public-private deals, "
                               "such as public safety housing by Fire Station #3."),
               ('differences', "Cites representing often underrepresented groups: experience as a former "
                               "apartment renter in the City, affordable housing zoning and finance "
                               "experience, and being a young African American man, the first elected to "
                               "Council in over 50 years."),
               ('platform', "Affordability (housing, taxes), small business, financial education, "
                            "homelessness, education and childcare, community building, environment, "
                            "safety. Proposes a Capital Acquisition and Land Preservation Fund, "
                            "green/accessible home-upgrade rebates, delayed-permit fee refunds."),
               ('accomplishments', "Cites expanding ties with George Mason (Homecoming City Crawl, Poetry "
                                   "Night), a Hire-a-Lion Job Fair, helping launch the Budget Open House, "
                                   "and supporting the first Affordability and Housing Strategic Plan, the"
                                   " Urban Forest Master Plan and the first Community Survey."),
               url='https://patch.com/virginia/fairfaxcity/anthony-amos-favors-case-case-development-reviews-fairfax-city-council-bid', published=_D(2026, 9, 9)),
            _r('Sandi W. Slappey Brown',
               ('slate', "Endorsed by a recognized political party (clarifies it is a recommendation from "
                         "the City of Fairfax Democratic Committee)"),
               ('why', "Cites nearly 40 years in social work, mostly in local government, and 20 years as "
                       "an election officer. Seeks to bring a balanced perspective valuing history and "
                       "growth, small businesses, affordable and diverse housing, and both long-time and "
                       "new residents."),
               ('pressing', "Development, taxes and services, intertwined. Service costs are rising; "
                            "believes Council and staff manage expenses diligently. Cites the Parks "
                            "Foundation as creative revenue; wants more commercial activity to ease real "
                            "estate taxes and the right mix of uses in mixed-use projects."),
               ('development', "Cites 24 projects underway, most seeming to seek special exceptions. Wants"
                               " clearer upfront expectations and faster review; backs the zoning "
                               "amendments. Interested in more commercial space for revenue; housing near "
                               "commercial centers; judge each project; keep character; use data."),
               ('differences', "Cites 30+ years in social work, mostly local government, and an approach "
                               "centered on listening, data and seeking understanding. Points to attending"
                               " many board and commission meetings, such as the Planning Commission and "
                               "School Board, to learn their work."),
               ('platform', "Top three priorities: development, housing and trust in government. "
                            "Interested in how the City can seek market-rate, attainable and affordable "
                            "housing and incentives for it; cites Beacon Landing, Fairfax Presbyterian "
                            "Church housing, the detached ADU ordinance; transparency."),
               ('accomplishments', "Cites a social work career leading child-welfare operations teams, "
                                   "including lead roles in an onboarding academy and an AI note-taking "
                                   "tool; a 2021-2023 organizational psychology master's; and 20 years as "
                                   "a chief or assistant chief election officer."),
               url='https://patch.com/virginia/fairfaxcity/sandi-slappey-brown-sees-taxes-city-services-key-fairfax-city-council', published=_D(2026, 9, 14)),
            _r("Kelly M. O'Brien",
               ('slate', "Recommended by the Fairfax City Democratic Committee, based on a completed "
                         "questionnaire; says she did not seek the recommendation"),
               ('why', "Cares about Fairfax and believes professional experience can help: 15+ years in "
                       "Virginia local government, including seven with the City, plus volunteer and "
                       "community roles. Wants to bring that understanding of how local government works "
                       "to Council."),
               ('pressing', "Uncertainty around growth and development in areas like Northfax, Kamp "
                            "Washington and Old Town. Would align the zoning ordinance with adopted Small "
                            "Area Plans for predictability and make special exceptions the exception, not "
                            "the norm."),
               ('development', "Concentrate redevelopment in areas the Small Area Plans and Comprehensive "
                               "Plan identify, not established neighborhoods. Judge requests for "
                               "substantially more than zoning allows on impacts and public benefit; fit "
                               "each project to its location and plans, not one-off negotiations."),
               ('differences', "Cites professional government experience plus years of civic involvement: "
                               "helping with the Fall Festival and July 4th parade, helping coordinate the"
                               " Asian Festival on Main for six years, and creating the Fairfax City 411 "
                               "Facebook group in 2023 to explain City meetings."),
               ('platform', "Transparency and accessibility (the reason for starting Fairfax411); "
                            "supporting existing local businesses and the commercial tax base to ease "
                            "residential taxes; respecting City staff expertise and care with taxpayer "
                            "dollars; bringing some joy back to local government."),
               ('accomplishments', "Cites seven years in the City Planning Department and eight in Vienna,"
                                   " leading zoning and comprehensive plan updates; coordinating the Asian"
                                   " Festival on Main; Parks and Recreation Advisory Board Vice Chair; "
                                   "Fairfax City 411; 2024 Women of Influence and Hometown Hero honors."),
               url='https://patch.com/virginia/fairfaxcity/kelly-o-brien-targets-development-uncertainty-fairfax-city-council-bid', published=_D(2026, 9, 14)),
            _r('Russell A. Jones',
               ('slate', 'Not endorsed by a party; not aligned with a candidate group'),
               ('why', "Doesn't like what is happening."),
               ('pressing', 'Tax increases.'),
               ('development', "Be cautious and weigh possible future issues before moving too quickly; "
                               "says it seems most past City developments didn't work out quite as "
                               "expected."),
               ('differences', 'Says he is older than most and has a no-nonsense point of view.'),
               ('platform', 'Reining in frivolous spending and staying within budget.'),
               ('accomplishments', "Cites 20 years as a government employee and 20 as a small business "
                                   "owner."),
               url='https://patch.com/virginia/fairfaxcity/russell-jones-puts-tax-increases-center-fairfax-city-council-bid', published=_D(2026, 9, 14)),
            _r('Susan Hartley Kuiler',
               ('slate', 'Aligned with a group of independent, nonpartisan candidates'),
               ('why', "Loves the City and wants to preserve its character while preparing for the future."
                       " Wants practical, transparent government; running as an independent to represent "
                       "people, not politics; wants to hear from everyone and build consensus."),
               ('pressing', "Managing growth in a small, built-out 6.4-square-mile city while preserving "
                            "natural resources and small-town character. Proposes collaborative, "
                            "transparent governance; targeted redevelopment, streamlined approvals, "
                            "flexible mixed use, small-business support; promoting parks."),
               ('development', "Growth should be deliberate, community-informed and appropriately scaled "
                               "in a built-out city. Would hold town halls on pace and scale before "
                               "decisions, weigh impacts on traffic, services, environment and taxes, and "
                               "hear from businesses on attracting and retaining local firms."),
               ('differences', "Emphasizes listening and open communication. Says City decisions can seem "
                               "made before residents know; calls for early, plain-language outreach "
                               "through multiple channels, and willingness to change course when residents"
                               " raise legitimate concerns."),
               ('platform', "Practical, common-sense leadership; thoughtful budgeting, efficient use of "
                            "resources and long-term financial health; open, honest communication and "
                            "clear decisions; listening to residents and working together."),
               ('accomplishments', "Cites cost and risk analysis and budget work; turning a money-losing "
                                   "retail store profitable; leading an HOA as president and grounds chair"
                                   " (repairs, contracts, budgets); 40 years in IT, including teams that "
                                   "built FEMA disaster systems."),
               url='https://patch.com/virginia/fairfaxcity/susan-hartley-kuiler-targets-growth-small-town-character-fairfax-council-bid', published=_D(2026, 9, 15)),
            _r('Steve S Chang',
               ('slate', "Aligned with a group of independent, nonpartisan candidates (names the Fairfax "
                         "Common Ground candidates)"),
               ('why', "Wants leadership that listens, plans responsibly and delivers results: preserve "
                       "neighborhood character, support local businesses, maintain public safety. Would "
                       "work collaboratively, focusing on fiscal responsibility and transparency, putting "
                       "Fairfax City first."),
               ('pressing', "Cites 3,000+ doors knocked: the City's financial health while keeping costs "
                            "and taxes manageable. Will push fiscal discipline and budget transparency, "
                            "scrutinize capital projects, seek efficiency before tax or fee hikes, broaden"
                            " the economic base, and fund essential services."),
               ('development', "Supports scaled redevelopment per the Comprehensive Plan, incl. underused "
                               "commercial sites and mixed use. Would oppose projects that overwhelm "
                               "infrastructure, are out of scale, or needlessly harm historic sites or "
                               "green space; housing or tax base alone isn't enough."),
               ('differences', "Cites business ownership, nonprofit and community leadership, and decades "
                               "of service. Emphasizes fiscal responsibility, responsible development, "
                               "local businesses and quality of life; hearing residents before major "
                               "decisions, not political agendas or special interests."),
               ('platform', 'Community-driven leadership, fiscal responsibility, local businesses, '
                            'responsible growth, public safety and quality of life. Says door-knocking '
                            'conversations are shaping the campaign; commitment is "Putting Fairfax First"'
                            ' through transparency and common sense.'),
               ('accomplishments', "Cites owning a fine jewelry store for 12 years, about 30 years in "
                                   "church and community leadership including as a pastor, and current "
                                   "multimedia publishing and real estate interests, which taught managing"
                                   " resources and making difficult decisions."),
               url='https://patch.com/virginia/fairfaxcity/fairfax-city-council-candidate-steve-chang-calls-greater-fiscal-discipline', published=_D(2026, 9, 16)),
            _r('Jessica L. Lough',
               ('slate', 'Aligned with a group of independent, nonpartisan candidates'),
               ('why', "Wants Council members who listen, work respectfully and decide on facts. Cites "
                       "executive leadership and financial discipline. Says public input often feels like "
                       "box-checking after decisions are made; wants resident feedback to shape outcomes."),
               ('pressing', "Responsible fiscal management: a 10-year plan with accountability metrics, "
                            "reviewing whether programs deliver results, planning for long-term costs, and"
                            " growing the commercial tax base, including being willing to pilot measures "
                            "to boost Old Town foot traffic."),
               ('development', "Preserve community character as a competitive advantage. Supports "
                               "redevelopment that complements neighborhoods, encourages local businesses,"
                               " uses underutilized space, protects green space and eases the tax burden; "
                               "study long-term impacts and give residents an early voice."),
               ('differences', "Says many share similar priorities; cites professional experience leading "
                               "complex programs and large budgets, and a data-driven approach. Wants "
                               "residents involved early, all data considered, and no political agenda."),
               ('platform', "Quality of life: a more vibrant Old Town with more foot traffic; safer "
                            "streets, walkability, traffic and parking solutions and infrastructure "
                            "investment; safety, excellent schools, parks and community events; planning "
                            "for the city 10 to 20 years out."),
               ('accomplishments', "Cites 20+ years managing complex programs at Amazon, Meta and Google, "
                                   "handling large budgets and data; board service at Earth League "
                                   "International; attending and speaking at Council meetings."),
               url='https://patch.com/virginia/fairfaxcity/jessica-lough-targets-fiscal-management-fairfax-city-council-bid', published=_D(2026, 9, 15)),
        ),
        note=("Questions on age, family, education, occupation, advice and anything else are left out "
              "(backgrounds are on each candidate's card), as are the follow-ups on party status and the "
              "question put only to challengers."),
    ),
)
