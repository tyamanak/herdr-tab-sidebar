"""Run a terminal program in a pty and return its final screen.

Just enough of a terminal to read what Herdr draws: cursor moves, erases, cell
widths, colours and text attributes.
"""
from __future__ import annotations

import fcntl
import os
import pty
import re
import select
import signal
import struct
import termios
import threading
import time
import unicodedata
from typing import List, NamedTuple, Optional, Tuple, Union

_SEQUENCE = re.compile(
    r"\x1b\[([0-9;:?<>=]*)([A-Za-z@`])|\x1b\]([^\x07\x1b]*)(?:\x07|\x1b\\)"
    r"|\x1b[()][A-Za-z0-9]|\x1b[=>78M]|\x1bP[^\x1b]*\x1b\\"
)

Colour = Union[None, int, Tuple[int, int, int]]


class Style(NamedTuple):
    """Colours are None (terminal default), a palette index or an RGB triple."""

    fg: Colour = None
    bg: Colour = None
    bold: bool = False
    dim: bool = False
    italic: bool = False
    underline: bool = False
    reverse: bool = False


PLAIN = Style()


class Cell(NamedTuple):
    # "" marks the second half of a double-width character.
    text: str = " "
    style: Style = PLAIN


class Screen:
    def __init__(self, rows: int, cols: int):
        self.rows = rows
        self.cols = cols
        self.cells: List[List[Cell]] = [[Cell()] * cols for _ in range(rows)]
        # What the program asked the terminal to show as its window title.
        self.title: Optional[str] = None

    def lines(self) -> List[str]:
        return ["".join(cell.text for cell in row).rstrip() for row in self.cells]


def _width(ch: str) -> int:
    if unicodedata.combining(ch) or ch in "︎️‍":
        return 0
    return 2 if unicodedata.east_asian_width(ch) in "WF" else 1


def _colour(args: List[int], index: int) -> Tuple[Colour, int]:
    """The colour of an extended SGR starting at args[index] (38 or 48)."""
    kind = args[index + 1] if index + 1 < len(args) else 0
    if kind == 5 and index + 2 < len(args):
        return args[index + 2], index + 3
    if kind == 2 and index + 4 < len(args):
        return (args[index + 2], args[index + 3], args[index + 4]), index + 5
    return None, len(args)


def _sgr(style: Style, text: str) -> Style:
    # "38:2::r:g:b" carries an empty colour space field; drop it.
    args = [int(a) if a.isdigit() else 0
            for a in text.replace("::", ":").replace(":", ";").split(";")]
    index = 0
    while index < len(args):
        code = args[index]
        index += 1
        if code == 0:
            style = PLAIN
        elif code == 1:
            style = style._replace(bold=True)
        elif code == 2:
            style = style._replace(dim=True)
        elif code == 3:
            style = style._replace(italic=True)
        elif code == 4:
            style = style._replace(underline=True)
        elif code == 7:
            style = style._replace(reverse=True)
        elif code == 22:
            style = style._replace(bold=False, dim=False)
        elif code == 23:
            style = style._replace(italic=False)
        elif code == 24:
            style = style._replace(underline=False)
        elif code == 27:
            style = style._replace(reverse=False)
        elif 30 <= code <= 37:
            style = style._replace(fg=code - 30)
        elif 90 <= code <= 97:
            style = style._replace(fg=code - 90 + 8)
        elif code == 39:
            style = style._replace(fg=None)
        elif 40 <= code <= 47:
            style = style._replace(bg=code - 40)
        elif 100 <= code <= 107:
            style = style._replace(bg=code - 100 + 8)
        elif code == 49:
            style = style._replace(bg=None)
        elif code in (38, 48):
            colour, index = _colour(args, index - 1)
            style = style._replace(fg=colour) if code == 38 else style._replace(bg=colour)
    return style


