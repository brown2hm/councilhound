"""County roster parsing: last names + districts on the annotated agenda,
resolved against the pinned roster."""
from councilhound.bodies import Registry
from councilhound.jurisdiction import JurisdictionConfig
from councilhound.seed import parse_roster, surname_forms

AGENDA = """FAIRFAX COUNTY
BOARD OF SUPERVISORS
August 25, 2026
AGENDA
10:00
Done
Matters Presented by Board Members
1.
Done
Chairman McKay
2.
Done
Supervisor Smith, Sully District
3.
Done
Supervisor Sizemore Heizer, Braddock District
4.
Done
Supervisor Bierman, Dranesville District
5.
Done
Supervisor Nobody, Nowhere District
"""


def county_body():
    cfg = JurisdictionConfig.load("fairfax_county_va")
    return Registry.from_config(cfg).bodies["board_of_supervisors"]


def test_bos_lines_resolve_against_static_roster():
    body = county_body()
    roster = parse_roster(AGENDA, body)
    assert roster["chairman"] == ["Jeffrey C. McKay"]
    assert roster["supervisor"] == ["Kathy L. Smith", "Rachna Sizemore Heizer", "James N. Bierman, Jr."]


def test_bos_falls_back_to_the_static_roster_when_nothing_parses():
    body = county_body()
    roster = parse_roster("Agenda with no member block", body)
    assert roster["chairman"] == ["Jeffrey C. McKay"] and len(roster["supervisor"]) == 9


def test_surname_forms_handle_two_word_surnames_and_suffixes():
    assert surname_forms("Rachna Sizemore Heizer") == ["Heizer", "Sizemore Heizer"]
    assert surname_forms("James N. Bierman, Jr.") == ["Bierman"]
    assert surname_forms("Pat Herrity") == ["Herrity"]
    assert surname_forms("Catherine S. Read") == ["Read"]


def test_seed_titles_for_county_roles():
    body = county_body()
    assert body.seed_titles("chairman") == ["Chairman", "Chair"]
    assert body.seed_titles("supervisor") == ["Supervisor"]


DISTRICTS = {"Braddock", "Dranesville", "Franconia", "Hunter Mill", "Mason",
             "Mount Vernon", "Providence", "Springfield", "Sully"}


def pc_body():
    cfg = JurisdictionConfig.load("fairfax_county_va")
    return Registry.from_config(cfg).bodies["planning_commission"]


def test_pc_roster_is_the_full_commission():
    """Twelve seats: one per supervisor district plus three at-large, with
    one chair and one vice chair (minutes of 2026-04-22 and 2026-06-24)."""
    static = pc_body().roster.static
    names = [m.name for m in static]
    assert len(static) == 12 and len(set(names)) == 12
    seats = [m.district for m in static]
    assert set(seats) - {"At-Large"} == DISTRICTS and seats.count("At-Large") == 3
    assert [m.name for m in static if m.role == "chair"] == ["Phillip A. Niedzielski-Eichner"]
    assert [m.name for m in static if m.role == "vice_chair"] == ["Evelyn S. Spain"]


def test_pc_roster_parses_without_an_agenda_block():
    roster = parse_roster("FAIRFAX COUNTY PLANNING COMMISSION MEETING AGENDA ...", pc_body())
    assert roster["chair"] == ["Phillip A. Niedzielski-Eichner"]
    assert roster["vice_chair"] == ["Evelyn S. Spain"]
    assert len(roster["commissioner"]) == 10


def test_district_aliases_skip_at_large_seats():
    from councilhound.seed import district_alias
    assert district_alias("Sully", "Commissioner") == "Sully District Commissioner"
    assert district_alias("Hunter Mill", "Supervisor") == "Hunter Mill District Supervisor"
    assert district_alias("At-Large", "Commissioner") is None
    assert district_alias(None, "Supervisor") is None


