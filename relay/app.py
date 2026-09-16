"""Single-owner, single-worker ephemeral screenshot relay."""

import hmac
import io
import os
import secrets
import threading
import time
from functools import wraps

from flask import Flask, Response, abort, jsonify, request
from google.auth.transport.requests import Request
from google.oauth2.id_token import verify_firebase_token
from PIL import Image, UnidentifiedImageError
from werkzeug.exceptions import HTTPException


def create_app(config=None, verify_token=None, clock=time.monotonic):
    app = Flask(__name__)
    app.config.update(
        FIREBASE_PROJECT_ID=os.getenv('FIREBASE_PROJECT_ID', 'sidecarpic'),
        OWNER_UID=os.getenv('OWNER_UID', ''),
        AGENT_SECRET=os.getenv('AGENT_SECRET', ''),
        ALLOWED_ORIGINS=os.getenv('ALLOWED_ORIGINS', 'https://sidecarpic.web.app,https://sidecarpic.firebaseapp.com').split(','),
        MAX_CONTENT_LENGTH=12 * 1024 * 1024,
        CAPTURE_TTL=90,
        IMAGE_TTL=120,
        POLL_SECONDS=20,
    )
    if config:
        app.config.update(config)
    condition = threading.Condition()
    state = {'last_seen': None, 'job': None}
    app.extensions['sidecar_state'] = state

    def prune():
        job = state['job']
        if job and clock() >= job['expires']:
            state['job'] = None

    def online():
        return state['last_seen'] is not None and clock() - state['last_seen'] < 45

    def verify(token):
        claims = verify_firebase_token(token, Request(), audience=app.config['FIREBASE_PROJECT_ID'])
        if claims.get('iss') != 'https://securetoken.google.com/' + app.config['FIREBASE_PROJECT_ID']:
            raise ValueError('Invalid issuer')
        return claims

    def protected(agent=False):
        def decorate(fn):
            @wraps(fn)
            def wrapped(*args, **kwargs):
                token = request.headers.get('Authorization', '').removeprefix('Bearer ')
                if agent:
                    secret = app.config['AGENT_SECRET']
                    if not secret or not hmac.compare_digest(token.encode(), secret.encode()):
                        abort(401, 'Device authentication failed.')
                else:
                    if not app.config['OWNER_UID']:
                        abort(503, 'The relay owner has not been configured.')
                    try:
                        claims = (verify_token or verify)(token)
                    except Exception:
                        abort(401, 'Please sign in again.')
                    if claims.get('sub') != app.config['OWNER_UID']:
                        abort(403, 'This account is not paired with this laptop.')
                return fn(*args, **kwargs)
            return wrapped
        return decorate

    @app.before_request
    def check_origin():
        origin = request.headers.get('Origin')
        if origin and origin not in app.config['ALLOWED_ORIGINS']:
            abort(403, 'Origin not allowed.')
        if request.method == 'OPTIONS':
            return Response(status=204)

    @app.after_request
    def headers(response):
        response.headers['Cache-Control'] = 'no-store, private'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        origin = request.headers.get('Origin')
        if origin in app.config['ALLOWED_ORIGINS']:
            response.headers['Access-Control-Allow-Origin'] = origin
            response.headers['Vary'] = 'Origin'
            response.headers['Access-Control-Allow-Headers'] = 'Authorization, Content-Type'
            response.headers['Access-Control-Allow-Methods'] = 'GET, POST, DELETE, OPTIONS'
        return response

    @app.errorhandler(HTTPException)
    def http_error(error):
        return jsonify(error=error.description), error.code

    @app.get('/health')
    def health():
        return jsonify(status='ok')

    @app.get('/api/status')
    @protected()
    def status():
        with condition:
            prune()
            return jsonify(connected=online(), device='Ubuntu laptop')

    @app.post('/api/captures')
    @protected()
    def capture():
        with condition:
            prune()
            if not online():
                abort(409, 'Your laptop is offline.')
            if state['job'] and state['job']['status'] in ('queued', 'capturing'):
                abort(409, 'A capture is already in progress.')
            job = {'id': secrets.token_urlsafe(24), 'status': 'queued',
                   'expires': clock() + app.config['CAPTURE_TTL']}
            state['job'] = job
            condition.notify_all()
            return jsonify(id=job['id']), 202

    def get_job(job_id):
        prune()
        job = state['job']
        if not job or job['id'] != job_id:
            abort(404, 'This capture has expired.')
        return job

    @app.get('/api/captures/<job_id>')
    @protected()
    def capture_status(job_id):
        with condition:
            job = get_job(job_id)
            return jsonify(status=job['status'], error=job.get('error'))

    @app.get('/api/captures/<job_id>/image')
    @protected()
    def image(job_id):
        with condition:
            job = get_job(job_id)
            if job['status'] != 'ready':
                abort(409, 'The image is not ready.')
            data = job.pop('image')
            state['job'] = None
            return Response(data, mimetype='image/jpeg')

    @app.delete('/api/captures/<job_id>')
    @protected()
    def discard(job_id):
        with condition:
            get_job(job_id)
            state['job'] = None
        return Response(status=204)

    @app.get('/api/agent/health')
    @protected(agent=True)
    def agent_health():
        return jsonify(status='ok')

    @app.get('/api/agent/poll')
    @protected(agent=True)
    def poll():
        deadline = clock() + app.config['POLL_SECONDS']
        with condition:
            while True:
                state['last_seen'] = clock()
                prune()
                job = state['job']
                if job and job['status'] == 'queued':
                    job['status'] = 'capturing'
                    return jsonify(id=job['id'])
                remaining = deadline - clock()
                if remaining <= 0:
                    return Response(status=204)
                condition.wait(min(remaining, 5))

    @app.post('/api/agent/captures/<job_id>')
    @protected(agent=True)
    def upload(job_id):
        with condition:
            job = get_job(job_id)
            if job['status'] != 'capturing':
                abort(409, 'Capture is not awaiting an image.')
        if request.is_json:
            payload = request.get_json()
            if not isinstance(payload, dict) or payload.get('error') not in ('permission', 'capture_failed'):
                abort(400, 'Invalid capture error.')
            with condition:
                job = get_job(job_id)
                job.update(status='failed', error=payload['error'])
            return Response(status=204)
        if request.mimetype != 'image/jpeg':
            abort(415, 'A JPEG image is required.')
        data = request.get_data()
        try:
            with Image.open(io.BytesIO(data)) as screenshot:
                if screenshot.format != 'JPEG' or screenshot.width * screenshot.height > 40_000_000:
                    raise ValueError()
                screenshot.verify()
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
            abort(400, 'Invalid screenshot.')
        with condition:
            job = get_job(job_id)
            job.update(status='ready', image=data, expires=clock() + app.config['IMAGE_TTL'])
        return Response(status=204)

    # Expire images even when no client makes another request.
    if not app.config.get('TESTING'):
        def reaper():
            while True:
                time.sleep(5)
                with condition:
                    prune()
        threading.Thread(target=reaper, daemon=True).start()
    return app


app = create_app()
