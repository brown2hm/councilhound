"""Follow-by-email subscriptions: a topic, a member's votes, a body's
meetings, an area of the city, or the weekly briefing. POST creates an
unconfirmed row and sends a confirmation link; the tokened GET links confirm
or remove it. Notifications themselves go out from the nightly job
(councilhound.notify)."""
import re
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from councilhound.bodies import BODY_KEYS
from councilhound.config import JURISDICTION

_ACTIVITY = JURISDICTION.identity.activity_noun
from councilhound.db.models import Entity, EntityAlias, EntityUpdate, TopicSubscription, Vote
from councilhound.mail import send_email
from councilhound.notify import API_BASE_URL, SITE_BASE_URL, describe

from app.db import db_session
from app.ratelimit import check_subscribe_rate

router = APIRouter()

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class SubscribeRequest(BaseModel):
    email: str
    # what to follow — see TopicSubscription.kind
    kind: str = "topic"
    entity_slug: str | None = None   # topic (non-person) or member (person)
    body: str | None = None          # body: a councilhound.bodies key
    lat: float | None = None         # area
    lng: float | None = None
    radius_m: int | None = None
    label: str | None = None         # area: how to describe it in emails


KINDS = {"topic", "member", "body", "area", "briefing"}
BODIES = set(BODY_KEYS)
MIN_RADIUS_M, MAX_RADIUS_M = 100, 10000


def _resolve_entity(session: Session, slug: str) -> Entity | None:
    entity = session.scalar(select(Entity).where(Entity.canonical_slug == slug))
    if entity is None:
        alias = session.scalar(select(EntityAlias)
                               .where(func.lower(EntityAlias.alias) == slug.lower()))
        entity = session.get(Entity, alias.entity_id) if alias else None
    return entity


def _page(title: str, body: str, link: str | None = None) -> HTMLResponse:
    back = f'<p><a href="{link or SITE_BASE_URL}">Back to CouncilHound</a></p>'
    return HTMLResponse(
        f"<!doctype html><html><head><title>{title} — CouncilHound</title>"
        f'<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"</head><body style=\"font-family:system-ui;max-width:480px;"
        f"margin:80px auto;padding:0 20px;line-height:1.5\">"
        f"<h1 style='font-size:22px'>{title}</h1><p>{body}</p>{back}</body></html>")


def _validate(req: SubscribeRequest, session: Session) -> dict:
    """Column values for the new row, or a 4xx. Each kind has its own key."""
    if req.kind not in KINDS:
        raise HTTPException(422, "unknown follow kind")
    if req.kind in ("topic", "member"):
        if not req.entity_slug:
            raise HTTPException(422, "entity_slug is required")
        entity = _resolve_entity(session, req.entity_slug)
        if entity is None:
            raise HTTPException(404, "unknown topic")
        if (entity.entity_type == "person") != (req.kind == "member"):
            raise HTTPException(422, "that isn't a " + ("member" if req.kind == "member" else "topic"))
        return {"entity_id": entity.id}
    if req.kind == "body":
        if req.body not in BODIES:
            raise HTTPException(422, "body must be one of: " + ", ".join(BODY_KEYS))
        return {"body": req.body}
    if req.kind == "area":
        if req.lat is None or req.lng is None or req.radius_m is None:
            raise HTTPException(422, "lat, lng, and radius_m are required")
        if not (-90 <= req.lat <= 90 and -180 <= req.lng <= 180):
            raise HTTPException(422, "coordinates out of range")
        radius = max(MIN_RADIUS_M, min(MAX_RADIUS_M, req.radius_m))
        return {"lat": round(req.lat, 5), "lng": round(req.lng, 5), "radius_m": radius,
                "label": (req.label or "").strip()[:120] or None}
    return {}


def _find_existing(session: Session, email: str, kind: str, key: dict):
    q = select(TopicSubscription).where(TopicSubscription.email == email,
                                        TopicSubscription.kind == kind)
    for col in ("entity_id", "body", "lat", "lng", "radius_m"):
        if col in key:
            q = q.where(getattr(TopicSubscription, col) == key[col])
    return session.scalar(q)


@router.post("/")
def subscribe(req: SubscribeRequest, request: Request,
              session: Session = Depends(db_session)):
    check_subscribe_rate(request)
    email = req.email.strip().lower()
    if not _EMAIL_RE.match(email):
        raise HTTPException(422, "that doesn't look like an email address")
    key = _validate(req, session)

    sub = _find_existing(session, email, req.kind, key)
    if sub is not None and sub.confirmed:
        return {"status": "already-following"}
    if sub is None:
        # watermarks start at the current high-water mark: subscribers hear
        # about what happens next, not the whole back-history
        max_update = session.scalar(select(func.coalesce(func.max(EntityUpdate.id), 0))) or 0
        max_vote = session.scalar(select(func.coalesce(func.max(Vote.id), 0))) or 0
        sub = TopicSubscription(email=email, kind=req.kind, token=secrets.token_urlsafe(24),
                                last_update_id=max_update, last_vote_id=max_vote, **key)
        session.add(sub)
        session.commit()

    name, link = describe(session, sub)
    confirm = f"{API_BASE_URL}/subscriptions/confirm?token={sub.token}"
    what = {"topic": "this topic", "member": "this member", "body": "these meetings",
            "area": "this area", "briefing": "the weekly briefing"}[sub.kind]
    sent = send_email(
        email,
        f"Confirm: follow {name} on CouncilHound",
        f"You (or someone with your address) asked to follow {name} "
        f"on CouncilHound. Confirm to get an email when the {_ACTIVITY} record "
        f"for {what} changes:\n\n{confirm}\n\nIf this wasn't you, "
        f"ignore this email and nothing will be sent.",
        f'<p>You (or someone with your address) asked to follow '
        f'<strong>{name}</strong> on CouncilHound.</p>'
        f'<p><a href="{confirm}">Confirm to follow {what}</a> and get an '
        f'email when its {_ACTIVITY} record changes.</p>'
        f"<p style='font-size:12px;color:#666'>If this wasn't you, ignore "
        f"this email and nothing will be sent.</p>")
    return {"status": "confirmation-sent" if sent else "email-unavailable"}


@router.get("/confirm")
def confirm(token: str, session: Session = Depends(db_session)):
    sub = session.scalar(select(TopicSubscription)
                         .where(TopicSubscription.token == token))
    if sub is None:
        return _page("Link expired", "This confirmation link is no longer valid.")
    sub.confirmed = True
    session.commit()
    name, link = describe(session, sub)
    return _page("You're following " + name,
                 "You'll get an email when there's news. "
                 "Every email has an unfollow link.", link)


@router.get("/unsubscribe")
def unsubscribe(token: str, session: Session = Depends(db_session)):
    sub = session.scalar(select(TopicSubscription)
                         .where(TopicSubscription.token == token))
    if sub is None:
        return _page("Already unfollowed", "This link was already used.")
    name, _link = describe(session, sub)
    session.delete(sub)
    session.commit()
    return _page("Unfollowed " + name,
                 "You won't get any more emails about this.")
