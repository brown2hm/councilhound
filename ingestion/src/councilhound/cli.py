"""
Command-line entrypoint for the ingestion pipeline.

  python -m councilhound.cli init-db                      # create/upgrade schema (Alembic)
  python -m councilhound.cli discover --since 2024-07-01  # meetings rows only
  python -m councilhound.cli ingest --since 2024-07-01    # discover + documents + audio
  python -m councilhound.cli ingest --limit 3 --skip-media
  python -m councilhound.cli status                       # counts by status/type
"""
import logging
from datetime import datetime

import click

from councilhound.config import GRANICUS_VIEW_IDS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("pgserver").setLevel(logging.WARNING)


def _parse_date(_ctx, _param, value):
    if value is None:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


view_id_option = click.option("--view-id", default=GRANICUS_VIEW_IDS[0], show_default=True)
since_option = click.option("--since", callback=_parse_date, default=None, help="YYYY-MM-DD")
until_option = click.option("--until", callback=_parse_date, default=None, help="YYYY-MM-DD")
limit_option = click.option("--limit", type=int, default=None, help="max meetings to process")


@click.group()
def cli():
    pass


@cli.command("init-db")
def init_db():
    """Create/upgrade the database schema via Alembic."""
    import os
    from alembic import command
    from alembic.config import Config

    ini = os.path.join(os.path.dirname(__file__), "..", "..", "alembic.ini")
    cfg = Config(os.path.abspath(ini))
    command.upgrade(cfg, "head")
    click.echo("schema up to date")


@cli.command()
@view_id_option
@since_option
@until_option
@limit_option
def discover(view_id, since, until, limit):
    """Phase 1: discover in-scope meetings and upsert meetings rows."""
    from councilhound import pipeline
    from councilhound.db.session import get_session

    with get_session() as session:
        result = pipeline.discover(session, view_id, since=since, until=until, limit=limit)
    click.echo(result)


@cli.command()
@view_id_option
@since_option
@until_option
@limit_option
@click.option("--skip-media", is_flag=True, help="skip MP3 downloads (documents only)")
def ingest(view_id, since, until, limit, skip_media):
    """Phase 1: discover + fetch documents and audio for in-scope meetings."""
    from councilhound import pipeline
    from councilhound.db.session import get_session

    with get_session() as session:
        run = pipeline.run_ingest(
            session, view_id, since=since, until=until, limit=limit, skip_media=skip_media
        )
        click.echo(
            f"run {run.id}: {run.meetings_processed} meetings processed, "
            f"{len(run.errors or [])} errors"
        )
        for err in run.errors or []:
            click.echo(f"  clip {err['clip_id']}: {err['error']}")


@cli.command("extract-text")
@limit_option
def extract_text(limit):
    """Phase 2: extract raw_text for downloaded documents (PDF/HTML)."""
    from councilhound.db.session import get_session
    from councilhound.extraction.pdf_text import extract_pending

    with get_session() as session:
        click.echo(extract_pending(session, limit=limit))


@cli.command()
@limit_option
@click.option("--clip-id", default=None, help="transcribe a single meeting by Granicus clip_id")
def transcribe(limit, clip_id):
    """Phase 2: transcribe downloaded meeting audio into transcript_chunks."""
    from sqlalchemy import select

    from councilhound.db.models import Meeting
    from councilhound.db.session import get_session
    from councilhound.extraction.transcript import transcribe_meeting, transcribe_pending

    with get_session() as session:
        if clip_id:
            meeting = session.scalar(select(Meeting).where(Meeting.granicus_clip_id == clip_id))
            if not meeting:
                raise click.ClickException(f"no meeting with clip_id={clip_id}")
            click.echo(f"{transcribe_meeting(session, meeting)} chunks")
        else:
            click.echo(transcribe_pending(session, limit=limit))


@cli.command("seed-entities")
def seed_entities():
    """Phase 3 setup: seed person entities + aliases from agenda headers."""
    from councilhound.db.session import get_session
    from councilhound.seed import seed_people

    with get_session() as session:
        click.echo(seed_people(session))


