# Changelog

## 0.2.0 — the interpretability round (July 2026)

A release focused on making the tracker trustworthy and legible for two
readers: a citizen following city projects, and a council member preparing
for a meeting.

### Topic quality

- **Entity dedup shipped.** Slug normalization now canonicalizes spelling
  drift (Blvd/Ave/Rd, thru/through, improvement/improvements, masterplan,
  Draft/Proposed prefixes); the nightly job re-slugs stranded entities and
  merges twins automatically; and `merge-entities-batch` applies the
  curated one-time merge of the 105 audited prod duplicate clusters
  (`ingestion/data/entity_merges_2026_07.json`) — Davies ×8, CIP ×11,
  Willard-Sherwood ×5, Blenheim ×4, and friends. Merges now carry official
  city-project links, geocodes, wiki pages, and follower subscriptions to
  the surviving entity, and old slugs keep resolving as aliases.
- **Minutes govern vote totals.** Profile synthesis (prompt v2) treats the
  minutes-derived dated record as authoritative for vote totals and
  outcomes; transcript excerpts supply color only. All profiles regenerate
  under the new rule on the next nightly run.

### Reach

- **Mobile works now.** Hamburger navigation below desktop widths; the
  header no longer forces a ~900 px minimum layout width that clipped and
  pan-scrolled every page on phones.
- **Every page has real metadata** — per-page titles, descriptions, and
  OpenGraph tags for search results and link-share cards.

### Following along

- **Follow a topic.** Email signup on every topic page: tokened
  confirmation, one digest per subscriber when followed topics get new
  updates (sent by the nightly job), one-click unsubscribe in every email.
- **Meeting calendar feed.** `/meetings/upcoming.ics` — subscribe from any
  calendar app; linked from the briefing and meetings pages.

### Interpretability

- **Plain-language fiscal summary** on impact pages: a deterministic,
  jargon-free paragraph reconciling the two net-fiscal framings as one
  cost/gain range, with one line on why they differ.
- **Negative currency renders as −$1.7M** (never `$-1.7M`), via one shared
  formatter.
- **Pre-meeting brief.** `/meetings/upcoming/<event>`: every tracked topic
  named on an upcoming agenda, with its status, the agenda line naming it,
  what happened last time, and links to full history and impact analysis.
  Linked from the briefing's Next-up card and from topic-page callouts.

### Release steps (prod)

1. Run the migration (adds `topic_subscriptions`):
   `alembic upgrade head` via the jobs machine.
2. Apply the curated merge batch once (dry-run first):
   `python -m councilhound.cli merge-entities-batch data/entity_merges_2026_07.json`
   then re-run with `--apply`. Safe to re-run; already-merged rows skip.
3. Set new secrets on the api and jobs apps for email:
   `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `MAIL_FROM`
   (unset = signups accepted but mail is logged and dropped), plus
   `SITE_BASE_URL` / `API_BASE_URL` if they differ from the defaults.
4. Deploy api and frontend as usual. The nightly `daily` job picks up the
   dedupe pass, profile regeneration (prompt v2), and the notifier on its
   next run.
