"""Optional deployment security smoke tests; install server dependencies."""
import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

AVAILABLE=all(importlib.util.find_spec(m) for m in ('starlette','argon2','httpx'))
if AVAILABLE:
    from starlette.testclient import TestClient
    from apps.api.hosted import create_app
    from packages.runtime.config import Settings
    from packages.runtime.auth import AuthStore,AccessError

@unittest.skipUnless(AVAILABLE,'Install requirements-server.txt for deployment tests')
class HostedTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory(); p=Path(self.temp.name)
        self.settings=Settings('https://testserver',p/'research.sqlite3',p/'auth.sqlite3',p/'jobs.sqlite3')
        self.auth=AuthStore(self.settings.auth_database)
        self.auth.add_user('reader','synthetic-password-123','viewer')
        self.client=TestClient(create_app(self.settings),base_url='https://testserver')
    def tearDown(self): self.client.close();self.temp.cleanup()
    def login(self):
        r=self.client.post('/auth/login',json={'username':'reader','password':'synthetic-password-123'},headers={'Origin':'https://testserver'})
        self.assertEqual(r.status_code,200)
        return self.client.get('/auth/me').json()['csrf']
    def test_anonymous_denied(self): self.assertEqual(self.client.get('/api/research').status_code,401)
    def test_host_rejected(self): self.assertEqual(self.client.get('/api/research',headers={'Host':'evil.test'}).status_code,400)
    def test_login_cookie_and_revocation(self):
        self.login(); self.assertEqual(self.client.get('/api/research').status_code,200)
        self.auth.change_user('reader',active=False)
        self.assertEqual(self.client.get('/api/research').status_code,401)
    def test_viewer_cannot_write_even_with_csrf(self):
        token=self.login()
        r=self.client.post('/api/research',json={'title':'x','brief':{}},headers={'Origin':'https://testserver','X-CSRF-Token':token})
        self.assertEqual(r.status_code,403)
    def test_csrf_required(self):
        self.login();self.assertEqual(self.client.post('/auth/logout',json={},headers={'Origin':'https://testserver'}).status_code,403)
    def test_wrong_origin_rejected(self):
        self.assertEqual(self.client.post('/auth/login',json={},headers={'Origin':'https://evil.test'}).status_code,403)

if __name__=='__main__':unittest.main()
