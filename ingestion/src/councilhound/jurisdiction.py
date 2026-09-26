"""The per-jurisdiction config: one YAML under ingestion/jurisdictions/<slug>.yaml.

Everything that used to name the City of Fairfax in code — the Granicus host
and view ids, the tracked bodies and how their archive rows classify, roster
parsing, the projects source, feed/email branding, map defaults, prompt
vocabulary, and the impact subsystem's FIPS/CRS/tax/budget pins — lives here.
Code reads it through `current()`, selected by the JURISDICTION env var
(default: the City, so every existing env, test and deployment is unchanged).

A process serves exactly one jurisdiction (one stack per jurisdiction: same
images, separate apps + database), so `current()` is a process-global cached
load, and module-level constants derived from it (councilhound.config,
councilhound.bodies) stay import-time constants.

The impact-owned keys (`fips`, `crs_projected`, `tax`, `budget`, `*_source`,
…) keep their top-level position so `require_rate("tax.meals_tax_rate")`,
`impact-setup-jurisdiction`'s dotted writes and `save()` round-trips are
untouched; councilhound.impact.jurisdiction re-exports the models.
"""
from __future__ import annotations

import functools
import os
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

import yaml
from pydantic import BaseModel, Field, model_validator

DEFAULT_SLUG = "fairfax_city_va"


def _default_dir() -> Path:
    env = os.environ.get("JURISDICTIONS_DIR")
    if env:
        return Path(env)
    # src/councilhound/jurisdiction.py -> parents[2] == ingestion/
    return Path(__file__).resolve().parents[2] / "jurisdictions"


JURISDICTIONS_DIR = _default_dir()


# --- impact-owned models (unchanged shape) ---------------------------------

class PinnedValue(BaseModel):
    """A config value that must carry its source. value=None means 'not yet
    pinned' — usable only after impact-setup-jurisdiction fills it in."""
    value: float | None = None
    source: str | None = None  # URL it was read from
    fy: str | None = None  # fiscal year / vintage


class TaxRates(BaseModel):
    real_estate_rate_per_100: PinnedValue = Field(default_factory=PinnedValue)
    meals_tax_rate: PinnedValue = Field(default_factory=PinnedValue)
    sales_tax_local_share: PinnedValue = Field(default_factory=PinnedValue)
    # per-household budget actuals (preferred) vs. rate-based vehicle estimate
    # (fallback) — fiscal.py uses whichever is pinned, actuals first
    personal_property_per_household: PinnedValue = Field(default_factory=PinnedValue)
    personal_property_rate_per_100: PinnedValue = Field(default_factory=PinnedValue)
    bpol_retail_rate_per_100: PinnedValue = Field(default_factory=PinnedValue)
    # BPOL is levied by business class; professional/business-service rates run
    # several times the retail rate, so office tenants need their own
    bpol_office_rate_per_100: PinnedValue = Field(default_factory=PinnedValue)
    # business tangible personal property (furniture, fixtures, equipment)
    bpp_rate_per_100: PinnedValue = Field(default_factory=PinnedValue)


class BudgetFacts(BaseModel):
    general_fund_expenditure: PinnedValue = Field(default_factory=PinnedValue)
    population_basis: PinnedValue = Field(default_factory=PinnedValue)
    # school-split cost model: when both are pinned, service costs become
    # residents x non-school per-capita + students x per-pupil, so student
    # generation drives the school component instead of being note-only
    education_transfer: PinnedValue = Field(default_factory=PinnedValue)
    school_enrollment: PinnedValue = Field(default_factory=PinnedValue)
    # state education revenue received by the locality (basic aid + education
    # sales tax); netted against the transfer so per-pupil cost is LOCAL cost
    state_school_revenue: PinnedValue = Field(default_factory=PinnedValue)


class Fips(BaseModel):
    state: str
    county: str


# --- core sections -----------------------------------------------------------

