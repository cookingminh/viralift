"""The in-app guide (ui/guide.py) must cover every status, page and table
column, and the result tables must stay sortable."""
from app.src.lifting.base import STATUS_META
from ui.guide import (
    FEATURE_COLUMN_HELP,
    GUIDE_STATUSES,
    PAGE_GUIDES,
    STAGE_TOPICS,
    STATUS_GUIDE,
    _page_guide_html,
    _rich,
    _status_reference_html,
)
from ui.ui_text import UI_TEXT
from ui.stages.results import FEATURE_COLUMNS, _position_cell


def test_every_status_is_explained():
    assert set(GUIDE_STATUSES) <= set(STATUS_GUIDE)
    assert set(STATUS_META) < set(GUIDE_STATUSES)
    html = _status_reference_html()
    for status in GUIDE_STATUSES:
        assert _rich(STATUS_GUIDE[status]) in html


def test_every_status_has_a_label():
    # A missing text key renders as its raw name, e.g. "status_overlong_annotation".
    assert [s for s in GUIDE_STATUSES if f"status_{s}" not in UI_TEXT["en"]] == []


def test_every_page_has_a_guide():
    for topic in {*STAGE_TOPICS.values(), "crawler", "alias"}:
        assert topic in PAGE_GUIDES
        assert PAGE_GUIDES[topic]["title"] in _page_guide_html(topic)


def test_every_table_column_has_help():
    assert set(FEATURE_COLUMNS) == set(FEATURE_COLUMN_HELP)


def test_position_cells_sort_numerically_as_text():
    cells = [_position_cell(value) for value in (12071, 190, 7701, 3)]
    assert sorted(cells) == [_position_cell(v) for v in (3, 190, 7701, 12071)]
    assert _position_cell(None) == ""


def test_rich_text_escapes_before_adding_markup():
    assert _rich("`<b>` and **ok**") == "<code>&lt;b&gt;</code> and <b>ok</b>"


def test_every_text_key_used_by_the_ui_exists():
    # _t() falls back to the raw key, so a missing entry shows up as e.g. "map_prev".
    import re
    from pathlib import Path

    ui_dir = Path(__file__).resolve().parents[3] / "ui"
    used = {
        (key, path.name)
        for path in ui_dir.rglob("*.py")
        for key in re.findall(r'_t\(\s*"([a-z0-9_]+)"', path.read_text(encoding="utf-8"))
    }
    assert sorted(item for item in used if item[0] not in UI_TEXT["en"]) == []
