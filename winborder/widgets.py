"""Small widgets the settings window is built from.

Everything here is drawn with the rasteriser in :mod:`winborder.raster`, because
Tk's canvas has no anti-aliasing and the shapes this window needs are all curves.
Every widget can repaint itself when the system theme changes.
"""

from __future__ import annotations

import math
import time
import tkinter as tk
from tkinter import ttk
from typing import Callable, Iterable

from . import i18n, keymap, theme
from .raster import Coverage, Raster, mix
from .theme import Theme

ICON_SIZE = 16

# The width every row's control occupies, so a card lines up down its right side.
CONTROL_WIDTH = 220

# How long a control takes to travel between its two states, and how often it is
# drawn on the way. Short enough that a click still feels like it did something
# at once, long enough to read as movement rather than as a redraw.
ANIMATION_MS = 150
FRAME_MS = 16

# Set while the form is being filled: a value arriving from the settings file is
# not a click, and every control on the page changing at once is not a sight
# worth showing.
_ANIMATED = True


def set_animated(value: bool) -> None:
    """Whether a change of state is animated."""
    global _ANIMATED
    _ANIMATED = bool(value)


def _smoothstep(part: float) -> float:
    """Ease in and out, so the movement starts and ends without a jolt."""
    return part * part * (3.0 - 2.0 * part)


def control_pack(control: tk.Widget) -> dict[str, object]:
    """How a control fills its row: fields stretch, switches sit on the edge."""
    from tkinter import ttk
    if isinstance(control, (ttk.Entry, ttk.Combobox)):
        return {"fill": "x"}
    return {"side": "right"}

# Set once by the window: drawn shapes have to grow with the text beside them,
# because fonts are in points and Tk scales those by the display dpi itself.
_SCALE = 1.0


def set_scale(scale: float) -> None:
    """Match the drawn widgets to the display scale."""
    global _SCALE
    _SCALE = max(1.0, scale)


def scaled(value: float) -> int:
    """A pixel size at the display scale."""
    return int(round(value * _SCALE))


class _Glyph:
    """Builds one icon out of smooth shapes, in a box of 16 units."""

    def __init__(self, size: int, colour: str, background: str) -> None:
        self.raster = Raster(size, size, background)
        self.unit = size / 16.0
        self.colour = colour
        self.background = background
        self.shapes: list[tuple[Coverage, str]] = []

    def _point(self, x: float, y: float) -> tuple[float, float]:
        return x * self.unit, y * self.unit

    def rect(self, x0: float, y0: float, x1: float, y1: float,
             radius: float = 1.4, colour: str | None = None) -> None:
        a, b = self._point(x0, y0)
        c, d = self._point(x1, y1)
        self.shapes.append((self.raster.rounded_rect(a, b, c, d, radius * self.unit),
                            colour or self.colour))

    def outline(self, x0: float, y0: float, x1: float, y1: float,
                width: float = 1.4) -> None:
        self.rect(x0, y0, x1, y1, 1.4, self.colour)
        self.rect(x0 + width, y0 + width, x1 - width, y1 - width, 0.8,
                  self.background)

    def stroke(self, x0: float, y0: float, x1: float, y1: float,
               width: float = 1.4) -> None:
        a, b = self._point(x0, y0)
        c, d = self._point(x1, y1)
        self.shapes.append((self.raster.capsule(a, b, c, d, width * self.unit),
                            self.colour))

    def ring(self, cx: float, cy: float, radius: float, width: float = 1.4,
             start: float = 0.0, extent: float = 360.0) -> None:
        x, y = self._point(cx, cy)
        self.shapes.append((self.raster.ring(x, y, radius * self.unit,
                                             width * self.unit, start, extent),
                            self.colour))

    def dot(self, cx: float, cy: float, radius: float = 0.9) -> None:
        x, y = self._point(cx, cy)
        self.shapes.append((self.raster.circle(x, y, radius * self.unit),
                            self.colour))

    def wedge(self, points: list[tuple[float, float]],
              colour: str | None = None) -> None:
        self.shapes.append((self.raster.polygon([self._point(x, y)
                                                 for x, y in points]),
                            colour or self.colour))

    def image(self, master: tk.Misc) -> tk.PhotoImage:
        for shape, colour in self.shapes:
            self.raster.fill(shape, colour)
        return self.raster.photo(master)