def test_seed_people_seeds_both_county_bodies(db_session, monkeypatch):
    """End to end under the County registry: the Board from its annotated
    agenda lines, the Commission from its pinned roster, each with the
    title and district aliases the record uses."""
    import datetime

    from councilhound import seed
    from councilhound.db.models import Document, Entity, EntityAlias, Meeting

    reg = Registry.from_config(JurisdictionConfig.load("fairfax_county_va"))
    monkeypatch.setattr(seed, "REGISTRY", reg)
    for i, (body, text) in enumerate([("board_of_supervisors", AGENDA),
                                      ("planning_commission", "PLANNING COMMISSION MEETING AGENDA")]):
        m = Meeting(granicus_clip_id=str(i), granicus_view_id="7", body=body, meeting_type="x",
                    meeting_date=datetime.date(2026, 9, 15), title=body)
        db_session.add(m)
        db_session.flush()
        db_session.add(Document(meeting_id=m.id, doc_type="agenda", source_url=f"https://x/{i}",
                                raw_text=text))
    db_session.commit()

    seed.seed_people(db_session)

    def aliases(name):
        e = db_session.query(Entity).filter_by(name=name).one()
        return {a.alias for a in db_session.query(EntityAlias).filter_by(entity_id=e.id)}

    spain = aliases("Evelyn Spain")
    assert {"Commission Vice Chair Spain", "Vice Chair Spain", "Commissioner Spain",
            "Sully District Commissioner"} <= spain
    chair = aliases("Phillip Niedzielski-Eichner")
    assert {"Commission Chair Niedzielski-Eichner", "Commissioner Niedzielski-Eichner"} <= chair
    assert not any("At-Large" in a for a in chair)
    assert "Sully District Supervisor" in aliases("Kathy Smith")
    assert "Chairman McKay" in aliases("Jeffrey McKay")
    people = db_session.query(Entity).filter_by(entity_type="person").count()
    assert people == 4 + 12  # the four Board members the agenda names, the full Commission


def county_pc():
    cfg = JurisdictionConfig.load("fairfax_county_va")
    return Registry.from_config(cfg).bodies["planning_commission"]


def test_hunter_mill_seat_is_paul_d_thomas():
    names = {m.name: m.district for m in county_pc().roster.static}
    assert names["Paul D. Thomas"] == "Hunter Mill" and names["James Thomas"] == "Springfield"
    assert "John A. Carter" not in names and len(names) == 12


def test_two_thomases_get_no_surname_alias(db_session):
    from sqlalchemy import select

    from councilhound.db.models import Entity, EntityAlias
    from councilhound.seed import _seed_person, drop_ambiguous_surname_aliases, shared_surnames

    body = county_pc()
    assert shared_surnames(body) == {"thomas"}
    titles = body.seed_titles("commissioner")
    # James was seeded before the shared surname existed: he holds the aliases
    _seed_person(db_session, "James Thomas", titles, None, ("Springfield District Commissioner",))
    # Paul is seeded with the rule in force
    _seed_person(db_session, "Paul D. Thomas", titles, None, ("Hunter Mill District Commissioner",),
                 skip_surnames=shared_surnames(body))
    db_session.commit()
    assert drop_ambiguous_surname_aliases(db_session, body) == 2  # "Thomas", "Commissioner Thomas"
    db_session.commit()

    def aliases(name):
        e = db_session.scalar(select(Entity).where(Entity.name == name))
        return {a.alias for a in db_session.scalars(select(EntityAlias).where(EntityAlias.entity_id == e.id))}

    james, paul = aliases("James Thomas"), aliases("Paul Thomas")
    assert "Springfield District Commissioner" in james and "Hunter Mill District Commissioner" in paul
    assert not {"Thomas", "Commissioner Thomas"} & (james | paul)
    # nobody answers to the ambiguous forms
    assert db_session.scalar(select(EntityAlias).where(EntityAlias.alias.in_(["Thomas", "Commissioner Thomas"]))) is None


def test_district_alias_follows_the_seat(db_session):
    from sqlalchemy import select

    from councilhound.db.models import Entity, EntityAlias
    from councilhound.seed import _seed_person, move_district_aliases

    body = county_pc()
    titles = body.seed_titles("commissioner")
    # the seat's previous holder was seeded with its alias
    _seed_person(db_session, "John A. Carter", titles, None, ("Hunter Mill District Commissioner",))
    _seed_person(db_session, "Paul D. Thomas", titles, None, ("Hunter Mill District Commissioner",))
    db_session.commit()
    move_district_aliases(db_session, body)
    db_session.commit()
    row = db_session.scalar(select(EntityAlias).where(EntityAlias.alias == "Hunter Mill District Commissioner"))
    assert db_session.get(Entity, row.entity_id).name == "Paul Thomas"
    assert move_district_aliases(db_session, body) == 0  # settled