@cli.command("dedupe-entities")
@click.option("--apply", "apply_", is_flag=True, help="perform the merges (default: dry-run print)")
def dedupe_entities(apply_):
    """Merge entities whose normalized slug matches an existing entity
    (e.g. 'george-snyder-trail-project' -> 'george-snyder-trail')."""
    from councilhound.db.session import get_session
    from councilhound.dedupe import dedupe_pass

    with get_session() as session:
        proposals = dedupe_pass(session, apply=apply_)
        for p in proposals:
            click.echo(f"{p['action']}: {p['source']} -> {p['target']} ({p['entity_type']})"
                       + (f"  moved {p['moved']}" if apply_ and p["action"] == "merge" else ""))
        click.echo(f"{len(proposals)} action(s) {'applied' if apply_ else 'proposed (use --apply)'}")


@cli.command("merge-entity")
@click.argument("source_slug")
@click.argument("target_slug")
@click.option("--force-cross-type", is_flag=True,
              help="allow merging entities of different types")
def merge_entity(source_slug, target_slug, force_cross_type):
    """Fold SOURCE_SLUG into TARGET_SLUG (mentions, updates, aliases move;
    the old name and slug become aliases of the survivor)."""
    from councilhound.db.session import get_session
    from councilhound.dedupe import merge_entities

    with get_session() as session:
        moved = merge_entities(session, source_slug, target_slug,
                               force_cross_type=force_cross_type)
        session.commit()
        click.echo(f"merged {source_slug} -> {target_slug}: {moved}")


@cli.command("merge-entities-batch")
@click.argument("merge_file", type=click.Path(exists=True))
@click.option("--apply", "apply_", is_flag=True, help="perform the merges (default: dry-run print)")
def merge_entities_batch(merge_file, apply_):
    """Apply a curated merge list (JSON: {"merges": [{"source", "target",
    "force_cross_type"?}, ...]}). Idempotent — safe to re-run; already-merged
    and missing slugs are reported and skipped."""
    import json

    from councilhound.db.session import get_session
    from councilhound.dedupe import merge_batch

    with open(merge_file) as fh:
        entries = json.load(fh)["merges"]
    with get_session() as session:
        results = merge_batch(session, entries, apply=apply_)
        for r in results:
            click.echo(f"{r['source']} -> {r['target']}: {r['result']}")
        applied = sum(1 for r in results if r["result"].startswith("merged"))
        click.echo(f"{len(results)} entries; {applied} merged"
                   + ("" if apply_ else " (dry-run — use --apply)"))


@cli.command()
@limit_option
@click.option("--clip-id", default=None, help="structure a single meeting by Granicus clip_id")
@click.option("--force", is_flag=True, help="re-run the LLM even if an extraction exists")
@click.option("--reapply", is_flag=True, help="re-apply stored extractions without calling the LLM")
def structure(limit, clip_id, force, reapply):
    """Phase 3: LLM structuring pass (agenda items, votes, entity timelines)."""
    from sqlalchemy import select

    from councilhound.db.models import Meeting
    from councilhound.db.session import get_session
    from councilhound.extraction.llm_structure import structure_meeting, structure_pending

    with get_session() as session:
        if clip_id:
            meeting = session.scalar(select(Meeting).where(Meeting.granicus_clip_id == clip_id))
            if not meeting:
                raise click.ClickException(f"no meeting with clip_id={clip_id}")
            structure_meeting(session, meeting, force=force, reapply_only=reapply)
            click.echo(f"structured meeting {meeting.id} ({meeting.title} {meeting.meeting_date})")
        elif reapply:
            from councilhound.db.models import Extraction
            from councilhound.extraction.llm_structure import apply_extraction

            for ext in session.scalars(select(Extraction)).all():
                meeting = session.get(Meeting, ext.meeting_id)
                apply_extraction(session, meeting, ext.raw_json)
            session.commit()
            click.echo("re-applied all stored extractions")
        else:
            click.echo(structure_pending(session, limit=limit))