def _draw(glyph: _Glyph, name: str) -> None:
    """Draw one icon, to one specification.

    The box is 16 units and every glyph is held to the same two numbers, because a
    column of icons is read as a column before it is read as icons:

    * the ink is 11 units high, stroke caps included, so no glyph looks smaller
      than the one above it;
    * the ink sits on the centre of the box. Some shapes carry more ink on one
      side -- the two joins of the Bluetooth rune, the tip of an arrow -- so a
      couple of them are drawn a fraction of a unit off centre to compensate.

    Shapes that are wide by nature (a keyboard, sliders, a frame) keep their width
    up to 14.6 units; nothing is stretched to fill the box.
    """
    if name == "status":
        glyph.ring(8, 8, 4.8, 1.4)
        glyph.dot(8, 5.6, 0.95)
        glyph.stroke(8, 7.8, 8, 10.6, 1.6)
    elif name == "link":
        # Two overlapping windows, the front one knocked out of the back one. The
        # pair is drawn 0.75 right: the front window is mostly background, so the
        # ink of the back window alone sat left of the column.
        glyph.rect(2.15, 2.7, 10.35, 13.3, 1.5)
        glyph.rect(7.15, 2.7, 15.35, 13.3, 1.5, glyph.background)
        glyph.rect(8.55, 4.1, 13.95, 11.9, 1.2)
    elif name == "pointer":
        # An arrow reads as one shape with its tail, so it keeps its tip at the
        # right and is drawn wider than its 8 units of outline suggest.
        glyph.wedge([(3.6, 2.3), (3.6, 13.3), (7.4, 10.0), (12.4, 10.0)])
    elif name == "edge":
        glyph.outline(1.6, 2.5, 8.8, 13.5)
        glyph.stroke(8.8, 8.0, 13.4, 8.0, 1.3)
        glyph.wedge([(11.8, 5.4), (15.0, 8.0), (11.8, 10.6)])
    elif name == "keyboard":
        # A slab, one run of keys, and a space bar: three rows of equal weight
        # read as a menu, which is what this used to look like.
        glyph.outline(0.8, 2.9, 15.2, 13.1, 1.2)
        for column in range(4):
            glyph.dot(3.4 + column * 3.1, 6.2, 0.7)
        glyph.rect(4.6, 8.3, 11.4, 10.2, 0.7)
        glyph.rect(2.4, 8.5, 3.6, 10.0, 0.5)
        glyph.rect(12.4, 8.5, 13.6, 10.0, 0.5)
    elif name == "log":
        glyph.stroke(2.6, 3.3, 13.4, 3.3, 1.5)
        glyph.stroke(2.6, 8.0, 11.0, 8.0, 1.5)
        glyph.stroke(2.6, 12.7, 13.4, 12.7, 1.5)
    elif name == "file":
        glyph.wedge([(3.5, 2.2), (9.3, 2.2), (12.5, 5.4), (12.5, 13.2),
                     (3.5, 13.2)])
        glyph.wedge([(4.9, 3.6), (8.7, 3.6), (11.1, 6.0), (11.1, 11.8),
                     (4.9, 11.8)], colour=glyph.background)
        glyph.stroke(6.3, 7.7, 9.7, 7.7, 1.1)
        glyph.stroke(6.3, 10.1, 9.7, 10.1, 1.1)
    elif name == "reload":
        glyph.ring(8.0, 8.0, 4.6, 1.6, start=70, extent=290)
        glyph.wedge([(10.0, 2.5), (13.8, 4.9), (9.7, 6.6)])
    elif name == "bluetooth":
        # The rune itself: a stem crossed by two strokes that join it at the top
        # and the bottom. Distinct from every other glyph by construction.
        #
        # Drawn 0.4 of a unit left of the box centre. The two joins on the right
        # carry more ink than the two crossings on the left, which are thin where
        # they meet the stem, so the rune sat to the right of the column of icons
        # beside it even though its outline was centred.
        glyph.stroke(7.6, 3.2, 7.6, 12.8, 1.3)
        glyph.stroke(7.6, 3.2, 11.2, 6.1, 1.3)
        glyph.stroke(11.2, 6.1, 4.0, 10.9, 1.3)
        glyph.stroke(7.6, 12.8, 11.2, 9.9, 1.3)
        glyph.stroke(11.2, 9.9, 4.0, 5.1, 1.3)
    elif name == "terminal":
        # A prompt in a frame: a log is a stream of lines, not a hamburger.
        glyph.outline(0.8, 2.5, 15.2, 13.5, 1.2)
        glyph.stroke(4.0, 5.9, 6.2, 8.0, 1.2)
        glyph.stroke(6.2, 8.0, 4.0, 10.1, 1.2)
        glyph.stroke(8.2, 10.1, 11.8, 10.1, 1.2)
    elif name == "gear":
        # Sliders: the usual mark for settings that are not a module.
        for height, knob in ((4.1, 6.0), (8.0, 11.0), (11.9, 5.0)):
            glyph.stroke(2.4, height, 13.6, height, 1.3)
            glyph.raster.fill(
                glyph.raster.circle(*glyph._point(knob, height), 1.9 * glyph.unit),
                glyph.background)
            glyph.raster.fill(
                glyph.raster.circle(*glyph._point(knob, height), 1.5 * glyph.unit),
                glyph.colour)
    elif name == "pause":
        # Two bars: the ink runs 7.2 wide and 10.8 tall, the same height as the
        # ring of a frame glyph, which is what a pause mark is squared against.
        glyph.rect(4.4, 2.6, 7.2, 13.4, 0.9)
        glyph.rect(8.8, 2.6, 11.6, 13.4, 0.9)
    elif name == "play":
        # The triangle has less ink than a square of the same box, so it is drawn
        # slightly wider, and its centroid sits on x = 8 rather than its outline.
        glyph.wedge([(5.2, 2.5), (13.8, 8.0), (5.2, 13.5)])
    elif name == "plus":
        # Two strokes crossing at the centre of the box, the same weight as the
        # other glyphs, so a plus reads as an icon rather than as a character.
        glyph.stroke(8.0, 2.5, 8.0, 13.5, 1.7)
        glyph.stroke(2.5, 8.0, 13.5, 8.0, 1.7)
    elif name == "cross":
        # The same weight as the plus, so a list of lines and their remove
        # buttons read as one set.
        glyph.stroke(4.1, 4.1, 11.9, 11.9, 1.7)
        glyph.stroke(11.9, 4.1, 4.1, 11.9, 1.7)
    elif name == "quit":
        glyph.ring(8.0, 8.0, 4.6, 1.6, start=110, extent=320)
        glyph.stroke(8.0, 3.0, 8.0, 7.8, 1.8)
    else:
        glyph.ring(8, 8, 4.8, 1.4)


