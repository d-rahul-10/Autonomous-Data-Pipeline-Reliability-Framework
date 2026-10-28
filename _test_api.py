import urllib.request, http.cookiejar, re, json

cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

def get_csrf(path='/auth'):
    html = opener.open('http://127.0.0.1:5000' + path, timeout=10).read().decode()
    m = re.search(r'meta name="csrf-token" content="([^"]+)"', html)
    return m.group(1) if m else None

def req(method, path, data=None, csrf_token=None, ct='application/json'):
    url = 'http://127.0.0.1:5000' + path
    body = None
    if data:
        if ct == 'application/json':
            body = json.dumps(data).encode()
        else:
            body = '&'.join(k + '=' + str(v) for k, v in data.items()).encode()
    h = {'Content-Type': ct}
    if csrf_token:
        h['X-CSRF-Token'] = csrf_token
    r = urllib.request.Request(url, data=body, headers=h, method=method)
    try:
        resp = opener.open(r, timeout=10)
        return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or '{}')

csrf = get_csrf()
print('Initial CSRF:', csrf[:20] if csrf else 'NONE')

# Signup
s, d = req('POST', '/api/auth/signup', {'name': 'Test User', 'email': 'test@example.com', 'password': 'TestPass123'}, csrf)
print('signup:', s, d.get('message'), d.get('error'))

# Refresh CSRF after session change
csrf = get_csrf()
print('After signup CSRF:', csrf[:20] if csrf else 'NONE')

# Login
s, d = req('POST', '/api/auth/login', {'email': 'test@example.com', 'password': 'TestPass123'}, csrf)
print('login:', s, d.get('message'), d.get('error'))

# Refresh CSRF after login
csrf = get_csrf()
print('After login CSRF:', csrf[:20] if csrf else 'NONE')

# me endpoint
s, d = req('GET', '/api/auth/me', csrf_token=csrf)
print('me:', s, d.get('user', {}).get('name'), d.get('error'))

# status
s, d = req('GET', '/api/status')
print('status:', s, d.get('ready'))

# analyze
s, d = req('POST', '/api/analyze', {'rows': '1000'}, csrf, 'application/x-www-form-urlencoded')
print('analyze:', s, d.get('rows_clean'), d.get('failures', {}).get('total_flagged'), d.get('error'))

# schedule
s, d = req('POST', '/api/schedule', {'enabled': False, 'interval_seconds': 3600, 'rows': 10000, 'source_type': 'sample'}, csrf)
print('schedule:', s, d.get('schedule', {}).get('enabled'), d.get('error'))

print('Done')
