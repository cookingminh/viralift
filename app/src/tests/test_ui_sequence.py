"""The sequence box in the gene detail (ui/components.py _sequence_html)."""
import re

from ui.components import _bases_html, _sequence_html


def _text(markup: str) -> str:
    return re.sub(r"<[^>]+>", "", markup)


def test_bases_keep_their_order_and_colour():
    markup = _bases_html("AAcGGTN")
    assert _text(markup) == "AAcGGTN"
    assert markup.startswith("<span class='a'>AA</span><span class='c'>c</span><span class='g'>GG</span>")
    assert markup.endswith("N")  # not a base: plain text


def test_a_short_sequence_is_shown_whole_without_a_toggle():
    markup = _sequence_html("ACGT" * 50)
    assert "<details" not in markup
    assert "ACGT" * 50 in _text(markup)


def test_a_long_sequence_opens_on_a_preview_and_shows_all_on_demand():
    sequence = "ACGTTGCA" * 100  # 800 nt
    markup = _sequence_html(sequence, limit=360)
    full = re.search(r"<div class='vl-seq-full'>(.*?)</div>", markup).group(1)
    preview = re.search(r"<div class='vl-seq-preview'>(.*?)</div>", markup).group(1)
    assert _text(full) == sequence  # the whole sequence, copyable as plain bases
    assert _text(preview).startswith(sequence[:360]) and "+440 nt" in _text(preview)
    assert "Show all" in markup and "Show less" in markup
