"""Thin authenticated FastAPI routes; registered on the existing protected app."""
import logging
import secrets
from urllib.parse import parse_qs, urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from services.integrations import john_deere as jd

log = logging.getLogger(__name__)


class CallbackPrivacyMiddleware:
    """Remove callback query from ASGI scope before access logging (including 401s).

    Only this router reads the private original query. Never log the private field.
    Also prevent callback referrers and caching on every integration response.
    """
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        protected = scope.get('path', '').startswith(('/integrations/john-deere', '/api/john-deere')) or scope.get('path') == '/callback'
        if scope.get('type') == 'http' and scope.get('path') == '/callback':
            scope['deere_callback_query'] = scope.get('query_string', b'')
            scope['query_string'] = b''
        async def private_send(message):
            if protected and message['type'] == 'http.response.start':
                message.setdefault('headers', []).extend([
                    (b'cache-control', b'no-store'), (b'referrer-policy', b'no-referrer')])
            await send(message)
        await self.app(scope, receive, private_send)


def router(verify_credentials):
    routes = APIRouter()

    def client(account):
        try:
            return jd.Client(account)
        except jd.DeereError as exc:
            raise HTTPException(503, str(exc)) from None

    def csrf(request, account, form_token=None):
        session = jd.browser_session(request.cookies.get(jd.COOKIE), account)
        supplied = form_token or request.headers.get('x-csrf-token', '')
        origin = request.headers.get('origin')
        if (not session or not supplied or not secrets.compare_digest(session['csrf_token'], supplied)
                or (origin and origin != str(request.base_url).rstrip('/'))):
            raise HTTPException(403, 'Invalid John Deere CSRF session. Reload Integrations.')

    @routes.get('/api/john-deere/status')
    def status(request: Request, account: str = Depends(verify_credentials)):
        cookie = request.cookies.get(jd.COOKIE)
        session = jd.browser_session(cookie, account)
        if session:
            token = session['csrf_token']
        else:
            cookie, token = jd.new_session(account)
        try:
            service = client(account)
            data = service.public_status()
            from services.integrations.john_deere_diagnostics import Diagnostics
            data['phase2a'] = Diagnostics(service).status()
            from services.integrations.john_deere_sync import Sync
            data['phase2b'] = Sync(account).status()
            data['configured'] = True
        except HTTPException as exc:
            data = dict(configured=False, environment='Sandbox', oauth='Not connected',
                        error=exc.detail, organizations_list=[])
        data['csrf_token'] = token  # Browser CSRF value only, never an OAuth credential.
        response = JSONResponse(data)
        response.set_cookie(jd.COOKIE, cookie, max_age=3600, httponly=True,
                            secure=request.url.scheme == 'https', samesite='lax', path='/')
        return response

    @routes.post('/integrations/john-deere/connect')
    async def connect(request: Request, account: str = Depends(verify_credentials)):
        body = await request.body()
        form_token = parse_qs(body.decode('utf-8', errors='replace')).get('csrf_token', [''])[0]
        csrf(request, account, form_token)
        service = client(account)
        if urlsplit(str(request.base_url)).netloc != urlsplit(service.config.redirect_uri).netloc:
            raise HTTPException(400, 'Open Forest AI at the configured callback host and port before connecting.')
        state = jd.begin_oauth(request.cookies[jd.COOKIE], account)
        # Returned only as redirect navigation, no frontend token processing.
        return RedirectResponse(jd.authorization_url(service.config, state), status_code=303)

    @routes.get('/callback')
    def callback(request: Request, account: str = Depends(verify_credentials)):
        params = parse_qs(request.scope.get('deere_callback_query', b'').decode('utf-8', errors='replace'))
        state = params.get('state', [''])[0]
        if not jd.consume_state(request.cookies.get(jd.COOKIE), account, state):
            log.warning('John Deere callback rejected: invalid or expired state')
            raise HTTPException(400, 'Invalid or expired OAuth state. Reconnect from Integrations.')
        if params.get('error') or not params.get('code'):
            log.warning('John Deere authorization was not completed')
            return RedirectResponse('/?john_deere=authorization_failed#integrations', status_code=303)
        service = client(account)
        try:
            service.exchange(params['code'][0])
        except jd.DeereError:
            log.warning('John Deere token exchange failed')
            return RedirectResponse('/?john_deere=token_failed#integrations', status_code=303)
        try:
            service.organizations()
        except jd.DeereError:
            pass  # OAuth succeeded; sanitized diagnostics offer Refresh on the dashboard.
        return RedirectResponse('/#integrations', status_code=303)

    @routes.post('/api/john-deere/refresh')
    def refresh(request: Request, account: str = Depends(verify_credentials)):
        csrf(request, account)
        service = client(account)
        try:
            service.organizations()
        except jd.DeereError as exc:
            raise HTTPException(502, str(exc)) from None
        return service.public_status()

    @routes.post('/api/john-deere/test')
    def test_apis(request: Request, account: str = Depends(verify_credentials)):
        csrf(request, account)
        from services.integrations.john_deere_diagnostics import Diagnostics
        return Diagnostics(client(account)).run()

    @routes.post('/api/john-deere/sync/{kind}')
    def sync_data(kind: str, request: Request, account: str = Depends(verify_credentials)):
        csrf(request, account)
        from services.integrations.john_deere_sync import Sync, KINDS
        if kind not in KINDS:
            raise HTTPException(400, 'Unknown Deere sync type.')
        return Sync(account).run(kind)

    @routes.post('/api/john-deere/machines/{equipment_id}/sector')
    async def map_sector(equipment_id: int, request: Request, account: str = Depends(verify_credentials)):
        csrf(request, account)
        from services.integrations.john_deere_sync import assign_sector
        try:
            body = await request.json()
            sector = body.get('sector')
            if not isinstance(sector, str):
                raise HTTPException(400, 'A sector name or empty string is required.')
            assign_sector(account, equipment_id, sector)
        except jd.DeereError as exc:
            raise HTTPException(400, str(exc)) from None
        except ValueError:
            raise HTTPException(400, 'Invalid JSON body.') from None
        return {'status': 'OK'}

    @routes.get('/integrations/john-deere/organizations/authorize')
    def authorize(account: str = Depends(verify_credentials)):
        return connection_redirect(account, 'connections')

    @routes.get('/integrations/john-deere/organizations/manage')
    def manage(account: str = Depends(verify_credentials)):
        return connection_redirect(account, 'manage_connection')

    def connection_redirect(account, relation):
        try:
            return RedirectResponse(client(account).connection_url(relation), status_code=303)
        except jd.DeereError as exc:
            raise HTTPException(400, str(exc)) from None

    return routes
