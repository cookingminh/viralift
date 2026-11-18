"""The in-app guide (ui/guide.py) must cover every status, page and table
column, and the result tables must stay sortable."""
from app.src.lifting.base import STATUS_META
from ui.guide import (
    FEATURE_COLUMN_HELP,
    GUIDE_STATUSES,
    PAGE_GUIDES,
    RECORD_COLUMN_HELP,
    STAGE_TOPICS,
    STATUS_GUIDE,
    _page_guide_html,
    _rich,
    _status_reference_html,
)
from ui.ui_text import UI_TEXT
from ui.stages.results import FEATURE_COLUMNS, RECORD_COLUMNS, _identity_cell, _position_cell


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
    assert set(RECORD_COLUMNS) == set(RECORD_COLUMN_HELP)


def test_identity_cells_sort_numerically_as_text():
    # The browser sorts text cells with localeCompare: fixed-width,
    # space-padded values keep numeric order, and a missing value is "".
    cells = [_identity_cell(value) for value in (100.0, 9.5, 47.4)]
    assert len({len(cell) for cell in cells}) == 1
    assert sorted(cells) == [_identity_cell(9.5), _identity_cell(47.4), _identity_cell(100.0)]
    assert _identity_cell(None) == ""


def test_position_cells_sort_numerically_as_text():
    cells = [_position_cell(value) for value in (12071, 190, 7701, 3)]
    assert sorted(cells) == [_position_cell(v) for v in (3, 190, 7701, 12071)]
    assert _position_cell(None) == ""


def test_rich_text_escapes_before_adding_markup():
    assert _rich("`<b>` and **ok**") == "<code>&lt;b&gt;</code> and <b>ok</b>"
