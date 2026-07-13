# Handoff: CouncilHound Frontend Redesign

## Overview

A full redesign of the CouncilHound Next.js frontend (`frontend/` in the councilhound repo), replacing the barebones slate-Tailwind UI with the warm, Clay-inspired system defined in `frontend/DESIGN.md`. Six screens: Briefing (home), Topic Tracker, Meetings, Meeting Detail, Topic Detail, and Ask. The home page moves from a plain two-list dashboard to a "civic briefing": decisions-first headline cards plus a right rail with a deep-teal hot-topics panel, upcoming meetings, and an Ask entry point.

## About the Design Files

The files in this bundle are **design references created in HTML** — an interactive prototype showing intended look and behavior, not production code to copy directly. The task is to **recreate this design in the existing Next.js app** (`frontend/`, App Router + Tailwind), reusing its established patterns: server components fetching via `lib/api.ts`, route structure (`/`, `/topics`, `/topics/[slug]`, `/meetings`, `/meetings/[id]`, `/ask`), and the `StatusBadge` component (restyled per the tokens below).

- `CouncilHound.dc.html` — the main prototype (all 6 screens, interactive; screen switching is prototype-only state — use real routes in Next.js)
- `Home Options.dc.html` — the three explored home directions (1c won, with 1b's teal hot panel)
- `Current UI.dc.html` — recreation of the pre-redesign UI, for before/after reference
- `hound.png` — logo mark (also already in the repo at `frontend/public/brand/hound.png`)

The `.dc.html` files open directly in a browser.

## Fidelity

**High-fidelity.** Colors, typography, spacing, radii, and copy patterns are final and follow `frontend/DESIGN.md` exactly. Recreate pixel-perfectly using Tailwind (extend the theme with the tokens below). Desktop layout only — apply DESIGN.md's responsive rules (hamburger nav < 768px, grids collapse to 1-up) when implementing.

## Global Chrome (all screens)

- **Page canvas**: `#fffaf0` (cream) everywhere. Never cool gray.
- **Font**: Inter (400/500/600). Display headlines: Inter 500 with negative letter-spacing (substitute for Plain Black per DESIGN.md).
- **Top nav**: 64px tall, cream background, `1px solid #f0f0f0` bottom border, sticky. Left: hound.png at 36px height + "CouncilHound" wordmark (18px/600, letter-spacing -0.4px), then nav pills with 40px gap. Nav items: 14px/500, padding 8px 16px; active item gets pill background `#f5f0e0`, border-radius 9999px; inactive items `#6a6a6a`, no background. Items: Briefing (`/`), Tracker (`/topics`), Meetings (`/meetings`), Ask (`/ask`). Right: "Ask a question" primary button → `/ask`.
- **Primary button**: background `#0a0a0a`, white text, 14px/600, padding 12px 20px, border-radius 12px. Hover: `#1f1f1f`.
- **Secondary button**: cream background, ink text, `1px solid #e5e5e5`, same shape (padding 11px 19px to compensate for border). Hover: border-color `#0a0a0a`.
- **Footer**: background `#faf5e8`, padding 24px 32px, 13px `#3a3a3a`. Disclaimer text left, hound.png (30px, opacity 0.9) right. Never dark.
- **Content width**: max 1280px centered, 32px side padding. Detail pages (meeting/topic): max 860px. Ask: max 760px.
- **List containers**: `1px solid #e5e5e5`, border-radius 16px, cream background; rows divided by `1px solid #f0f0f0`, padding 12px 20px, hover background `#faf5e8`, cursor pointer.
- **Status badges** (replaces `StatusBadge.tsx` colors): border-radius 9999px, padding 3px 10px, 12px/500.
  - in progress: bg `#f7e5b8` / text `#5c4708`
  - proposed: bg `#e3daf8` / text `#3d2c73`
  - approved, completed: bg `#cfe8de` / text `#14453a`
  - denied, failed: bg `#ffd3cd` / text `#7a1f14`
  - deferred, continued, withdrawn (and unknown): bg `#ebe6d6` / text `#3a3a3a`
- **Filter pills**: border-radius 9999px, padding 8px 16px, 14px/500, white-space nowrap. Active: bg `#0a0a0a`, text `#fffaf0`. Inactive: cream bg, text `#6a6a6a`, `1px solid #e5e5e5`.
- **Eyebrow label**: 12px/600, letter-spacing 1.5px, uppercase, `#6a6a6a`.

## Screens / Views

### 1. Briefing (`/`)
- **Purpose**: decisions-first weekly digest. Data: recent meetings' agenda-item outcomes/votes (left), hot topics (`/entities/hot`), upcoming meetings, ask entry.
- **Layout**: eyebrow "THE BRIEFING · WEEK OF <date> · CITY OF FAIRFAX, VA", then grid `1.5fr 1fr`, 32px gap.
- **Left column**: display headline summarizing the week (32px/500, letter-spacing -0.5px, line-height 1.15), then decision cards (12px gap). Each card: `1px solid #e5e5e5`, radius 16px, padding 16px 20px; hover border `#0a0a0a`; links to its meeting page. Card content: outcome badge (status-badge style but 600 weight, uppercase text like "PASSED 4–1", "CONTINUED", "FAILED 2–3", "RECOMMENDED") + meta (13px `#6a6a6a`, "City Council · Jun 24 · item 8"), title (16px/600), one-sentence summary (14px/1.55 `#3a3a3a`).
- **Right rail** (20px gap):
  - **Hot topics panel**: bg `#1a3a3a`, white text, radius 24px, padding 28px. Eyebrow "HOT RIGHT NOW" in mint `#a4d4c5`; heading "What the council is spending its time on" (24px/500, -0.3px). Ranked rows (14px gap): name (14px/600) + minutes (13px/600 mint) on one line, then 6px-tall bar — track `rgba(255,255,255,0.14)`, fill mint, width proportional to max minutes, radius 9999px. Rows link to topic pages. Bottom: "See all hot topics" button (cream bg `#fffaf0`, ink text, primary shape) → `/topics?type=hot`.
  - **Next up card**: hairline card, radius 24px, padding 24px. Eyebrow "NEXT UP"; rows of date (14px/600, 52px fixed width) + meeting title (14px/600) + note (13px `#6a6a6a`).
  - **Ask card**: bg `#f5f0e0`, radius 24px, padding 24px. hound.png (30px) + "Ask the hound" (16px/600); inline input (cream bg, hairline border, radius 12px) with black "Ask" button inside (radius 8px, padding 8px 14px, 13px/600). Submitting navigates to `/ask` with the question.

### 2. Topic Tracker (`/topics`)
- **Title**: "Topic tracker" (32px/500, -0.5px) + sub (14px `#6a6a6a`).
- **Pills row**: "🔥 Hot" + entity types (project, ordinance, resolution, case number, topic, location, person) as filter pills; search input right-aligned (radius 12px, hairline border, padding 10px 16px, 220px wide, hidden in Hot view). Search filters the list by name (current app uses `?q=` param — keep that).
- **Hot view**: caption line, then list container. Row: rank (15px/600 `#9a9a9a`, right-aligned 24px), name (14px/600) + "N mentions…" meta (13px `#6a6a6a`), a 220px bar cluster (6px bar, track `#ebe6d6`, fill `#1a3a3a`, minutes label 13px/600 `#14453a`), status badge.
- **Type views**: rows with name (14px/600), "N updates · last <date>" meta, status badge right. Empty state: "Nothing here yet." (14px `#6a6a6a`, padding 24px 20px).

### 3. Meetings (`/meetings`)
- Title "Meetings" + sub, body filter pills (All bodies / City Council / Planning Commission), list rows: title (14px/600), meta "Body · N agenda items · M min" (13px `#6a6a6a`), date right-aligned (13px/500 `#6a6a6a`).

### 4. Meeting Detail (`/meetings/[id]`)
- Max 860px. "← All meetings" back link (14px/600 `#6a6a6a`, hover ink). Eyebrow "BODY · DATE", title (32px/500), then button row: "▶ Watch recording" (primary), "Agenda ↗" and "Minutes ↗" (secondary), meta text "N agenda items · M min" (13px `#6a6a6a`). Render each button only if its URL exists.
- "Agenda" heading (18px/600), agenda-item cards (12px gap): hairline, radius 16px, padding 18px 20px. Label chip (mono 12px/600, bg `#f5f0e0`, radius 6px, padding 2px 8px) + title (15px/600); description 14px/1.55 `#3a3a3a`; "Outcome:" prefix 600 `#6a6a6a`.
- **Vote block**: bg `#faf5e8`, radius 12px, padding 12px 14px. Result word 600 (passed `#14453a`, failed `#7a1f14`, else `#5c4708`) + motion description. Breakdown: flex-wrap row (column-gap 14px), "Member: vote" spans (13px/500, white-space nowrap) colored yes `#14453a`, no `#7a1f14`, abstain `#5c4708`, absent `#9a9a9a`.
- Empty agenda: dashed hairline card, "Not yet processed — agenda items appear after the extraction pass."

### 5. Topic Detail (`/topics/[slug]`)
- Max 860px. "← Topic tracker" back link, entity-type eyebrow, name (32px/500) + status badge inline.
- **Summary**: 18px/600 heading; paragraph in hairline card (radius 16px, padding 18px 20px, 14px/1.6 `#3a3a3a`). Only if profile summary exists.
- **Open questions & options on the table**: warm callout cards — bg `#faf3dd`, `1px solid #e8b94a`, radius 16px, padding 14px 18px, text `#5c4708`.
- **What members have said**: 2-column grid (12px gap) of hairline cards; member name 14px/600, summary 14px/1.6. Fine-print caveat below (13px `#9a9a9a`).
- **Full history**: vertical timeline — `2px solid #ebe6d6` left border, 24px left padding, 28px gap. Dot: 12px circle, bg `#1a3a3a`, 2px cream border, at each entry. Entry: date (14px/600) + underlined meeting link ("City Council · item 8") + optional status badge; update text 14px/1.6; "minutes ↗ / agenda ↗" links (13px `#9a9a9a`, hover ink).
- Empty timeline: "No tracked updates yet."

### 6. Ask (`/ask`)
- Max 760px, top padding 48px. hound.png (44px) + "Ask the hound" (32px/500) side by side; sub-line 14px `#6a6a6a`.
- **Input bar**: hairline container radius 16px, padding 8px (20px left); borderless input (15px) + primary "Ask" button. Enter submits. Button label becomes "Searching…" while loading.
- **Idle**: suggestion chips (pill, bg `#f5f0e0`, padding 8px 16px, 14px/500 `#3a3a3a`, hover `#ebe6d6`); clicking submits that question.
- **Loading**: hound.png (28px) + "Sniffing through the record…" (14px `#6a6a6a`).
- **Answer**: hairline card, radius 16px, padding 22px 24px, 15px/1.6 `#1a1a1a`, `white-space: pre-wrap`. Then "SOURCES" eyebrow and citation cards: `[n]` mono chip (bg `#f5f0e0`, radius 6px), meeting title 600, date 13px `#6a6a6a`, optional "@ mm:ss" timestamp 13px `#9a9a9a`; excerpt in quotes 13px `#6a6a6a`; link "▶ Watch this moment" (transcript) or "Open document" — 13px/600 underlined ink.

## Interactions & Behavior

- All list rows, decision cards, and hot-topic rows are links (hover: `#faf5e8` row background or ink border on cards).
- Filters are URL params as in the current app (`/topics?type=`, `?q=`, `/meetings?body=`) — server components re-render.
- Ask flow: POST `/ask/` as in the current `ask/page.tsx`; states idle → loading → answer/error. Error text: 14px in the denied red `#7a1f14`.
- Scroll to top on navigation (default Next.js behavior).
- No animations required; keep hover states only as specified.

## State Management

Reuse the existing architecture: server components + `lib/api.ts` for meetings/entities/hot; client component for Ask (`question`, `loading`, `error`, `result`). The briefing page needs decisions data — derive from recent `MeetingDetail.agenda_items` outcomes/votes, or add a dedicated API endpoint; the prototype's cards show the target shape (badge, meta, title, one-line summary). "Next up" requires upcoming-meeting data (not in the current API — omit the card until it exists).

## Design Tokens

Colors (from `frontend/DESIGN.md`, plus derived tints used here):
- canvas `#fffaf0` · surface-soft `#faf5e8` · surface-card `#f5f0e0` · surface-strong `#ebe6d6`
- ink `#0a0a0a` · primary-active `#1f1f1f` · body-strong `#1a1a1a` · body `#3a3a3a` · muted `#6a6a6a` · muted-soft `#9a9a9a`
- hairline `#e5e5e5` · hairline-soft `#f0f0f0`
- brand-teal `#1a3a3a` · brand-mint `#a4d4c5` · brand-ochre `#e8b94a`
- Derived status tints (harmonized with the brand palette): ochre-tint `#f7e5b8`/`#5c4708`, lavender-tint `#e3daf8`/`#3d2c73`, mint-tint `#cfe8de`/`#14453a`, coral-tint `#ffd3cd`/`#7a1f14`, warm callout `#faf3dd`

Typography: Inter. Display 32px/500/-0.5px (page titles, headlines), 24px/500/-0.3px (panel heading), 18px/600 (section heads), 16px/600 (card titles), 15px/600 (row emphasis), 14px/400–600 (body/UI), 13px (meta), 12px/600/+1.5px uppercase (eyebrows). Line-height 1.55–1.6 for running text.

Radii: 6px (chips), 8px (small buttons), 12px (buttons, inputs, vote blocks), 16px (cards, list containers), 24px (rail feature panels), 9999px (pills, badges, bars).

Spacing: 4px base; key values 8/12/16/20/24/28/32px; 32px page gutters; 64px nav height.

## Assets

- `hound.png` — logo mark, 239×209 with true alpha, from `frontend/public/brand/hound.png` in the repo. Used in nav (36px), ask card (30px), ask page (44px), loading state (28px), footer (30px).
- Inter via Google Fonts (weights 400/500/600/700).
- No other imagery or icons; arrows/▶/🔥 are text glyphs.

## Files

- `CouncilHound.dc.html` — main interactive prototype (source of truth)
- `Home Options.dc.html` — home-page explorations (1a/1b/1c)
- `Current UI.dc.html` — pre-redesign recreation (before/after reference)
- `hound.png` — logo asset
