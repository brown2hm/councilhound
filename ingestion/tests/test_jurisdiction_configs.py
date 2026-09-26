"""Every checked-in jurisdiction config loads, and the City's registry
reproduces the behavior that used to be hard-coded."""
import pytest

from councilhound import jurisdiction as jur
from councilhound.bodies import Registry
from councilhound.jurisdiction import JurisdictionConfig, available


@pytest.mark.parametrize("slug", available())
def test_every_config_loads(slug):
    cfg = JurisdictionConfig.load(slug)
    assert cfg.slug == slug and cfg.identity.short_name
    reg = Registry.from_config(cfg)
    assert reg.keys, slug
    for view in cfg.granicus.views:
        if view.layout == "single":
            assert view.body in reg.bodies


def test_city_registry_matches_the_old_literals():
    reg = Registry.from_config(JurisdictionConfig.load("fairfax_city_va"))
    assert reg.keys == ("city_council", "planning_commission", "school_board", "prab", "hhcab")
    assert reg.labels["hhcab"] == "Housing and Healthy Communities Advisory Board"
    assert reg.bodies["planning_commission"].archive_section == "Community Development and Planning Meetings"
    assert reg.bodies["planning_commission"].title_must_contain == ("planning commission",)
    assert reg.bodies["school_board"].meeting_types[0] == ("closed", "school_board_closed")
    assert reg.bodies["prab"].recorded is False and reg.bodies["prab"].default_meeting_type == "prab_meeting"
    assert reg.bodies["planning_commission"].seed_titles("chair") == ["Chair", "Chairman", "Commissioner"]
    assert reg.bodies["city_council"].seed_titles("member") == [
        "Councilmember", "Council Member", "Councilwoman", "Councilman"]
    # the members router's title tables, as they were hand-written
    assert set(reg.title_prefixes()) == {
        "school board chair ", "school board member ", "mayor ", "councilmember ",
        "council member ", "councilwoman ", "councilman ", "vice-chair ", "vice chair ",
        "chairman ", "chair ", "commissioner "}
    assert reg.title_prefixes()[0] == "school board member "  # longest first
    assert reg.role_order() == {"Mayor": 0, "Councilmember": 1, "Chair": 2, "Vice-Chair": 3,
                                "Commissioner": 4, "School Board Chair": 5, "School Board Member": 6}
    assert {(t, b) for _p, t, b in reg.title_roles()} >= {
        ("Mayor", "city_council"), ("Commissioner", "planning_commission"),
        ("School Board Chair", "school_board")}


def test_self_reference_is_per_jurisdiction():
    city = Registry.from_config(JurisdictionConfig.load("fairfax_city_va"))
    assert city.is_self_reference("the City of Fairfax School Board")
    assert not city.is_self_reference("Fairfax County Public Schools")
    other = Registry(
        [], self_names=("Testville",), self_prefixes=("testville ",), other_body_names=("Arts Board",))
    assert other.is_self_reference("Testville") and other.is_self_reference("Testville Arts Board")
    assert not other.is_self_reference("City of Fairfax")


def test_validation_catches_bad_configs(tmp_path, monkeypatch):
    monkeypatch.setattr(jur, "JURISDICTIONS_DIR", tmp_path)
    base = ("name: T\nfips: {state: '51', county: '600'}\ncrs_projected: EPSG:2283\n"
            "projects_index_url: https://x\n")
    (tmp_path / "dup.yaml").write_text(base + "bodies:\n  - {key: a, label: A, short: a, archive_section: A}\n"
                                       "  - {key: a, label: B, short: b, archive_section: B}\n")
    with pytest.raises(ValueError, match="duplicate body keys"):
        JurisdictionConfig.load("dup")
    (tmp_path / "view.yaml").write_text(base + "granicus:\n  views: [{view_id: '7', layout: single, body: nope}]\n"
                                        "bodies:\n  - {key: a, label: A, short: a, archive_section: A}\n")
    with pytest.raises(ValueError, match="unknown body"):
        JurisdictionConfig.load("view")
    (tmp_path / "tz.yaml").write_text(base + "identity: {timezone: Mars/Olympus}\n")
    with pytest.raises(ValueError, match="timezone"):
        JurisdictionConfig.load("tz")
    (tmp_path / "titles.yaml").write_text(
        base + "bodies:\n"
        "  - {key: a, label: A, short: a, archive_section: A, roster: {roles: {c: {title: Chair, aliases: [Chair]}}}}\n"
        "  - {key: b, label: B, short: b, archive_section: B, roster: {roles: {c: {title: Chair, aliases: [Chair]}}}}\n")
    with pytest.raises(ValueError, match="titles must be unique"):
        JurisdictionConfig.load("titles")


def test_current_honours_env(monkeypatch):
    monkeypatch.setenv("JURISDICTION", "fairfax_city_va")
    jur.current.cache_clear()
    assert jur.current().slug == "fairfax_city_va"
    monkeypatch.setenv("JURISDICTION", "nowhere_xx")
    jur.current.cache_clear()
    with pytest.raises(RuntimeError, match="nowhere_xx"):
        jur.current()
    monkeypatch.delenv("JURISDICTION")
    jur.current.cache_clear()
    assert jur.current().slug == jur.DEFAULT_SLUG
