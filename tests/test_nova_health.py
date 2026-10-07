"""Core consume readiness verificada y resume la cola sin datos privados."""

import isolated_env  # noqa: F401  (antes que core: nunca leer el .env real)

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import os
os.environ.setdefault("JARVIS_SECRET_TOKEN", "test-master-token-0123456789abcdef")
import core
from nova_event_bus import NovaEventBus


class Response:
    status_code=200
    def __init__(self,payload):
        self.payload=payload
    def json(self):
        return self.payload


class NovaHealthTests(unittest.TestCase):
    def check(self,payload):
        with patch.object(core,'NOVA_ENABLED',True), patch.dict(core.plugins,{'local_ia':{}}), patch.object(core.requests,'get',return_value=Response(payload)):
            return core.check_local_ai_status()

    def test_legacy_connected_marker_does_not_prove_readiness(self):
        body=self.check({'status':'ok','nova':'connected'})
        self.assertFalse(body['connected'])
        self.assertFalse(body['model_loaded'])
        self.assertEqual(body['error'],'nova_not_ready')

    def test_semantic_failure_remains_visible_while_chat_is_ready(self):
        body=self.check({'status':'degraded','liveness':True,
                         'readiness':{'ready':True,'status':'degraded'},
                         'dependencies':{'qdrant':{'state':'unavailable','reason':'http_503'}},
                         'checked_at':'2026-09-14T12:00:00+00:00'})
        self.assertTrue(body['connected'])
        self.assertFalse(body['model_loaded'])
        self.assertEqual(body['status'],'degraded')
        self.assertEqual(body['dependencies']['qdrant']['reason'],'http_503')

    def test_alive_without_ready_and_malformed_health_do_not_claim_availability(self):
        for payload in [None,[],{'liveness':True,'readiness':{'ready':False}},
                        {'liveness':True,'readiness':None}]:
            with self.subTest(payload=payload):
                self.assertFalse(self.check(payload)['connected'])

    def test_network_exception_does_not_expose_url_or_credentials(self):
        with patch.object(core,'NOVA_ENABLED',True), patch.dict(core.plugins,{'local_ia':{}}), patch.object(core.requests,'get',side_effect=RuntimeError('PRIVATE_SECRET')):
            body=core.check_local_ai_status()
        self.assertNotIn('PRIVATE_SECRET',json.dumps(body))
        self.assertEqual(body['error'],'nova_health_unavailable')

    def test_outbox_age_attempts_and_discard_are_visible_without_envelopes(self):
        with tempfile.TemporaryDirectory() as directory:
            bus=NovaEventBus(Path(directory)/'outbox.db','http://localhost',start_worker=False)
            try:
                event={'event_id':'PRIVATE_EVENT','source':'pearl-core','event_type':'synthetic',
                       'occurred_at':datetime.now(timezone.utc).isoformat(),
                       'payload':{'text':'PRIVATE_PROMPT'}}
                bus.publish(event)
                old=(datetime.now(timezone.utc)-timedelta(seconds=400)).isoformat()
                with bus._connection:
                    bus._connection.execute('UPDATE nova_event_outbox SET created_at=?,attempts=2',(old,))
                body=bus.health_summary()
                self.assertGreaterEqual(body['oldest_pending_age_seconds'],399)
                self.assertTrue(body['degraded'])
                self.assertEqual(body['max_pending_attempts'],2)
                self.assertIsNotNone(body['last_attempt_at'])
                self.assertNotIn('PRIVATE_',json.dumps(body))
                with patch.object(core,'NOVA_ENABLED',True),patch.dict(core.app.config,{'NOVA_EVENT_BUS':bus}):
                    self.assertEqual(core.nova_outbox_health()['counts']['pending'],1)
            finally:
                bus.close()

    def test_outbox_not_initialized_or_closed_is_reported_as_degraded(self):
        with patch.object(core,'NOVA_ENABLED',True),patch.object(core,'_nova_event_bus',None),patch.dict(core.app.config,{'NOVA_EVENT_BUS':None}):
            self.assertEqual(core.nova_outbox_health()['error'],'outbox_not_initialized')


if __name__=='__main__':
    unittest.main()
