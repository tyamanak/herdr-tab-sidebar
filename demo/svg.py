"""Draw a captured terminal screen (tests/isolated/screen.py) as an SVG image."""
from __future__ import annotations

from xml.sax.saxutils import escape

CELL_W = 8.4
CELL_H = 18
FONT_SIZE = 14
PADDING = 12
BACKGROUND = "#1e1e2e"
FOREGROUND = "#cdd6f4"
FONT = ("ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, "
        "'DejaVu Sans Mono', 'Liberation Mono', monospace")
# The sixteen named terminal colours.
ANSI = ["#45475a", "#f38ba8", "#a6e3a1", "#f9e2af", "#89b4fa", "#f5c2e7", "#94e2d5", "#bac2de",
        "#585b70", "#f38ba8", "#a6e3a1", "#f9e2af", "#89b4fa", "#f5c2e7", "#94e2d5", "#a6adc8"]
# U+2800 is the blank the plugin pads labels with; it must not draw dots.
INVISIBLE = (" ", "", "⠀")


def _hex(colour, default):
    if colour is None:
        return default
    if isinstance(colour, tuple):
        return "#%02x%02x%02x" % colour
    if colour < 16:
        return ANSI[colour]
    if colour < 232:
        index = colour - 16
        levels = [0, 95, 135, 175, 215, 255]
        return "#%02x%02x%02x" % (levels[index // 36], levels[index // 6 % 6], levels[index % 6])
    grey = 8 + (colour - 232) * 10
    return "#%02x%02x%02x" % (grey, grey, grey)


def _colours(style):
    fg, bg = _hex(style.fg, FOREGROUND), _hex(style.bg, BACKGROUND)
    return (bg, fg) if style.reverse else (fg, bg)


def _line(x1, y1, x2, y2, colour, width=1.0):
    return ('<path d="M%.2f %.2fL%.2f %.2f" stroke="%s" stroke-width="%s" fill="none"/>'
            % (x1, y1, x2, y2, colour, width))


# Box-drawing characters as (left, right, up, down) arms. Drawn as lines so
# that borders join whatever font the viewer has.
_ARMS = {
    "─": "lr", "│": "ud", "┌": "rd", "┐": "ld", "└": "ru", "┘": "lu", "├": "udr", "┤": "udl",
    "┬": "lrd", "┴": "lru", "┼": "lrud", "╭": "rd", "╮": "ld", "╰": "ru", "╯": "lu",
    "━": "LR", "┃": "UD", "┏": "RD", "┓": "LD", "┗": "RU", "┛": "LU",
}


def _box(ch, x, y, colour):
    arms = _ARMS[ch]
    width = 2.0 if arms.isupper() else 1.0
    cx, cy = x + CELL_W / 2, y + CELL_H / 2
    ends = {"l": (x, cy), "r": (x + CELL_W, cy), "u": (cx, y), "d": (cx, y + CELL_H)}
    return "".join(_line(cx, cy, ends[arm][0], ends[arm][1], colour, width)
                   for arm in arms.lower())


def render(screen) -> str:
    width = screen.cols * CELL_W + 2 * PADDING
    height = screen.rows * CELL_H + 2 * PADDING
    out = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %.0f %.0f" width="%.0f" '
        'height="%.0f" font-family="%s" font-size="%d">'
        % (width, height, width, height, escape(FONT, {'"': "&quot;"}), FONT_SIZE),
        '<rect width="100%%" height="100%%" rx="8" fill="%s"/>' % BACKGROUND,
    ]
    backgrounds, shapes, texts = [], [], []
    for row, cells in enumerate(screen.cells):
        y = PADDING + row * CELL_H
        col = 0
        while col < len(cells):
            # Backgrounds: one rectangle per run of cells that share a colour.
            _fg, bg = _colours(cells[col].style)
            end = col + 1
            while end < len(cells) and _colours(cells[end].style)[1] == bg:
                end += 1
            if bg != BACKGROUND:
                backgrounds.append('<rect x="%.2f" y="%.2f" width="%.2f" height="%d" fill="%s"/>' % (
                    PADDING + col * CELL_W, y, (end - col) * CELL_W + 0.3, CELL_H, bg))
            col = end
        for col, cell in enumerate(cells):
            if cell.text in INVISIBLE:
                continue
            fg, _bg = _colours(cell.style)
            x = PADDING + col * CELL_W
            if cell.text in _ARMS:
                shapes.append(_box(cell.text, x, y, fg))
                continue
            wide = col + 1 < len(cells) and cells[col + 1].text == ""
            attributes = ['x="%.2f"' % (x + (CELL_W if wide else CELL_W / 2)),
                          'y="%.2f"' % (y + CELL_H * 0.72), 'fill="%s"' % fg]
            if cell.style.bold:
                attributes.append('font-weight="bold"')
            if cell.style.italic:
                attributes.append('font-style="italic"')
            if cell.style.dim:
                attributes.append('opacity="0.6"')
            if cell.style.underline:
                attributes.append('text-decoration="underline"')
            # One element per character, centred in its cell, so that columns
            # line up even where the viewer's font is wider or narrower.
            texts.append("<text %s>%s</text>" % (" ".join(attributes), escape(cell.text)))
    out.append("<g>%s</g>" % "".join(backgrounds))
    out.append('<g stroke-linecap="square">%s</g>' % "".join(shapes))
    out.append('<g text-anchor="middle">%s</g>' % "".join(texts))
    out.append("</svg>")
    return "\n".join(out) + "\n"