class Identity(BaseModel):
    short_name: str = ""                 # "City of Fairfax" — subjects, masthead
    noun: Literal["city", "county", "town"] = "city"
    state_abbr: str = "VA"
    timezone: str = "America/New_York"
    geocode_suffix: str = ""             # appended to bare street addresses
    # [min_lat, min_lng, max_lat, max_lng]; a geocode outside it is a miss
    geocode_bbox: list[float] | None = None
    # the jurisdiction's own names — never topics (see bodies.is_self_reference)
    self_names: list[str] = Field(default_factory=list)
    self_prefixes: list[str] = Field(default_factory=list)
    # boards/commissions on the archive that are not tracked, also not topics
    other_body_names: list[str] = Field(default_factory=list)
    legislative_body_label: str = "City Council"
    record_phrase: str = "council business"   # "what changed in <X> council business"
    activity_noun: str = "council"            # "new council activity", "the council record"


class Site(BaseModel):
    site_base_url: str = "https://councilhound.net"
    api_base_url: str = "https://api.councilhound.net"
    uid_domain: str = "councilhound.net"      # ICS UIDs, Atom tag: URIs
    mail_from: str = "CouncilHound <hound@councilhound.net>"
    okf_bundle_name: str = "councilhound-fairfax"   # knowledge/<name>
    ics_filename: str = "councilhound.ics"
    fly_app_prefix: str = "councilhound"


class LabelRule(BaseModel):
    contains: str   # lowercased substring of the link/option text
    type: str       # document type to record


class GranicusView(BaseModel):
    view_id: str
    # sections: one ViewPublisher view whose <h3> headers name the bodies
    # (bodies[].archive_section); single: the whole view is one body
    layout: Literal["sections", "single"] = "sections"
    body: str | None = None


class ExternalArchive(BaseModel):
    """A per-row link off Granicus to the jurisdiction's own meeting page."""
    link_text_contains: str = "Full Meeting Archive"
    doc_type: str = "meeting_page"
    follow_pdfs: list[LabelRule] = Field(default_factory=list)
    enabled: bool = False


class GranicusRow(BaseModel):
    clip_select: Literal["first", "last"] = "first"   # when a row has several clips
    clip_label_prefer: str | None = None              # e.g. "English" (captions language)
    external_archive: ExternalArchive | None = None


class GranicusDocuments(BaseModel):
    # MinutesViewer links classify by their label; the fallback type applies
    # when no rule matches (the County labels its annotated agenda with an
    # empty anchor, so its fallback is "agenda")
    label_rules: list[LabelRule] = Field(default_factory=lambda: [
        LabelRule(contains="reporter", type="actions_report"),
        LabelRule(contains="action", type="actions_report"),
        LabelRule(contains="minutes", type="minutes"),
    ])
    minutesviewer_default: str = "other"


class GranicusMedia(BaseModel):
    """Where a meeting's transcript comes from, in order of preference:
    captions (Granicus /videos/<clip>/captions.vtt when the tenant publishes
    real captions), mp3 (the archive MP3, transcribed locally), or
    mp4_audio_extract (download the MP4, keep only its audio track, then
    transcribe). The first source that yields a file wins."""
    sources: list[Literal["captions", "mp3", "mp4_audio_extract"]] = Field(
        default_factory=lambda: ["mp3"])
    keep_video: bool = False


class Canary(BaseModel):
    min_meetings: int = 50
    min_recent_agendas: int = 5
    min_recent_audio: int = 3
    min_upcoming: int = 5
    expect_mp3: bool = True


class Granicus(BaseModel):
    base_url: str = "https://fairfax.granicus.com"
    media_host_slug: str = "fairfax"   # archive-video.granicus.com/<slug>/...
    views: list[GranicusView] = Field(default_factory=lambda: [GranicusView(view_id="13")])
    row: GranicusRow = Field(default_factory=GranicusRow)
    documents: GranicusDocuments = Field(default_factory=GranicusDocuments)
    media: GranicusMedia = Field(default_factory=GranicusMedia)
    canary: Canary = Field(default_factory=Canary)


class MeetingTypeRule(BaseModel):
    contains: str
    type: str


class UpcomingRule(BaseModel):
    starts_with: list[str] = Field(default_factory=list)
    contains: list[str] = Field(default_factory=list)
    default_for_view: str | None = None   # rows on this view default to the body


class RosterRole(BaseModel):
    title: str                             # display title, unique per jurisdiction
    aliases: list[str] = Field(default_factory=list)   # "Mayor Read", "Councilmember Read"
    also: list[str] = Field(default_factory=list)      # other role keys whose aliases this
                                                        # role also gets (a chair is a commissioner)


