"""
Command-line entrypoint for the ingestion pipeline.

  python -m councillens.cli init-db                      # create/upgrade schema (Alembic)
  python -m councillens.cli discover --since 2024-07-01  # meetings rows only
  python -m councillens.cli ingest --since 2024-07-01    # discover + documents + audio
  python -m councillens.cli ingest --limit 3 --skip-media
  python -m councillens.cli status                       # counts by status/type
"""
import logging
from datetime import datetime

import click

from councillens.config import GRANICUS_VIEW_IDS

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
    from councillens import pipeline
    from councillens.db.session import get_session

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
    from councillens import pipeline
    from councillens.db.session import get_session

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
    from councillens.db.session import get_session
    from councillens.extraction.pdf_text import extract_pending

    with get_session() as session:
        click.echo(extract_pending(session, limit=limit))


@cli.command()
@limit_option
@click.option("--clip-id", default=None, help="transcribe a single meeting by Granicus clip_id")
def transcribe(limit, clip_id):
    """Phase 2: transcribe downloaded meeting audio into transcript_chunks."""
    from sqlalchemy import select

    from councillens.db.models import Meeting
    from councillens.db.session import get_session
    from councillens.extraction.transcript import transcribe_meeting, transcribe_pending

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
    from councillens.db.session import get_session
    from councillens.seed import seed_people

    with get_session() as session:
        click.echo(seed_people(session))


@cli.command()
@limit_option
@click.option("--clip-id", default=None, help="structure a single meeting by Granicus clip_id")
@click.option("--force", is_flag=True, help="re-run the LLM even if an extraction exists")
@click.option("--reapply", is_flag=True, help="re-apply stored extractions without calling the LLM")
def structure(limit, clip_id, force, reapply):
    """Phase 3: LLM structuring pass (agenda items, votes, entity timelines)."""
    from sqlalchemy import select

    from councillens.db.models import Meeting
    from councillens.db.session import get_session
    from councillens.extraction.llm_structure import structure_meeting, structure_pending

    with get_session() as session:
        if clip_id:
            meeting = session.scalar(select(Meeting).where(Meeting.granicus_clip_id == clip_id))
            if not meeting:
                raise click.ClickException(f"no meeting with clip_id={clip_id}")
            structure_meeting(session, meeting, force=force, reapply_only=reapply)
            click.echo(f"structured meeting {meeting.id} ({meeting.title} {meeting.meeting_date})")
        elif reapply:
            from councillens.db.models import Extraction
            from councillens.extraction.llm_structure import apply_extraction

            for ext in session.scalars(select(Extraction)).all():
                meeting = session.get(Meeting, ext.meeting_id)
                apply_extraction(session, meeting, ext.raw_json)
            session.commit()
            click.echo("re-applied all stored extractions")
        else:
            click.echo(structure_pending(session, limit=limit))


@cli.command()
def status():
    """Show ingest progress: meeting counts by status and type."""
    from sqlalchemy import func, select

    from councillens.db.models import Document, Meeting
    from councillens.db.session import get_session

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

        from councillens.db.models import (
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


if __name__ == "__main__":
    cli()
