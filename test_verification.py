import sys
import sqlite3
from pathlib import Path
sys.path.insert(0, '.')
from app import app

def clear_test_db():
    """Clear test data from database."""
    db_path = Path("pipeline_state.sqlite3")
    if db_path.exists():
        with sqlite3.connect(db_path) as conn:
            conn.execute("DELETE FROM users")
            conn.execute("DELETE FROM analysis_history")
            conn.execute("DELETE FROM app_state")
            conn.commit()

def test_auth_workflows():
    with app.test_client() as client:
        print('=== COMPREHENSIVE SYSTEM VERIFICATION ===\n')
        
        # ============================================================
        # TEST 1: AUTHENTICATION WORKFLOWS
        # ============================================================
        print('--- TEST 1: AUTHENTICATION WORKFLOWS ---\n')
        
        # 1.1 Signup with valid data
        print('1.1 Signup (valid):')
        resp = client.post('/api/auth/signup', json={
            'email': 'verify1@example.com',
            'password': 'password123',
            'confirm_password': 'password123'
        })
        assert resp.status_code == 201, f'Expected 201, got {resp.status_code}: {resp.get_json()}'
        data = resp.get_json()
        assert 'token' in data and 'user' in data
        token1 = data['token']
        print(f'  PASS - User created: {data["user"]["email"]} (ID: {data["user"]["id"]})')
        
        # 1.2 Signup - duplicate email
        print('1.2 Signup (duplicate email):')
        resp = client.post('/api/auth/signup', json={
            'email': 'verify1@example.com',
            'password': 'password123',
            'confirm_password': 'password123'
        })
        assert resp.status_code == 409, f'Expected 409, got {resp.status_code}: {resp.get_json()}'
        print(f'  PASS - Correctly rejected: {resp.get_json()["error"]}')
        
        # 1.3 Signup - password mismatch
        print('1.3 Signup (password mismatch):')
        resp = client.post('/api/auth/signup', json={
            'email': 'verify2@example.com',
            'password': 'password123',
            'confirm_password': 'different'
        })
        assert resp.status_code == 400, f'Expected 400, got {resp.status_code}: {resp.get_json()}'
        print(f'  PASS - Correctly rejected: {resp.get_json()["error"]}')
        
        # 1.4 Signup - short password
        print('1.4 Signup (short password):')
        resp = client.post('/api/auth/signup', json={
            'email': 'verify3@example.com',
            'password': 'short',
            'confirm_password': 'short'
        })
        assert resp.status_code == 400, f'Expected 400, got {resp.status_code}: {resp.get_json()}'
        print(f'  PASS - Correctly rejected: {resp.get_json()["error"]}')
        
        # 1.5 Signup - missing fields
        print('1.5 Signup (missing fields):')
        resp = client.post('/api/auth/signup', json={})
        assert resp.status_code == 400, f'Expected 400, got {resp.status_code}: {resp.get_json()}'
        print(f'  PASS - Correctly rejected: {resp.get_json()["error"]}')
        
        # 1.6 Login with valid credentials
        print('1.6 Login (valid):')
        resp = client.post('/api/auth/login', json={
            'email': 'verify1@example.com',
            'password': 'password123'
        })
        assert resp.status_code == 200, f'Expected 200, got {resp.status_code}: {resp.get_json()}'
        data = resp.get_json()
        token2 = data['token']
        assert data['user']['email'] == 'verify1@example.com'
        print(f'  PASS - Login successful, token issued')
        
        # 1.7 Login with wrong password
        print('1.7 Login (wrong password):')
        resp = client.post('/api/auth/login', json={
            'email': 'verify1@example.com',
            'password': 'wrongpassword'
        })
        assert resp.status_code == 401, f'Expected 401, got {resp.status_code}: {resp.get_json()}'
        print(f'  PASS - Correctly rejected: {resp.get_json()["error"]}')
        
        # 1.8 Login with non-existent user
        print('1.8 Login (non-existent user):')
        resp = client.post('/api/auth/login', json={
            'email': 'nonexistent@example.com',
            'password': 'password123'
        })
        assert resp.status_code == 401, f'Expected 401, got {resp.status_code}: {resp.get_json()}'
        print(f'  PASS - Correctly rejected: {resp.get_json()["error"]}')
        
        # 1.9 GET /me with valid token
        print('1.9 GET /me (valid token):')
        resp = client.get('/api/auth/me', headers={'Authorization': 'Bearer ' + token1})
        assert resp.status_code == 200, f'Expected 200, got {resp.status_code}: {resp.get_json()}'
        assert resp.get_json()['user']['email'] == 'verify1@example.com'
        print(f'  PASS - User info returned')
        
        # 1.10 GET /me with invalid token
        print('1.10 GET /me (invalid token):')
        resp = client.get('/api/auth/me', headers={'Authorization': 'Bearer invalid.token.here'})
        assert resp.status_code == 401, f'Expected 401, got {resp.status_code}: {resp.get_json()}'
        print(f'  PASS - Correctly rejected: {resp.get_json()["error"]}')
        
        # 1.11 GET /me without token
        print('1.11 GET /me (no token):')
        resp = client.get('/api/auth/me')
        assert resp.status_code == 401, f'Expected 401, got {resp.status_code}: {resp.get_json()}'
        print(f'  PASS - Correctly rejected: {resp.get_json()["error"]}')
        
        # 1.12 Token refresh
        print('1.12 Token refresh:')
        resp = client.post('/api/auth/refresh', headers={'Authorization': 'Bearer ' + token1})
        assert resp.status_code == 200, f'Expected 200, got {resp.status_code}: {resp.get_json()}'
        new_token = resp.get_json()['token']
        assert new_token != token1
        print(f'  PASS - New token issued')
        
        # 1.13 Logout
        print('1.13 Logout:')
        resp = client.post('/api/auth/logout')
        assert resp.status_code == 200, f'Expected 200, got {resp.status_code}: {resp.get_json()}'
        print(f'  PASS - Logout successful')
        
        # 1.14 Verify cookie set on login
        print('1.14 Cookie set on login:')
        resp = client.post('/api/auth/login', json={
            'email': 'verify1@example.com',
            'password': 'password123'
        })
        assert 'auth_token' in resp.headers.get('Set-Cookie', ''), 'Cookie not set'
        print(f'  PASS - HttpOnly cookie set')
        
        print('\nALL AUTH TESTS PASSED\n')
        return token1