class RosterMember(BaseModel):
    name: str
    role: str
    district: str | None = None


class Roster(BaseModel):
    parser: str = "static"                 # id in councilhound.seed.ROSTER_PARSERS
    static: list[RosterMember] = Field(default_factory=list)
    roles: dict[str, RosterRole] = Field(default_factory=dict)
    # the noun in a member's district alias ("Sully District Supervisor",
    # "Braddock District Commissioner"); defaults to the role's first alias
    district_title: str | None = None


class BodyConfig(BaseModel):
    key: str
    label: str
    short: str
    archive_section: str | None = None
    title_must_contain: list[str] = Field(default_factory=list)
    recorded: bool = True
    color: int | None = None               # palette index (frontend)
    hot: bool = False                      # hot-topics panels
    recommends: bool = False               # outcomes are recommendations, not decisions
    agenda_has_outcomes: bool = False      # the agenda doc carries official outcomes
    # for archives whose rows link no agenda: a strftime-style template of
    # the jurisdiction's own agenda URL, e.g. ".../calendar/%Y/%-m.%-d.%y.pdf"
    agenda_url_template: str | None = None
    meeting_types: list[MeetingTypeRule] = Field(default_factory=list)
    default_meeting_type: str | None = None
    upcoming: UpcomingRule = Field(default_factory=UpcomingRule)
    roster: Roster | None = None


class Projects(BaseModel):
    adapter: str = "none"                  # id in councilhound.scraper.projects
    generic_name_tokens: list[str] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)


class Extraction(BaseModel):
    comment_period_items: list[str] = Field(default_factory=list)
    vote_notes: list[str] = Field(default_factory=list)
    max_doc_chars: int = 60_000
    # output budget for the structuring call; a 40-item annotated agenda with
    # entities per item runs well past 8k tokens
    max_output_tokens: int = 8192


class Display(BaseModel):
    map_center: list[float] = Field(default_factory=lambda: [38.8462, -77.3064])
    map_zoom: dict[str, int] = Field(default_factory=lambda: {"compact": 15, "full": 14})
    map_bounds: list[list[float]] = Field(
        default_factory=lambda: [[38.83, -77.33], [38.87, -77.27]])
    nearby_radii_m: list[int] = Field(default_factory=lambda: [805, 1609, 3219])
    example_address: str = ""
    address_strip_regex: str = ""
    ask_suggestions: list[str] = Field(default_factory=list)
    ask_placeholder: str = ""
    boilerplate_terms: list[str] = Field(default_factory=list)
    glossary_overrides: list[dict[str, Any]] = Field(default_factory=list)


class Features(BaseModel):
    impact: bool = True
    projects: bool = True


# --- the config ---------------------------------------------------------------