@cli.command()
@limit_option
@click.option("--slug", default=None, help="synthesize one entity's profile by slug")
@click.option("--all", "include_fresh", is_flag=True, help="regenerate even fresh profiles")
def profile(limit, slug, include_fresh):
    """Synthesize entity profiles (summary, open questions, member commentary)."""
    from sqlalchemy import select

    from councilhound.db.models import Entity
    from councilhound.db.session import get_session
    from councilhound.extraction.entity_profile import profile_pending, synthesize_profile

    with get_session() as session:
        if slug:
            entity = session.scalar(select(Entity).where(Entity.canonical_slug == slug))
            if not entity:
                raise click.ClickException(f"no entity with slug={slug}")
            synthesize_profile(session, entity)
            click.echo(f"profiled {slug}")
        else:
            click.echo(profile_pending(session, limit=limit, stale_only=not include_fresh))


@cli.command()
@limit_option
def embed(limit):
    """Phase 4: embed transcript chunks + agenda items for RAG retrieval."""
    from councilhound.db.session import get_session
    from councilhound.embeddings.embed import embed_pending

    with get_session() as session:
        click.echo(embed_pending(session, limit=limit))


@cli.command()
@click.option("--days", default=14, show_default=True,
              help="look-back window for new/updated meetings")
def daily(days):
    """Phase 6: the nightly job. Discover + fetch recent meetings, then run
    every downstream pass (all idempotent, so re-runs are safe): text
    extraction, transcription, LLM structuring, roster seeding, profile
    refresh, embeddings."""
    import datetime

    from councilhound import pipeline
    from councilhound.config import GRANICUS_VIEW_IDS
    from councilhound.db.session import get_session
    from councilhound.embeddings.embed import embed_pending
    from councilhound.extraction.entity_profile import profile_pending
    from councilhound.extraction.llm_structure import structure_pending
    from councilhound.extraction.pdf_text import extract_pending
    from councilhound.extraction.transcript import transcribe_pending
    from councilhound.seed import seed_people

    since = datetime.date.today() - datetime.timedelta(days=days)
    with get_session() as session:
        for view_id in GRANICUS_VIEW_IDS:
            run = pipeline.run_ingest(session, view_id, since=since)
            click.echo(f"ingest view {view_id}: {run.meetings_processed} meetings, "
                       f"{len(run.errors or [])} errors")
            click.echo(f"upcoming view {view_id}: {pipeline.sync_upcoming(session, view_id)}")
        click.echo(f"projects:     {pipeline.sync_projects(session)}")
        click.echo(f"extract-text: {extract_pending(session)}")
        click.echo(f"transcribe:   {transcribe_pending(session)}")
        click.echo(f"structure:    {structure_pending(session)}")
        click.echo(f"index-points: {pipeline.link_index_points_pending(session)}")
        click.echo(f"seed:         {seed_people(session)}")
        from councilhound.dedupe import dedupe_pass
        click.echo(f"dedupe:       {len(dedupe_pass(session, apply=True))} action(s)")
        from councilhound.geocode import geocode_pending
        click.echo(f"geocode:      {geocode_pending(session)}")
        click.echo(f"profile:      {profile_pending(session)}")
        click.echo(f"embed:        {embed_pending(session)}")
        from councilhound.notify import notify_subscribers
        click.echo(f"notify:       {notify_subscribers(session)}")


@cli.command()
@click.option("--days", default=5, show_default=True,
              help="look-back window for new/updated meetings")