def render_icon(master: tk.Misc, name: str, size: int, colour: str,
                background: str) -> tk.PhotoImage:
    """Draw one glyph, anti-aliased, at ``size`` pixels."""
    glyph = _Glyph(size, colour, background)
    _draw(glyph, name)
    return glyph.image(master)


def draw_icon(canvas: tk.Canvas, name: str, size: int, colour: str,
              background: str) -> None:
    """Draw one glyph onto a canvas."""
    canvas.delete("all")
    canvas.configure(background=background)
    photo = render_icon(canvas, name, size, colour, background)
    canvas.create_image(0, 0, image=photo, anchor="nw")
    canvas.image = photo                     # keep it alive


class Icon(tk.Canvas):
    """A glyph that repaints itself when the palette changes."""

    def __init__(self, parent: tk.Widget, name: str, palette: Theme,
                 size: int | None = None, colour: str | None = None,
                 background: str | None = None) -> None:
        size = scaled(ICON_SIZE if size is None else size)
        super().__init__(parent, width=size, height=size, highlightthickness=0,
                         borderwidth=0)
        self._name = name
        self._size = size
        self._colour = colour
        self._background = background
        self.image: tk.PhotoImage | None = None
        self.repaint(palette)

    def repaint(self, palette: Theme) -> None:
        colour = self._colour or palette.accent
        background = self._background or palette.bg
        draw_icon(self, self._name, self._size, colour, background)

    def set_name(self, name: str) -> None:
        """Draw another glyph, for a row whose meaning changes."""
        self._name = name

    def set_background(self, background: str) -> None:
        """Draw the glyph on another colour.

        The shape is painted onto the canvas, so a widget whose own background
        changes underneath it has to be redrawn with the new one; a row that is
        highlighted would otherwise keep a tile of the old colour around its
        icon.
        """
        self._background = background


class IconButton(Icon):
    """A glyph with no frame around it: the glyph itself is the button.

    A ttk button brings a plate of its own, which on a card surface reads as a
    raised chip -- a one-glyph action then looks like a field with something in
    it. This draws the glyph straight onto the surface it sits on, takes the click
    itself, and answers hover by taking the accent colour.
    """

    def __init__(self, parent: tk.Widget, name: str, palette: Theme,
                 command: Callable[[], None] | None = None,
                 size: int | None = None, colour: str | None = None,
                 background: str | None = None) -> None:
        # Set before Icon.__init__, which paints once through repaint() below.
        self._command = command
        self._hover = False
        self._rest_colour = colour
        super().__init__(parent, name, palette, size=size, colour=colour,
                         background=background)
        self.configure(cursor="hand2")
        self.bind("<Button-1>", lambda _event: self.invoke())
        self.bind("<Enter>", lambda _event: self._set_hover(True))
        self.bind("<Leave>", lambda _event: self._set_hover(False))

    def invoke(self) -> None:
        """Do what a click does."""
        if self._command is not None:
            self._command()

    def _set_hover(self, on: bool) -> None:
        if on != self._hover:
            self._hover = on
            self.repaint(self._palette)

    def repaint(self, palette: Theme) -> None:
        self._palette = palette
        if self._hover:
            colour = palette.accent
        else:
            colour = self._rest_colour or palette.fg
        background = self._background or palette.surface
        draw_icon(self, self._name, self._size, colour, background)


class _Animated(tk.Canvas):
    """A canvas that travels between two states rather than jumping to one.

    What the paint routine draws is the progress from one state to the other.
    The movement is measured against the clock instead of counted in frames, so
    a control takes the same time to change however long the frames themselves
    turn out to be, and a second click on the way reverses it from wherever it
    had got to.
    """

    def watch(self, variable: tk.BooleanVar) -> None:
        """Draw the state of a variable, and follow it from then on."""
        self._progress = 1.0 if variable.get() else 0.0     # 0 off, 1 on
        self._from = self._progress
        self._started = 0.0
        self._job: str | None = None
        variable.trace_add("write", lambda *_: self._state_changed())
        self.bind("<Destroy>", self._stop)

    def _state_changed(self) -> None:
        if not self.winfo_exists():           # the form was built again
            return
        target = 1.0 if self.variable.get() else 0.0
        if not _ANIMATED or target == self._progress:
            self._stop()
            self._progress = target
            self.repaint(self._palette)
            return
        self._from = self._progress
        self._started = time.perf_counter()
        if self._job is None:
            self._job = self.after(FRAME_MS, self._advance)

    def _advance(self) -> None:
        self._job = None
        target = 1.0 if self.variable.get() else 0.0
        part = min(1.0, (time.perf_counter() - self._started) * 1000.0 / ANIMATION_MS)
        self._progress = (target if part >= 1.0 else
                          self._from + (target - self._from) * _smoothstep(part))
        self.repaint(self._palette)
        if part < 1.0 and self.winfo_exists():
            self._job = self.after(FRAME_MS, self._advance)

    def _stop(self, _event: tk.Event | None = None) -> None:
        """Let go of the frame that is waiting to be drawn."""
        job, self._job = self._job, None
        if job is not None:
            try:
                self.after_cancel(job)
            except tk.TclError:              # the canvas is already gone
                pass


