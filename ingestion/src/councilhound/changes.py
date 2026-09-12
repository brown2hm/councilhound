"""What changed: status transitions and first appearances in a window,
shared by the API's change feed and the weekly briefing email. Each affected
entity's full status history is walked so a change is measured against the
last status actually set, not the previous row (which may carry none)."""
import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from councilhound.db.models import AgendaItem, Entity, EntityUpdate, Meeting


def recent_changes(session: Session, days: int,
                   since: datetime.date | None = None) -> list[dict]:
    since = since or (datetime.date.today() - datetime.timedelta(days=days))
    touched = (select(EntityUpdate.entity_id)
               .join(Meeting, EntityUpdate.meeting_id == Meeting.id)
               .where(Meeting.meeting_date >= since).distinct())
    rows = session.execute(
        select(EntityUpdate, Meeting, Entity, AgendaItem)
        .join(Meeting, EntityUpdate.meeting_id == Meeting.id)
        .join(Entity, EntityUpdate.entity_id == Entity.id)
        .outerjoin(AgendaItem, EntityUpdate.agenda_item_id == AgendaItem.id)
        .where(EntityUpdate.entity_id.in_(touched), Entity.entity_type != "person")
        .order_by(EntityUpdate.entity_id, Meeting.meeting_date, EntityUpdate.id)
    ).all()

    changes: list[dict] = []
    prev_status: dict[int, str | None] = {}
    seen_before: set[int] = set()
    for upd, meeting, entity, item in rows:
        # a freshly flushed row may still hold the ISO string it was built with
        mdate = meeting.meeting_date
        if not isinstance(mdate, datetime.date):
            mdate = datetime.date.fromisoformat(str(mdate))
        in_window = mdate >= since
        first = entity.id not in seen_before
        seen_before.add(entity.id)
        before = prev_status.get(entity.id)
        kind = None
        if in_window and first:
            kind = "new"
        elif in_window and upd.status_after and upd.status_after != before:
            kind = "status_change"
        if kind:
            changes.append({
                "id": upd.id,
                "kind": kind,
                "slug": entity.canonical_slug,
                "name": entity.name,
                "entity_type": entity.entity_type,
                "from_status": None if first else before,
                "to_status": upd.status_after,
                "current_status": entity.current_status,
                "date": mdate.isoformat(),
                "meeting_id": meeting.id,
                "meeting_title": meeting.title,
                "body": meeting.body,
                "granicus_view_id": meeting.granicus_view_id,
                "granicus_clip_id": meeting.granicus_clip_id,
                "agenda_item_label": item.label if item else None,
                "start_seconds": item.start_seconds if item else None,
                "update_text": upd.update_text,
            })
        if upd.status_after:
            prev_status[entity.id] = upd.status_after
    changes.sort(key=lambda c: (c["date"], c["id"]), reverse=True)
    return changes


def status_words(status: str | None) -> str:
    return (status or "no status").replace("_", " ")
