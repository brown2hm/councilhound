"""Follow-a-topic email subscriptions. POST creates an unconfirmed row and
sends a confirmation link; the tokened GET links confirm or remove it.
Notifications themselves go out from the nightly job (councilhound.notify)."""
import re
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from councilhound.db.models import Entity, EntityAlias, EntityUpdate, TopicSubscription
from councilhound.mail import send_email
from councilhound.notify import API_BASE_URL, SITE_BASE_URL

from app.db import db_session
from app.ratelimit import check_subscribe_rate

router = APIRouter()

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class SubscribeRequest(BaseModel):
    email: str
    entity_slug: str


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


@router.post("/")
def subscribe(req: SubscribeRequest, request: Request,
              session: Session = Depends(db_session)):
    check_subscribe_rate(request)
    email = req.email.strip().lower()
    if not _EMAIL_RE.match(email):
        raise HTTPException(422, "that doesn't look like an email address")
    entity = _resolve_entity(session, req.entity_slug)
    if entity is None:
        raise HTTPException(404, "unknown topic")

    sub = session.scalar(select(TopicSubscription).where(
        TopicSubscription.email == email,
        TopicSubscription.entity_id == entity.id))
    if sub is not None and sub.confirmed:
        return {"status": "already-following"}
    if sub is None:
        # watermark starts at the current high-water mark: subscribers hear
        # about what happens next, not the whole back-history
        max_update = session.scalar(
            select(func.coalesce(func.max(EntityUpdate.id), 0))
            .where(EntityUpdate.entity_id == entity.id)) or 0
        sub = TopicSubscription(email=email, entity_id=entity.id,
                                token=secrets.token_urlsafe(24),
                                last_update_id=max_update)
        session.add(sub)
        session.commit()

    confirm = f"{API_BASE_URL}/subscriptions/confirm?token={sub.token}"
    sent = send_email(
        email,
        f"Confirm: follow {entity.name} on CouncilHound",
        f"You (or someone with your address) asked to follow {entity.name} "
        f"on CouncilHound. Confirm to get an email when the council record "
        f"for this topic changes:\n\n{confirm}\n\nIf this wasn't you, "
        f"ignore this email and nothing will be sent.",
        f'<p>You (or someone with your address) asked to follow '
        f'<strong>{entity.name}</strong> on CouncilHound.</p>'
        f'<p><a href="{confirm}">Confirm to follow this topic</a> and get an '
        f'email when its council record changes.</p>'
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
    entity = session.get(Entity, sub.entity_id)
    link = f"{SITE_BASE_URL}/topics/{entity.canonical_slug}"
    return _page("You're following " + entity.name,
                 "You'll get an email when this topic's council record changes. "
                 "Every email has an unfollow link.", link)


@router.get("/unsubscribe")
def unsubscribe(token: str, session: Session = Depends(db_session)):
    sub = session.scalar(select(TopicSubscription)
                         .where(TopicSubscription.token == token))
    if sub is None:
        return _page("Already unfollowed", "This link was already used.")
    entity = session.get(Entity, sub.entity_id)
    session.delete(sub)
    session.commit()
    return _page("Unfollowed " + entity.name,
                 "You won't get any more emails about this topic.")
