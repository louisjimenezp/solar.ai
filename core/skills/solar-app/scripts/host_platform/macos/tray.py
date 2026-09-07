#!/usr/bin/env python3
"""macOS menu bar tray for Solar Host (requires rumps)."""
from __future__ import annotations

import atexit
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import voice_core as vc  # noqa: E402
from host_platform.macos import client, hud, notifications, voice_session, webview  # noqa: E402

MENU_LABELS = ("Voice", "Solar", "Dashboard", "Switch workspace", "Quit")


def main() -> int:
    if sys.platform != "darwin":
        print("WARN: tray is macOS-only", file=sys.stderr)
        return 0

    try:
        import rumps  # type: ignore
    except ImportError:
        print(
            "WARN: rumps not available — tray needs: bash .../run_host_tray.sh",
            file=sys.stderr,
        )
        return 0

    class SolarHostApp(rumps.App):
        def __init__(self) -> None:
            super().__init__("Solar", quit_button="Quit")
            self._seen_events: set[str] = set()
            self._voice = voice_session.TrayVoice()
            self._voice_item = rumps.MenuItem("Voice", callback=self.toggle_voice)
            self._workspace_menu = rumps.MenuItem("Switch workspace")
            self._workspace_menu.add(rumps.MenuItem("Loading…", callback=lambda *_: None))
            self.menu = [
                self._voice_item,
                None,
                rumps.MenuItem("Solar", callback=self.open_solar),
                rumps.MenuItem("Dashboard", callback=self.open_dashboard),
                self._workspace_menu,
            ]
            self._pending = 0
            self._bootstrapped = False
            atexit.register(self._voice.shutdown)

        @rumps.timer(1)
        def _bootstrap(self, _: object) -> None:
            if self._bootstrapped:
                return
            self._bootstrapped = True
            vc.reap_orphan_recorders()
            self._refresh_workspaces()
            self.refresh_badge(_)

        def _open_window(self, path: str, *, title: str, key: str) -> None:
            url = f"{client.host_url()}{path}"
            kind = webview.open_app_window(url, title=title, key=key)
            if kind == "none":
                notifications.show_notification(
                    "Solar",
                    "No se pudo abrir la ventana",
                    "Instala Chrome o PyObjC WebKit (run_host_tray.sh).",
                )

        def open_solar(self, _: object) -> None:
            self._open_window("/app", title="Solar", key="solar")

        def open_dashboard(self, _: object) -> None:
            self._open_window("/dashboard", title="Dashboard", key="dashboard")

        def toggle_voice(self, _: object) -> None:
            self._voice.toggle()
            self._sync_voice_ui(None)

        def _use_workspace(self, path: str) -> None:
            if client.switch_workspace(path):
                self._voice.reset_conversation()
                notifications.show_notification(
                    "Solar",
                    "Workspace active",
                    Path(path).name,
                )
            else:
                notifications.show_notification("Solar", "Error", "Could not switch workspace")
            self._refresh_workspaces()
            self.refresh_badge(None)

        def _refresh_workspaces(self) -> None:
            if getattr(self._workspace_menu, "_menu", None) is None:
                return
            self._workspace_menu.clear()
            workspaces = client.list_workspaces()
            if not workspaces:
                self._workspace_menu.add(
                    rumps.MenuItem("(Host offline)", callback=lambda *_: None)
                )
                return
            for ws in workspaces:
                path = str(ws.get("path", ""))
                label = str(ws.get("label") or Path(path).name)
                suffix = " ✓" if ws.get("active") else ""
                self._workspace_menu.add(
                    rumps.MenuItem(
                        f"{label}{suffix}",
                        callback=lambda _, p=path: self._use_workspace(p),
                    )
                )

        @rumps.timer(0.12)
        def _sync_voice_ui(self, _: object) -> None:
            snap = self._voice.snapshot()
            if self._voice_item.title != snap.menu:
                self._voice_item.title = snap.menu
            if snap.state == "idle":
                if snap.hud:
                    hud.show(snap.hud)
                else:
                    hud.hide()
                    n = getattr(self, "_pending", 0)
                    self.title = f"Solar ({n})" if n else "Solar"
            else:
                hud.show(snap.hud)
                self.title = snap.title

        @rumps.timer(30)
        def refresh_badge(self, _: object) -> None:
            self._pending = client.pending_approval_count()
            self._refresh_workspaces()
            if self._voice.snapshot().state == "idle":
                self.title = f"Solar ({self._pending})" if self._pending else "Solar"

        @rumps.timer(15)
        def poll_notifications(self, _: object) -> None:
            for event in notifications.poll_new_events(self._seen_events):
                title, subtitle, message = notifications.format_notification(event)
                notifications.show_notification(title, subtitle, message)

    SolarHostApp().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
