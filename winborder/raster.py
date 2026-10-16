"""Anti-aliased drawing for the controls the window draws itself.

Tk's canvas has no anti-aliasing: circles and diagonal lines come out stepped,
which shows badly at the sizes this window uses. Anything drawn rather than
themed is therefore rasterised here, using signed distance fields so the edges
stay smooth at any size.

A shape is a coverage function over the pixel grid. Filling blends it over what
is already there and records how opaque the pixel became, so the same buffer can
be written out either flattened or with a transparent background.
"""

from __future__ import annotations

import math
import tkinter as tk
from typing import Callable

Colour = tuple[int, int, int]
Coverage = Callable[[float, float], float]


class Raster:
    """A small software rasteriser for flat shapes."""

    def __init__(self, width: int, height: int, background: str) -> None:
        self.width = max(1, int(width))
        self.height = max(1, int(height))
        self._pixels = [[_rgb(background)] * self.width for _ in range(self.height)]
        self._alpha = [[0.0] * self.width for _ in range(self.height)]

    # -- shapes -----------------------------------------------------------

    def rounded_rect(self, x0: float, y0: float, x1: float, y1: float,
                     radius: float) -> Coverage:
        half_w = max(0.0, (x1 - x0)) / 2 - radius
        half_h = max(0.0, (y1 - y0)) / 2 - radius
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        radius = max(0.0, radius)

        def coverage(x: float, y: float) -> float:
            dx = abs(x - cx) - half_w
            dy = abs(y - cy) - half_h
            outside = math.hypot(max(dx, 0.0), max(dy, 0.0))
            inside = min(max(dx, dy), 0.0)
            return _edge(outside + inside - radius)
        return coverage

    def circle(self, cx: float, cy: float, radius: float) -> Coverage:
        def coverage(x: float, y: float) -> float:
            return _edge(math.hypot(x - cx, y - cy) - radius)
        return coverage

    def ring(self, cx: float, cy: float, radius: float, width: float,
             start_deg: float = 0.0, extent_deg: float = 360.0) -> Coverage:
        half = width / 2
        start = math.radians(start_deg)
        extent = math.radians(extent_deg)
        full = extent_deg >= 359.9
        low, high = start, start + extent

        def coverage(x: float, y: float) -> float:
            dx, dy = x - cx, cy - y
            distance = math.hypot(dx, dy)
            band = _edge(abs(distance - radius) - half)
            if band <= 0.0 or full:
                return band
            angle = math.atan2(dy, dx) % (2 * math.pi)
            for candidate in (angle, angle + 2 * math.pi):
                if low <= candidate <= high:
                    return band
            return 0.0
        return coverage

    def capsule(self, x0: float, y0: float, x1: float, y1: float,
                width: float) -> Coverage:
        half = width / 2
        dx, dy = x1 - x0, y1 - y0
        length_sq = dx * dx + dy * dy

        def coverage(x: float, y: float) -> float:
            if length_sq == 0.0:
                distance = math.hypot(x - x0, y - y0)
            else:
                t = max(0.0, min(1.0, ((x - x0) * dx + (y - y0) * dy) / length_sq))
                distance = math.hypot(x - (x0 + t * dx), y - (y0 + t * dy))
            return _edge(distance - half)
        return coverage

    def polygon(self, points: list[tuple[float, float]]) -> Coverage:
        """A filled polygon, sampled: it is small and rarely repainted."""
        samples = ((-0.25, -0.25), (0.25, -0.25), (-0.25, 0.25), (0.25, 0.25))

        def inside(x: float, y: float) -> bool:
            result = False
            count = len(points)
            for index in range(count):
                x0, y0 = points[index]
                x1, y1 = points[(index + 1) % count]
                if (y0 > y) != (y1 > y):
                    cut = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
                    if x < cut:
                        result = not result
            return result

        def coverage(x: float, y: float) -> float:
            hits = sum(1 for ox, oy in samples if inside(x + ox, y + oy))
            return hits / len(samples)
        return coverage

    # -- painting ---------------------------------------------------------

    def fill(self, shape: Coverage, colour: str) -> None:
        """Blend a shape over what is already there."""
        target = _rgb(colour)
        for y in range(self.height):
            row = self._pixels[y]
            alpha_row = self._alpha[y]
            for x in range(self.width):
                coverage = shape(x + 0.5, y + 0.5)
                if coverage <= 0.0:
                    continue
                if coverage >= 1.0:
                    row[x] = target
                    alpha_row[x] = 1.0
                    continue
                current = row[x]
                row[x] = (int(current[0] + (target[0] - current[0]) * coverage),
                          int(current[1] + (target[1] - current[1]) * coverage),
                          int(current[2] + (target[2] - current[2]) * coverage))
                alpha_row[x] = max(alpha_row[x], coverage)

    def erase(self, shape: Coverage) -> None:
        """Take ink away again, for the hollow parts of a mark.

        Painting the background colour instead would only look right on the
        background it was drawn for; clearing the coverage leaves a real hole.
        """
        for y in range(self.height):
            alpha_row = self._alpha[y]
            for x in range(self.width):
                coverage = shape(x + 0.5, y + 0.5)
                if coverage > 0.0:
                    alpha_row[x] = max(0.0, alpha_row[x] - coverage)

    def photo(self, master: tk.Misc, transparent: bool = False) -> tk.PhotoImage:
        """The buffer as an image, optionally keeping its background clear."""
        image = tk.PhotoImage(master=master, width=self.width, height=self.height)
        rows = ["{" + " ".join(_hex(pixel) for pixel in row) + "}"
                for row in self._pixels]
        image.put(" ".join(rows))
        if transparent:
            for y in range(self.height):
                alpha_row = self._alpha[y]
                for x in range(self.width):
                    if alpha_row[x] <= 0.0:
                        image.transparency_set(x, y, True)
        return image

    def rgba(self) -> bytes:
        """The buffer as BGRA rows, top down, with the coverage as alpha."""
        out = bytearray()
        for y in range(self.height):
            row = self._pixels[y]
            alpha_row = self._alpha[y]
            for x in range(self.width):
                red, green, blue = row[x]
                out += bytes((blue, green, red, int(alpha_row[x] * 255)))
        return bytes(out)


def _edge(distance: float) -> float:
    """Coverage from a signed distance: one pixel wide transition."""
    return max(0.0, min(1.0, 0.5 - distance))


def _rgb(colour: str) -> Colour:
    """#rgb or #rrggbb, so a shorthand colour is not a mystery crash."""
    digits = colour.lstrip("#")
    if len(digits) == 3:
        digits = "".join(character * 2 for character in digits)
    if len(digits) != 6:
        raise ValueError(f"not a colour: {colour!r}")
    return (int(digits[0:2], 16), int(digits[2:4], 16), int(digits[4:6], 16))


def _hex(pixel: Colour) -> str:
    return "#{:02x}{:02x}{:02x}".format(*pixel)


def mix(first: str, second: str, amount: float) -> str:
    """A colour part way from one to the other.

    Used while a control is moving: at either end the answer is exactly the
    colour that was asked for, so a control at rest looks like the palette and
    not like a frame of an animation.
    """
    start, end = _rgb(first), _rgb(second)
    return _hex(tuple(int(round(a + (b - a) * amount))
                      for a, b in zip(start, end)))
