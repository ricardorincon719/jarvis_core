import isolated_env  # noqa: F401  (antes que core: nunca leer el .env real)

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import os
os.environ.setdefault("JARVIS_SECRET_TOKEN", "test-master-token-0123456789abcdef")
import core
from branches.local_ia.current import plugin as local_ia
from device_sessions import DeviceSessionStore


class Response:
    def __init__(self, body, code=200):
        self.status_code = code
        self.body = body

    def json(self):
        return self.body


class NovaAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = DeviceSessionStore(Path(self.temporary.name) / 'sessions.json', 3600)
        self.token = self.store.issue('synthetic-device', 'synthetic')
        self.session_patch = patch.object(core, 'device_session_store', self.store)
        self.session_patch.start()
        self.client = core.app.test_client()
        self.headers = {'Authorization': 'Bearer ' + self.token}

    def tearDown(self):
        self.session_patch.stop()
        self.temporary.cleanup()

    def test_explicit_memory_decision_is_transport_command_never_sent_to_model(self):
        response = Response({'status': 'succeeded', 'output': {'text': 'Memoria guardada.'}})
        for path in ['/ask', '/ask_stream']:
            with self.subTest(path=path), patch.object(core.requests, 'post', return_value=response) as post, patch.object(core, 'route_query') as route:
                result = self.client.post(path, json={'pregunta': '/confirmar_memoria op-1'}, headers=self.headers)
                self.assertEqual(result.status_code, 200)
                self.assertEqual(result.get_json()['respuesta'], 'Memoria guardada.')
                self.assertEqual(post.call_args.kwargs['json'], {'confirmation': {'operation_id': 'op-1', 'decision': 'approve'}})
                self.assertEqual(post.call_args.kwargs['headers'], self.headers)
                route.assert_not_called()

    def test_reject_and_pending_are_session_authenticated(self):
        with patch.object(core.requests, 'post', return_value=Response({'status': 'rejected', 'output': {'text': 'No guardada.'}})) as post:
            result = self.client.post('/ask', json={'pregunta': '/rechazar_memoria op-1'}, headers=self.headers)
            self.assertEqual(result.status_code, 200)
            self.assertEqual(post.call_args.kwargs['json']['confirmation']['decision'], 'reject')
        response = Response({'status': 'ok', 'pending': [{'operation_id': 'op-1', 'summary': 'Dato sintetico'}]})
        with patch.object(core.requests, 'post', return_value=response) as post:
            result = self.client.post('/ask', json={'pregunta': '/memorias_pendientes'}, headers=self.headers)
            self.assertEqual(result.status_code, 200)
            self.assertIn('/confirmar_memoria op-1', result.get_json()['respuesta'])
            self.assertEqual(post.call_args.kwargs['json'], {'pending': True})

    def test_master_or_revoked_session_cannot_decide(self):
        self.store.revoke(self.token)
        for headers in [self.headers, {'Authorization': 'Bearer ' + core.SECRET_TOKEN}]:
            with self.subTest(master=headers != self.headers), patch.object(core.requests, 'post') as post:
                result = self.client.post('/ask', json={'pregunta': '/confirmar_memoria op-1'}, headers=headers)
                self.assertEqual(result.status_code, 403)
                post.assert_not_called()

    def test_startup_initializes_existing_outbox_worker(self):
        with patch.object(core, 'load_plugins') as load, patch.object(core, 'get_nova_event_bus') as bus, patch.object(core.atexit, 'register') as register:
            core.start_runtime()
            load.assert_called_once()
            bus.assert_called_once()
            register.assert_called_once_with(bus.return_value.close)

    def test_startup_observer_failure_does_not_stop_pearl(self):
        with patch.object(core, 'load_plugins'), patch.object(core, 'get_nova_event_bus', side_effect=RuntimeError('synthetic')):
            core.start_runtime()

    def test_local_ia_forwards_validated_device_and_shows_public_proposal(self):
        result = {'status': 'succeeded', 'route': {'assistant': 'nova', 'action': 'chat'},
                  'output': {'text': 'Respuesta sintetica', 'integrations': {
                      'jinnex_memory_write': {'request_id': 'op-1', 'status': 'confirmation_required',
                                              'summary': 'Guardar dato', 'confirmation_token': 'must-not-leak'}}}}
        with core.app.test_request_context('/ask', headers=self.headers):
            core.app.preprocess_request()
            with patch.object(local_ia, 'NOVA_BRIDGE_ENABLED', True), patch.object(local_ia.requests, 'post', return_value=Response(result)) as post:
                body = local_ia.handle('Guarda en Jinnex que dato')
            self.assertEqual(post.call_args.kwargs['headers'], self.headers)
            self.assertNotIn('session_id', post.call_args.kwargs['json'])
            self.assertIn('/confirmar_memoria op-1', body['respuesta'])
            self.assertNotIn('must-not-leak', json.dumps(body))
            self.assertEqual(body['memory_proposal']['operation_id'], 'op-1')
            with patch.object(local_ia, 'NOVA_BRIDGE_ENABLED', True), patch.object(
                local_ia.requests, 'post', return_value=Response(result)
            ):
                events = [json.loads(event) for event in local_ia.handle_stream('Dato')]
            self.assertEqual(events[-1]['memory_proposal'], body['memory_proposal'])
            self.assertNotIn('must-not-leak', json.dumps(events))


if __name__ == '__main__':
    unittest.main()
