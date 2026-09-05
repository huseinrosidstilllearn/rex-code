"""
rex.cli_spinner
Reusable dinosaur spinner for the Rex Code CLI.
Uses rich.live.Live with a green brand color (#22C55E).
"""

from __future__ import annotations

import itertools
from typing import Optional

from rich.console import Console, Group
from rich.live import Live
from rich.text import Text

BRAND_GREEN = "#22C55E"

# 12-frame dinosaur animation (side-view dino walking)
_DINO_FRAMES = [
    r"""
      __
     /  \
    ( o  o)
    |   __|
    |  |  |
    \__/  \__""",
    r"""
      __
     /  \
    ( o  o)
    |   __|
    |  |  |
    \__/  \__""",
    r"""
      __
     /  \
    ( -  -)
    |   __|
    |  |  |
    \__/  \__""",
    r"""
      __
     /  \
    ( o  o)
    |   __|
    |  |  |
    \__/  \__""",
    r"""
      __
     /  \
    ( o  o)
    |  __ |
    |  |  |
    \__/  \__""",
    r"""
      __
     /  \
    ( -  -)
    |  __ |
    |  |  |
    \__/  \__""",
    r"""
      __
     /  \
    ( o  o)
    |   __|
    |  |  |
    \__/  \__""",
    r"""
      __
     /  \
    ( o  o)
    |   __|
    |  |  |
    \__/  \__""",
    r"""
      __
     /  \
    ( -  -)
    |   __|
    |  |  |
    \__/  \__""",
    r"""
      __
     /  \
    ( o  o)
    |   __|
    |  |  |
    \__/  \__""",
    r"""
      __
     /  \
    ( o  o)
    |  __ |
    |  |  |
    \__/  \__""",
    r"""
      __
     /  \
    ( -  -)
    |  __ |
    |  |  |
    \__/  \__""",
]


class DinoSpinner:
    """Context manager that displays a green dinosaur spinner."""

    def __init__(
        self,
        console: Optional[Console] = None,
        text: str = "",
        color: str = BRAND_GREEN,
        speed: float = 0.1,
    ) -> None:
        self._console = console or Console()
        self._text = text
        self._color = color
        self._speed = speed
        self._live: Optional[Live] = None
        self._frame_iter = itertools.cycle(range(len(_DINO_FRAMES)))

    def _render(self, frame_idx: int) -> Group:
        dino = Text(_DINO_FRAMES[frame_idx], style=self._color)
        label = Text(self._text, style="bold") if self._text else Text("")
        return Group(dino, label)

    def __enter__(self) -> "DinoSpinner":
        self._live = Live(
            self._render(next(self._frame_iter)),
            console=self._console,
            transient=True,
            refresh_per_second=10,
        )
        self._live.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._live is not None:
            self._live.__exit__(exc_type, exc_val, exc_tb)
            self._live = None

    def update_text(self, text: str) -> None:
        """Update the spinner label while running."""
        self._text = text
        if self._live is not None:
            self._live.update(self._render(next(self._frame_iter)))


def spinner(
    console: Optional[Console] = None,
    text: str = "",
    color: str = BRAND_GREEN,
) -> DinoSpinner:
    """Convenience factory for DinoSpinner."""
    return DinoSpinner(console=console, text=text, color=color)