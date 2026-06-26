"""Tests for the folded-back G5 hardening: the structure-preserving passage renderer (fold 1),
the kid-facing title deriver + build-time guard (fold 3), and the publisher masteryThreshold
default (fold 4).

These pin the hard-won fixes that were one-off scripts in g5-merged-course/ so the next build can't
re-introduce them:
  • the flattener that split passages on EVERY newline and escaped everything (welded titles onto
    bodies, ran passages together, flattened tables) is replaced by arpack.passage_html_div;
  • QA/cert jargon, question stems, and structural labels can no longer reach a learner title;
  • the powerpath-100 mastery gate is stamped (90) by default instead of shipping null (gate off).
"""
import os
import sys

import pytest

import arpack

EXAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples")
if EXAMPLES not in sys.path:
    sys.path.insert(0, EXAMPLES)


# ═════════════════════════════ fold 1 — passage renderer ═════════════════════════════
def test_paragraphs_split_on_blank_lines_not_single_newline():
    # soft-wrapped lines inside a paragraph join; blank lines separate paragraphs.
    src = "The fox is quick.\nIt runs at night.\n\nThe owl is quiet.\nIt hunts at dawn."
    out = arpack.passage_html_div(src)
    assert out.count("<p>") == 2, out
    assert "<p>The fox is quick. It runs at night.</p>" in out
    assert "<p>The owl is quiet. It hunts at dawn.</p>" in out


def test_markdown_heading_promoted_and_not_welded_to_body():
    # the live regression: "# Title\nBody" used to collapse into one tagless <p> ("PapyrusIn...").
    src = "# The Papyrus Plant\nIn ancient Egypt, papyrus grew along the Nile."
    out = arpack.passage_html_div(src)
    assert "<h3>The Papyrus Plant</h3>" in out
    assert "<p>In ancient Egypt, papyrus grew along the Nile.</p>" in out
    assert "PapyrusIn" not in out.replace(" ", "")


def test_title_prepended_only_when_body_lacks_leading_heading():
    assert "<h3>My Title</h3>" in arpack.passage_html_div("A plain sentence.", title="My Title")
    # body already opens with its own heading -> the passed title is NOT double-stamped
    out = arpack.passage_html_div("# Real Heading\nBody.", title="Should Not Appear")
    assert "Should Not Appear" not in out
    assert "<h3>Real Heading</h3>" in out


@pytest.mark.parametrize("sep", ["|:-|:-|", "|---|---|", "|:---:|:---:|", "| --- | --- |"])
def test_pipe_table_reconstructed(sep):
    src = "| Use | Where |\n%s\n| Paper | Egypt |\n| Boats | The Nile |" % sep
    out = arpack.passage_html_div(src)
    assert "<table>" in out and "<th>Use</th>" in out
    assert "<td>Paper</td>" in out and "<td>The Nile</td>" in out


def test_dash_in_prose_is_not_misread_as_table():
    out = arpack.passage_html_div("The cost was high -- very high.\nIt rose again -- twice.")
    assert "<table>" not in out
    assert "<p>" in out


def test_existing_html_preserved_and_void_tags_repaired():
    out = arpack.passage_html_div("<p>Line one.<br>Line two.</p><p>Next.</p>")
    assert "<br/>" in out and "<br>" not in out.replace("<br/>", "")
    assert out.count("<p>") == 2


def test_inline_markdown_bold_and_list():
    out = arpack.passage_html_div("Key terms:\n\n- **erosion** wears rock\n- **delta** builds land")
    assert "<ul>" in out and out.count("<li>") == 2
    assert "<strong>erosion</strong>" in out


def test_html_escaping_of_plain_text():
    out = arpack.passage_html_div("5 < 7 & 7 > 3")
    assert "&lt;" in out and "&amp;" in out and "&gt;" in out


def test_empty_input_is_safe():
    assert arpack.passage_blocks("") == []
    assert arpack.passage_blocks("   ") == []
    assert arpack.passage_html_div("") == '<div class="passage"><p></p></div>'


