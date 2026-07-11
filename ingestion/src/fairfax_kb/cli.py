"""
Command-line entrypoint for the ingestion pipeline.

  python -m fairfax_kb.cli init-db                      # create/upgrade schema (Alembic)
  python -m fairfax_kb.cli discover --since 2024-07-01  # meetings rows only
  python -m fairfax_kb.cli ingest --since 2024-07-01    # discover + documents + audio
  python -m fairfax_kb.cli ingest --limit 3 --skip-media
  python -m fairfax_kb.cli status                       # counts by status/type
"""
import logging
from datetime import datetime

import click

from fairfax_kb.config import GRANICUS_VIEW_IDS

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
    from fairfax_kb import pipeline
    from fairfax_kb.db.session import get_session

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
    from fairfax_kb import pipeline
    from fairfax_kb.db.session import get_session

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


@cli.command()
def status():
    """Show ingest progress: meeting counts by status and type."""
    from sqlalchemy import func, select

    from fairfax_kb.db.models import Document, Meeting
    from fairfax_kb.db.session import get_session

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


if __name__ == "__main__":
    cli()
