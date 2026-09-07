"""Menu-bar Voice contracts: labels, transcript gating and window argv (no rumps)."""
import sys
import unittest
from pathlib import Path

CORE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(CORE / "skills/solar-app/scripts"))

from host_platform.macos import client
from host_platform.macos.tray import MENU_LABELS
from host_platform.macos.webview import chrome_app_argv


class TrayMenuTests(unittest.TestCase):
    def test_menu_is_the_voice_os_surface(self):
        self.assertEqual(MENU_LABELS, ("Voice", "Solar", "Dashboard", "Switch workspace", "Quit"))
        joined = " ".join(MENU_LABELS)
        self.assertNotIn("Inbox", joined)
        self.assertNotIn("Refresh", joined)
        self.assertNotIn("Open Host", joined)

    def test_last_assistant_text_and_transcript_gate(self):
        self.assertEqual(
            client.last_assistant_text(
                {"messages": [{"role": "user", "text": "Hola"}, {"role": "assistant", "text": "Me pongo con ello."}]}
            ),
            "Me pongo con ello.",
        )
        self.assertTrue(client.transcript_ok("Prepara una nota"))
        self.assertFalse(client.transcript_ok("[voice] Micrófono sin señal"))
        self.assertFalse(client.transcript_ok("  "))

    def test_chrome_app_window_argv(self):
        argv = chrome_app_argv(
            "http://127.0.0.1:9000/app",
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/tmp/solar-chrome",
        )
        self.assertEqual(argv[1], "--app=http://127.0.0.1:9000/app")
        self.assertIn("--user-data-dir=/tmp/solar-chrome", argv)


if __name__ == "__main__":
    unittest.main()