class ToggleSwitch(_Animated):
    """An on/off switch, drawn rather than themed."""

    WIDTH = 40
    HEIGHT = 21

    def __init__(self, parent: tk.Widget, variable: tk.BooleanVar,
                 palette: Theme, command: Callable[[], None] | None = None,
                 background: str | None = None) -> None:
        self.width = scaled(self.WIDTH)
        self.height = scaled(self.HEIGHT)
        super().__init__(parent, width=self.width, height=self.height,
                         highlightthickness=0, borderwidth=0, cursor="hand2")
        self.variable = variable
        self._palette = palette
        self._command = command
        self._background = background
        self._hover = False
        self.image: tk.PhotoImage | None = None
        self.bind("<Button-1>", self._toggle)
        self.bind("<Enter>", lambda _event: self._set_hover(True))
        self.bind("<Leave>", lambda _event: self._set_hover(False))
        self.watch(variable)
        self.repaint(palette)

    def _set_hover(self, value: bool) -> None:
        self._hover = value
        self.repaint(self._palette)

    def _toggle(self, _event=None) -> None:
        self.variable.set(not self.variable.get())
        if self._command is not None:
            self._command()

    def repaint(self, palette: Theme) -> None:
        self._palette = palette
        background = self._background or palette.surface
        width, height = self.width, self.height
        progress = self._progress

        raster = Raster(width, height, background)
        raster.fill(raster.rounded_rect(0.5, 0.5, width - 0.5, height - 0.5,
                                        (height - 1) / 2),
                    mix(palette.border, palette.accent, progress))
        raster.fill(raster.rounded_rect(1.0, 1.0, width - 1.0, height - 1.0,
                                        (height - 2) / 2),
                    mix(palette.surface_alt, palette.accent, progress))
        # The knob crosses the track and pinches slightly on the way, which is
        # what makes the movement read as the knob moving rather than as the
        # whole control being redrawn.
        radius = height / 2 - max(2.0, height * 0.14)
        centre = height / 2 + (width - height) * progress
        pinch = 1.0 - 0.10 * math.sin(math.pi * progress)
        raster.fill(raster.circle(centre, height / 2, radius * pinch),
                    mix(palette.muted, "#ffffff", progress))

        self.image = raster.photo(self)
        self.delete("all")
        self.configure(background=background)
        self.create_image(0, 0, image=self.image, anchor="nw")


# The tick of a checkbox, as the corner points of the two strokes it is drawn
# from, in the box of 17 units the widget is measured in.
TICK = ((4.4, 9.2), (7.5, 12.5), (13.0, 5.2))


def tick_strokes(unit: float, progress: float) -> list[tuple[float, float, float, float]]:
    """How much of the tick to draw, for a box part way through changing."""
    points = [(x * unit, y * unit) for x, y in TICK]
    parts = [math.dist(start, end) for start, end in zip(points, points[1:])]
    left = sum(parts) * progress
    strokes = []
    for start, end, length in zip(points, points[1:], parts):
        if left <= 0.0:
            break
        if left < length:
            strokes.append((*start, start[0] + (end[0] - start[0]) * (left / length),
                            start[1] + (end[1] - start[1]) * (left / length)))
            break
        strokes.append((*start, *end))
        left -= length
    return strokes


class CheckBox(_Animated):
    """A checkbox drawn to match the palette, with a label beside it."""

    SIZE = 18

    def __init__(self, parent: tk.Widget, variable: tk.BooleanVar, palette: Theme,
                 command=None, background: str | None = None) -> None:
        self.size = scaled(self.SIZE)
        super().__init__(parent, width=self.size, height=self.size,
                         highlightthickness=0, borderwidth=0, cursor="hand2")
        self.variable = variable
        self._palette = palette
        self._command = command
        self._background = background
        self._hover = False
        self.image: tk.PhotoImage | None = None
        self.bind("<Button-1>", self._toggle)
        self.bind("<Enter>", lambda _event: self._set_hover(True))
        self.bind("<Leave>", lambda _event: self._set_hover(False))
        self.watch(variable)
        self.repaint(palette)

    def _set_hover(self, value: bool) -> None:
        self._hover = value
        self.repaint(self._palette)

    def _toggle(self, _event=None) -> None:
        self.variable.set(not self.variable.get())
        if self._command is not None:
            self._command()

    def repaint(self, palette: Theme) -> None:
        self._palette = palette
        background = self._background or palette.bg
        size = self.size
        unit = size / 17.0
        radius = max(3.0, 4 * unit)
        progress = self._progress
        # The tick is drawn on as the box fills, so the two ends of the movement
        # are still simply empty and ticked.
        rest = palette.surface_alt if self._hover else palette.surface

        raster = Raster(size, size, background)
        raster.fill(raster.rounded_rect(0.7, 0.7, size - 0.7, size - 0.7,
                                        radius + 0.7), palette.border)
        raster.fill(raster.rounded_rect(1.4, 1.4, size - 1.4, size - 1.4, radius),
                    mix(rest, palette.accent, progress))
        for start_x, start_y, end_x, end_y in tick_strokes(unit, progress):
            raster.fill(raster.capsule(start_x, start_y, end_x, end_y, 2.1 * unit),
                        palette.accent_fg)

        self.image = raster.photo(self)
        self.delete("all")
        self.configure(background=background)
        self.create_image(0, 0, image=self.image, anchor="nw")


