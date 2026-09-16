"""Roster header parsers — agenda header format drift would silently stop
person seeding, degrading vote/commentary resolution for new meetings."""
from councilhound.seed import parse_council_header, parse_pc_header, parse_school_board_header

COUNCIL_HEADER = """City Council Meeting

City of Fairfax, Virginia

City Council Meeting Agenda

Mayor

 Catherine S. Read

City Council

Anthony T. Amos

Billy M. Bates

Stacy R. Hall

City Council Regular Meeting
COUNCIL CHAMBERS
Tuesday, July 7, 2026
"""

PC_HEADER = (
    "Planning Commission Regular Meeting/Work Session "
    "Chair: James Feather / Vice-Chair: Kirsten Lockhart / "
    "Commissioners: Betsy Briggs, Anthony Coleman, Paul Cunningham "
    "1. Pledge of Allegiance."
)


def test_parse_council_header():
    parsed = parse_council_header(COUNCIL_HEADER)
    assert parsed["mayor"] == "Catherine S. Read"
    assert parsed["members"] == ["Anthony T. Amos", "Billy M. Bates", "Stacy R. Hall"]


def test_parse_council_header_absent():
    parsed = parse_council_header("Some other document\nwith no roster block\n")
    assert parsed == {"mayor": None, "members": []}


def test_parse_pc_header():
    parsed = parse_pc_header(PC_HEADER)
    assert parsed["chair"] == "James Feather"
    assert parsed["vice_chair"] == "Kirsten Lockhart"
    assert parsed["commissioners"] == ["Betsy Briggs", "Anthony Coleman", "Paul Cunningham"]


# html_to_text output of a School Board agenda header: the two-column member
# layout collapses to two names per line (verified against 2021-2026 agendas).
SCHOOL_BOARD_HEADER = """City of Fairfax, Virginia
School Board Meeting Agenda

Chair

Carolyn Pitches

Board Members

Lauren Bartelme Kristina Cecere

Amit Hickman Sarah Kelsey 

School Board Regular Meeting
City Hall
Wednesday, July 1, 2026
"""


def test_parse_school_board_header():
    parsed = parse_school_board_header(SCHOOL_BOARD_HEADER)
    assert parsed["chair"] == "Carolyn Pitches"
    assert parsed["members"] == ["Lauren Bartelme", "Kristina Cecere", "Amit Hickman", "Sarah Kelsey"]


def test_parse_school_board_header_title_first_variant():
    # 2025 agendas title the meeting "Regular School Board Meeting" — four
    # capitalised words right after the roster, which must not become names
    parsed = parse_school_board_header(
        SCHOOL_BOARD_HEADER.replace("School Board Regular Meeting", "Regular School Board Meeting"))
    assert parsed["members"] == ["Lauren Bartelme", "Kristina Cecere", "Amit Hickman", "Sarah Kelsey"]


def test_parse_school_board_header_chairman_variant():
    parsed = parse_school_board_header(SCHOOL_BOARD_HEADER.replace("Chair\n", "Chairman\n"))
    assert parsed["chair"] == "Carolyn Pitches"


def test_parse_school_board_header_absent():
    assert parse_school_board_header("Planning Commission Regular Meeting\nChair: X / Vice-Chair: Y\n") == {
        "chair": None, "members": [],
    }
