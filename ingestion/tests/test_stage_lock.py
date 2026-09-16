"""One runner per pipeline stage.

The nightly `daily`, the hourly `catchup` and ad-hoc one-off machines all
work the same database. On 2026-09-16 the hourly catchup started while a
backfill was mid-way through structuring: both selected the same pending
meetings, both paid Claude, and the loser died on the
(meeting_id, prompt_version) unique constraint. A session-level advisory
lock per stage lets the second runner notice the first and skip.
"""
import pytest
import sqlalchemy as sa
from click.testing import CliRunner

from councilhound import cli
from councilhound.db import session as dbsession
from councilhound.db.session import stage_lock


@pytest.fixture
def engine(db_session):
    """The scratch database's engine — each ``engine.connect()`` is its own
    Postgres backend, which is exactly what two runners look like."""
    return db_session.get_bind()


def test_second_runner_cannot_take_a_held_stage(engine):
    with stage_lock("structure", engine=engine) as first:
        assert first is True
        with stage_lock("structure", engine=engine) as second:
            assert second is False


def test_stages_are_independent(engine):
    """A backfill structuring meetings must not stop catchup from ingesting."""
    with stage_lock("structure", engine=engine) as structuring:
        with stage_lock("ingest", engine=engine) as ingesting:
            assert structuring is True
            assert ingesting is True


def test_lock_is_released_on_exit(engine):
    with stage_lock("embed", engine=engine) as held:
        assert held is True
    with stage_lock("embed", engine=engine) as again:
        assert again is True


def test_lock_is_released_when_the_body_raises(engine):
    with pytest.raises(RuntimeError):
        with stage_lock("profile", engine=engine):
            raise RuntimeError("stage blew up")
    with stage_lock("profile", engine=engine) as again:
        assert again is True


def test_lock_dies_with_the_connection(engine):
    """A machine that is killed mid-stage leaves nothing behind: the lock is
    session-level, so Postgres drops it with the connection."""
    other = sa.create_engine(engine.url)
    conn = other.connect()
    assert conn.execute(sa.text(
        "SELECT pg_try_advisory_lock(:ns, :key)"),
        {"ns": dbsession.ADVISORY_NAMESPACE,
         "key": dbsession.STAGE_LOCK_KEYS["transcribe"]}).scalar() is True
    with stage_lock("transcribe", engine=engine) as held:
        assert held is False
    conn.invalidate()   # the "process died" path: real close, no unlock
    other.dispose()
    with stage_lock("transcribe", engine=engine) as held:
        assert held is True


def test_unknown_stage_is_a_programming_error(engine):
    with pytest.raises(ValueError, match="unknown stage"):
        with stage_lock("dedupe", engine=engine):
            pass


# --- the CLI -------------------------------------------------------------

@pytest.fixture
def cli_env(db_session, engine, monkeypatch):
    """Point the CLI's engine and session factory at the scratch database."""
    monkeypatch.setattr(dbsession, "get_engine", lambda: engine)
    monkeypatch.setattr(dbsession, "get_session", lambda: db_session)
    return CliRunner()


def test_structure_command_skips_when_another_runner_holds_the_stage(cli_env, engine, monkeypatch):
    from councilhound.extraction import llm_structure

    called = []
    monkeypatch.setattr(llm_structure, "structure_pending",
                        lambda session, limit=None: called.append(limit) or {"structured": 0})
    with stage_lock("structure", engine=engine):          # the backfill machine
        result = cli_env.invoke(cli.cli, ["structure"])   # the hourly catchup's twin
    assert result.exit_code == 0, result.output
    assert "another runner holds structure; skipping" in result.output
    assert called == []


def test_structure_command_runs_when_the_stage_is_free(cli_env, monkeypatch):
    from councilhound.extraction import llm_structure

    monkeypatch.setattr(llm_structure, "structure_pending",
                        lambda session, limit=None: {"structured": 2})
    result = cli_env.invoke(cli.cli, ["structure"])
    assert result.exit_code == 0, result.output
    assert "{'structured': 2}" in result.output
    assert "skipping" not in result.output


def test_catchup_skips_only_the_held_stage(cli_env, engine, monkeypatch):
    """The 2026-09-16 incident, replayed: a backfill holds `structure`, the
    hourly catchup arrives. It must still ingest and embed, skip structuring
    with one line, and exit 0."""
    from councilhound import pipeline, seed
    from councilhound.embeddings import embed
    from councilhound.extraction import llm_structure, pdf_text

    ran = []

    def stage(name, value):
        def _stub(session, *a, **k):
            ran.append(name)
            return value
        return _stub

    class _Run:
        id = 1
        meetings_processed = 0
        errors = []

    monkeypatch.setattr(pipeline, "run_ingest", stage("ingest", _Run()))
    monkeypatch.setattr(pipeline, "sync_upcoming", stage("upcoming", 0))
    monkeypatch.setattr(pipeline, "sync_projects", stage("projects", 0))
    monkeypatch.setattr(pipeline, "link_index_points_pending", stage("index-points", 0))
    monkeypatch.setattr(pdf_text, "extract_pending", stage("extract-text", 0))
    monkeypatch.setattr(llm_structure, "structure_pending", stage("structure", 0))
    monkeypatch.setattr(seed, "seed_people", stage("seed", 0))
    monkeypatch.setattr(embed, "embed_pending", stage("embed", 0))

    with stage_lock("structure", engine=engine):
        result = cli_env.invoke(cli.cli, ["catchup"])
    assert result.exit_code == 0, result.output
    assert "structure:    another runner holds structure; skipping" in result.output
    assert "structure" not in ran
    assert "ingest" in ran and "embed" in ran


def test_ingest_command_skips_when_another_runner_holds_the_stage(cli_env, engine, monkeypatch):
    from councilhound import pipeline

    monkeypatch.setattr(pipeline, "run_ingest",
                        lambda *a, **k: pytest.fail("ingest ran under a held lock"))
    with stage_lock("ingest", engine=engine):
        result = cli_env.invoke(cli.cli, ["ingest"])
    assert result.exit_code == 0, result.output
    assert "another runner holds ingest; skipping" in result.output