class Card(tk.Frame):
    """A group of rows on a panel, with a thin outline."""

    def __init__(self, parent: tk.Widget, palette: Theme, padding: int = 0) -> None:
        super().__init__(parent, background=palette.surface,
                         highlightthickness=1, highlightbackground=palette.border,
                         highlightcolor=palette.border, borderwidth=0)
        self.palette = palette
        self.inner = tk.Frame(self, background=palette.surface)
        self.inner.pack(fill="both", expand=True, padx=padding, pady=padding)

    def repaint(self, palette: Theme) -> None:
        self.palette = palette
        self.configure(background=palette.surface,
                       highlightbackground=palette.border,
                       highlightcolor=palette.border)
        self.inner.configure(background=palette.surface)


class Row(tk.Frame):
    """Title, description and a control, laid out like a settings row.

    The control is built by ``make_control`` with this row as its parent: a
    widget can only be placed in the grid of its own container, so building it
    against the card would put every control of the card in the card's grid.
    """

    def __init__(self, parent: tk.Widget, palette: Theme, title: str,
                 description: str, make_control=None,
                 icon: str | None = None,
                 control_width: int = CONTROL_WIDTH) -> None:
        super().__init__(parent, background=palette.surface)
        self.columnconfigure(2, weight=1)
        self._children: list[tk.Widget] = []

        column = 0
        if icon:
            self._icon = Icon(self, icon, palette, background=palette.surface,
                              colour=palette.muted)
            self._icon.grid(row=0, column=column, rowspan=2, sticky="n",
                            padx=(scaled(14), scaled(12)), pady=scaled(12))
            column += 1

        self.title = tk.Label(self, text=title, font=theme.UI_FONT, anchor="w",
                              background=palette.surface, foreground=palette.fg)
        self.title.grid(row=0, column=column, sticky="w", pady=(scaled(12), 0),
                        padx=(scaled(14) if not icon else 0, scaled(12)))
        self.description = tk.Label(self, text=description, font=theme.UI_FONT,
                                    anchor="w", justify="left",
                                    wraplength=scaled(420),
                                    background=palette.surface,
                                    foreground=palette.muted)
        self.description.grid(row=1, column=column, sticky="w",
                              pady=(scaled(2), scaled(12)),
                              padx=(scaled(14) if not icon else 0, scaled(12)))
        if not description:
            self.description.grid_remove()

        self.control: tk.Widget | None = None
        if make_control is not None:
            # One width for every control, so entries, dropdowns and switches in
            # a card line up instead of each sizing to its own contents. A row
            # whose value is long text rather than a control asks for more: the
            # holder keeps its right edge either way.
            holder = tk.Frame(self, background=palette.surface,
                              width=scaled(control_width))
            holder.grid(row=0, column=2, rowspan=2, sticky="e",
                        padx=(scaled(12), scaled(16)))
            self.holder = holder
            self.control = make_control(holder)
            # The width is fixed so the column lines up, and the height is taken
            # from the control: holding back only the width would squeeze the
            # control to whatever height the holder was left with.
            self.control.pack(**control_pack(self.control))
            holder.pack_propagate(False)
            self.fit()
        self._children.extend([self.title, self.description])

    def fit(self) -> None:
        """Give the holder the height its control actually needs.

        Asked again after the window is styled: a ttk style with padding makes
        every control taller, and a holder that kept the height it was given while
        the window was still being built clips what it holds -- a button loses the
        bottom of its own text.
        """
        if self.control is None:
            return
        self.holder.configure(height=self.control.winfo_reqheight())

    def repaint(self, palette: Theme) -> None:
        self.configure(background=palette.surface)
        for child in self._children:
            child.configure(background=palette.surface)
        self.title.configure(foreground=palette.fg)
        self.description.configure(foreground=palette.muted)


def filter_names(names: Iterable[str], query: str) -> list[str]:
    """The key names that contain what was typed, in their given order."""
    wanted = query.strip().lower()
    if not wanted:
        return list(names)
    return [name for name in names if wanted in name.lower()]