# ═════════════════════════════ fold 3 — title deriver ═════════════════════════════
def test_derive_title_from_real_heading():
    t, conf, how = arpack.derive_title(
        "<qti-stimulus-body><h2>How Volcanoes Erupt</h2><p>Magma rises.</p></qti-stimulus-body>")
    assert t == "How Volcanoes Erupt" and conf == "high" and how == "heading"


def test_declarative_qword_heading_is_a_title_not_a_question():
    # "How X Y" with no '?' and no subject-aux inversion is a legitimate title.
    for title in ("How Volcanoes Erupt", "Why Leaves Change Color", "Who Sailed First"):
        t, conf, how = arpack.derive_title(
            "<qti-stimulus-body><h2>%s</h2><p>Body.</p></qti-stimulus-body>" % title)
        assert t == title and how == "heading", (title, t, how)


def test_real_question_heading_falls_back_to_prose():
    # ends with '?' OR shows inversion -> not a heading title; prose fallback (or none).
    for h in ("Why do volcanoes erupt?", "How do volcanoes erupt"):
        t, conf, how = arpack.derive_title(
            "<qti-stimulus-body><h2>%s</h2><p>Magma rises from deep below.</p>"
            "</qti-stimulus-body>" % h)
        assert how != "heading", (h, how)


def test_prose_fallback_when_no_heading():
    t, conf, how = arpack.derive_title(
        "<qti-stimulus-body><p>The desert fox hunts at night to avoid the heat.</p>"
        "</qti-stimulus-body>")
    assert how == "prose" and conf == "med" and t


def test_strips_passage_prefix_from_heading():
    t, conf, how = arpack.derive_title(
        "<qti-stimulus-body><h2>Passage 2: The Coral Reef</h2><p>x</p></qti-stimulus-body>")
    assert t == "The Coral Reef" and how == "heading"


# ═════════════════════════════ fold 3 — build-time guard ═════════════════════════════
@pytest.mark.parametrize("bad", [
    "Verified · Lesson 3",
    "Unit 1 — Verified: cross-family blind-certified",
    "Uncertified passage",
    "How does the author support the main idea?",   # question stem (ends with ?)
    "How do volcanoes erupt",                        # question stem (inversion, no ?)
    "Panel 2",                                       # structural label
    "Figure",
    "Lesson 7",                                      # placeholder
    "",                                              # empty
])
def test_guard_blocks_leaky_titles(bad):
    with pytest.raises(ValueError):
        arpack.assert_kid_facing_title(bad)


@pytest.mark.parametrize("ok", [
    "How Volcanoes Erupt",
    "Why Leaves Change Color",
    "The Papyrus Plant",
    "Reading Practice 4",
    "The Coral Reef",
])
def test_guard_passes_clean_titles(ok):
    assert arpack.assert_kid_facing_title(ok) == ok


# ═════════════════════════════ fold 4 — mastery threshold default ═════════════════════════════
@pytest.mark.parametrize("mod_name", ["publish_powerpath", "publish_powerpath_g5"])
def test_parse_mastery_defaults_and_disables(mod_name):
    mod = __import__(mod_name)
    assert mod._parse_mastery("90") == 90
    assert mod._parse_mastery("80") == 80
    for off in ("0", "none", "off", "", "null"):
        assert mod._parse_mastery(off) is None, off


@pytest.mark.parametrize("mod_name", ["publish_powerpath", "publish_powerpath_g5"])
def test_publisher_txt_to_html_delegates_to_arpack(mod_name):
    # the publisher flattener must now be structure-preserving (delegates to arpack).
    mod = __import__(mod_name)
    out = mod._txt_to_html("First para.\n\nSecond para.\n\n| A | B |\n|:-|:-|\n| 1 | 2 |")
    assert out.count("<p>") == 2 and "<table>" in out
