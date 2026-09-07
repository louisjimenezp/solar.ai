"""Recorder cleanup must not interrupt live captures or unrelated processes."""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'skills/solar-app/scripts'))
import voice_core as vc


class RecorderCleanupTests(unittest.TestCase):
    def cleanup(self, parent=1, uid=None, path='/tmp/solar-audio-abcdef.wav', executable='/opt/homebrew/bin/rec'):
        uid = os.getuid() if uid is None else uid
        command = f'{executable} {path}'
        identity = f'{uid} {parent} {executable} {command}'
        with patch.object(vc.subprocess, 'check_output', side_effect=[f'98765 {command}', identity]), \
             patch.object(vc, 'active_workspace', return_value='/tmp/workspace'), \
             patch.object(vc.os, 'kill') as kill:
            count = vc.reap_orphan_recorders()
            return count, kill.called

    def test_live_app_or_tray_recording_is_preserved(self):
        self.assertEqual(self.cleanup(parent=12345), (0, False))

    def test_abandoned_solar_recording_is_stopped(self):
        self.assertEqual(self.cleanup(), (1, True))

    def test_other_user_or_non_solar_path_is_preserved(self):
        self.assertEqual(self.cleanup(uid=os.getuid()+1), (0, False))
        self.assertEqual(self.cleanup(path='/tmp/capture_meeting.wav'), (0, False))
        self.assertEqual(self.cleanup(path='/tmp/other/solar-audio-abcdef.wav'), (0, False))
        self.assertEqual(self.cleanup(executable='/tmp/not-rec'), (0, False))

    def test_unreadable_identity_is_preserved(self):
        with patch.object(vc.subprocess, 'check_output', side_effect=['98765 /usr/bin/rec /tmp/solar-audio-abc.wav', OSError()]), \
             patch.object(vc.os, 'kill') as kill:
            self.assertEqual(vc.reap_orphan_recorders(), 0)
            kill.assert_not_called()
