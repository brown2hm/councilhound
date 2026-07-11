"""
SQLAlchemy models mirroring schema.sql.

Kept in sync manually for now (schema.sql is the source of truth, loaded via
docker-entrypoint-initdb.d). If this project grows, switch to Alembic
migrations generated from these models instead of hand-written SQL.
"""
from sqlalchemy import (
    Column, Integer, String, Text, Date, DateTime, ForeignKey, JSON, Numeric
)
from sqlalchemy.orm import declarative_base, relationship
from pgvector.sqlalchemy import Vector

Base = declarative_base()


class Meeting(Base):
    __tablename__ = "meetings"
    id = Column(Integer, primary_key=True)
    granicus_clip_id = Column(String, nullable=False)
    granicus_view_id = Column(String, nullable=False)
    meeting_type = Column(String, nullable=False)
    meeting_date = Column(Date, nullable=False)
    title = Column(Text)
    video_url = Column(Text)
    agenda_url = Column(Text)
    minutes_url = Column(Text)
    status = Column(String, nullable=False, default="discovered")
    created_at = Column(DateTime)

    documents = relationship("Document", back_populates="meeting")


class Document(Base):
    __tablename__ = "documents"
    id = Column(Integer, primary_key=True)
    meeting_id = Column(Integer, ForeignKey("meetings.id"))
    doc_type = Column(String, nullable=False)
    source_url = Column(Text, nullable=False)
    local_path = Column(Text)
    agenda_item_label = Column(Text)
    raw_text = Column(Text)
    fetched_at = Column(DateTime)

    meeting = relationship("Meeting", back_populates="documents")


class TranscriptChunk(Base):
    __tablename__ = "transcript_chunks"
    id = Column(Integer, primary_key=True)
    meeting_id = Column(Integer, ForeignKey("meetings.id"))
    start_seconds = Column(Numeric)
    end_seconds = Column(Numeric)
    text = Column(Text, nullable=False)
    embedding = Column(Vector(1536))


class Entity(Base):
    __tablename__ = "entities"
    id = Column(Integer, primary_key=True)
    entity_type = Column(String, nullable=False)
    name = Column(Text, nullable=False)
    canonical_slug = Column(String, unique=True, nullable=False)
    first_seen_meeting_id = Column(Integer, ForeignKey("meetings.id"))
    summary = Column(Text)


class EntityMention(Base):
    __tablename__ = "entity_mentions"
    id = Column(Integer, primary_key=True)
    entity_id = Column(Integer, ForeignKey("entities.id"))
    meeting_id = Column(Integer, ForeignKey("meetings.id"))
    document_id = Column(Integer, ForeignKey("documents.id"))
    transcript_chunk_id = Column(Integer, ForeignKey("transcript_chunks.id"))
    context_text = Column(Text)
    role = Column(String)


class Vote(Base):
    __tablename__ = "votes"
    id = Column(Integer, primary_key=True)
    meeting_id = Column(Integer, ForeignKey("meetings.id"))
    agenda_item_label = Column(Text)
    description = Column(Text)
    motion_result = Column(String)
    vote_breakdown = Column(JSON)