class KeyPicker(tk.Toplevel):
    """Every key name, for the keys the keyboard in front of you does not have.

    Pressing the key is the quick way and covers nine cases out of ten. The tenth
    is a key that is simply absent: a second Windows key on a board that has one,
    PageDown on a laptop that folds it into an arrow, or the Mac's Option and
    Command keys -- which reach this program as Alt and Win, because that is what
    they are.

    The list is a window of its own rather than a combobox dropdown, for two
    reasons: a dropdown of 116 entries is a search problem with a scroll bar for
    an answer, and the one Tk builds inside a scrolling page is placed by widget
    coordinates, which put it half off the screen.
    """

    def __init__(self, anchor: tk.Widget, palette: Theme, names: Iterable[str],
                 on_pick: Callable[[str], None]) -> None:
        super().__init__(anchor)
        self.overrideredirect(True)
        self.configure(background=palette.surface)
        self.attributes("-topmost", True)
        self.palette = palette
        self.names = tuple(names)
        self._on_pick = on_pick

        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self.query = tk.StringVar()
        prompt = tk.Label(self, text=i18n.t("label_search_keys"), anchor="w",
                          font=theme.UI_FONT_SMALL, background=palette.surface,
                          foreground=palette.muted)
        prompt.grid(row=0, column=0, sticky="ew", padx=scaled(8),
                    pady=(scaled(8), 0))
        entry = ttk.Entry(self, textvariable=self.query, width=18)
        entry.grid(row=1, column=0, sticky="ew", padx=scaled(8), pady=scaled(4))
        self.listbox = tk.Listbox(self, height=10, width=22, activestyle="none",
                                  exportselection=False, borderwidth=0,
                                  highlightthickness=0,
                                  background=palette.surface,
                                  foreground=palette.fg,
                                  selectbackground=palette.accent,
                                  selectforeground=palette.accent_fg)
        self.listbox.grid(row=2, column=0, sticky="nsew", padx=scaled(8),
                          pady=(0, scaled(8)))

        self.query.trace_add("write", lambda *_: self._refill())
        entry.bind("<Return>", lambda _event: self._choose())
        entry.bind("<Down>", lambda _event: self.listbox.focus_set())
        for widget in (entry, self.listbox):
            widget.bind("<Escape>", lambda _event: self.close())
            widget.bind("<FocusOut>", lambda _event: self._check_focus())
        self.listbox.bind("<Return>", lambda _event: self._choose())
        self.listbox.bind("<ButtonRelease-1>", lambda _event: self._choose())

        self._refill()
        self._place(anchor)
        self.grab_set()
        entry.focus_set()

    # ---------------------------------------------------------------- filling

    def _refill(self) -> None:
        self.listbox.delete(0, "end")
        for name in filter_names(self.names, self.query.get()):
            self.listbox.insert("end", name)
        if self.listbox.size():
            self.listbox.selection_set(0)
            self.listbox.see(0)

    def _choose(self) -> None:
        chosen = self.listbox.curselection()
        if not chosen:
            return
        self._on_pick(self.listbox.get(chosen[0]))
        self.close()

    # ------------------------------------------------------------------ shell

    def _place(self, anchor: tk.Widget) -> None:
        """Under the field, and inside the screen: the screen wins."""
        self.update_idletasks()
        width = max(self.winfo_reqwidth(), scaled(180))
        height = max(self.winfo_reqheight(), scaled(160))
        x = anchor.winfo_rootx()
        y = anchor.winfo_rooty() + anchor.winfo_height() + scaled(2)
        if x + width > self.winfo_screenwidth():
            x = max(0, self.winfo_screenwidth() - width - scaled(8))
        if y + height > self.winfo_screenheight():
            y = max(0, anchor.winfo_rooty() - height - scaled(2))
        self.geometry(f"{width}x{height}+{x}+{y}")

    def _check_focus(self) -> None:
        # Moving between the box and the list is not leaving the picker, and the
        # focus report arrives before the next widget has it.
        self.after_idle(self._close_if_unfocused)

    def _close_if_unfocused(self) -> None:
        focused = self.focus_get()
        if focused is None or focused.winfo_toplevel() is not self:
            self.close()

    def close(self) -> None:
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()


class KeyField(ttk.Button):
    """A key name that is set by pressing the key.

    The list of names is 116 long, which makes a dropdown a search problem
    dressed as a field: the entries are clipped, a scroll bar becomes a second
    control, and the key you want is never where you look. Pressing the key says
    the same thing in one motion, and it cannot name a key that does not exist.

    Leaving the field gives up, so a field that was clicked by accident stays
    empty instead of capturing whatever is typed next. A key the keyboard does
    not have cannot be pressed at all, so a right click opens the whole list.
    """

    #: Windows sends one virtual key code for both sides of a modifier, so a
    #: capture that lands on it names the left hand key; the right hand one is in
    #: the list the right click offers.
    GENERIC_MODIFIERS = {0x10: "LeftShift", 0x11: "LeftCtrl", 0x12: "LeftAlt",
                         0x5B: "LeftWin", 0x5C: "RightWin"}

    def __init__(self, parent: tk.Widget, palette: Theme, value: str = "",
                 on_change: Callable[[], None] | None = None,
                 width: int = 10) -> None:
        self.value = value
        self._on_change = on_change
        self._capturing = False
        self.palette = palette
        self.picker: KeyPicker | None = None
        super().__init__(parent, text=self._label(), width=width,
                         command=self.capture)
        self.bind("<KeyPress>", self._pressed)
        self.bind("<FocusOut>", self._give_up)
        self.bind("<Button-3>", lambda _event: self.pick())

    def _label(self) -> str:
        return self.value or i18n.t("label_press_key")

    def _show(self) -> None:
        """Draw the label, and size the button to it.

        A fixed width made a two character key name sit in a bar the width of the
        settings column, which reads as an empty field rather than a key. Sized to
        its own text, the control looks like what it is: one key.
        """
        label = self._label()
        key_width = len(label) + 2
        # "label_press_key" is a prompt, not a key: it needs the room to be read.
        self.configure(text=label,
                       width=max(6, key_width) if self.value else 14)

    def set(self, value: str) -> None:
        self.value = value
        self._capturing = False
        self._show()

    def capture(self) -> None:
        """Wait for the next key, and show that it is waiting."""
        self._capturing = True
        self.configure(text="…", width=6)
        self.focus_set()

    def pick(self) -> "KeyPicker":
        """Offer every name, for a key this keyboard does not carry."""
        self.picker = KeyPicker(self, self.palette, sorted(keymap.KEY_NAMES),
                                on_pick=self.assign)
        return self.picker

    def assign(self, name: str) -> None:
        """Name a key, and report the change like any other edit."""
        self.set(name)
        if self._on_change is not None:
            self._on_change()

    def _pressed(self, event) -> str:
        if not self._capturing:
            return ""
        # On Windows a Tk key event carries the virtual key code, which is what
        # the key map is written in -- except for the modifiers, which arrive as
        # VK_SHIFT / VK_CONTROL / VK_MENU with no side to them.
        code = int(getattr(event, "keycode", 0))
        name = self.GENERIC_MODIFIERS.get(code) or keymap.describe_vk(code)
        if name not in keymap.KEY_NAMES:
            self.bell()
            return "break"
        self.assign(name)
        return "break"

    def _give_up(self, _event=None) -> None:
        if self._capturing:
            self.set(self.value)