def catchup(days):
    """Lightweight hourly pass: get newly-posted meetings into the tracker
    fast. Discovers, fetches documents (NOT audio), extracts text, structures,
    links index points, seeds rosters, and embeds — everything cheap. The
    heavy stages (audio download, transcription, profile regeneration) stay on
    the nightly `daily` run, so this exits in seconds when nothing is new."""
    import datetime

    from councilhound import pipeline
    from councilhound.config import GRANICUS_VIEW_IDS
    from councilhound.db.session import get_session
    from councilhound.embeddings.embed import embed_pending
    from councilhound.extraction.llm_structure import structure_pending
    from councilhound.extraction.pdf_text import extract_pending
    from councilhound.seed import seed_people

    since = datetime.date.today() - datetime.timedelta(days=days)
    with get_session() as session:
        for view_id in GRANICUS_VIEW_IDS:
            run = pipeline.run_ingest(session, view_id, since=since, skip_media=True)
            click.echo(f"ingest view {view_id}: {run.meetings_processed} meetings, "
                       f"{len(run.errors or [])} errors")
            click.echo(f"upcoming view {view_id}: {pipeline.sync_upcoming(session, view_id)}")
        click.echo(f"projects:     {pipeline.sync_projects(session)}")
        click.echo(f"extract-text: {extract_pending(session)}")
        click.echo(f"structure:    {structure_pending(session)}")
        click.echo(f"index-points: {pipeline.link_index_points_pending(session)}")
        click.echo(f"seed:         {seed_people(session)}")
        click.echo(f"embed:        {embed_pending(session)}")


@cli.command()
@limit_option
def geocode(limit):
    """Geocode location entities (US Census, free) for the map view."""
    from councilhound.db.session import get_session
    from councilhound.geocode import geocode_pending

    with get_session() as session:
        click.echo(geocode_pending(session, limit=limit))


@cli.command()
@view_id_option
def upcoming(view_id):
    """Refresh the upcoming/in-progress events list from Granicus."""
    from councilhound import pipeline
    from councilhound.db.session import get_session

    with get_session() as session:
        click.echo(pipeline.sync_upcoming(session, view_id))


@cli.command()
@click.option("--skip-details", is_flag=True, help="only use list page + ArcGIS fields")
def projects(skip_details):
    """Refresh official City of Fairfax development-project records."""
    from councilhound import pipeline
    from councilhound.db.session import get_session

    with get_session() as session:
        click.echo(pipeline.sync_projects(session, fetch_details=not skip_details))


@cli.command("index-points")
@limit_option
def index_points(limit):
    """Link agenda items to the official Granicus video index points."""
    from councilhound import pipeline
    from councilhound.db.session import get_session

    with get_session() as session:
        click.echo(pipeline.link_index_points_pending(session, limit=limit))


@cli.command()
def status():
    """Show ingest progress: meeting counts by status and type."""
    from sqlalchemy import func, select

    from councilhound.db.models import Document, Meeting
    from councilhound.db.session import get_session

    with get_session() as session:
        rows = session.execute(
            select(Meeting.meeting_type, Meeting.status, func.count())
            .group_by(Meeting.meeting_type, Meeting.status)
            .order_by(Meeting.meeting_type)
        ).all()
        for meeting_type, mstatus, count in rows:
            click.echo(f"{meeting_type:28} {mstatus:12} {count}")
        docs = session.execute(
            select(Document.doc_type, func.count(), func.count(Document.local_path))
            .group_by(Document.doc_type)
        ).all()
        for doc_type, total, on_disk in docs:
            click.echo(f"documents/{doc_type:20} {on_disk}/{total} fetched")

        from councilhound.db.models import (
            AgendaItem, Entity, EntityUpdate, Extraction, TranscriptChunk, Vote,
        )
        n_tc_meetings = session.scalar(
            select(func.count(func.distinct(TranscriptChunk.meeting_id))))
        click.echo(f"transcripts: {n_tc_meetings} meetings, "
                   f"{session.scalar(select(func.count(TranscriptChunk.id)))} chunks")
        click.echo(f"extractions: {session.scalar(select(func.count(Extraction.id)))} meetings | "
                   f"agenda_items: {session.scalar(select(func.count(AgendaItem.id)))} | "
                   f"votes: {session.scalar(select(func.count(Vote.id)))} | "
                   f"entity_updates: {session.scalar(select(func.count(EntityUpdate.id)))}")
        ents = session.execute(
            select(Entity.entity_type, func.count()).group_by(Entity.entity_type)
        ).all()
        if ents:
            click.echo("entities: " + ", ".join(f"{t}={c}" for t, c in ents))


