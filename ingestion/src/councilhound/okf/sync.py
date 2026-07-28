"""The maintenance loop: one invocation that takes the bundle from "new
meetings landed" to "prod is serving them".

    refresh -> curate -> lint -> commit -> push

The order is load-bearing in two places. Lint gates everything downstream: a
bundle that does not lint is neither committed nor pushed, because lint is
the only automated check standing between an LLM edit and a live page — the
curator's first production run shipped two 404s, and lint is what now catches
that class of error. And commit precedes push so whatever prod serves always
corresponds to a commit; a failed push can be retried, an unrecorded push
cannot be reconstructed.

Seeding is deliberately NOT part of the default loop. refresh only walks
directories that already exist, so new projects never appear on their own —
but wiki_candidates currently returns unmerged duplicates of projects that
already have wikis, and seeding those would manufacture near-duplicate pages.
The loop reports how many candidates lack a wiki and leaves creating them to
a human with --seed.

This runs locally against a proxied prod DB rather than on the jobs machine:
the bundle is git-canonical, and a container writing to an ephemeral
filesystem is exactly how the 2026-07-21 bundle was stranded.
"""
import logging
import os
import subprocess
from datetime import date

from sqlalchemy.orm import Session

from councilhound.okf.curate import curate_pending
from councilhound.okf.export import refresh_bundle, seed_bundle, wiki_candidates
from councilhound.okf.lint import lint_bundle
from councilhound.okf.push import push_bundle

log = logging.getLogger(__name__)


def _git(root: str, *args: str) -> str:
    proc = subprocess.run(["git", "-C", root, *args],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {proc.stderr.strip()}")
    return proc.stdout.strip()


def _pending(root: str, path: str) -> str:
    return _git(root, "status", "--porcelain", "--", path)


def _unseeded(session: Session, bundle_dir: str) -> list[str]:
    """Candidate projects with no wiki directory yet."""
    projects_root = os.path.join(bundle_dir, "projects")
    have = set()
    if os.path.isdir(projects_root):
        have = {d for d in os.listdir(projects_root)
                if os.path.isdir(os.path.join(projects_root, d))}
    return sorted(e.canonical_slug for e in wiki_candidates(session)
                  if e.canonical_slug not in have)


def _commit_message(result: dict) -> str:
    refreshed = result.get("refreshed", {}).get("refreshed", 0)
    curated = (result.get("curated") or {}).get("updated", 0)
    seeded = (result.get("seeded") or {}).get("seeded", 0)
    bits = []
    if seeded:
        bits.append(f"seeded {seeded}")
    if refreshed:
        bits.append(f"refreshed {refreshed}")
    if curated:
        bits.append(f"curated {curated}")
    headline = ", ".join(bits) or "no content change"
    lines = [f"okf-sync: {headline}", ""]
    for stage in ("seeded", "refreshed", "curated"):
        if result.get(stage):
            lines.append(f"{stage}: {result[stage]}")
    rejected = (result.get("curated") or {}).get("rejected", 0)
    failed = (result.get("curated") or {}).get("failed", 0)
    if rejected or failed:
        lines += ["",
                  f"curator: {rejected} edit(s) rejected for touching a "
                  f"curator:off region, {failed} failed — those pages are "
                  f"unchanged and will be retried next run."]
    return "\n".join(lines)


def sync_bundle(session: Session, bundle_dir: str, *, seed: bool = False,
                curate: bool = True, curate_limit: int | None = None,
                commit: bool = True, push: bool = True,
                push_session: Session | None = None) -> dict:
    """Run the loop. Returns a result dict; `ok` is False when a precondition
    or the lint gate stopped it, with `aborted` naming the reason.

    On abort the working tree is left exactly as the run made it — refresh and
    curate output is preserved so it can be inspected and fixed rather than
    silently discarded. Nothing is committed and nothing reaches prod."""
    result: dict = {"ok": True, "aborted": None}
    root = _git(bundle_dir, "rev-parse", "--show-toplevel")

    if commit and _pending(root, bundle_dir):
        result.update(ok=False, aborted=(
            "the bundle has uncommitted changes. Commit or stash them so this "
            "run's commit contains only what it produced, or pass --no-commit."))
        return result

    if seed:
        result["seeded"] = seed_bundle(session, bundle_dir)
    result["unseeded_candidates"] = _unseeded(session, bundle_dir)
    result["refreshed"] = refresh_bundle(session, bundle_dir)
    if curate:
        result["curated"] = curate_pending(session, bundle_dir,
                                           limit=curate_limit)

    problems = lint_bundle(bundle_dir, session)
    result["lint_problems"] = problems
    if problems:
        result.update(ok=False, aborted=(
            f"{len(problems)} lint problem(s); nothing committed or pushed. "
            f"The working tree holds this run's edits — fix or revert them."))
        return result

    if commit and _pending(root, bundle_dir):
        _git(root, "add", "--", bundle_dir)
        _git(root, "commit", "-m", _commit_message(result))
        result["commit"] = _git(root, "rev-parse", "--short", "HEAD")

    if push:
        # idempotent, so run it even when nothing changed this pass — it
        # self-heals a previous run that committed but failed to push
        result["pushed"] = push_bundle(push_session or session, bundle_dir)
    return result
