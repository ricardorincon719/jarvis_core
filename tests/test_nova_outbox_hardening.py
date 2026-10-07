import isolated_env  # noqa: F401  (antes que core: nunca leer el .env real)

import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from nova_event_bus import NovaEventBus


class Response:
    def __init__(self, code=200, body=None):
        self.status_code = code
        self.body = body

    def json(self):
        return self.body


def envelope(event_id):
    return {'event_id': event_id, 'source': 'pearl-core',
            'event_type': 'audit.synthetic', 'occurred_at': '2026-09-14T12:00:00+00:00',
            'payload': {}}


def delivered(event_id):
    return Response(body={'status': 'succeeded', 'output': {'status': 'candidate',
                    'complex_event': {'source_event_id': event_id, 'auto_execute': False}}})


class OutboxHardeningTests(unittest.TestCase):
    def test_pending_is_delivered_on_start_without_publishing_new_event(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'outbox.db'
            bus = NovaEventBus(path, 'http://localhost', start_worker=False)
            bus.publish(envelope('preexisting'))
            bus.close()
            seen = threading.Event()
            def post(url, **kwargs):
                seen.set()
                return delivered(kwargs['json']['event_id'])
            bus = NovaEventBus(path, 'http://localhost', http_post=post, retry_seconds=100)
            try:
                self.assertTrue(seen.wait(timeout=3))
            finally:
                bus.close()
            bus = NovaEventBus(path, 'http://localhost', start_worker=False)
            try:
                self.assertEqual(bus.list_outbox()[0]['status'], 'delivered')
            finally:
                bus.close()

    def test_bad_response_backoff_bounded_attempts_and_discard_do_not_starve_new_events(self):
        now = [100.0]
        with tempfile.TemporaryDirectory() as temporary:
            def post(url, **kwargs):
                return Response(503, {}) if kwargs['json']['event_id'] == 'bad' else delivered(kwargs['json']['event_id'])
            bus = NovaEventBus(Path(temporary) / 'outbox.db', 'http://localhost',
                               http_post=post, start_worker=False, clock=lambda: now[0],
                               max_attempts=2, retry_seconds=1)
            try:
                bus.publish(envelope('bad'))
                bus.publish(envelope('good'))
                self.assertEqual(bus.deliver_pending_once(), 1)
                bad = next(item for item in bus.list_outbox() if item['event_id'] == 'bad')
                self.assertEqual((bad['attempts'], bad['status']), (1, 'pending'))
                self.assertGreater(bad['next_attempt_at'], now[0])
                self.assertEqual(bus.deliver_pending_once(), 0)
                now[0] += 2
                self.assertEqual(bus.deliver_pending_once(), 0)
                self.assertEqual(next(item for item in bus.list_outbox() if item['event_id'] == 'bad')['status'], 'discarded')
                bus.publish(envelope('later'))
                self.assertEqual(bus.deliver_pending_once(), 1)
            finally:
                bus.close()

    def test_200_without_matching_non_executable_candidate_is_not_delivery(self):
        bad_bodies = [None, [], {}, {'status': 'succeeded', 'output': []},
                      {'status': 'succeeded', 'output': {'status': 'candidate',
                       'complex_event': {'source_event_id': 'different', 'auto_execute': False}}},
                      {'status': 'succeeded', 'output': {'status': 'candidate',
                       'complex_event': {'source_event_id': 'test', 'auto_execute': True}}}]
        for body in bad_bodies:
            with self.subTest(body=body), tempfile.TemporaryDirectory() as temporary:
                bus = NovaEventBus(Path(temporary) / 'outbox.db', 'http://localhost',
                                   http_post=lambda *a, **k: Response(body=body), start_worker=False)
                try:
                    bus.publish(envelope('test'))
                    self.assertEqual(bus.deliver_pending_once(), 0)
                    self.assertEqual(bus.list_outbox()[0]['status'], 'pending')
                finally:
                    bus.close()

    def test_terminal_status_discards_immediately_but_409_busy_retries(self):
        for code, error_code, expected in [(400, 'invalid_payload', 'discarded'),
                                           (409, 'idempotency_conflict', 'discarded'),
                                           (409, 'nova_event_busy', 'pending'),
                                           (429, 'rate_limit', 'pending')]:
            with self.subTest(code=code, error=error_code), tempfile.TemporaryDirectory() as temporary:
                bus = NovaEventBus(Path(temporary) / 'outbox.db', 'http://localhost',
                                   http_post=lambda *a, **k: Response(code, {'error': {'code': error_code}}),
                                   start_worker=False)
                try:
                    bus.publish(envelope('test'))
                    bus.deliver_pending_once()
                    self.assertEqual(bus.list_outbox()[0]['status'], expected)
                finally:
                    bus.close()

    def test_old_schema_is_upgraded_additively_and_envelope_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'outbox.db'
            connection = sqlite3.connect(path)
            connection.execute('CREATE TABLE nova_event_outbox(event_id TEXT PRIMARY KEY,envelope_json TEXT NOT NULL,status TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,last_error TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)')
            connection.commit()
            connection.close()
            bus = NovaEventBus(path, 'http://localhost', start_worker=False)
            try:
                bus.publish(envelope('old'))
                self.assertEqual(bus.list_outbox()[0]['next_attempt_at'], 0)
                self.assertEqual(bus._connection.execute('PRAGMA quick_check').fetchone()[0], 'ok')
            finally:
                bus.close()


if __name__ == '__main__':
    unittest.main()