class ThemedLabel(tk.Label):
    """A label that repaints itself when the palette changes.

    A plain ``tk.Label`` keeps the colours it was built with, so the window has to
    remember to recolour it -- and the two places that remembered were three lines
    away from the ones that forgot. This one knows which palette it belongs to and
    which of its colours is meant: a tone from the palette, or one literal colour
    for something that is state (an error line) rather than style.
    """

    #: Which of the palette's colours the text takes. ``fg`` and ``muted`` are the
    #: two every label uses; ``accent`` marks a live link or an action.
    TONES = ("fg", "muted", "accent")

    def __init__(self, parent: tk.Widget, palette: Theme, text: str = "",
                 font=None, anchor: str = "w", justify: str = "left",
                 wraplength: int = 0, tone: str = "fg", on: str = "bg",
                 colour: str | None = None) -> None:
        self._palette = palette
        self._tone = tone if tone in self.TONES else "fg"
        self._on = on
        self._colour = colour
        super().__init__(parent, text=text, anchor=anchor, justify=justify,
                         background=self._background(),
                         foreground=self._foreground())
        if font is not None:
            self.configure(font=font)
        if wraplength:
            self.configure(wraplength=wraplength)

    def _background(self) -> str:
        return self._palette.surface if self._on == "surface" else self._palette.bg

    def _foreground(self) -> str:
        return self._colour or getattr(self._palette, self._tone)

    def set_tone(self, tone: str) -> None:
        """Follow another palette colour, dropping a literal one."""
        self._tone = tone if tone in self.TONES else "fg"
        self._colour = None
        self.configure(foreground=self._foreground())

    def set_colour(self, colour: str | None) -> None:
        """Take a literal colour, or None to follow the palette again."""
        self._colour = colour
        self.configure(foreground=self._foreground())

    def repaint(self, palette: Theme) -> None:
        self._palette = palette
        self.configure(background=self._background(),
                       foreground=self._foreground())


class Separator(tk.Frame):
    """A hairline between rows of a card."""

    def __init__(self, parent: tk.Widget, palette: Theme) -> None:
        super().__init__(parent, height=1, background=palette.border)

    def repaint(self, palette: Theme) -> None:
        self.configure(background=palette.border)


class RemapList(tk.Frame):
    """Key remaps edited as a list: one From → To line each, and a way to add one.

    A text box with ``From=To`` per line puts the syntax in the user's way: it has
    to be remembered, a typo is a rejected commit, and the existing remaps are
    invisible until you read the whole block. A line per remap shows what is set,
    and each side is a field that is filled by pressing the key itself.

    The lines read as a table: the two fields line up, and every line has its
    remove button in the same column, so the list can be scanned down rather than
    read across.
    """

    #: Characters a key name gets. Long enough for ``PageDown`` and ``RightShift``.
    NAME_WIDTH = 14

    def __init__(self, parent: tk.Widget, palette: Theme,
                 on_change: Callable[[], None] | None = None) -> None:
        super().__init__(parent, background=palette.surface)

        self.palette = palette
        self.on_change = on_change
        self._rows: list[dict[str, tk.Widget]] = []
        self.columnconfigure(0, weight=1)

        self.lines = tk.Frame(self, background=palette.surface)
        self.lines.grid(row=0, column=0, sticky="ew")
        self.empty = tk.Label(self, text=i18n.t("msg_no_keys_remapped"),
                              font=theme.UI_FONT_SMALL, anchor="w",
                              background=palette.surface,
                              foreground=palette.muted)
        self.empty.grid(row=1, column=0, sticky="w", pady=(scaled(2), 0))
        self._show_empty()

    # ------------------------------------------------------------------ rows

    def add_row(self, source: str = "", target: str = "") -> None:
        """Append one remap line, and report the change like an edit."""
        line = tk.Frame(self.lines, background=self.palette.surface)
        line.pack(fill="x", pady=scaled(3))

        source_field = KeyField(line, self.palette, source,
                                on_change=self._changed, width=self.NAME_WIDTH)
        source_field.pack(side="left")
        tk.Label(line, text=i18n.t("label_remap_to"), font=theme.UI_FONT_SMALL,
                 background=self.palette.surface,
                 foreground=self.palette.muted).pack(side="left",
                                                    padx=scaled(10))
        target_field = KeyField(line, self.palette, target,
                                on_change=self._changed, width=self.NAME_WIDTH)
        target_field.pack(side="left")
        remove = IconButton(line, "cross", self.palette,
                            command=lambda: self._remove(entry),
                            colour=self.palette.muted)
        remove.pack(side="left", padx=(scaled(10), 0))

        entry = {"frame": line, "source": source_field, "target": target_field,
                 "remove": remove}
        self._rows.append(entry)
        self._show_empty()
        # A line that is still blank is not a change: nothing can be saved from
        # it, and reporting one would have the window commit -- and, when the
        # commit is refused, rebuild the list under the cursor.

    def _remove(self, entry: dict[str, tk.Widget]) -> None:
        if entry not in self._rows:
            return
        self._rows.remove(entry)
        entry["frame"].destroy()
        self._show_empty()
        self._changed()

    def set_pairs(self, pairs: Iterable[tuple[str, str]]) -> None:
        """Replace every line, without reporting a change."""
        wanted = list(pairs)
        for entry in list(self._rows):
            entry["frame"].destroy()
        self._rows.clear()
        for source, target in wanted:
            self.add_row(source, target)
        self._show_empty()

    def pairs(self) -> list[tuple[str, str]]:
        """The lines that name a key on both sides.

        A line that is only half filled in is a remap in progress, not a remap
        with an error in it: it is left out of what gets saved, and it stays on
        screen so it can be finished.
        """
        found: list[tuple[str, str]] = []
        for entry in self._rows:
            source = entry["source"].value.strip()
            target = entry["target"].value.strip()
            if not source or not target:
                continue
            found.append((source, target))
        return found

    # ----------------------------------------------------------------- state

    def _show_empty(self) -> None:
        if self._rows:
            self.empty.grid_remove()
        else:
            self.empty.grid()

    def _changed(self) -> None:
        if self.on_change is not None:
            self.on_change()

    def repaint(self, palette: Theme) -> None:
        self.palette = palette
        self.configure(background=palette.surface)
        self.lines.configure(background=palette.surface)
        self.empty.configure(background=palette.surface, foreground=palette.muted)
        for entry in self._rows:
            entry["remove"].repaint(palette)