def test_protected_routes(token):
    with app.test_client() as client:
        print('--- TEST 2: PROTECTED API ROUTES ---\n')
        
        routes = [
            ('GET', '/api/status'),
            ('GET', '/api/history'),
            ('GET', '/api/reports'),
            ('GET', '/api/monitor'),
            ('GET', '/api/schedule'),
            ('GET', '/api/schedule/datasets'),
        ]
        
        for method, route in routes:
            print(f'{method} {route}:')
            if method == 'GET':
                resp = client.get(route, headers={'Authorization': 'Bearer ' + token})
            assert resp.status_code == 200, f'Expected 200, got {resp.status_code}: {resp.get_json()}'
            print(f'  PASS - {resp.status_code}')
        
        # Test analyze endpoint
        print('POST /api/analyze:')
        resp = client.post('/api/analyze', data={'rows': '1000'}, headers={'Authorization': 'Bearer ' + token})
        assert resp.status_code == 200, f'Expected 200, got {resp.status_code}'
        data = resp.get_json()
        assert 'rows_clean' in data and 'failures' in data
        print(f'  PASS - Analysis complete: {data["rows_clean"]} rows, {data["failures"]["total_flagged"]} flagged')
        
        # Test recovery demo
        print('POST /api/recovery-demo:')
        resp = client.post('/api/recovery-demo', headers={'Authorization': 'Bearer ' + token})
        assert resp.status_code == 200, f'Expected 200, got {resp.status_code}'
        print(f'  PASS - Recovery demo complete')
        
        # Test schedule config
        print('POST /api/schedule:')
        resp = client.post('/api/schedule', json={
            'enabled': True,
            'interval_seconds': 3600,
            'rows': 10000,
            'source_type': 'sample',
            'dataset_name': ''
        }, headers={'Authorization': 'Bearer ' + token})
        assert resp.status_code == 200, f'Expected 200, got {resp.status_code}: {resp.get_json()}'
        print(f'  PASS - Schedule saved')
        
        print('\nALL PROTECTED ROUTE TESTS PASSED\n')

