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
from councilhound.impact.schemas import EvaluationBundle, ModuleResult, ProjectSpec

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

    docs = gather_documents(project)
    extracted = extract_spec_fields(docs)

    ctx = JurisdictionContext(jurisdiction)
    pins, geometry, resolved_acres, method = [], None, None, None
    try:
        pins, geometry, resolved_acres, method = resolve_site(
            ctx, project, extracted["parcel_pins"])
    except ParcelResolutionError as exc:
        extracted["notes"].append(str(exc))
        log.warning("%s", exc)

    fields = extracted["fields"]

    def val(dotted):
        return fields[dotted]["value"]

    spec = ProjectSpec(
        name=project.name,
        jurisdiction=jurisdiction,
        city_project_slug=slug,
        source_url=project.detail_url,
        project_type=extracted["project_type"],
        status=project.official_status or "unknown",
        parcels=pins,
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
        },
        extraction_confidence={k: v["confidence"] for k, v in fields.items()},
        extraction_quotes={k: v["source_quote"] for k, v in fields.items() if v["source_quote"]},
        extraction_notes=extracted["conflicts"] + extracted["notes"]
        + ([f"parcels resolved via {method}; polygon area {resolved_acres:.2f} ac"]
           if method else []),
        documents=[d.provenance for d in docs],
    )

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
        value = getattr(getattr(spec, section), attr, None)
        quote = spec.extraction_quotes.get(field)
        lines.append(f"  {field:28} {str(value):>12}  [{confidence}]"
                     + (f'  "{quote}"' if quote else ""))
    return "\n".join(lines)


def confirm(session: Session, slug: str, spec_path: str | None = None,
            assume_yes: bool = False) -> str:
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

    # a human editing the parcel list is the expected fix for a wrong/partial
    # site polygon — re-resolve geometry from the (possibly edited) PINs
    stored = (evaluation.spec or {}).get("parcels") or []
    if spec.parcels and (spec.parcels != stored or spec.geometry is None):
        from councilhound.impact.intake.parcels import ParcelResolutionError, resolve_site
        from councilhound.impact.jurisdiction import JurisdictionContext
        try:
            pins, geometry, acres, method = resolve_site(
                JurisdictionContext(spec.jurisdiction), project, spec.parcels)
            spec.parcels, spec.geometry = pins, geometry
            spec.extraction_notes.append(
                f"geometry re-resolved at confirm from edited parcels via {method}: "
                f"{acres:.2f} ac")
            path_obj = _spec_yaml_path(slug)
            path_obj.write_text(_spec_to_yaml(spec))
        except ParcelResolutionError as exc:
            raise SystemExit(f"edited parcels failed to resolve: {exc}") from None

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
    module_names = modules or registry.DEFAULT_MODULES

    results: list[ModuleResult] = []
    map_layers: dict[str, dict] = {}
    for name in module_names:
        run = registry.get_module(name)
        log.info("running module: %s", name)
        result, layers = run(spec, ctx, prior=list(results))
        _check_adjust_terms(result)
        results.append(result)
        map_layers.update(layers)

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
