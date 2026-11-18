"""Shared parts of the explorers: a box of controls over a static Matplotlib picture, and safe calls of your code.

Every redraw renders the figure to a PNG with Matplotlib's Agg canvas and shows it in an ipywidgets ``Image``:
no ipympl, no pyplot, no display needed. Nothing here starts a thread or a process, so a redraw runs in the
kernel itself, under the thread caps that ``st.init`` set.

Credit: Minseong Seo (SGTL, Seoul National University). License: MIT.
"""
from __future__ import annotations

import html
import io
import time
from contextlib import contextmanager
from typing import Any, Callable, Iterator, Optional, Tuple


def require_ipywidgets() -> Any:
    """The ipywidgets module, or an ImportError that says how to get it."""
    try:
        import ipywidgets
    except ImportError as exc:  # pragma: no cover - the course environment has it
        raise ImportError("The explorers need ipywidgets 8, which the course environment installs "
                          "(bin/sgtl-install env --apply).") from exc
    return ipywidgets


def func_name(func: Optional[Callable], fallback: str) -> str:
    """The name to show for one of your functions."""
    name = getattr(func, "__name__", None)
    return name if isinstance(name, str) and name.isidentifier() else fallback


def call_yours(func: Callable, label: str, *args: Any) -> Tuple[Any, Optional[str]]:
    """Call one of your functions: (its result, None), or (None, a short message) when it raised.

    The message names the function and the kind of error only; it never says what the right result would be.
    """
    try:
        return func(*args), None
    except NotImplementedError:
        return None, f"your {label} is not written yet"
    except Exception as exc:  # any error in your code becomes a message, not a broken explorer
        text = str(exc).strip().splitlines()[0][:160] if str(exc).strip() else ""
        return None, f"your {label} raised {type(exc).__name__}" + (f": {text}" if text else "")


def new_figure(width_in: float, height_in: float) -> Any:
    """A Matplotlib Figure with its own Agg canvas (no pyplot, so no backend and no display are involved)."""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    fig = Figure(figsize=(width_in, height_in), layout="constrained")
    FigureCanvasAgg(fig)
    return fig


def png_bytes(fig: Any, dpi: int) -> bytes:
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=dpi)
    return buffer.getvalue()


def status_html(lines: list) -> str:
    """Status lines as small HTML text (each line escaped)."""
    body = "<br>".join(html.escape(str(line)) for line in lines if line)
    return f'<div style="font-size: 0.9em; line-height: 1.4;">{body}</div>'


class Explorer:
    """Base class: controls, a picture and a status line; ``redraw()`` runs after every change of a control.

    Attributes you can use: ``figure`` (the Matplotlib Figure of the last redraw; ``figure.savefig(...)`` keeps
    it), ``state`` (the numbers of the last redraw), ``redraw_seconds`` (how long the last redraw took).
    """

    dpi = 100

    def __init__(self, width_in: float, height_in: float) -> None:
        widgets = require_ipywidgets()
        self._widgets = widgets
        self.figure = new_figure(width_in, height_in)
        self.image = widgets.Image(format="png")
        self.status = widgets.HTML()
        self.box: Any = None
        self.state: dict = {}
        self.lines: dict = {}
        self.redraw_seconds = float("nan")
        self.redraws = 0
        self._held = False

    @contextmanager
    def hold(self) -> Iterator[None]:
        """Change several controls without a redraw after each one."""
        before, self._held = self._held, True
        try:
            yield
        finally:
            self._held = before

    def redraw(self) -> None:
        if self._held:
            return
        start = time.perf_counter()
        self.lines = {}
        self.figure.clear()
        self._draw()
        self.image.value = png_bytes(self.figure, self.dpi)
        self.redraw_seconds = time.perf_counter() - start
        self.redraws += 1

    def _changed(self, _change: Any = None) -> None:
        self.redraw()

    def _draw(self) -> None:  # pragma: no cover - every explorer defines it
        raise NotImplementedError

    def _repr_mimebundle_(self, **kwargs: Any) -> Any:
        return self.box._repr_mimebundle_(**kwargs)