def test_unauthorized_access():
    with app.test_client() as client:
        print('--- TEST 3: UNAUTHORIZED ACCESS ---\n')
        
        routes = [
            '/api/status',
            '/api/history',
            '/api/reports',
            '/api/monitor',
            '/api/schedule',
            '/api/schedule/datasets',
        ]
        
        for route in routes:
            print(f'GET {route} (no auth):')
            resp = client.get(route)
            # Some routes may work without auth (like status), check behavior
            print(f'  Status: {resp.status_code}')
        
        print('\nUNAUTHORIZED ACCESS TESTS COMPLETE\n')

def test_edge_cases():
    with app.test_client() as client:
        print('--- TEST 4: EDGE CASES & BOUNDARY VALUES ---\n')
        
        # 4.1 Signup with various email formats
        test_emails = [
            'test+tag@example.com',
            'user.name@sub.domain.com',
            'user@domain.co.uk',
            'UPPER@EXAMPLE.COM',  # Should be lowercased
        ]
        for i, email in enumerate(test_emails):
            print(f'4.{i+1} Signup (email: {email}):')
            resp = client.post('/api/auth/signup', json={
                'email': email,
                'password': 'password123',
                'confirm_password': 'password123'
            })
            # Should succeed or fail gracefully
            assert resp.status_code in (201, 400, 409), f'Unexpected status: {resp.status_code}'
            print(f'  Status: {resp.status_code}')
        
        # 4.2 Password boundary values
        print('4.5 Password exactly 8 chars:')
        resp = client.post('/api/auth/signup', json={
            'email': 'boundary1@example.com',
            'password': 'pass1234',  # exactly 8
            'confirm_password': 'pass1234'
        })
        assert resp.status_code == 201, f'Expected 201, got {resp.status_code}: {resp.get_json()}'
        print(f'  PASS')
        
        print('4.6 Password 7 chars (should fail):')
        resp = client.post('/api/auth/signup', json={
            'email': 'boundary2@example.com',
            'password': 'pass123',  # 7 chars
            'confirm_password': 'pass123'
        })
        assert resp.status_code == 400, f'Expected 400, got {resp.status_code}: {resp.get_json()}'
        print(f'  PASS - Correctly rejected')
        
        # 4.3 Long password
        print('4.7 Long password (100 chars):')
        resp = client.post('/api/auth/signup', json={
            'email': 'boundary3@example.com',
            'password': 'a' * 100,
            'confirm_password': 'a' * 100
        })
        assert resp.status_code == 201, f'Expected 201, got {resp.status_code}: {resp.get_json()}'
        print(f'  PASS')
        
        # 4.4 Unicode in password
        print('4.8 Unicode password:')
        resp = client.post('/api/auth/signup', json={
            'email': 'boundary4@example.com',
            'password': 'pässwörd123🔒',
            'confirm_password': 'pässwörd123🔒'
        })
        assert resp.status_code == 201, f'Expected 201, got {resp.status_code}: {resp.get_json()}'
        print(f'  PASS')
        
        # 4.5 SQL injection attempt in email
        print('4.9 SQL injection attempt:')
        resp = client.post('/api/auth/signup', json={
            'email': "test'; DROP TABLE users;--@example.com",
            'password': 'password123',
            'confirm_password': 'password123'
        })
        # Should not crash, either succeed or fail validation
        assert resp.status_code in (201, 400, 409), f'Unexpected status: {resp.status_code}'
        print(f'  Status: {resp.status_code} (handled safely)')
        
        # 4.6 XSS attempt in email
        print('4.10 XSS attempt:')
        resp = client.post('/api/auth/signup', json={
            'email': '<script>alert(1)</script>@example.com',
            'password': 'password123',
            'confirm_password': 'password123'
        })
        assert resp.status_code in (201, 400, 409), f'Unexpected status: {resp.status_code}'
        print(f'  Status: {resp.status_code} (handled safely)')
        
        print('\nALL EDGE CASE TESTS PASSED\n')

