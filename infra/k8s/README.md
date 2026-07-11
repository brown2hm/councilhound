# Kubernetes manifests (Phase 6 - later)

Not needed for local dev (docker-compose handles that). When ready to move
to k8s:

- Deployments for `api` and `frontend` (stateless, scale horizontally)
- StatefulSet or managed Postgres (with pgvector) - don't run Postgres as a
  bare Deployment in production
- CronJob for the ingestion pipeline (Phase 1-3), running on a schedule
  (e.g. daily) instead of the docker-compose placeholder `tail -f /dev/null`
- Secrets for ANTHROPIC_API_KEY, DATABASE_URL
- Ingress in front of `frontend` + `api`

Revisit this once Phases 1-5 are working locally via docker-compose - no
manifests written yet on purpose.
