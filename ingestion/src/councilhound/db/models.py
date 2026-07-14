"""SQLAlchemy models — source of truth for the schema (PLAN.md section 3).
Migrations are managed by Alembic (ingestion/alembic/); run
`python -m councilhound.cli init-db` to create/upgrade a database."""
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import declarative_base, relationship
from pgvector.sqlalchemy import Vector

Base = declarative_base()


class Meeting(Base):
    __tablename__ = "meetings"
    __table_args__ = (UniqueConstraint("granicus_view_id", "granicus_clip_id"),)

    id = Column(Integer, primary_key=True)
    granicus_clip_id = Column(String, nullable=False)
    granicus_view_id = Column(String, nullable=False)
    body = Column(String, nullable=False)  # 'city_council' | 'planning_commission'
    meeting_type = Column(String, nullable=False)  # 'council_regular','council_work_session',...
    meeting_date = Column(Date, nullable=False, index=True)
    title = Column(Text, nullable=False)
    duration_seconds = Column(Integer)
    video_url = Column(Text)
    audio_url = Column(Text)
    agenda_url = Column(Text)
    minutes_url = Column(Text)
    audio_local_path = Column(Text)
    status = Column(String, nullable=False, default="discovered")  # discovered|fetched|extracted
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    documents = relationship("Document", back_populates="meeting")
    agenda_items = relationship("AgendaItem", back_populates="meeting")


class UpcomingMeeting(Base):
    """Upcoming/in-progress events from the Granicus ViewPublisher page.
    Fully refreshed each sync (no history — past events become real Meetings
    via the archive). agenda_text is kept for matching tracked entities
    against what's on the next agenda."""
    __tablename__ = "upcoming_meetings"

    id = Column(Integer, primary_key=True)
    granicus_event_id = Column(String, unique=True, nullable=False)
    granicus_view_id = Column(String, nullable=False)
    title = Column(Text, nullable=False)
    body = Column(String)  # NULL for out-of-scope committees/boards
    starts_at = Column(DateTime)  # city-local; NULL while the event is live
    in_progress = Column(Boolean, nullable=False, default=False)
    agenda_url = Column(Text)
    agenda_text = Column(Text)
    synced_at = Column(DateTime(timezone=True), server_default=func.now())


class AgendaItem(Base):
    """First-class agenda items — the natural unit of a project 'thread'.
    Populated in Phase 3 by parsing the agenda; votes and mentions FK here."""
    __tablename__ = "agenda_items"
    __table_args__ = (UniqueConstraint("meeting_id", "label"),)

    id = Column(Integer, primary_key=True)
    meeting_id = Column(Integer, ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False)
    label = Column(String, nullable=False)  # e.g. '7a'
    title = Column(Text)
    description = Column(Text)
    outcome = Column(Text)
    # official Granicus index-point timestamp: seconds into the meeting
    # video where this item was taken up; NULL when the city didn't index it
    start_seconds = Column(Integer)
    # embeds label+title+description+outcome; part of the RAG corpus
    embedding = Column(Vector(768))

    meeting = relationship("Meeting", back_populates="agenda_items")


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True)
    meeting_id = Column(Integer, ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False)
    agenda_item_id = Column(Integer, ForeignKey("agenda_items.id"))
    doc_type = Column(String, nullable=False)  # 'agenda','minutes','actions_report','agenda_item_pdf','other'
    title = Column(Text)
    source_url = Column(Text, nullable=False, unique=True)
    local_path = Column(Text)
    raw_text = Column(Text)
    fetched_at = Column(DateTime(timezone=True))

    meeting = relationship("Meeting", back_populates="documents")


class TranscriptChunk(Base):
    __tablename__ = "transcript_chunks"

    id = Column(Integer, primary_key=True)
    meeting_id = Column(Integer, ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False)
    start_seconds = Column(Numeric)
    end_seconds = Column(Numeric)
    text = Column(Text, nullable=False)
    # Raw diarization label ('SPEAKER_00'); kept even after attribution.
    speaker_label = Column(String)
    # Set only on confident attribution (Phase 3) — never guessed.
    speaker_entity_id = Column(Integer, ForeignKey("entities.id"))
    # 768 = bge-base-en-v1.5 (local sentence-transformers, the Phase 4
    # provider decision). Changing providers means a migration + re-embed.
    embedding = Column(Vector(768))


class Entity(Base):
    __tablename__ = "entities"

    id = Column(Integer, primary_key=True)
    entity_type = Column(String, nullable=False)  # 'person','project','ordinance','case_number','location','topic'
    name = Column(Text, nullable=False)
    canonical_slug = Column(String, unique=True, nullable=False)
    first_seen_meeting_id = Column(Integer, ForeignKey("meetings.id"))
    current_status = Column(String)  # rolled up from latest EntityUpdate.status_after


