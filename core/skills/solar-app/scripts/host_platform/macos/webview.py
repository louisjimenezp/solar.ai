#!/usr/bin/env python3
"""Open /app and /dashboard in an app window, not a generic browser tab."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Optional

from host_platform.paths import host_global_dir

_CHROME_BINS = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
)

_windows: Dict[str, object] = {}


def chrome_bin() -> Optional[str]:
    for path in _CHROME_BINS:
        if Path(path).is_file():
            return path
    return shutil.which("google-chrome") or shutil.which("chromium")


def chrome_app_argv(url: str, binary: str, profile: str) -> list[str]:
    return [binary, f"--app={url}", f"--user-data-dir={profile}"]


def _chrome_profile() -> str:
    path = host_global_dir() / "chrome-app-profile"
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def _open_webkit(url: str, title: str, key: str) -> bool:
    try:
        from AppKit import (  # type: ignore
            NSApp,
            NSBackingStoreBuffered,
            NSMakeRect,
            NSScreen,
            NSWindow,
            NSWindowStyleMaskClosable,
            NSWindowStyleMaskMiniaturizable,
            NSWindowStyleMaskResizable,
            NSWindowStyleMaskTitled,
        )
        from Foundation import NSURL, NSURLRequest  # type: ignore
        from WebKit import WKWebView, WKWebViewConfiguration  # type: ignore
    except ImportError:
        return False

    existing = _windows.get(key)
    if existing is not None:
        try:
            existing.makeKeyAndOrderFront_(None)
            NSApp.activateIgnoringOtherApps_(True)
            return True
        except Exception:  # noqa: BLE001
            _windows.pop(key, None)

    screen = NSScreen.mainScreen().visibleFrame()
    width, height = (1100.0, 760.0) if key == "solar" else (980.0, 720.0)
    rect = NSMakeRect(
        screen.origin.x + 72,
        screen.origin.y + max(40.0, (screen.size.height - height) / 2),
        min(width, screen.size.width - 80),
        min(height, screen.size.height - 80),
    )
    mask = (
        NSWindowStyleMaskTitled
        | NSWindowStyleMaskClosable
        | NSWindowStyleMaskMiniaturizable
        | NSWindowStyleMaskResizable
    )
    window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        rect, mask, NSBackingStoreBuffered, False
    )
    window.setTitle_(title)
    window.setReleasedWhenClosed_(False)
    config = WKWebViewConfiguration.alloc().init()
    webview = WKWebView.alloc().initWithFrame_configuration_(window.contentView().bounds(), config)
    webview.setAutoresizingMask_(18)
    window.setContentView_(webview)
    request = NSURLRequest.requestWithURL_(NSURL.URLWithString_(url))
    webview.loadRequest_(request)
    window.makeKeyAndOrderFront_(None)
    NSApp.activateIgnoringOtherApps_(True)
    _windows[key] = window
    return True


def _open_chrome(url: str) -> bool:
    binary = chrome_bin()
    if not binary:
        return False
    env = {k: v for k, v in os.environ.items() if not k.startswith("DYLD_")}
    subprocess.Popen(
        chrome_app_argv(url, binary, _chrome_profile()),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        env=env,
    )
    return True


def open_app_window(url: str, *, title: str, key: str) -> str:
    """Return 'webkit', 'chrome', or 'none'."""
    if _open_webkit(url, title, key):
        return "webkit"
    if _open_chrome(url):
        return "chrome"
    return "none"
