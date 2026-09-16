import io

import pytest
from PIL import Image

from relay.app import create_app


@pytest.fixture
def relay():
    now = [100.0]
    def verify(token):
        if token == 'owner-token':
            return {'sub': 'owner'}
        if token == 'other-token':
            return {'sub': 'other'}
        raise ValueError()
    app = create_app({'TESTING': True, 'OWNER_UID': 'owner', 'AGENT_SECRET': 'device-secret',
        'POLL_SECONDS': 0, 'ALLOWED_ORIGINS': ['https://sidecarpic.web.app']}, verify, lambda: now[0])
    return app.test_client(), now, app


OWNER = {'Authorization': 'Bearer owner-token'}
AGENT = {'Authorization': 'Bearer device-secret'}


def queued(client):
    assert client.get('/api/agent/poll', headers=AGENT).status_code == 204
    response = client.post('/api/captures', headers=OWNER)
    assert response.status_code == 202
    return response.json['id']


def jpeg():
    data = io.BytesIO()
    Image.new('RGB', (80, 60), '#2455e8').save(data, 'JPEG')
    return data.getvalue()


def test_authentication_and_owner_isolation(relay):
    client, _, _ = relay
    assert client.get('/api/status').status_code == 401
    assert client.get('/api/status', headers={'Authorization': 'Bearer other-token'}).status_code == 403
    assert client.get('/api/agent/poll', headers=OWNER).status_code == 401
    assert client.get('/api/status', headers=AGENT).status_code == 401
    assert client.get('/api/agent/poll', headers={'Authorization': 'Bearer \u00e9'}).status_code == 401
    assert client.get('/api/agent/health', headers=AGENT).status_code == 200
    assert client.get('/api/status', headers=OWNER).json['connected'] is False


def test_complete_capture_consumes_image(relay):
    client, _, app = relay
    identifier = queued(client)
    assert client.get('/api/agent/poll', headers=AGENT).json['id'] == identifier
    assert client.get('/api/agent/poll', headers=AGENT).status_code == 204
    assert client.post('/api/agent/captures/' + identifier, headers=AGENT,
        data=jpeg(), content_type='image/jpeg').status_code == 204
    assert client.get('/api/captures/' + identifier, headers=OWNER).json['status'] == 'ready'
    response = client.get('/api/captures/' + identifier + '/image', headers=OWNER)
    assert response.data == jpeg()
    assert response.headers['Cache-Control'] == 'no-store, private'
    assert app.extensions['sidecar_state']['job'] is None
    assert client.get('/api/captures/' + identifier + '/image', headers=OWNER).status_code == 404


def test_offline_busy_and_expiry(relay):
    client, now, _ = relay
    assert client.post('/api/captures', headers=OWNER).status_code == 409
    identifier = queued(client)
    assert client.post('/api/captures', headers=OWNER).status_code == 409
    now[0] += 91
    assert client.get('/api/captures/' + identifier, headers=OWNER).status_code == 404
    assert client.get('/api/status', headers=OWNER).json['connected'] is False


def test_reject_invalid_image_and_late_upload(relay):
    client, _, _ = relay
    identifier = queued(client)
    endpoint = '/api/agent/captures/' + identifier
    assert client.post(endpoint, headers=AGENT, data=jpeg(), content_type='image/jpeg').status_code == 409
    client.get('/api/agent/poll', headers=AGENT)
    assert client.post(endpoint, headers=AGENT, data=b'not a jpeg', content_type='image/jpeg').status_code == 400
    assert client.post(endpoint, headers=AGENT, data=b'<svg/>', content_type='image/svg+xml').status_code == 415
    assert client.delete('/api/captures/' + identifier, headers=OWNER).status_code == 204
    assert client.post(endpoint, headers=AGENT, data=jpeg(), content_type='image/jpeg').status_code == 404


def test_permission_error_and_cors(relay):
    client, _, _ = relay
    identifier = queued(client)
    client.get('/api/agent/poll', headers=AGENT)
    assert client.post('/api/agent/captures/' + identifier, headers=AGENT,
        json={'error': 'permission'}).status_code == 204
    assert client.get('/api/captures/' + identifier, headers=OWNER).json['error'] == 'permission'
    bad = client.get('/api/status', headers={**OWNER, 'Origin': 'https://evil.example'})
    assert bad.status_code == 403
    assert 'Access-Control-Allow-Origin' not in bad.headers
    good = client.options('/api/status', headers={'Origin': 'https://sidecarpic.web.app'})
    assert good.status_code == 204
    assert good.headers['Access-Control-Allow-Origin'] == 'https://sidecarpic.web.app'


def test_ready_image_expires(relay):
    client, now, app = relay
    identifier = queued(client)
    client.get('/api/agent/poll', headers=AGENT)
    client.post('/api/agent/captures/' + identifier, headers=AGENT, data=jpeg(), content_type='image/jpeg')
    now[0] += 121
    assert client.get('/api/captures/' + identifier + '/image', headers=OWNER).status_code == 404
    assert app.extensions['sidecar_state']['job'] is None


def test_oversized_upload(relay):
    client, _, app = relay
    app.config['MAX_CONTENT_LENGTH'] = 16
    identifier = queued(client)
    client.get('/api/agent/poll', headers=AGENT)
    assert client.post('/api/agent/captures/' + identifier, headers=AGENT,
        data=jpeg(), content_type='image/jpeg').status_code == 413
