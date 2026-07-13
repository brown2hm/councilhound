"""Granicus deep links. We never host or embed video — every watch link goes
to the city's own player, seeked via the starttime param."""
from councilhound.config import GRANICUS_BASE_URL


def clip_link(view_id: str, clip_id: str | None, start_seconds: float | int | None = None) -> str | None:
    if not clip_id:
        return None
    url = f"{GRANICUS_BASE_URL}/MediaPlayer.php?view_id={view_id}&clip_id={clip_id}"
    if start_seconds is not None:
        url += f"&starttime={int(start_seconds)}"
    return url
