# Frontend (Phase 5)

Next.js app, not yet scaffolded beyond this placeholder. Planned pages:

- `/` - meeting timeline/dashboard (filter by date, type, topic)
- `/topics/[slug]` - entity/project tracker, showing history across meetings
- `/ask` - Q&A chat hitting the API's /ask endpoint, with clickable citations
  back to the source Granicus clip timestamp or document

Talks to the API service (see ../api) - set NEXT_PUBLIC_API_URL in .env.
Run `npx create-next-app@latest .` (or equivalent) here to properly scaffold
once Phase 4 (API) has real endpoints to build against - no point wiring up
pages before there's data to show.
