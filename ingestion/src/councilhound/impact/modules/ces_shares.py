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

# Approximate expenditure-income elasticities per category, consistent with
# the income gradients visible in the CE quintile tables (Engel tradition:
# necessities scale sublinearly with income, discretionary categories about
# linearly). Category spend scales as (income ratio)^elasticity rather than
# linearly, so a high-income tract no longer implies proportionally more
# grocery spending.
CATEGORY_ELASTICITY: dict[str, float] = {
    "grocery": 0.45,
    "restaurant_bar": 0.85,
    "retail_comparison": 0.95,
    "retail_convenience": 0.60,
    "personal_services": 0.90,
    "entertainment": 1.05,
}


def provenance() -> Provenance:
    return prov(
        f"BLS Consumer Expenditure Survey {CES_YEAR}, average annual expenditures "
        "per consumer unit", CES_URL, CES_YEAR,
        "line items: " + "; ".join(f"{k}: {v[1]}" for k, v in CATEGORY_SPEND.items())
        + "; income scaling uses per-category expenditure elasticities "
        + ", ".join(f"{k}={v}" for k, v in CATEGORY_ELASTICITY.items())
        + " (Engel gradients per CE quintile tables)",
    )


def category_spend_per_household(hh_income: float) -> dict[str, float]:
    """Annual $ per household by category, income-scaled from the CES base."""
    scale = hh_income / CES_AVG_PRETAX_INCOME
    return {cat: amount * scale for cat, (amount, _) in CATEGORY_SPEND.items()}
