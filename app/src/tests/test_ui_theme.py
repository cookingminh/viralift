import tomllib
from pathlib import Path

import pytest

from ui.theme import PALETTE, _theme_css


ROOT = Path(__file__).resolve().parents[3]

# Streamlit config key -> ui.theme.PALETTE token. Native widgets read the
# config, ViraLift's HTML components read the tokens; they must agree or the
# two halves of the page drift apart (the old "dark tables on a light page").
SHARED_COLORS = {
    "primaryColor": "primary",
    "backgroundColor": "bg",
    "secondaryBackgroundColor": "surface-2",
    "textColor": "text",
    "borderColor": "border",
}


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_streamlit_config_matches_palette(mode):
    config = tomllib.loads((ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8"))
    section = config["theme"][mode]
    for config_key, token in SHARED_COLORS.items():
        assert section[config_key].upper() == PALETTE[mode][token].upper(), config_key


def test_both_palettes_define_the_same_tokens():
    assert set(PALETTE["light"]) == set(PALETTE["dark"])


def test_theme_css_fills_every_placeholder():
    css = _theme_css()
    assert "__LIGHT_TOKENS__" not in css
    assert "__DARK_TOKENS__" not in css
    assert f"--vl-primary: {PALETTE['light']['primary']};" in css
    assert f"--vl-primary: {PALETTE['dark']['primary']};" in css


def test_theme_css_has_no_markup():
    # st.html sanitises with DOMPurify, which drops a whole <style> element whose
    # text contains "<" followed by a letter or "/" (even inside a CSS comment),
    # leaving the app unstyled. Write "details element", never "<details>".
    import re
    from ui.theme import _theme_css

    assert not re.search(r"<[/\w]", _theme_css())