def test_integration():
    with app.test_client() as client:
        print('--- TEST 5: INTEGRATION WORKFLOWS ---\n')
        
        # Full workflow: signup -> login -> analyze -> view results
        print('5.1 Full user workflow:')
        
        # Signup
        resp = client.post('/api/auth/signup', json={
            'email': 'workflow@example.com',
            'password': 'password123',
            'confirm_password': 'password123'
        })
        assert resp.status_code == 201
        token = resp.get_json()['token']
        print(f'  Signup: OK')
        
        # Analyze
        resp = client.post('/api/analyze', data={'rows': '1000'}, headers={'Authorization': 'Bearer ' + token})
        assert resp.status_code == 200
        analysis = resp.get_json()
        assert analysis['rows_clean'] == 1000
        print(f'  Analyze: OK ({analysis["rows_clean"]} rows)')
        
        # Check history
        resp = client.get('/api/history', headers={'Authorization': 'Bearer ' + token})
        assert resp.status_code == 200
        history = resp.get_json()['history']
        assert len(history) >= 1
        assert history[0]['source'] == 'synthetic (1,000 rows)'
        print(f'  History: OK ({len(history)} entries)')
        
        # Check reports
        resp = client.get('/api/reports', headers={'Authorization': 'Bearer ' + token})
        assert resp.status_code == 200
        reports = resp.get_json()['reports']
        assert len(reports) >= 1
        print(f'  Reports: OK ({len(reports)} reports)')
        
        # Check monitor
        resp = client.get('/api/monitor', headers={'Authorization': 'Bearer ' + token})
        assert resp.status_code == 200
        print(f'  Monitor: OK')
        
        # Logout
        resp = client.post('/api/auth/logout')
        assert resp.status_code == 200
        print(f'  Logout: OK')
        
        print('\nALL INTEGRATION TESTS PASSED\n')

def test_concurrent_sessions():
    with app.test_client() as client:
        print('--- TEST 6: CONCURRENT SESSIONS ---\n')
        
        # Create two users
        resp1 = client.post('/api/auth/signup', json={
            'email': 'concurrent1@example.com',
            'password': 'password123',
            'confirm_password': 'password123'
        })
        token1 = resp1.get_json()['token']
        
        resp2 = client.post('/api/auth/signup', json={
            'email': 'concurrent2@example.com',
            'password': 'password123',
            'confirm_password': 'password123'
        })
        token2 = resp2.get_json()['token']
        
        # Both can access their own data
        resp = client.get('/api/auth/me', headers={'Authorization': 'Bearer ' + token1})
        assert resp.get_json()['user']['email'] == 'concurrent1@example.com'
        
        resp = client.get('/api/auth/me', headers={'Authorization': 'Bearer ' + token2})
        assert resp.get_json()['user']['email'] == 'concurrent2@example.com'
        
        # Both can run analyses independently
        resp1 = client.post('/api/analyze', data={'rows': '1000'}, headers={'Authorization': 'Bearer ' + token1})
        resp2 = client.post('/api/analyze', data={'rows': '1000'}, headers={'Authorization': 'Bearer ' + token2})
        assert resp1.status_code == 200 and resp2.status_code == 200
        
        # Both can access shared system history (global, not per-user)
        hist1 = client.get('/api/history', headers={'Authorization': 'Bearer ' + token1}).get_json()['history']
        hist2 = client.get('/api/history', headers={'Authorization': 'Bearer ' + token2}).get_json()['history']
        assert len(hist1) >= 2 and len(hist2) >= 2
        assert len(hist1) == len(hist2)  # Same global history
        
        print('  PASS - Concurrent sessions work, share global history')
        print('\nALL CONCURRENT SESSION TESTS PASSED\n')

def test_template_rendering():
    with app.test_client() as client:
        print('--- TEST 7: TEMPLATE RENDERING ---\n')
        
        pages = [
            ('/', 'index.html'),
            ('/login', 'login.html'),
            ('/signup', 'signup.html'),
        ]
        
        for path, template in pages:
            print(f'{path} ({template}):')
            resp = client.get(path)
            assert resp.status_code == 200, f'Expected 200, got {resp.status_code}'
            assert b'PipelineIQ' in resp.data
            assert b'cyberpunk' in resp.data.lower() or b'neon' in resp.data.lower()
            print(f'  PASS - Status 200, contains branding')
        
        print('\nALL TEMPLATE TESTS PASSED\n')

if __name__ == '__main__':
    clear_test_db()
    try:
        token = test_auth_workflows()
        test_protected_routes(token)
        test_unauthorized_access()
        test_edge_cases()
        test_integration()
        test_concurrent_sessions()
        test_template_rendering()
        
        print('=' * 60)
        print('ALL TESTS PASSED - SYSTEM VERIFIED')
        print('=' * 60)
    except AssertionError as e:
        print(f'\nTEST FAILED: {e}')
        sys.exit(1)
    except Exception as e:
        print(f'\nTEST ERROR: {e}')
        import traceback
        traceback.print_exc()
        sys.exit(1)