def render(text: str, rows: int, cols: int) -> Screen:
    screen = Screen(rows, cols)
    grid = screen.cells
    style = PLAIN
    row = col = 0
    index = 0

    def blank() -> Cell:
        return Cell(" ", Style(bg=style.bg))

    while index < len(text):
        match = _SEQUENCE.match(text, index)
        if match:
            index = match.end()
            if match.group(3) is not None:
                number, _, value = match.group(3).partition(";")
                if number in ("0", "2"):
                    screen.title = value
                continue
            kind = match.group(2)
            if not kind:
                continue
            if kind == "m":
                style = _sgr(style, match.group(1))
                continue
            args = [int(a) if a.isdigit() else 0 for a in match.group(1).split(";")]
            first = args[0] if args else 0
            if kind in "Hf":
                row = max(first, 1) - 1
                col = max(args[1] if len(args) > 1 else 1, 1) - 1
            elif kind == "J":
                for y in range(rows):
                    if first == 2 or (first == 0 and y > row) or (first == 1 and y < row):
                        grid[y] = [blank()] * cols
            elif kind == "K" and 0 <= row < rows:
                span = (range(col, cols) if first == 0 else
                        range(0, min(col + 1, cols)) if first == 1 else range(cols))
                for x in span:
                    grid[row][x] = blank()
            elif kind == "X" and 0 <= row < rows:
                for x in range(col, min(col + (first or 1), cols)):
                    grid[row][x] = blank()
            elif kind == "C":
                col += first or 1
            elif kind == "D":
                col = max(col - (first or 1), 0)
            elif kind == "G":
                col = max(first, 1) - 1
            elif kind == "d":
                row = max(first, 1) - 1
            elif kind == "A":
                row -= first or 1
            elif kind == "B":
                row += first or 1
            continue
        ch = text[index]
        index += 1
        if ch == "\r":
            col = 0
        elif ch == "\n":
            row += 1
        elif ch == "\x08":
            col = max(col - 1, 0)
        elif ch >= " ":
            width = _width(ch)
            if not width:
                # A variation selector or joiner belongs to the cell before it.
                x = col - 1
                while x > 0 and 0 <= row < rows and x < cols and grid[row][x].text == "":
                    x -= 1
                if 0 <= row < rows and 0 <= x < cols:
                    grid[row][x] = grid[row][x]._replace(text=grid[row][x].text + ch)
                continue
            if 0 <= row < rows and 0 <= col < cols:
                grid[row][col] = Cell(ch, style)
                if width == 2 and col + 1 < cols:
                    grid[row][col + 1] = Cell("", style)
            col += width
    return screen


def capture(argv: list, env: dict, rows: int = 45, cols: int = 130,
            seconds: float = 3.0, attached=None) -> Screen:
    """The screen ``argv`` has drawn after ``seconds``.

    ``attached``, if given, is called once the program has been drawing for a
    second; the screen is then read ``seconds`` after it returns.
    """
    pid, fd = pty.fork()
    if pid == 0:
        os.execve(argv[0], argv, env)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    os.kill(pid, signal.SIGWINCH)
    data = b""
    deadline = time.time() + seconds
    worker = None
    if attached is not None:
        worker = threading.Timer(1.0, attached)
        worker.start()
    try:
        while time.time() < deadline or worker is not None:
            if worker is not None and not worker.is_alive():
                worker = None
                deadline = time.time() + seconds
            ready, _, _ = select.select([fd], [], [], 0.2)
            if not ready:
                continue
            try:
                chunk = os.read(fd, 65536)
            except OSError:
                break
            data += chunk
            if b"\x1b[6n" in chunk:
                os.write(fd, b"\x1b[1;1R")
    finally:
        if worker is not None:
            worker.cancel()
            worker.join()
        os.kill(pid, signal.SIGHUP)
        os.close(fd)
        os.waitpid(pid, 0)
    return render(data.decode("utf-8", "replace"), rows, cols)


def agents_panel(lines: list) -> dict:
    """The Agents panel of a captured Herdr screen: header text and entry lines."""
    column = [line.split("│")[0] for line in lines]
    start = next(i for i, line in enumerate(column) if line.strip().startswith("agents"))
    body = [line.rstrip() for line in column[start + 1:]]
    return {
        "header": column[start].split(),
        "lines": [line for line in body if line.strip() and line.strip() != "«"],
    }
