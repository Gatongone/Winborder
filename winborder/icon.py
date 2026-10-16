"""The application mark, in one place.

Four panes in a square, with a right angle at each corner: the panes are the two
screens, the corner marks are the shared border they are crossed at. The same
shapes are used for the window icon, the notification area icon and the icon
embedded in the built executable, so they cannot drift apart.
"""

from __future__ import annotations

import tkinter as tk

from .raster import Coverage, Raster

# Below this the four panes stop being legible and one stands in for them.
DETAIL_LIMIT = 28


def app_icon_shapes(size: int, colour: str,
                    background: str) -> list[tuple[Coverage, str | None]]:
    """The mark, drawn in a box of 32 units scaled to ``size``.

    A shape paired with ``None`` is a hole rather than a colour, so the open
    panes let whatever is behind the icon through.
    """
    unit = size / 32.0
    raster = Raster(1, 1, background)

    def rect(x0: float, y0: float, x1: float, y1: float,
             radius: float = 2.5) -> Coverage:
        return raster.rounded_rect(x0 * unit, y0 * unit, x1 * unit, y1 * unit,
                                   radius * unit)

    def stroke(x0: float, y0: float, x1: float, y1: float,
               width: float = 2.4) -> Coverage:
        return raster.capsule(x0 * unit, y0 * unit, x1 * unit, y1 * unit,
                              width * unit)

    shapes: list[tuple[Coverage, str | None]] = []

    # A right angle in each corner of the frame.
    arm, thick, inset = 5.5, 2.4, 1.2
    far = 32.0 - inset
    for horizontal, vertical in ((inset, inset), (inset, far),
                                 (far, inset), (far, far)):
        sign_x = 1.0 if horizontal == inset else -1.0
        sign_y = 1.0 if vertical == inset else -1.0
        shapes.append((stroke(horizontal, vertical,
                              horizontal + sign_x * arm, vertical, thick), colour))
        shapes.append((stroke(horizontal, vertical,
                              horizontal, vertical + sign_y * arm, thick), colour))

    if size >= DETAIL_LIMIT:
        # Four panes, the outer pair filled and the inner pair outlined. The
        # block is centred: the margin is whatever is left over on both sides.
        span, gap = 10.0, 2.0
        edge = (32.0 - (2 * span + gap)) / 2
        second = edge + span + gap
        for index, (x, y) in enumerate(((edge, edge), (second, edge),
                                        (edge, second), (second, second))):
            filled = index in (0, 3)
            shapes.append((rect(x, y, x + span, y + span), colour))
            if not filled:
                shapes.append((rect(x + 1.6, y + 1.6, x + span - 1.6,
                                    y + span - 1.6), None))
    else:
        shapes.append((rect(10.0, 10.0, 22.0, 22.0), colour))

    return shapes


def render(master: tk.Misc, size: int, colour: str,
           background: str | None = None) -> tk.PhotoImage:
    """The mark as an image, transparent unless a background is given."""
    clear = background or "#000000"
    image = Raster(size, size, clear)
    for shape, fill in app_icon_shapes(size, colour, clear):
        if fill is None:
            image.erase(shape)
        else:
            image.fill(shape, fill)
    return image.photo(master, transparent=background is None)


def rgba(size: int, colour: str, background: str) -> bytes:
    """The mark as BGRA rows, for an icon handle or an .ico file."""
    image = Raster(size, size, background)
    for shape, fill in app_icon_shapes(size, colour, background):
        if fill is None:
            image.erase(shape)
        else:
            image.fill(shape, fill)
    return image.rgba()
