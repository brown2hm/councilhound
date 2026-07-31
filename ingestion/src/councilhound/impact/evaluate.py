"""Evaluation orchestrator + lifecycle over ProjectEvaluation rows.

    extract  -> row(status=extracted)  + spec YAML emitted for human review
    confirm  -> status=confirmed       (the HITL gate; hand-edits welcome)
    evaluate -> status=computed        (deterministic modules)
             -> status=synthesized     (LLM narrative + validator)

Everything the frontend needs is persisted on the row; full-resolution
artifacts additionally land in DATA_DIR/impact/runs/<slug>/<ts>/ for audit.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from councilhound.db.models import CityProject, ProjectEvaluation
from councilhound.impact.cache import atomic_write_json, run_dir, specs_dir
from councilhound.impact.schemas import (EvaluationBundle, ExternalEstimate,
                                         ModuleResult, ProjectSpec)

log = logging.getLogger(__name__)

MAP_LAYERS_MAX_BYTES = 2 * 1024 * 1024  # hard guard: DB row + API payload budget

STATUS_ORDER = ("extracted", "confirmed", "computed", "synthesized")


def _project(session: Session, slug: str) -> CityProject:
    project = session.scalar(select(CityProject).where(CityProject.external_slug == slug))
    if project is None:
        raise SystemExit(
            f"no city project with slug '{slug}' — run `python -m councilhound.cli projects` "
            "first, or check `impact-status` / the development directory for slugs"
        )
    return project


def _evaluation(session: Session, project: CityProject) -> ProjectEvaluation | None:
    return session.scalar(select(ProjectEvaluation)
                          .where(ProjectEvaluation.city_project_id == project.id))


def _spec_yaml_path(slug: str):
    return specs_dir() / f"{slug}.yaml"


def extract(session: Session, slug: str, jurisdiction: str = "fairfax_city_va",
            force: bool = False) -> str:
    from councilhound.impact.intake.documents import gather_documents
    from councilhound.impact.intake.extractor import (
        DEFAULT_MODEL, EXTRACT_PROMPT_VERSION, extract_spec_fields,
    )
    from councilhound.impact.intake.parcels import ParcelResolutionError, resolve_site
    from councilhound.impact.jurisdiction import JurisdictionContext

    project = _project(session, slug)
    evaluation = _evaluation(session, project)
    if evaluation is not None and not force:
        raise SystemExit(f"evaluation for '{slug}' already exists (status={evaluation.status}) "
                         "— pass --force to re-extract")

    docs = gather_documents(project, session=session)
    extracted = extract_spec_fields(docs)

    ctx = JurisdictionContext(jurisdiction)
    pins, geometry, resolved_acres, method = [], None, None, None
    try:
        pins, geometry, resolved_acres, method, resolve_warnings = resolve_site(
            ctx, project, extracted["parcel_pins"])
        extracted["notes"].extend(resolve_warnings)
    except ParcelResolutionError as exc:
        extracted["notes"].append(str(exc))
        log.warning("%s", exc)

    fields = extracted["fields"]

    def val(dotted):
        return fields[dotted]["value"]

    strings = extracted.get("strings", {})
    corridor = None
    if (strings.get("corridor.street_name") or extracted.get("corridor_facilities")
            or val("corridor.length_ft") is not None):
        corridor = {
            "length_ft": val("corridor.length_ft"),
            "facilities": extracted.get("corridor_facilities", []),
            "street_name": strings.get("corridor.street_name"),
            "from_street": strings.get("corridor.from_street"),
            "to_street": strings.get("corridor.to_street"),
        }

    spec = ProjectSpec(
        name=project.name,
        jurisdiction=jurisdiction,
        city_project_slug=slug,
        source_url=project.detail_url,
        project_type=extracted["project_type"],
        status=project.official_status or "unknown",
        parcels=pins,
        document_pins=extracted["parcel_pins"],
        geometry=geometry,
        existing={
            "use": extracted["existing_use"],
            "sqft": val("existing.sqft"),
            "units": int(v) if (v := val("existing.units")) is not None else None,
            "assessed_value": val("existing.assessed_value"),
        },
        proposed={
            "units": int(v) if (v := val("proposed.units")) is not None else None,
            "retail_sqft": val("proposed.retail_sqft"),
            "office_sqft": val("proposed.office_sqft"),
            "stories": int(v) if (v := val("proposed.stories")) is not None else None,
            "acres": val("proposed.acres"),
            "parking_spaces": int(v) if (v := val("proposed.parking_spaces")) is not None else None,
            "affordable_units": int(v) if (v := val("proposed.affordable_units")) is not None else None,
            "corridor": corridor,
        },
        extraction_confidence={k: v["confidence"] for k, v in fields.items()},
        extraction_quotes={k: v["source_quote"] for k, v in fields.items() if v["source_quote"]},
        extraction_notes=extracted["conflicts"] + extracted["notes"]
        + ([f"parcels resolved via {method}; polygon area {resolved_acres:.2f} ac"]
           if method else []),
        documents=[d.provenance for d in docs],
    )

    # corridor projects: the corridor LINE is the analysis geometry — it
    # wins over any parcel polygon the documents' PINs resolved (street
    # plans routinely cite right-of-way/adjacent parcels). The human reviews
    # the method note at confirm; --geometry is the manual override.
    if (corridor and corridor["street_name"]
            and spec.project_type in ("street_multimodal", "park")):
        from councilhound.impact.intake.corridors import (
            CorridorResolutionError, resolve_corridor)
        try:
            geometry, length_ft, method = resolve_corridor(
                ctx, corridor["street_name"],
                corridor["from_street"], corridor["to_street"])
            if spec.geometry is not None:
                spec.extraction_notes.append(
                    "corridor line replaces the parcel polygon as the spec "
                    "geometry (resolved parcel PINs are kept on the spec)")
            spec.geometry = geometry
            spec.extraction_notes.append(
                f"corridor geometry resolved via {method}: {length_ft:,.0f} ft "
                "along the walk network")
            if spec.proposed.corridor.length_ft is None:
                spec.proposed.corridor.length_ft = round(length_ft)
                spec.extraction_notes.append(
                    "corridor length_ft filled from the resolved network path "
                    "(not document-stated)")
            else:
                # the corridor analog of the parcel acreage drift gate
                stated_ft = spec.proposed.corridor.length_ft
                drift = abs(length_ft - stated_ft) / stated_ft
                if drift > 0.30:
                    spec.extraction_notes.append(
                        f"WARNING: resolved corridor length {length_ft:,.0f} ft "
                        f"differs from document-stated {stated_ft:,.0f} ft by "
                        f"{drift:.0%} — trim the geometry or supply it with "
                        "`impact-confirm --geometry` before evaluating")
        except CorridorResolutionError as exc:
            spec.extraction_notes.append(str(exc))
            log.warning("%s", exc)

    # cross-check: resolved polygon vs. document-stated acreage (±15% gate
    # is advisory here — the human sees it at the confirm step)
    stated = spec.proposed.acres
    if stated and resolved_acres:
        drift = abs(resolved_acres - stated) / stated
        if drift > 0.15:
            spec.extraction_notes.append(
                f"WARNING: resolved parcel area {resolved_acres:.2f} ac differs from "
                f"stated {stated:.2f} ac by {drift:.0%}")

    if evaluation is None:
        evaluation = ProjectEvaluation(city_project_id=project.id)
        session.add(evaluation)
    evaluation.status = "extracted"
    evaluation.spec = spec.model_dump(mode="json")
    evaluation.extraction_model = DEFAULT_MODEL
    evaluation.extraction_prompt_version = EXTRACT_PROMPT_VERSION
    evaluation.confirmed_at = None
    evaluation.module_results = None
    evaluation.map_layers = None
    evaluation.report_markdown = None
    session.commit()

    path = _spec_yaml_path(slug)
    path.write_text(_spec_to_yaml(spec))
    summary = _confidence_summary(spec)
    return (f"extracted '{slug}' -> {path}\n{summary}\n"
            f"review the YAML (edit if needed), then: impact-confirm {slug}")


def _spec_to_yaml(spec: ProjectSpec) -> str:
    data = spec.model_dump(mode="json")
    header = (
        "# ProjectSpec awaiting human confirmation (impact-confirm).\n"
        "# Edit values freely — numbers you set here are treated as human-\n"
        "# confirmed. extraction_confidence/quotes document where LLM values\n"
        "# came from; notes list demotions and document conflicts.\n"
    )
    return header + yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def _confidence_summary(spec: ProjectSpec) -> str:
    lines = []
    for field, confidence in sorted(spec.extraction_confidence.items()):
        section, _, attr = field.partition(".")
        holder = (spec.proposed.corridor if section == "corridor"
                  else getattr(spec, section, None))
        value = getattr(holder, attr, None) if holder is not None else None
        quote = spec.extraction_quotes.get(field)
        lines.append(f"  {field:28} {str(value):>12}  [{confidence}]"
                     + (f'  "{quote}"' if quote else ""))
    return "\n".join(lines)


def confirm(session: Session, slug: str, spec_path: str | None = None,
            assume_yes: bool = False, geometry_path: str | None = None) -> str:
    import click

    project = _project(session, slug)
    evaluation = _evaluation(session, project)
    if evaluation is None:
        raise SystemExit(f"no extraction for '{slug}' — run impact-extract first")

    path = spec_path or _spec_yaml_path(slug)
    try:
        data = yaml.safe_load(open(path).read())
    except FileNotFoundError:
        raise SystemExit(f"spec YAML not found at {path} — re-run impact-extract") from None
    spec = ProjectSpec.model_validate(data)  # re-validate hand edits

    # manual geometry override: the recovery path when parcel/corridor
    # resolution fails or resolves the wrong extent
    if geometry_path:
        geo = json.loads(open(geometry_path).read())
        if geo.get("type") == "FeatureCollection":
            geo = geo["features"][0]
        if geo.get("type") == "Feature":
            geo = geo["geometry"]
        if "type" not in geo or "coordinates" not in geo:
            raise SystemExit(f"{geometry_path} is not GeoJSON geometry/Feature")
        spec.geometry = geo
        spec.extraction_notes.append(
            f"geometry supplied manually at confirm ({geo['type']})")
        _spec_yaml_path(slug).write_text(_spec_to_yaml(spec))

    # a human editing the parcel list is the expected fix for a wrong/partial
    # site polygon — re-resolve geometry from the (possibly edited) PINs
    stored = (evaluation.spec or {}).get("parcels") or []
    if geometry_path:
        pass  # manual geometry wins; skip re-resolution paths
    elif spec.parcels and (spec.parcels != stored or spec.geometry is None):
        from councilhound.impact.intake.parcels import ParcelResolutionError, resolve_site
        from councilhound.impact.jurisdiction import JurisdictionContext
        try:
            pins, geometry, acres, method, resolve_warnings = resolve_site(
                JurisdictionContext(spec.jurisdiction), project, spec.parcels)
            spec.parcels, spec.geometry = pins, geometry
            spec.extraction_notes.append(
                f"geometry re-resolved at confirm from edited parcels via {method}: "
                f"{acres:.2f} ac")
            spec.extraction_notes.extend(resolve_warnings)
            path_obj = _spec_yaml_path(slug)
            path_obj.write_text(_spec_to_yaml(spec))
        except ParcelResolutionError as exc:
            raise SystemExit(f"edited parcels failed to resolve: {exc}") from None
    elif (spec.proposed.corridor and spec.proposed.corridor.street_name
            and spec.project_type in ("street_multimodal", "park")
            and (spec.geometry is None
                 or spec.geometry.get("type") not in ("LineString", "MultiLineString"))):
        # corridor project without a corridor line (extraction-time resolution
        # failed, or a parcel polygon slipped in): snap with the current names
        from councilhound.impact.intake.corridors import (
            CorridorResolutionError, resolve_corridor)
        from councilhound.impact.jurisdiction import JurisdictionContext
        c = spec.proposed.corridor
        try:
            geometry, length_ft, method = resolve_corridor(
                JurisdictionContext(spec.jurisdiction),
                c.street_name, c.from_street, c.to_street)
            spec.geometry = geometry
            spec.extraction_notes.append(
                f"corridor geometry resolved at confirm via {method}: "
                f"{length_ft:,.0f} ft")
            _spec_yaml_path(slug).write_text(_spec_to_yaml(spec))
        except CorridorResolutionError as exc:
            click.echo(f"corridor resolution failed: {exc}")

    if not assume_yes:
        click.echo(_confidence_summary(spec))
        low = [f for f, c in spec.extraction_confidence.items() if c == "low"]
        if low:
            click.echo(f"low-confidence/unextracted fields: {', '.join(low)}")
        if spec.geometry is None:
            click.echo("NOTE: no site geometry resolved — spatial metrics will be skipped "
                       "unless you add parcels and re-extract")
        if not click.confirm(f"confirm spec for '{slug}'?"):
            raise SystemExit("not confirmed")

    evaluation.spec = spec.model_dump(mode="json")
    evaluation.status = "confirmed"
    evaluation.confirmed_at = datetime.now(timezone.utc)
    session.commit()
    return f"confirmed '{slug}' — next: impact-evaluate {slug}"


def _recover_document_pins(project, ctx) -> tuple[list[str], str]:
    """PIN-shaped tokens from the already-downloaded document corpus, kept only
    when they name a real parcel in the layer.

    Specs extracted before `document_pins` existed discarded the stated PINs
    whenever resolution fell through, so recovering them from the cached text
    is the only alternative to a fresh (LLM) extraction. The parcel-layer
    filter is what makes a bare regex safe: a PIN-shaped token that matches no
    parcel is dropped rather than resolved.
    """
    from councilhound.impact.intake.documents import gather_documents
    from councilhound.impact.pins import candidate_pins, norm_pin

    docs = gather_documents(project)  # disk-cached; no re-download, no LLM
    corpus = "\n".join(doc.text for doc in docs)
    known = {norm_pin(p) for p in ctx.parcels["pin"]}
    found = [p for p in candidate_pins(corpus) if p in known]
    return found, f"{len(docs)} cached document(s)"


def enrich(session: Session, slug: str, external: bool = False,
           tenure: bool = False) -> str:
    """Add narrowly-scoped extracted fields to an existing spec.

    The backfill path for specs predating a field. `impact-extract --force`
    would rewrite the whole YAML and discard hand edits, so this runs only the
    targeted extraction pass(es) and merges their results.
    """
    from councilhound.impact.intake.documents import gather_documents
    from councilhound.impact.intake.extractor import (
        TENURE_EVIDENCE, enforce_enum_firewall, extract_external_estimates,
        _call_claude, _build_prompt)

    if not external and not tenure:
        raise SystemExit("pass --external-estimates and/or --tenure")

    project = _project(session, slug)
    evaluation = _evaluation(session, project)
    if evaluation is None:
        raise SystemExit(f"no extraction for '{slug}' — run impact-extract first")
    spec = ProjectSpec.model_validate(evaluation.spec)

    docs = gather_documents(project, session=session)
    lines = [f"{slug}: {len(docs)} document(s) in corpus"]

    if external:
        estimates, notes = extract_external_estimates(docs, project_name=project.name)
        spec.external_estimates = [ExternalEstimate.model_validate(e) for e in estimates]
        spec.extraction_notes.extend(notes)
        for e in spec.external_estimates:
            span = ""
            if e.net_annual_low is not None or e.net_annual_high is not None:
                span = (f" net ${(e.net_annual_low or 0):,.0f}"
                        f"-${(e.net_annual_high or 0):,.0f}/yr")
            lines.append(f"  external [{e.kind}] {e.source}{span}")
            lines.append(f"      \"{e.quote}\"")
        for note in notes:
            lines.append(f"  ! {note}")

    if tenure:
        corpus = "\n".join(d.text for d in docs)
        raw = _call_claude(_build_prompt(docs))
        entry, notes = enforce_enum_firewall(
            raw.get("proposed_tenure"), corpus, "proposed.tenure", TENURE_EVIDENCE)
        spec.proposed.tenure = entry["value"]
        if entry["value"]:
            spec.extraction_confidence["proposed.tenure"] = entry["confidence"]
            if entry["source_quote"]:
                spec.extraction_quotes["proposed.tenure"] = entry["source_quote"]
        spec.extraction_notes.extend(notes)
        lines.append(f"  tenure: {entry['value']} [{entry['confidence']}]"
                     + (f'  "{entry["source_quote"]}"' if entry["source_quote"] else ""))
        for note in notes:
            lines.append(f"  ! {note}")

    evaluation.spec = spec.model_dump(mode="json")
    if evaluation.status in ("computed", "synthesized"):
        evaluation.status = "confirmed"
    session.commit()
    _spec_yaml_path(slug).write_text(_spec_to_yaml(spec))
    lines.append(f"wrote {_spec_yaml_path(slug)}; next: impact-confirm {slug} then "
                 f"impact-evaluate {slug} --force")
    return "\n".join(lines)


def _trim_to_stated_acreage(ctx, candidates: list[str], stated: float,
                            gate: float = 0.15, max_drop: int = 2,
                            tie: float = 0.03,
                            ) -> tuple[list[str], list[str], list[list[str]]]:
    """Drop up to `max_drop` candidate parcels when doing so brings the site
    area materially closer to the document-stated acreage.

    Returns (kept, dropped, ties). A set already inside the drift gate is left
    alone — the goal is to catch the cross-referenced-neighbour case, not to
    optimize against a figure that is itself approximate ("1.78 +/- acres").

    Similarly-sized parcels make this genuinely ambiguous: at City Centre West
    two candidates are both ~0.34 ac, so dropping either one fits the stated
    1.78 ac equally well while naming a different site. When that happens the
    alternatives are returned in `ties` and the caller must not pick one —
    acreage cannot settle it, and guessing produces a confident wrong answer.
    """
    from itertools import combinations

    def drift(pins):
        acres = _resolved_acres(ctx, pins)
        return None if acres is None else abs(acres - stated) / stated

    best = drift(candidates)
    if best is None or best <= gate:
        return candidates, [], []

    scored: list[tuple[float, list[str], list[str]]] = []
    for size in range(1, min(max_drop, len(candidates) - 1) + 1):
        for combo in combinations(candidates, size):
            subset = [p for p in candidates if p not in combo]
            d = drift(subset)
            if d is not None and d < best - 0.02:  # a real improvement, not noise
                scored.append((d, subset, list(combo)))
        if scored and min(s[0] for s in scored) <= gate:
            break
    if not scored:
        return candidates, [], []

    scored.sort(key=lambda s: s[0])
    best_drift, kept, dropped = scored[0]
    # any equally-good subset that names a DIFFERENT set of parcels is a tie
    ties = [subset for d, subset, _ in scored[1:]
            if d <= best_drift + tie and set(subset) != set(kept)]
    return kept, dropped, ties


def _resolved_acres(ctx, pins) -> float | None:
    """Projected-CRS acreage of the parcels currently on a spec, for the
    no-regression comparison. None when none of them match the layer.

    Union, not sum: stacked condominium records share one footprint, and
    summing per-parcel areas counts it once per unit."""
    from shapely.ops import unary_union

    from councilhound.impact.pins import norm_pin

    if not pins:
        return None
    wanted = {norm_pin(p) for p in pins}
    parcels = ctx.parcels
    hit = parcels[parcels["pin"].map(norm_pin).isin(wanted)]
    if not len(hit):
        return None
    projected = hit.geometry.to_crs(ctx.cfg.crs_projected)
    return float(unary_union(list(projected)).area / 43_560.0)


def reresolve(session: Session, slugs: tuple[str, ...] = (),
              all_specs: bool = False, apply: bool = False) -> str:
    """Re-run parcel resolution for existing specs after the PIN-normalization
    fix, without re-extracting.

    `impact-extract --force` would rewrite the whole spec YAML and discard
    every hand edit, so this walks the narrower path: recover the stated PINs,
    re-resolve geometry from them, and touch only parcels/document_pins/
    geometry. Dry-run by default — the printed diff is the review artifact.
    """
    from councilhound.impact.intake.parcels import ParcelResolutionError, resolve_site
    from councilhound.impact.jurisdiction import JurisdictionContext
    from councilhound.impact.pins import norm_pin

    if not slugs and not all_specs:
        raise SystemExit("pass project slugs or --all")

    query = (select(CityProject.external_slug, ProjectEvaluation)
             .join(ProjectEvaluation, ProjectEvaluation.city_project_id == CityProject.id))
    if slugs:
        query = query.where(CityProject.external_slug.in_(slugs))
    rows = session.execute(query).all()
    missing = set(slugs) - {slug for slug, _ in rows}
    if missing:
        raise SystemExit(f"no evaluation for: {', '.join(sorted(missing))}")

    contexts: dict[str, object] = {}
    lines: list[str] = []
    changed = 0
    for slug, evaluation in sorted(rows, key=lambda row: row[0]):
        spec = ProjectSpec.model_validate(evaluation.spec)
        if spec.project_type in ("street_multimodal", "park"):
            lines.append(f"{slug}: skipped (corridor project — geometry is a line)")
            continue
        ctx = contexts.setdefault(spec.jurisdiction,
                                  JurisdictionContext(spec.jurisdiction))
        project = _project(session, slug)

        # a spec whose current parcels already fit the stated acreage needs no
        # churn — this is also what keeps a hand-set parcel list (the human
        # answer to an earlier REVIEW) from being re-flagged on every sweep
        current_acres = _resolved_acres(ctx, spec.parcels)
        if (spec.proposed.acres and current_acres is not None
                and abs(current_acres - spec.proposed.acres) / spec.proposed.acres <= 0.15):
            lines.append(f"{slug}: unchanged ({len(spec.parcels)} parcel(s), "
                         f"{current_acres:.2f} ac fits stated "
                         f"{spec.proposed.acres:.2f} ac)")
            continue

        stated = list(spec.document_pins)
        source = "spec.document_pins"
        if not stated:
            stated, source = _recover_document_pins(project, ctx)
        candidates = list(dict.fromkeys(
            [norm_pin(p) for p in stated] + [norm_pin(p) for p in spec.parcels]))
        if not candidates:
            lines.append(f"{slug}: no candidate PINs (from {source}) — unchanged")
            continue

        # A regex over the corpus also picks up parcels the documents merely
        # cross-reference (an adjacent property, a neighbouring driveway in a
        # traffic study). The document-stated acreage is the independent check:
        # when the full candidate set overshoots it, drop the one or two
        # candidates whose removal best restores the fit.
        stated_acres = spec.proposed.acres
        trimmed: list[str] = []
        if stated_acres and len(candidates) > 1:
            candidates, trimmed, ties = _trim_to_stated_acreage(
                ctx, candidates, stated_acres)
            if ties:
                # print what DIFFERS between the tied subsets, not every pin —
                # a large condo block would otherwise dump hundreds per line
                all_sets = [set(candidates)] + [set(t) for t in ties]
                common = set.intersection(*all_sets)
                pool_set = set(candidates) | set(trimmed)
                alternatives = "\n".join(
                    "      without " + ", ".join(sorted(pool_set - s)[:8])
                    for s in all_sets)
                pool = sorted(set(candidates) | set(trimmed))
                shown = ", ".join(pool[:12]) + (f", ... and {len(pool) - 12} more"
                                                if len(pool) > 12 else "")
                lines.append(
                    f"{slug}: REVIEW — several parcel sets fit the stated "
                    f"{stated_acres:.2f} ac equally well ({len(common)} pins in "
                    "common), so acreage cannot say which is the site. Set "
                    "`parcels:` by hand from the documents and run impact-confirm.\n"
                    f"    candidates  {shown}\n"
                    f"    equally-good subsets:\n{alternatives}")
                continue

        try:
            pins, geometry, acres, method, warnings = resolve_site(ctx, project, candidates)
        except ParcelResolutionError as exc:
            lines.append(f"{slug}: resolution failed — {exc}")
            continue
        if trimmed:
            warnings.append(
                f"dropped candidate parcel(s) {', '.join(trimmed)}: the documents "
                "mention them, but including them puts the site area further from "
                f"the stated {stated_acres:.2f} ac (they are most likely "
                "cross-referenced neighbours rather than part of the site)")

        old_pins = [norm_pin(p) for p in spec.parcels]
        if [norm_pin(p) for p in pins] == old_pins:
            lines.append(f"{slug}: unchanged ({len(pins)} parcel(s), {acres:.2f} ac)")
            continue

        from councilhound.impact.modules.fiscal import _giscama_values
        old_av = sum(_giscama_values(ctx, spec.parcels).values())
        new_av = sum(_giscama_values(ctx, pins).values())
        stated_acres = spec.proposed.acres

        # no-regression guard. Recovered PINs are only as good as the regex
        # that found them: a document naming an adjacent or superseded parcel
        # produces a candidate set that resolves to the wrong extent. The
        # document-stated acreage is the independent check, so a proposal that
        # fits it WORSE than the current geometry is reported for human
        # attention rather than offered as a fix.
        drift_note = ""
        if stated_acres:
            old_acres = _resolved_acres(ctx, spec.parcels)
            new_drift = abs(acres - stated_acres) / stated_acres
            old_drift = (abs(old_acres - stated_acres) / stated_acres
                         if old_acres is not None else None)
            drift_note = (f", stated {stated_acres:.2f} ac (drift "
                          + (f"{old_drift:.0%} -> " if old_drift is not None else "")
                          + f"{new_drift:.0%})")
            if old_drift is not None and new_drift > old_drift + 0.02:
                lines.append(
                    f"{slug}: REVIEW — recovered PINs resolve to {acres:.2f} ac "
                    f"({new_drift:.0%} off the stated {stated_acres:.2f} ac), worse "
                    f"than the current {old_acres:.2f} ac ({old_drift:.0%}). Not "
                    "proposed; set `parcels:` by hand in the spec YAML and run "
                    "impact-confirm if the recovered set is right.\n"
                    f"    candidates  {', '.join(pins)}")
                continue

        lines.append(
            f"{slug}: {len(spec.parcels)} -> {len(pins)} parcel(s) via {method} "
            f"[candidates from {source}]\n"
            f"    acres  {acres:.2f}{drift_note}\n"
            f"    pins   {', '.join(spec.parcels) or '(none)'} -> {', '.join(pins)}\n"
            f"    bulk AV  ${old_av:,.0f} -> ${new_av:,.0f}")
        for warning in warnings:
            lines.append(f"    ! {warning}")
        changed += 1

        if apply:
            spec.parcels = pins
            spec.document_pins = stated or spec.document_pins
            spec.geometry = geometry
            spec.extraction_notes.append(
                f"parcels re-resolved after the PIN-normalization fix via {method}: "
                f"{len(pins)} parcel(s), {acres:.2f} ac (was {len(old_pins)} parcel(s))")
            spec.extraction_notes.extend(warnings)
            evaluation.spec = spec.model_dump(mode="json")
            # computed artifacts are stale by construction now
            if evaluation.status in ("computed", "synthesized"):
                evaluation.status = "confirmed"
            _spec_yaml_path(slug).write_text(_spec_to_yaml(spec))

    if apply:
        session.commit()
        lines.append(f"\napplied to {changed} spec(s); next: impact-confirm <slug> then "
                     "impact-evaluate <slug> --force")
    else:
        lines.append(f"\n{changed} spec(s) would change — re-run with --apply to write")
    return "\n".join(lines)


def _check_adjust_terms(result: ModuleResult) -> None:
    """Invariant: a metric's adjustment terms must reproduce its value exactly
    at the published assumption centrals (sum of term values == value). This
    is the drift guard for the interactive assumptions page — a module change
    that breaks a decomposition fails the evaluation instead of silently
    publishing a wrong client-side model. Tolerance covers stored rounding."""
    for m in result.metrics:
        if m.adjust is None:
            continue
        total = sum(t.value for t in m.adjust)
        if abs(total - m.value) > max(1e-6 * abs(m.value), 0.51):
            raise RuntimeError(
                f"adjustment terms for '{m.name}' sum to {total:,.2f} but the "
                f"metric value is {m.value:,.2f} — the term decomposition in "
                f"module '{result.module}' no longer matches the formula")


def evaluate(session: Session, slug: str, modules: tuple[str, ...] | None = None,
             skip_synthesis: bool = False, force: bool = False) -> str:
    from councilhound.impact.jurisdiction import JurisdictionContext
    from councilhound.impact.modules import registry

    project = _project(session, slug)
    evaluation = _evaluation(session, project)
    if evaluation is None or evaluation.status == "extracted":
        raise SystemExit(f"'{slug}' is not confirmed yet — impact-extract then impact-confirm")
    if evaluation.status == "synthesized" and not force:
        raise SystemExit(f"'{slug}' already synthesized — pass --force to recompute")

    spec = ProjectSpec.model_validate(evaluation.spec)
    ctx = JurisdictionContext(spec.jurisdiction)
    module_names = modules or registry.modules_for(spec.project_type)

    results: list[ModuleResult] = []
    map_layers: dict[str, dict] = {}
    for name in module_names:
        run = registry.get_module(name)
        log.info("running module: %s", name)
        result, layers = run(spec, ctx, prior=list(results))
        _check_adjust_terms(result)
        results.append(result)
        map_layers.update(layers)

    # an override key no module declares is almost always a typo in the spec
    # YAML, and it would otherwise look exactly like a working override
    from councilhound.impact.assumption_util import unknown_override_keys
    declared = {a.key for r in results for a in r.assumptions}
    stray = unknown_override_keys(spec, declared)
    if stray:
        raise SystemExit(
            f"spec.assumption_overrides names assumption(s) no module declares: "
            f"{', '.join(stray)}. Known keys: {', '.join(sorted(declared))}")

    encoded = json.dumps(map_layers)
    if len(encoded) > MAP_LAYERS_MAX_BYTES:
        raise RuntimeError(
            f"map_layers serialize to {len(encoded)/1e6:.1f} MB (> "
            f"{MAP_LAYERS_MAX_BYTES/1e6:.0f} MB budget) — tighten the layer "
            "builders (top-N edges / simplification) before shipping this row")

    bundle = EvaluationBundle(spec=spec, results=results, map_layers=map_layers)
    evaluation.module_results = [r.model_dump(mode="json") for r in results]
    evaluation.map_layers = map_layers
    evaluation.assumptions = [a.model_dump(mode="json") for a in bundle.all_assumptions()]
    evaluation.sources = [p.model_dump(mode="json") for p in bundle.all_sources()]
    evaluation.status = "computed"
    evaluation.computed_at = datetime.now(timezone.utc)
    session.commit()

    audit = run_dir(slug)
    atomic_write_json(audit / "spec.json", evaluation.spec)
    atomic_write_json(audit / "module_results.json", evaluation.module_results)
    atomic_write_json(audit / "map_layers.json", map_layers)

    headline = [m for r in results for m in r.metrics if m.headline]
    lines = [f"computed '{slug}': {len(results)} modules, "
             f"{sum(len(r.metrics) for r in results)} metrics"]
    for m in headline:
        bounds = (f"  [{m.low:,.0f} – {m.high:,.0f}]"
                  if m.low is not None and m.high is not None else "")
        lines.append(f"  {m.name:38} {m.value:>14,.0f} {m.unit}{bounds}")

    if not skip_synthesis:
        from councilhound.impact.synthesis.report import synthesize_report
        report_md, model, version = synthesize_report(bundle)
        evaluation.report_markdown = report_md
        evaluation.report_model = model
        evaluation.report_prompt_version = version
        evaluation.status = "synthesized"
        evaluation.synthesized_at = datetime.now(timezone.utc)
        session.commit()
        (audit / "report.md").write_text(report_md)
        lines.append(f"synthesized report ({len(report_md.split())} words) -> "
                     f"view at /development/{slug}")
    return "\n".join(lines)


# columns copied verbatim by impact-push (everything the API serves)
_PUSH_COLUMNS = (
    "status", "spec", "extraction_model", "extraction_prompt_version",
    "confirmed_at", "module_results", "map_layers", "assumptions", "sources",
    "report_markdown", "report_model", "report_prompt_version",
    "computed_at", "synthesized_at",
)


def push(session: Session, dsn: str, slugs: tuple[str, ...] = (),
         push_all: bool = False) -> str:
    """Upsert locally synthesized evaluations into a TARGET database (the
    production DB, reached e.g. via `fly proxy`). Compute stays local — heavy
    geo deps and fairfaxva.gov IP-blocking — so this sync is how results ship.

    Rows are matched to the target's city_projects by external_slug; a slug
    the target hasn't ingested yet is skipped with a warning rather than
    invented (the nightly cloud ingest owns that table)."""
    from sqlalchemy import create_engine
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    if not slugs and not push_all:
        raise SystemExit("pass project slugs or --all")

    # same driver normalization as db.session (psycopg v3)
    if dsn.startswith("postgres://"):
        dsn = "postgresql://" + dsn[len("postgres://"):]
    if dsn.startswith("postgresql://"):
        dsn = "postgresql+psycopg://" + dsn[len("postgresql://"):]

    query = (select(CityProject.external_slug, ProjectEvaluation)
             .join(ProjectEvaluation, ProjectEvaluation.city_project_id == CityProject.id)
             .where(ProjectEvaluation.status == "synthesized"))
    if slugs:
        query = query.where(CityProject.external_slug.in_(slugs))
    rows = session.execute(query).all()
    missing = set(slugs) - {slug for slug, _ in rows}
    if missing:
        raise SystemExit(f"not synthesized locally: {', '.join(sorted(missing))}")
    if not rows:
        return "nothing to push (no synthesized evaluations)"

    lines = []
    engine = create_engine(dsn)
    try:
        with engine.begin() as target:
            for slug, evaluation in rows:
                target_project_id = target.execute(
                    select(CityProject.id).where(CityProject.external_slug == slug)
                ).scalar()
                if target_project_id is None:
                    lines.append(f"SKIP {slug}: target has no city_projects row "
                                 "(cloud ingest hasn't synced it)")
                    continue
                values = {c: getattr(evaluation, c) for c in _PUSH_COLUMNS}
                values["city_project_id"] = target_project_id
                stmt = pg_insert(ProjectEvaluation.__table__).values(**values)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["city_project_id"],
                    set_={c: stmt.excluded[c] for c in _PUSH_COLUMNS},
                )
                target.execute(stmt)
                size_kb = len(json.dumps(evaluation.map_layers or {})) / 1024
                lines.append(f"pushed {slug} (map layers {size_kb:,.0f} KB, "
                             f"synthesized {evaluation.synthesized_at:%Y-%m-%d %H:%M})")
    finally:
        engine.dispose()
    return "\n".join(lines)