# --- impact analysis (councilhound.impact) -------------------------------
# LOCAL-RUN stages: heavy geo deps (requirements-impact.txt) + fairfaxva.gov
# IP-blocking keep these out of the cloud `daily`/`catchup` flows.

jurisdiction_option = click.option(
    "--jurisdiction", default="fairfax_city_va", show_default=True,
    help="jurisdiction config stem under ingestion/jurisdictions/",
)


@cli.command("impact-context")
@jurisdiction_option
@click.option("--refresh", default=None, metavar="LAYER",
              help="delete + rebuild one layer (boundary|networks|census|lodes|pois|transit|parcels|all)")
def impact_context(jurisdiction, refresh):
    """Build/refresh the jurisdiction context cache (networks, census, POIs...)."""
    from councilhound.impact.context.build import build_context

    build_context(jurisdiction, refresh=refresh, echo=click.echo)


@cli.command("impact-extract")
@click.argument("slug")
@jurisdiction_option
@click.option("--force", is_flag=True, help="re-extract over an existing evaluation row")
def impact_extract(slug, jurisdiction, force):
    """Extract a ProjectSpec from a city project's documents (LLM + parcel resolution)."""
    from councilhound.db.session import get_session
    from councilhound.impact.evaluate import extract

    with get_session() as session:
        click.echo(extract(session, slug, jurisdiction=jurisdiction, force=force))


@cli.command("impact-confirm")
@click.argument("slug")
@click.option("--file", "spec_path", type=click.Path(exists=True), default=None,
              help="hand-edited spec YAML to confirm (defaults to the emitted one)")
@click.option("--yes", is_flag=True, help="skip the interactive review prompt")
def impact_confirm(slug, spec_path, yes):
    """Human-in-the-loop gate: confirm an extracted ProjectSpec."""
    from councilhound.db.session import get_session
    from councilhound.impact.evaluate import confirm

    with get_session() as session:
        click.echo(confirm(session, slug, spec_path=spec_path, assume_yes=yes))


@cli.command("impact-evaluate")
@click.argument("slug")
@click.option("--modules", "module_names", default=None,
              help="comma-separated module list (default: economic,fiscal)")
@click.option("--skip-synthesis", is_flag=True, help="stop after deterministic modules")
@click.option("--force", is_flag=True, help="recompute even if already synthesized")
def impact_evaluate(slug, module_names, skip_synthesis, force):
    """Run analysis modules + report synthesis for a confirmed project."""
    from councilhound.db.session import get_session
    from councilhound.impact.evaluate import evaluate

    modules = tuple(m.strip() for m in module_names.split(",")) if module_names else None
    with get_session() as session:
        click.echo(evaluate(session, slug, modules=modules,
                            skip_synthesis=skip_synthesis, force=force))


@cli.command("impact-push")
@click.argument("slugs", nargs=-1)
@click.option("--all", "push_all", is_flag=True, help="push every synthesized evaluation")
@click.option("--dsn", envvar="IMPACT_PUSH_DATABASE_URL", required=True,
              help="target Postgres DSN (e.g. via `fly proxy` to the prod DB); "
                   "defaults to $IMPACT_PUSH_DATABASE_URL")
def impact_push(slugs, push_all, dsn):
    """Upsert locally synthesized evaluations into the production database."""
    from councilhound.db.session import get_session
    from councilhound.impact.evaluate import push

    with get_session() as session:
        click.echo(push(session, dsn, slugs=slugs, push_all=push_all))


@cli.command("impact-setup-jurisdiction")
@jurisdiction_option
def impact_setup_jurisdiction(jurisdiction):
    """Guided pinning of tax/budget rates + data-source URLs into the YAML."""
    from councilhound.impact.setup import run_setup

    run_setup(jurisdiction, echo=click.echo)


# --- OKF knowledge bundle (councilhound.okf) ------------------------------
# The wiki-style knowledge base: one directory of markdown concept files per
# tracked project (Open Knowledge Format v0.1). Seed once, then the nightly
# flow is refresh -> curate -> lint -> push.

bundle_dir_option = click.option(
    "--bundle-dir", default=None,
    help="bundle root (defaults to $OKF_BUNDLE_DIR)")


