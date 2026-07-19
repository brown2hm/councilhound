"""Open Knowledge Format (OKF) knowledge bundle.

One wiki-style directory per tracked development project, rendered from the
DB per the OKF v0.1 spec (markdown concepts + YAML frontmatter, reserved
index.md/log.md). The bundle is canonical for narrative knowledge; okf-push
mirrors it into wiki_pages so the cloud API can serve it.

Page ownership (the rule that makes incremental maintenance safe):
- pipeline-owned: history.md, every index.md, frontmatter status fields —
  regenerated deterministically, never hand-edited;
- curator-owned: overview.md, positions.md, impact.md — seeded once, then
  edited incrementally (LLM curator or humans); regeneration never clobbers.
Impact numbers never appear literally in prose — pages reference metrics via
{{metric:<key>}} markers the frontend resolves against the live evaluation.
"""
