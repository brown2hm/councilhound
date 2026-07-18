"""BLS Consumer Expenditure Survey category spending — static reference table.

Average annual spending per consumer unit from the CES 2023 tables (released
September 2024), mapped onto the POI taxonomy the Huff model runs over.
Household spending is scaled by the ratio of local household income to the
CES average pre-tax income, and the whole table carries a single sensitivity
assumption (ces_scale) rather than pretending each line item is precise —
these are screening inputs, not a budget.

Line items and their CES table names are recorded so an auditor can trace
each figure to the publication.
"""
from __future__ import annotations

from councilhound.impact.provenance import prov
from councilhound.impact.schemas import Provenance

CES_YEAR = "2023"
CES_URL = "https://www.bls.gov/cex/tables.htm"
CES_AVG_PRETAX_INCOME = 101_805.0  # CES 2023: income before taxes per consumer unit

# category -> (annual $ per consumer unit, CES line item(s))
CATEGORY_SPEND: dict[str, tuple[float, str]] = {
    "grocery": (5_703.0, "Food at home"),
    "restaurant_bar": (3_933.0, "Food away from home"),
    "retail_comparison": (4_649.0, "Apparel and services + household furnishings and equipment"),
    "retail_convenience": (950.0, "Personal care products and services (products share)"),
    "personal_services": (1_100.0, "Personal services incl. laundry/cleaning, haircare services"),
    "entertainment": (3_635.0, "Entertainment"),
}


def provenance() -> Provenance:
    return prov(
        f"BLS Consumer Expenditure Survey {CES_YEAR}, average annual expenditures "
        "per consumer unit", CES_URL, CES_YEAR,
        "line items: " + "; ".join(f"{k}: {v[1]}" for k, v in CATEGORY_SPEND.items()),
    )


def category_spend_per_household(hh_income: float) -> dict[str, float]:
    """Annual $ per household by category, income-scaled from the CES base."""
    scale = hh_income / CES_AVG_PRETAX_INCOME
    return {cat: amount * scale for cat, (amount, _) in CATEGORY_SPEND.items()}