def _bundle_dir(value):
    from councilhound.config import OKF_BUNDLE_DIR
    return value or OKF_BUNDLE_DIR


@cli.command("okf-seed")
@bundle_dir_option
@click.option("--slug", "slugs", multiple=True, help="seed specific project slug(s)")
@limit_option
@click.option("--force", is_flag=True, help="re-draft curator pages of existing wikis")
def okf_seed(bundle_dir, slugs, limit, force):
    """One-time draft of project wiki directories from profiles + records."""
    from councilhound.db.session import get_session
    from councilhound.okf.export import seed_bundle

    with get_session() as session:
        click.echo(seed_bundle(session, _bundle_dir(bundle_dir),
                               slugs=list(slugs) or None, limit=limit, force=force))


@cli.command("okf-refresh")
@bundle_dir_option
def okf_refresh(bundle_dir):
    """Deterministic pass: regenerate history.md, indexes, status frontmatter."""
    from councilhound.db.session import get_session
    from councilhound.okf.export import refresh_bundle

    with get_session() as session:
        click.echo(refresh_bundle(session, _bundle_dir(bundle_dir)))


@cli.command("okf-curate")
@bundle_dir_option
@limit_option
def okf_curate(bundle_dir, limit):
    """LLM curator: minimal edits to overview/positions for stale wikis."""
    from councilhound.db.session import get_session
    from councilhound.okf.curate import curate_pending

    with get_session() as session:
        click.echo(curate_pending(session, _bundle_dir(bundle_dir), limit=limit))


@cli.command("okf-lint")
@bundle_dir_option
@click.option("--no-db", is_flag=True, help="skip DB-backed metric-marker checks")
def okf_lint(bundle_dir, no_db):
    """Validate OKF conformance; exits nonzero on problems."""
    from councilhound.okf.lint import lint_bundle

    if no_db:
        problems = lint_bundle(_bundle_dir(bundle_dir))
    else:
        from councilhound.db.session import get_session
        with get_session() as session:
            problems = lint_bundle(_bundle_dir(bundle_dir), session)
    for p in problems:
        click.echo(p)
    if problems:
        raise click.ClickException(f"{len(problems)} problem(s)")
    click.echo("bundle conformant")


@cli.command("okf-push")
@bundle_dir_option
@click.option("--dsn", envvar="IMPACT_PUSH_DATABASE_URL", default=None,
              help="target Postgres DSN (e.g. via `fly proxy` to the prod DB); "
                   "defaults to the app database")
def okf_push(bundle_dir, dsn):
    """Mirror the bundle into wiki_pages so the API can serve it."""
    from councilhound.okf.push import push_bundle

    if dsn:
        import sqlalchemy as sa
        from sqlalchemy.orm import sessionmaker
        engine = sa.create_engine(dsn)
        session = sessionmaker(bind=engine)()
        try:
            click.echo(push_bundle(session, _bundle_dir(bundle_dir)))
        finally:
            session.close()
            engine.dispose()
    else:
        from councilhound.db.session import get_session
        with get_session() as session:
            click.echo(push_bundle(session, _bundle_dir(bundle_dir)))


@cli.command("impact-status")
def impact_status():
    """List impact evaluations and their lifecycle state."""
    from sqlalchemy import select

    from councilhound.db.models import CityProject, ProjectEvaluation
    from councilhound.db.session import get_session

    with get_session() as session:
        rows = session.execute(
            select(CityProject.external_slug, CityProject.name, ProjectEvaluation)
            .join(ProjectEvaluation, ProjectEvaluation.city_project_id == CityProject.id)
            .order_by(CityProject.external_slug)
        ).all()
        if not rows:
            click.echo("no evaluations yet — run impact-extract <slug>")
            return
        for slug, name, ev in rows:
            stamp = ev.synthesized_at or ev.computed_at or ev.confirmed_at or ev.created_at
            click.echo(f"{slug:40} {ev.status:12} {stamp:%Y-%m-%d %H:%M} {name}")


if __name__ == "__main__":
    cli()
