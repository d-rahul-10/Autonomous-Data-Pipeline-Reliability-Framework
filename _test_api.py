#!/usr/bin/env python3
"""Simple API integration test script."""

import http.cookiejar
import json
import re
import urllib.error
import urllib.request


BASE_URL = "http://127.0.0.1:5000"


def main() -> None:
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

    def get_csrf(path: str = "/auth") -> str | None:
        html = opener.open(BASE_URL + path, timeout=10).read().decode()
        m = re.search(r'meta name="csrf-token" content="([^"]+)"', html)
        return m.group(1) if m else None

    def req(method: str, path: str, data: dict | None = None, csrf_token: str | None = None, ct: str = "application/json"):
        url = BASE_URL + path
        body = None
        if data is not None:
            if ct == "application/json":
                body = json.dumps(data).encode()
            else:
                body = "&".join(k + "=" + str(v) for k, v in data.items()).encode()
        h = {"Content-Type": ct}
        if csrf_token:
            h["X-CSRF-Token"] = csrf_token
        r = urllib.request.Request(url, data=body, headers=h, method=method)
        try:
            resp = opener.open(r, timeout=10)
            return resp.status, json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read().decode() or "{}")
            except (json.JSONDecodeError, AttributeError):
                return e.code, {}

    csrf = get_csrf()
    print("Initial CSRF:", csrf[:20] if csrf else "NONE")

    s, d = req("POST", "/api/auth/signup", {"name": "Test User", "email": "test@example.com", "password": "TestPass123"}, csrf)
    print("signup:", s, d.get("message"), d.get("error"))

    csrf = get_csrf()
    print("After signup CSRF:", csrf[:20] if csrf else "NONE")

    s, d = req("POST", "/api/auth/login", {"email": "test@example.com", "password": "TestPass123"}, csrf)
    print("login:", s, d.get("message"), d.get("error"))

    csrf = get_csrf()
    print("After login CSRF:", csrf[:20] if csrf else "NONE")

    s, d = req("GET", "/api/auth/me", csrf_token=csrf)
    print("me:", s, d.get("user", {}).get("name"), d.get("error"))

    s, d = req("GET", "/api/status")
    print("status:", s, d.get("ready"))

    s, d = req("POST", "/api/analyze", {"rows": "1000"}, csrf, "application/x-www-form-urlencoded")
    print("analyze:", s, d.get("rows_clean"), d.get("failures", {}).get("total_flagged"), d.get("error"))

    s, d = req("POST", "/api/schedule", {"enabled": False, "interval_seconds": 3600, "rows": 10000, "source_type": "sample"}, csrf)
    print("schedule:", s, d.get("schedule", {}).get("enabled"), d.get("error"))

    print("Done")


if __name__ == "__main__":
    main()
