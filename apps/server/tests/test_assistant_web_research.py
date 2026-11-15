"""Web research (`web_research.py`, M7 part D stage 3)."""

from test_assistant_actions import audit_rows, setup

from athena.assistant.web_research import EXA_API_KEY_ENV, web_research_capabilities


def test_web_research_is_off_by_default():
    assert web_research_capabilities(False) == []


def test_web_research_offers_exa_tools():
    caps = web_research_capabilities(True, api_key="k")
    assert len(caps) == 1
    assert caps[0].id == "exa_search"
    toolset = caps[0].get_toolset()
    assert set(toolset.tools) == {"web_search", "get_page"}


def test_env_var_name_is_documentable():
    assert EXA_API_KEY_ENV == "EXA_API_KEY"


def test_the_web_research_setting_is_audited(tmp_path):
    client, _, _, _ = setup(tmp_path)
    for value in (True, False, True):
        client.put("/api/settings/ai", json={"web_research_enabled": value}).raise_for_status()
    rows = [t for a, t in audit_rows(client) if a == "settings.assistant_web_research"]
    assert rows == ["on", "off", "on"]