class EntityGeocode(Base):
    """Coordinates for 'location' entities (US Census geocoder). A 'miss'
    row records that geocoding was attempted and failed (area names like
    'Old Town' don't geocode) so the nightly pass doesn't retry forever."""
    __tablename__ = "entity_geocodes"

    id = Column(Integer, primary_key=True)
    entity_id = Column(Integer, ForeignKey("entities.id", ondelete="CASCADE"),
                       nullable=False, unique=True)
    status = Column(String, nullable=False)  # 'ok' | 'miss'
    lat = Column(Numeric)
    lng = Column(Numeric)
    matched_address = Column(Text)
    geocoded_at = Column(DateTime(timezone=True), server_default=func.now())


class EntityProfile(Base):
    """LLM-synthesized rollup for an entity's detail page: overall summary,
    open questions / options on the table, and commentary binned per council
    member (from minutes-recorded positions, not diarization). A regenerable
    CACHE derived from entity_updates + votes + transcript excerpts —
    through_meeting_id marks freshness; regenerate when new updates land."""
    __tablename__ = "entity_profiles"

    id = Column(Integer, primary_key=True)
    entity_id = Column(Integer, ForeignKey("entities.id", ondelete="CASCADE"),
                       nullable=False, unique=True)
    summary = Column(Text)
    open_questions = Column(JSON)  # ["...", ...] pending decisions / options considered
    member_commentary = Column(JSON)  # [{"member": "...", "slug": ..., "summary": "..."}]
    through_meeting_id = Column(Integer, ForeignKey("meetings.id"))
    model = Column(String)
    prompt_version = Column(String)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class EntityAlias(Base):
    """Alternate names resolving to one entity ('Mayor Read' -> catherine-read)."""
    __tablename__ = "entity_aliases"
    __table_args__ = (UniqueConstraint("alias"),)

    id = Column(Integer, primary_key=True)
    entity_id = Column(Integer, ForeignKey("entities.id", ondelete="CASCADE"), nullable=False)
    alias = Column(Text, nullable=False)


class EntityUpdate(Base):
    """One row per (entity, meeting): what happened to this entity at this
    meeting. Progress over time = SELECT ... ORDER BY meeting_date. The
    unique constraint makes Phase 3 re-runs replace instead of double-append."""
    __tablename__ = "entity_updates"
    __table_args__ = (UniqueConstraint("entity_id", "meeting_id"),)

    id = Column(Integer, primary_key=True)
    entity_id = Column(Integer, ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True)
    meeting_id = Column(Integer, ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False)
    agenda_item_id = Column(Integer, ForeignKey("agenda_items.id"))
    update_text = Column(Text, nullable=False)
    status_after = Column(String)


class EntityMention(Base):
    __tablename__ = "entity_mentions"
    __table_args__ = (
        UniqueConstraint("entity_id", "meeting_id", "document_id", "transcript_chunk_id", "role"),
    )

    id = Column(Integer, primary_key=True)
    entity_id = Column(Integer, ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True)
    meeting_id = Column(Integer, ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False)
    agenda_item_id = Column(Integer, ForeignKey("agenda_items.id"))
    document_id = Column(Integer, ForeignKey("documents.id"))
    transcript_chunk_id = Column(Integer, ForeignKey("transcript_chunks.id"))
    context_text = Column(Text)
    role = Column(String)  # 'sponsor','vote_yes','vote_no','discussed',...


class Vote(Base):
    __tablename__ = "votes"
    __table_args__ = (UniqueConstraint("meeting_id", "agenda_item_id", "description"),)

    id = Column(Integer, primary_key=True)
    meeting_id = Column(Integer, ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False)
    agenda_item_id = Column(Integer, ForeignKey("agenda_items.id"))
    description = Column(Text)
    motion_result = Column(String)  # 'passed','failed','deferred'
    vote_breakdown = Column(JSON)  # {member: 'yes'|'no'|'abstain'|'absent'}


class Extraction(Base):
    """Raw LLM output per (meeting, prompt_version) so Phase 3 can be re-run
    and diffed without re-scraping or re-transcribing."""
    __tablename__ = "extractions"
    __table_args__ = (UniqueConstraint("meeting_id", "prompt_version"),)

    id = Column(Integer, primary_key=True)
    meeting_id = Column(Integer, ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False)
    prompt_version = Column(String, nullable=False)
    model = Column(String)
    raw_json = Column(JSON)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class IngestRun(Base):
    """Job log for pipeline runs (manual now, scheduled in Phase 6)."""
    __tablename__ = "ingest_runs"

    id = Column(Integer, primary_key=True)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    finished_at = Column(DateTime(timezone=True))
    phase = Column(String, nullable=False)
    meetings_processed = Column(Integer, default=0)
    bytes_downloaded = Column(BigInteger, default=0)
    errors = Column(JSON, default=list)
