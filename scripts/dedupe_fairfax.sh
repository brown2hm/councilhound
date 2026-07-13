#!/bin/sh
# One-time curated entity merges for the Fairfax deployment (July 2026 audit).
# These are same-thread duplicates the normalization heuristics can't prove:
# multi-word suffixes, cross-type drift, and phrasing variants. Run after
# `dedupe-entities --apply`. Idempotent-ish: re-runs fail fast on missing
# source slugs, which just means the merge already happened.
#
# Usage: from ingestion/, with the target DATABASE_URL exported (or unset for
# the local dev DB):   sh ../scripts/dedupe_fairfax.sh
set -x

CLI="python -m councilhound.cli"
[ -x ../.venv/bin/python ] && CLI="../.venv/bin/python -m councilhound.cli"

PYTHONPATH=src $CLI merge-entity courthouse-plaza-shopping-center-redevelopment courthouse-plaza
PYTHONPATH=src $CLI merge-entity courthouse-plaza-mixed-use-development courthouse-plaza
PYTHONPATH=src $CLI merge-entity willard-sherwood-community-center-special-use-permit willard-sherwood-community-center
PYTHONPATH=src $CLI merge-entity willard-sherwood-community-center-potential-land-use-request willard-sherwood-community-center
PYTHONPATH=src $CLI merge-entity willard-sherwood-community-center-expansion willard-sherwood-community-center
PYTHONPATH=src $CLI merge-entity accessory-dwelling-units-zoning-options accessory-dwelling-units
PYTHONPATH=src $CLI merge-entity detached-accessory-dwelling-units-zoning-text-amendments detached-accessory-dwelling-units
PYTHONPATH=src $CLI merge-entity personnel-matters-closed-meeting personnel-matters
PYTHONPATH=src $CLI merge-entity boards-and-commissions-interviews-and-appointments boards-and-commissions-interviews
PYTHONPATH=src $CLI merge-entity fy26-budget-appropriation-resolutions fy26-budget
PYTHONPATH=src $CLI merge-entity urban-agriculture-zoning-text-amendments urban-agriculture
PYTHONPATH=src $CLI merge-entity 10300-willard-way-courthouse-plaza 10300-willard-way
