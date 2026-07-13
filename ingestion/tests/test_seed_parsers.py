"""Roster header parsers — agenda header format drift would silently stop
person seeding, degrading vote/commentary resolution for new meetings."""
from councilhound.seed import parse_council_header, parse_pc_header

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
