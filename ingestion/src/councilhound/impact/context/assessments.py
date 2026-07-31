"""Patriot Properties WebPro assessment client (realestate.fairfaxva.gov).

The city publishes no bulk assessment layer (the GeoHub Parcels service has
no value fields), so the fiscal module pulls the handful of records an
evaluation needs — the site parcels plus the multifamily comp set — from
the public WebPro search UI, politely (~1 req/s) and cached to disk.

Privacy: Virginia makes these records public, but per the project guardrail
owner names are neither parsed nor stored — only parcel id, values, areas,
units, and year built.

The server negotiates legacy TLS (renegotiation + old cipher suites) that
OpenSSL 3 rejects by default, hence the custom SSL context.
"""
from __future__ import annotations

import json
import logging
import re
import ssl
import time
import urllib.parse
import urllib.request
from datetime import date
from http.cookiejar import CookieJar

from councilhound.impact.cache import atomic_write_json, raw_path
from councilhound.impact.pins import norm_pin, pins_match

log = logging.getLogger(__name__)

BASE = "https://realestate.fairfaxva.gov/"
REQUEST_DELAY_S = 1.0
APARTMENT_LUC = "352"

# WebPro's ASP only applies filters when the WHOLE form is present — a
# request carrying just one Search* field paginates the entire city.
FORM_FIELDS = (
    "SearchParcel", "SearchAccountNumber", "SearchOwner", "SearchStreetNumber",
    "SearchStreetName", "SearchBuildingType", "SearchYearBuilt", "SearchYearBuiltThru",
    "SearchLotSize", "SearchLotSizeThru", "SearchTotalValue", "SearchTotalValueThru",
    "SearchBedrooms", "SearchBedroomsThru", "SearchBathrooms", "SearchBathroomsThru",
    "SearchFinSize", "SearchFinSizeThru", "SearchLUC", "SearchLUCDescription",
    "SearchNeighborhood", "SearchNBHDescription", "SearchSaleDate", "SearchSaleDateThru",
    "SearchSalePrice", "SearchSalePriceThru", "SearchBook", "SearchPage",
)


