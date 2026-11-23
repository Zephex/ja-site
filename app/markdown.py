"""A deliberately small, safe Markdown subset.

Supported: # / ## / ### headings, - lists, paragraphs, **bold**, *italic*,
~~strike~~, `code`, [links](https://...). Everything is HTML-escaped first, so
visitors can never inject markup. Only http(s) and mailto links are allowed.
"""

import html
import re


def _safe_url(url):
    low = url.strip().lower()
    return low.startswith(("http://", "https://", "mailto:"))


def inline(text):
    text = html.escape(text, quote=True)
    placeholders = []

    def stash(value):
        placeholders.append(value)
        return "\x00%d\x00" % (len(placeholders) - 1)

    # Code and links first so later emphasis rules do not touch generated HTML.
    text = re.sub(r"`([^`]+)`", lambda m: stash("<code>" + m.group(1) + "</code>"), text)

    def link(match):
        label, url = match.group(1), match.group(2)
        if not _safe_url(html.unescape(url)):
            return label
        return stash(
            '<a href="' + url + '" target="_blank" rel="noopener noreferrer">' + label + "</a>"
        )

    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", link, text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"~~(.+?)~~", r"<del>\1</del>", text)
    text = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", text)

    for i, value in enumerate(placeholders):
        text = text.replace("\x00%d\x00" % i, value)
    return text


def render(source):
    source = (source or "").replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    out, paragraph, in_list = [], [], False

    def flush_paragraph():
        if paragraph:
            out.append("<p>" + inline("\n".join(paragraph)).replace("\n", "<br>") + "</p>")
            paragraph.clear()

    def flush_list():
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

    for raw in source.split("\n"):
        line = raw.strip()
        if not line:
            flush_paragraph()
            flush_list()
            continue
        heading = re.match(r"^(#{1,3})\s+(.*)$", line)
        if heading:
            flush_paragraph()
            flush_list()
            level = len(heading.group(1))
            out.append("<h%d>%s</h%d>" % (level, inline(heading.group(2)), level))
        elif line.startswith("- "):
            flush_paragraph()
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append("<li>" + inline(line[2:]) + "</li>")
        else:
            flush_list()
            paragraph.append(line)

    flush_paragraph()
    flush_list()
    return "\n".join(out)
