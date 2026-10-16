"""Small widgets the settings window is built from.

Everything here is drawn with the rasteriser in :mod:`winborder.raster`, because
Tk's canvas has no anti-aliasing and the shapes this window needs are all curves.
Every widget can repaint itself when the system theme changes.
"""

from __future__ import annotations

import math
import time
import tkinter as tk
from typing import Callable

from . import theme
from .raster import Coverage, Raster, mix
from .theme import Theme

ICON_SIZE = 16
HERO_ICON_SIZE = 32

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
    if name == "status":
        # An "i" in a ring: the one glyph whose ink is centred by construction.
        glyph.ring(8, 8, 6.4, 1.4)
        glyph.dot(8, 5.3, 0.95)
        glyph.stroke(8, 7.9, 8, 11.0, 1.7)
    elif name == "link":
        glyph.rect(1.4, 3.0, 9.6, 13.0, 1.5)
        glyph.rect(6.4, 3.0, 14.6, 13.0, 1.5, glyph.background)
        glyph.rect(7.8, 4.4, 13.2, 11.6, 1.2)
    elif name == "pointer":
        glyph.wedge([(4.0, 2.0), (4.0, 13.0), (7.4, 10.2), (12.0, 10.2)])
    elif name == "edge":
        glyph.outline(1.6, 3.0, 8.8, 13.0)
        glyph.stroke(8.8, 8.0, 13.4, 8.0, 1.3)
        glyph.wedge([(11.8, 5.4), (15.0, 8.0), (11.8, 10.6)])
    elif name == "keyboard":
        glyph.outline(1.0, 4.0, 15.0, 12.0, 1.3)
        for column in range(3):
            for row in range(2):
                glyph.dot(4.0 + column * 3.6, 6.8 + row * 2.8, 0.85)
    elif name == "log":
        glyph.stroke(2.6, 4.4, 13.4, 4.4)
        glyph.stroke(2.6, 8.0, 11.0, 8.0)
        glyph.stroke(2.6, 11.6, 13.4, 11.6)
    elif name == "file":
        glyph.wedge([(3.6, 2.0), (9.4, 2.0), (12.6, 5.2), (12.6, 14.0),
                     (3.6, 14.0)])
        glyph.wedge([(5.0, 3.4), (8.8, 3.4), (11.2, 5.8), (11.2, 12.6),
                     (5.0, 12.6)], colour=glyph.background)
        glyph.stroke(6.4, 8.0, 9.8, 8.0, 1.1)
        glyph.stroke(6.4, 10.6, 9.8, 10.6, 1.1)
    elif name == "reload":
        glyph.ring(8.0, 8.0, 5.4, 1.8, start=70, extent=290)
        glyph.wedge([(10.4, 1.0), (14.6, 3.8), (9.8, 5.8)])
    elif name == "gear":
        # Sliders: the usual mark for settings that are not a module.
        for index, (height, knob) in enumerate(((4.6, 6.0), (8.0, 11.0), (11.4, 5.0))):
            glyph.stroke(2.4, height, 13.6, height, 1.3)
            glyph.raster.fill(
                glyph.raster.circle(*glyph._point(knob, height), 2.1 * glyph.unit),
                glyph.background)
            glyph.raster.fill(
                glyph.raster.circle(*glyph._point(knob, height), 1.6 * glyph.unit),
                glyph.colour)
    elif name == "pause":
        # Two bars, centred in the box: the ink runs 5.2 to 10.8, and 3.4 to 12.6.
        glyph.rect(5.2, 3.4, 7.2, 12.6, 0.9)
        glyph.rect(8.8, 3.4, 10.8, 12.6, 0.9)
    elif name == "play":
        # The same box: the triangle spans it and its width is centred on x = 8.
        glyph.wedge([(6.2, 3.6), (12.0, 8.0), (6.2, 12.4)])
    elif name == "quit":
        glyph.ring(8.0, 9.2, 5.4, 1.8, start=110, extent=320)
        glyph.stroke(8.0, 2.0, 8.0, 8.4, 1.8)
    else:
        glyph.ring(8, 8, 6.4, 1.4)


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
            holder.configure(height=self.control.winfo_reqheight())
            holder.pack_propagate(False)
            self.control.pack(**control_pack(self.control))
        self._children.extend([self.title, self.description])

    def repaint(self, palette: Theme) -> None:
        self.configure(background=palette.surface)
        for child in self._children:
            child.configure(background=palette.surface)
        self.title.configure(foreground=palette.fg)
        self.description.configure(foreground=palette.muted)


class Separator(tk.Frame):
    """A hairline between rows of a card."""

    def __init__(self, parent: tk.Widget, palette: Theme) -> None:
        super().__init__(parent, height=1, background=palette.border)

    def repaint(self, palette: Theme) -> None:
        self.configure(background=palette.border)


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