class JurisdictionConfig(BaseModel):
    name: str
    slug: str = ""  # file stem, e.g. "fairfax_city_va"; set by load()
    fips: Fips
    crs_projected: str  # e.g. "EPSG:2283" — all distance math happens here
    projects_index_url: str
    boundary_source: str | None = None  # ArcGIS layer URL — discovered, then pinned
    parcels_source: str | None = None
    zoning_source: str | None = None
    assessment_source: str | None = None
    development_review_map_source: str | None = None
    geohub_portal_url: str | None = None
    tax: TaxRates = Field(default_factory=TaxRates)
    budget: BudgetFacts = Field(default_factory=BudgetFacts)
    # assessment land-use codes for comp selection, by product class. Condo
    # comps are what a for-sale project should be valued against; when the
    # condo code is unpinned the fiscal module falls back to its screening
    # default rather than pricing condos off apartment buildings.
    assessment_lucs: dict[str, str | None] = Field(
        default_factory=lambda: {"apartment": "352", "condo": None})
    transit_feeds: list[str] = Field(default_factory=list)
    fringe_reference_blockgroup: str | None = None  # environmental module (M6 seam)
    calibration_counts: dict | None = None  # optional pedestrian counts

    identity: Identity = Field(default_factory=Identity)
    site: Site = Field(default_factory=Site)
    granicus: Granicus = Field(default_factory=Granicus)
    bodies: list[BodyConfig] = Field(default_factory=list)
    projects: Projects = Field(default_factory=Projects)
    extraction: Extraction = Field(default_factory=Extraction)
    display: Display = Field(default_factory=Display)
    features: Features = Field(default_factory=Features)

    @model_validator(mode="after")
    def _check(self) -> "JurisdictionConfig":
        keys = [b.key for b in self.bodies]
        if len(keys) != len(set(keys)):
            raise ValueError(f"duplicate body keys: {keys}")
        colors = [b.color for b in self.bodies if b.color is not None]
        if len(colors) != len(set(colors)):
            raise ValueError(f"body colors must be unique: {colors}")
        titles: dict[str, str] = {}
        # a title alias is how the members roster tells which body a person
        # sits on ("Chair McKay" -> Board of Supervisors), so the same alias
        # word on two bodies would file one body's officer under the other
        alias_body: dict[str, str] = {}
        for b in self.bodies:
            if b.roster:
                for role_key, role in b.roster.roles.items():
                    if role.title in titles and titles[role.title] != b.key:
                        raise ValueError(
                            f"roster title {role.title!r} is used by both "
                            f"{titles[role.title]} and {b.key}; titles must be unique")
                    titles[role.title] = b.key
                    for alias in role.aliases:
                        other = alias_body.setdefault(alias.lower(), b.key)
                        if other != b.key:
                            raise ValueError(
                                f"roster alias {alias!r} is used by both {other} and {b.key}; "
                                "qualify it (e.g. 'Commission Chair')")
                    for other in role.also:
                        if other not in b.roster.roles:
                            raise ValueError(
                                f"{b.key}.roster.roles.{role_key}.also names unknown role {other!r}")
        for view in self.granicus.views:
            if view.layout == "single":
                if not view.body:
                    raise ValueError(f"view {view.view_id}: layout 'single' needs a body")
                if view.body not in keys:
                    raise ValueError(f"view {view.view_id}: unknown body {view.body!r}")
            elif self.bodies and not any(b.archive_section for b in self.bodies):
                raise ValueError(
                    f"view {view.view_id}: layout 'sections' needs bodies[].archive_section")
        try:
            ZoneInfo(self.identity.timezone)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"unknown timezone {self.identity.timezone!r}") from exc
        if self.identity.geocode_bbox is not None and len(self.identity.geocode_bbox) != 4:
            raise ValueError("identity.geocode_bbox must be [min_lat, min_lng, max_lat, max_lng]")
        return self

    # --- accessors ---
    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.identity.timezone)

    @property
    def bodies_by_key(self) -> dict[str, BodyConfig]:
        return {b.key: b for b in self.bodies}

    def body(self, key: str) -> BodyConfig | None:
        return self.bodies_by_key.get(key)

    def view_for(self, view_id: str) -> GranicusView | None:
        for v in self.granicus.views:
            if v.view_id == str(view_id):
                return v
        return None

    @classmethod
    def load(cls, slug: str) -> "JurisdictionConfig":
        path = JURISDICTIONS_DIR / f"{slug}.yaml"
        if not path.exists():
            raise FileNotFoundError(f"no jurisdiction config at {path}")
        data = yaml.safe_load(path.read_text()) or {}
        data["slug"] = slug
        return cls.model_validate(data)

    def save(self) -> Path:
        """Write the config back (used by setup to pin discovered values)."""
        path = JURISDICTIONS_DIR / f"{self.slug}.yaml"
        data = self.model_dump(exclude={"slug"}, exclude_none=False)
        path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
        return path


def slug_from_env() -> str:
    # .env may carry JURISDICTION; config.py loads it too, but a caller can
    # import bodies (and so this) before config, so load it here as well
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:  # pragma: no cover
        pass
    return os.environ.get("JURISDICTION", DEFAULT_SLUG).strip() or DEFAULT_SLUG


@functools.lru_cache(maxsize=1)
def current() -> JurisdictionConfig:
    """The process's jurisdiction, from JURISDICTION (default: the City)."""
    slug = slug_from_env()
    try:
        return JurisdictionConfig.load(slug)
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"JURISDICTION={slug!r} has no config under {JURISDICTIONS_DIR} "
            "(set JURISDICTIONS_DIR to the directory holding <slug>.yaml)") from exc


def available() -> list[str]:
    """Slugs of every config on disk."""
    return sorted(p.stem for p in JURISDICTIONS_DIR.glob("*.yaml"))
