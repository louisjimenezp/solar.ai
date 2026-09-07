"""Unit contracts for the bounded local voice conductor."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

CORE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(CORE / 'skills/solar-app/scripts'))
import voice_conductor


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, _limit):
        return self.payload


class VoiceConductorTests(unittest.TestCase):
    def test_catalogue_is_compact_and_does_not_read_skills(self):
        entries = voice_conductor.catalogue('/a/root/that/does/not/exist')
        self.assertEqual(entries, list(voice_conductor.CAPABILITIES))
        self.assertLessEqual(len(entries), 4)

    def test_request_uses_bounded_schema_and_token_budget(self):
        reply = {'action': 'dispatch', 'title': 'Informe', 'thread_id': None, 'reply': 'Me pongo.'}
        observed = {}

        def open_request(request, timeout):
            observed['body'] = json.loads(request.data)
            observed['timeout'] = timeout
            return _Response(json.dumps({'message': {'content': json.dumps(reply)}}).encode())

        with patch('urllib.request.urlopen', open_request):
            result = voice_conductor.decide('Prepara un informe', [], '/unused', model='test-light')

        self.assertEqual(result, reply)
        self.assertEqual(observed['timeout'], 4)
        self.assertEqual(observed['body']['options']['num_predict'], 96)
        self.assertEqual(observed['body']['format'], voice_conductor.JSON_SCHEMA)
        self.assertEqual(observed['body']['messages'][1]['content'], json.dumps({
            'utterance': 'Prepara un informe', 'threads': [],
            'capabilities': list(voice_conductor.CAPABILITIES),
        }, ensure_ascii=False))

    def test_unknown_thread_remains_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Unknown thread'):
            voice_conductor.validate(
                {'action': 'dispatch', 'title': 'Informe', 'thread_id': 'invented', 'reply': 'Me pongo.'},
                set(),
            )


if __name__ == '__main__':
    unittest.main()
