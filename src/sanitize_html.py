#!/usr/bin/env python3
"""Sanitize HTML to valid XHTML for Timeback QTI payloads.

Usage:
    # As a module
    from sanitize_html import sanitize_html_for_xhtml
    clean = sanitize_html_for_xhtml(dirty_html)

    # As a CLI
    python sanitize_html.py input.html > output.html
    echo '<p>CO2 & H2O<br></p>' | python sanitize_html.py
"""
import re
import sys
import xml.etree.ElementTree as ET


def sanitize_html_for_xhtml(html: str) -> str:
    """Sanitize HTML to be valid XHTML for the Timeback stimulus/item API.

    The API parses content as XML via SAX. Invalid HTML causes silent render
    failures — items look fine in the API response but break in the student UI.
    """
    # 1. Self-close void elements: <br> → <br/>, <hr> → <hr/>, etc.
    html = re.sub(
        r'<(br|hr|col|embed|input|link|meta|param|source|track|wbr)'
        r'(\s[^>]*)?\s*(?<!/)\s*>',
        r'<\1\2/>',
        html,
    )
    # img may have many attributes
    html = re.sub(r'<img((?:\s+[^>]*?)?)(?<!/)>', r'<img\1/>', html)

    # 2. Escape bare < that aren't part of HTML tags (e.g., math: "x < 5")
    html = re.sub(r'<(?![a-zA-Z/!])', '&lt;', html)

    # 3. Escape bare & that aren't already entities
    # Valid entities: &amp; &lt; &gt; &quot; &apos; &#NNN; &#xHHH;
    html = re.sub(
        r'&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)',
        '&amp;',
        html,
    )

    # 4. Fix boolean HTML attributes for XHTML compliance
    for attr in (
        "allowfullscreen", "disabled", "checked", "selected", "readonly",
        "required", "autofocus", "autoplay", "controls", "loop", "muted",
    ):
        html = re.sub(
            rf'(<[^>]*\s){attr}(?=[\s/>])',
            rf'\1{attr}="{attr}"',
            html,
        )

    return html


def split_tables_from_p(html: str) -> str:
    """Move <table> elements out of <p> tags.

    <table> inside <p> is the #1 rendering bug on Timeback.
    """
    # Split <p>...<table>...</table>...</p> into <p>...</p><table>...</table><p>...</p>
    html = re.sub(
        r'<p([^>]*)>(.*?)<table',
        lambda m: f'<p{m.group(1)}>{m.group(2)}</p><table' if m.group(2).strip() else f'<table',
        html,
        flags=re.DOTALL,
    )
    html = re.sub(
        r'</table>(.*?)</p>',
        lambda m: f'</table><p>{m.group(1)}</p>' if m.group(1).strip() else '</table>',
        html,
        flags=re.DOTALL,
    )
    return html


def html_entities_to_unicode(html: str) -> str:
    """Replace HTML named entities with Unicode (XML only supports 5 named entities)."""
    replacements = {
        '&mdash;': '\u2014', '&ndash;': '\u2013', '&rarr;': '\u2192',
        '&larr;': '\u2190', '&harr;': '\u2194', '&Delta;': '\u0394',
        '&delta;': '\u03B4', '&deg;': '\u00B0', '&micro;': '\u00B5',
        '&pi;': '\u03C0', '&sigma;': '\u03C3', '&alpha;': '\u03B1',
        '&beta;': '\u03B2', '&gamma;': '\u03B3', '&lambda;': '\u03BB',
        '&theta;': '\u03B8', '&omega;': '\u03C9', '&infin;': '\u221E',
        '&ge;': '\u2265', '&le;': '\u2264', '&ne;': '\u2260',
        '&asymp;': '\u2248', '&plusmn;': '\u00B1', '&times;': '\u00D7',
        '&divide;': '\u00F7', '&raquo;': '\u00BB', '&laquo;': '\u00AB',
        '&bull;': '\u2022', '&hellip;': '\u2026', '&trade;': '\u2122',
        '&copy;': '\u00A9', '&reg;': '\u00AE', '&nbsp;': '\u00A0',
        '&lsquo;': '\u2018', '&rsquo;': '\u2019',
        '&ldquo;': '\u201C', '&rdquo;': '\u201D',
        '&prime;': '\u2032', '&Prime;': '\u2033',
        '&sum;': '\u2211', '&prod;': '\u220F',
        '&int;': '\u222B', '&part;': '\u2202',
        '&nabla;': '\u2207', '&forall;': '\u2200',
        '&exist;': '\u2203', '&isin;': '\u2208',
        '&sub;': '\u2282', '&sup;': '\u2283',
        '&cup;': '\u222A', '&cap;': '\u2229',
        '&empty;': '\u2205', '&equiv;': '\u2261',
    }
    for entity, char in replacements.items():
        html = html.replace(entity, char)
    return html


def validate_xml(xml_str: str) -> tuple[bool, str]:
    """Validate that a string is well-formed XML. Returns (valid, error_message)."""
    try:
        ET.fromstring(xml_str)
        return True, ""
    except ET.ParseError as e:
        return False, str(e)


def full_sanitize(html: str) -> str:
    """Apply all sanitization steps in order."""
    html = html_entities_to_unicode(html)
    html = split_tables_from_p(html)
    html = sanitize_html_for_xhtml(html)
    return html


if __name__ == "__main__":
    if len(sys.argv) > 1:
        with open(sys.argv[1]) as f:
            html = f.read()
    else:
        html = sys.stdin.read()

    print(full_sanitize(html))
