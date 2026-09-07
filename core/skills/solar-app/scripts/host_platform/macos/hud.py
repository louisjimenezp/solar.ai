#!/usr/bin/env python3
"""Compact Voice HUD near the macOS menu bar."""
from __future__ import annotations

from typing import Optional

_panel = None
_label = None
_available: Optional[bool] = None


def available() -> bool:
    global _available  # noqa: PLW0603
    if _available is not None:
        return _available
    try:
        from AppKit import NSPanel, NSTextField  # noqa: F401, PLC0415

        _available = True
    except ImportError:
        _available = False
    return _available


def _build() -> None:
    global _panel, _label  # noqa: PLW0603
    from AppKit import (  # type: ignore
        NSColor,
        NSFont,
        NSMakeRect,
        NSPanel,
        NSScreen,
        NSTextField,
        NSWindowStyleMaskNonactivatingPanel,
        NSWindowStyleMaskTitled,
        NSFloatingWindowLevel,
    )

    width, height = 320.0, 56.0
    screen = NSScreen.mainScreen().visibleFrame()
    rect = NSMakeRect(
        screen.origin.x + (screen.size.width - width) / 2,
        screen.origin.y + screen.size.height - height - 12,
        width,
        height,
    )
    panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
        rect,
        NSWindowStyleMaskTitled | NSWindowStyleMaskNonactivatingPanel,
        2,  # NSBackingStoreBuffered
        False,
    )
    panel.setTitle_("Solar")
    panel.setLevel_(NSFloatingWindowLevel)
    panel.setHidesOnDeactivate_(False)
    panel.setReleasedWhenClosed_(False)
    panel.setFloatingPanel_(True)
    label = NSTextField.alloc().initWithFrame_(NSMakeRect(12, 12, width - 24, 28))
    label.setBezeled_(False)
    label.setDrawsBackground_(False)
    label.setEditable_(False)
    label.setSelectable_(False)
    label.setAlignment_(1)  # NSTextAlignmentCenter
    label.setFont_(NSFont.systemFontOfSize_(15))
    label.setTextColor_(NSColor.labelColor())
    panel.contentView().addSubview_(label)
    _panel = panel
    _label = label


def show(text: str) -> None:
    if not available():
        return
    if _panel is None:
        _build()
    assert _panel is not None and _label is not None
    _label.setStringValue_(text)
    _panel.orderFrontRegardless()


def hide() -> None:
    if _panel is None:
        return
    _panel.orderOut_(None)
