"""The API's view of the jurisdiction config: what the front end needs to
render one jurisdiction (name, bodies, map defaults, features) without any
of it baked into the web image."""
from councilhound.bodies import REGISTRY
from councilhound.config import JURISDICTION
from councilhound.jurisdiction import JurisdictionConfig


def public_payload(cfg: JurisdictionConfig = JURISDICTION) -> dict:
    ident, site, disp = cfg.identity, cfg.site, cfg.display
    def roles(b) -> list[str]:
        return [r.title for r in b.roster.roles.values()] if b.roster else []
    bodies = [
        {"key": b.key, "label": b.label, "short": b.short, "color": b.color,
         "hot": b.hot, "recommends": b.recommends, "recorded": b.recorded, "roles": roles(b)}
        for b in REGISTRY.bodies.values()
    ] if cfg is JURISDICTION else [
        {"key": b.key, "label": b.label, "short": b.short, "color": b.color or 0,
         "hot": b.hot, "recommends": b.recommends, "recorded": b.recorded, "roles": roles(b)}
        for b in cfg.bodies
    ]
    return {
        "slug": cfg.slug,
        "name": cfg.name,
        "identity": {
            "short_name": ident.short_name, "noun": ident.noun,
            "state_abbr": ident.state_abbr, "timezone": ident.timezone,
            "legislative_body_label": ident.legislative_body_label,
            "record_phrase": ident.record_phrase, "activity_noun": ident.activity_noun,
        },
        "site": {"site_base_url": site.site_base_url, "api_base_url": site.api_base_url},
        "bodies": bodies,
        "display": {
            "map_center": disp.map_center, "map_zoom": disp.map_zoom,
            "map_bounds": disp.map_bounds, "nearby_radii_m": disp.nearby_radii_m,
            "example_address": disp.example_address,
            "address_strip_regex": disp.address_strip_regex,
            "ask_suggestions": disp.ask_suggestions, "ask_placeholder": disp.ask_placeholder,
            "boilerplate_terms": disp.boilerplate_terms,
            "glossary_overrides": disp.glossary_overrides,
        },
        "features": {"impact": cfg.features.impact, "projects": cfg.features.projects},
    }