class WebProClient:
    def __init__(self):
        ctx = ssl.create_default_context()
        ctx.minimum_version = ssl.TLSVersion.TLSv1
        ctx.set_ciphers("DEFAULT:@SECLEVEL=0")
        ctx.options |= 0x4  # OP_LEGACY_SERVER_CONNECT
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=ctx),
            urllib.request.HTTPCookieProcessor(CookieJar()),
        )
        self._opener.addheaders = [
            ("User-Agent", "Mozilla/5.0 (compatible; CouncilHound/0.1; +https://councilhound.net)")]
        self._last = 0.0

    def _get(self, path: str, params: dict | None = None) -> str:
        wait = self._last + REQUEST_DELAY_S - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        url = BASE + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        with self._opener.open(url, timeout=45) as resp:
            return resp.read().decode("latin-1")

    # -- search results ----------------------------------------------------
    def search(self, **criteria) -> list[dict]:
        """criteria: WebPro Search* form fields, e.g. SearchParcel,
        SearchLUC, SearchYearBuilt/Thru. % is the wildcard. Returns the
        first result page (52 rows) — every query this module issues is
        narrow, and the server's session-bound paging is unreliable enough
        that following it can walk the whole city. Owner column is
        intentionally not parsed."""
        params = {field: "" for field in FORM_FIELDS}
        params.update({"SearchSubmitted": "yes", **criteria})
        html = self._get("SearchResults.asp", params)
        rows = list(self._parse_results(html))
        match = re.search(r"page \d+ of (\d+)", html)
        if match and int(match.group(1)) > 1:
            log.warning("WebPro search %s spans %s pages; only the first page is used "
                        "— narrow the criteria", criteria, match.group(1))
        return rows

    _CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
    _ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
    _ACCT = re.compile(r"Summary\.asp\?AccountNumber=(\d+)")

    def _parse_results(self, html: str):
        for row_html in self._ROW.findall(html):
            acct = self._ACCT.search(row_html)
            if not acct:
                continue
            cells = [re.sub(r"<[^>]+>|&nbsp;?", " ", c) for c in self._CELL.findall(row_html)]
            cells = [re.sub(r"\s+", " ", c).strip() for c in cells]
            # columns: parcel, address, owner, yearbuilt+type, total value,
            # beds/baths, areas, LUC + desc, neighborhood, book-page
            if len(cells) < 8:
                continue
            value = re.search(r"\$([\d,]+)", " ".join(cells))
            year = re.match(r"(\d{4})", cells[3] or "")
            luc = re.match(r"(\d+)\s+(.*)", cells[7] or "")
            yield {
                "account": acct.group(1),
                "pin": re.sub(r"\s+", " ", cells[0]).strip(),
                "address": cells[1],
                "year_built": int(year.group(1)) if year else None,
                "total_value": float(value.group(1).replace(",", "")) if value else None,
                "luc": luc.group(1) if luc else None,
                "luc_description": luc.group(2).strip() if luc else (cells[7] or None),
            }

    # -- parcel detail -----------------------------------------------------
    def detail(self, account: str) -> dict:
        """Summary-page facts for one account. WebPro keeps the 'current
        parcel' in session state: hit Summary.asp first, then read the
        bottom frame."""
        cached = raw_path("assessments", "webpro", f"account_{account}.json")
        if cached.exists():
            return json.loads(cached.read_text())
        self._get("Summary.asp", {"AccountNumber": account})
        html = self._get("summary-bottom.asp")
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>|&nbsp;?", " ", html))

        def grab(pattern, cast=float):
            m = re.search(pattern, text)
            if not m:
                return None
            raw = m.group(1).replace(",", "")
            try:
                return cast(raw)
            except ValueError:
                return None

        record = {
            "account": account,
            "pin": (re.search(r"Parcel ID\s+([\d]+ [\d ]*?[\dA-Z]+?)\s+Old Parcel", text)
                    or re.search(r"Parcel ID\s+(\S[^O]*?)\s+Old Parcel", text)),
            "value_year": grab(r"Value Year\s+([\d,]+)", int),
            "building_value": grab(r"Building Value\s+([\d,]+)"),
            "land_value": grab(r"Land Value\s+([\d,]+)"),
            "total_value": grab(r"Total Value\s+([\d,]+)"),
            "acres": grab(r"([\d.]+)\s+ACRES"),
            "residential_units": grab(r"(\d+)\s+residential unit", int),
            "commercial_units": grab(r"(\d+)\s+commercial unit", int),
            "year_built": grab(r"built about\s+(\d{4})", int),
        }
        record["pin"] = (re.sub(r"\s+", " ", record["pin"].group(1)).strip()
                         if record["pin"] else None)
        atomic_write_json(cached, record)
        return record

    # -- higher-level queries ---------------------------------------------
    def discover_lucs(self, description_like: str) -> list[tuple[str, str]]:
        """Distinct (code, description) land-use codes whose description matches
        a wildcard pattern, e.g. "%CONDO%". Used once per jurisdiction by
        impact-probe-luc so a human can pin the right code in the YAML —
        WebPro publishes no code list."""
        rows = self.search(SearchLUCDescription=description_like)
        seen: dict[str, str] = {}
        for row in rows:
            if row.get("luc"):
                seen.setdefault(row["luc"], row.get("luc_description") or "")
        return sorted(seen.items())

    def residential_comps(self, built_since: int, luc: str = APARTMENT_LUC,
                          unit_mode: str = "per_building",
                          year_window: int = 0) -> list[dict]:
        """Residential comps of one assessment class built since `built_since`,
        carrying per-unit assessed values.

        unit_mode="per_building" (apartments): one account holds the whole
        building, so per-unit value is total / residential_units.
        unit_mode="per_account" (condos): each unit is its own account, so the
        account's total value IS the per-unit value.

        `year_window` splits the query into N-year slices. WebPro returns only
        the first result page (52 rows), and condo classes have far more
        accounts than apartment buildings do, so windowing is how a condo
        query stays inside one page per slice.
        """
        this_year = date.today().year
        windows = []
        if year_window and year_window > 0:
            start = built_since
            while start <= this_year:
                windows.append((start, min(start + year_window - 1, this_year)))
                start += year_window
        else:
            windows.append((built_since, 2100))

        rows: list[dict] = []
        seen_accounts: set[str] = set()
        for lo, hi in windows:
            for row in self.search(SearchLUC=luc, SearchYearBuilt=str(lo),
                                   SearchYearBuiltThru=str(hi)):
                if row["account"] not in seen_accounts:
                    seen_accounts.add(row["account"])
                    rows.append(row)

        comps = []
        for row in rows:
            det = self.detail(row["account"])
            units = det.get("residential_units")
            total = det.get("total_value") or row.get("total_value")
            if not total:
                log.info("comp %s (%s) lacks value — skipped", row["pin"], row.get("address"))
                continue
            if unit_mode == "per_account":
                # a condo account is a single dwelling; some carry units=1,
                # some carry none at all
                if units and units > 1:
                    per_unit = total / units
                else:
                    per_unit = total
                    units = units or 1
            elif units and units > 0:
                per_unit = total / units
            else:
                log.info("comp %s (%s) lacks units — skipped", row["pin"], row.get("address"))
                continue
            comps.append({**det, "total_value": total, "residential_units": units,
                          "luc": row.get("luc"), "per_unit_value": per_unit})
        return comps

    def multifamily_comps(self, built_since: int) -> list[dict]:
        """Apartment-class comps (LUC 352). Kept as the historical entry
        point; residential_comps is the general form."""
        return self.residential_comps(built_since, luc=APARTMENT_LUC,
                                      unit_mode="per_building")

    def assessment_for_pin(self, pin: str) -> dict | None:
        """Site-parcel lookup. Documents hyphenate PINs, GeoHub pads groups
        with spaces, and WebPro pads differently again — compare canonical
        forms (councilhound.impact.pins) and fall back to a wildcarded query
        built from the canonical groups."""
        groups = norm_pin(pin).split()
        for query in (pin, "%".join(groups) + "%"):
            rows = self.search(SearchParcel=query)
            for row in rows:
                if pins_match(row["pin"], pin):
                    return self.detail(row["account"])
            if rows and len(rows) == 1:
                return self.detail(rows[0]["account"])
        return None