class NavItem(tk.Frame):
    """One entry of the sidebar."""

    def __init__(self, parent: tk.Widget, palette: Theme, label: str, icon: str,
                 command: Callable[[], None], selected: bool = False) -> None:
        super().__init__(parent, background=palette.sidebar, cursor="hand2")
        self.columnconfigure(2, weight=1)
        self._command = command
        self._selected = selected
        self._palette = palette

        self.marker = tk.Frame(self, width=3, background=palette.sidebar)
        self.marker.grid(row=0, column=0, sticky="ns")
        self._icon = Icon(self, icon, palette, background=palette.sidebar,
                          colour=palette.muted)
        self._icon.grid(row=0, column=1, padx=(scaled(13), scaled(12)),
                        pady=scaled(11))
        self.label = tk.Label(self, text=label, font=theme.NAV_FONT, anchor="w",
                              background=palette.sidebar, foreground=palette.fg)
        self.label.grid(row=0, column=2, sticky="ew", padx=(0, scaled(12)),
                        pady=scaled(11))

        for widget in (self, self._icon, self.label):
            widget.bind("<Button-1>", self._click)
            widget.bind("<Enter>", lambda _event: self._hover(True))
            widget.bind("<Leave>", lambda _event: self._hover(False))

    def _click(self, _event=None) -> None:
        self._command()

    def _hover(self, value: bool) -> None:
        if not self._selected:
            colour = self._palette.surface_alt if value else self._palette.sidebar
            self._paint(colour)

    def select(self, selected: bool, palette: Theme) -> None:
        self._selected = selected
        self._palette = palette
        colour = palette.surface_alt if selected else palette.sidebar
        self._paint(colour)
        self.marker.configure(background=palette.accent if selected
                              else palette.sidebar)
        self._icon.repaint(palette)

    def set_text(self, label: str, icon: str) -> None:
        """Say something else, for a row that is also a switch."""
        self.label.configure(text=label)
        self._icon.set_name(icon)
        self._icon.repaint(self._palette)

    def _paint(self, colour: str) -> None:
        self.configure(background=colour)
        self._icon.configure(background=colour)
        self._icon.set_background(colour)
        self._icon.repaint(self._palette)
        self.label.configure(background=colour)


class Sidebar(tk.Frame):
    """Navigation list with a section at the bottom."""

    def __init__(self, parent: tk.Widget, palette: Theme,
                 width: int = 208) -> None:
        super().__init__(parent, background=palette.sidebar,
                         width=scaled(width))
        self.pack_propagate(False)
        self.palette = palette
        self.items: dict[str, NavItem] = {}
        self._top = tk.Frame(self, background=palette.sidebar)
        self._top.pack(fill="x", pady=(scaled(10), 0))
        self._bottom = tk.Frame(self, background=palette.sidebar)
        self._bottom.pack(side="bottom", fill="x", pady=(0, scaled(10)))

    def add(self, key: str, label: str, icon: str, command, bottom: bool = False):
        item = NavItem(self._bottom if bottom else self._top, self.palette, label,
                       icon, command)
        item.pack(fill="x")
        self.items[key] = item
        return item

    def select(self, key: str) -> None:
        for name, item in self.items.items():
            item.select(name == key, self.palette)

    def repaint(self, palette: Theme) -> None:
        self.palette = palette
        self.configure(background=palette.sidebar)
        for frame in (self._top, self._bottom):
            frame.configure(background=palette.sidebar)
        for item in self.items.values():
            item.select(item._selected, palette)
