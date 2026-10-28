# UPSTREAM IDLE TIMEOUT — ON-CALL RUNBOOK
*Target resolution: < 2 min decision → < 15 min mitigation*

---

## ⚡ IMMEDIATE TRIAGE (30 sec)

```
1. IS IT RETRYABLE? → Check: GET/HEAD/OPTIONS? OR POST with Idempotency-Key?
   NO  → STOP. Do not retry. Escalate.
   YES → Continue.

2. WHAT'S THE ERROR CODE?
   504 Gateway Timeout        → Gateway gave up waiting
   502 Bad Gateway            → Upstream connection failed
   503 Service Unavailable    → Upstream overloaded
   408 Request Timeout        → Client-side (your timeout)
   Other 5xx                  → Retryable

3. CAN YOU BYPASS GATEWAY?
   curl -v --max-time 120 http://UPSTREAM_DIRECT/health
   Works? → Gateway config issue. Skip to GATEWAY FIXES.
   Fails? → Upstream is slow/down. Skip to UPSTREAM FIXES.
```

---

## 🔧 QUICK MITIGATION (pick one, apply in < 5 min)

| If... | Do This Now |
|-------|-------------|
| Gateway timeout | **nginx**: `proxy_read_timeout 300s; proxy_send_timeout 300s;` in location block → `nginx -s reload` |
| ALB timeout | AWS Console → Load Balancer → Attributes → **Idle timeout: 300** (max 4000) |
| Cloudflare | Rules → **Origin Timeout: 100s** (Enterprise) or gray-cloud DNS temporarily |
| Vercel/Netlify | `vercel.json`: `"functions": { "maxDuration": 60 }` or upgrade plan |
| K8s Ingress | `nginx.ingress.kubernetes.io/proxy-read-timeout: "300"` annotation |
| Client (aiohttp) | `ClientTimeout(total=120, sock_read=60, sock_connect=10)` |
| Client (httpx) | `Timeout(120.0, connect=10.0, read=60.0)` |

---

## 🔁 RETRY DECISION MATRIX

```
┌─────────────────────────────────────────────────────────────┐
│  RETRY?    │  CONDITION                                     │
├────────────┼────────────────────────────────────────────────┤
│  ✅ YES    │  Idempotent (GET/HEAD/OPTIONS/PUT/DELETE)      │
│  ✅ YES    │  POST with Idempotency-Key header              │
│  ❌ NO     │  POST without idempotency key                  │
│  ❌ NO     │  4xx (except 408, 429)                         │
│  ⚠️ MAYBE  │  5xx but non-idempotent → queue for manual    │
└────────────┴────────────────────────────────────────────────┘

BACKOFF: 1s → 2s → 4s (max 3 attempts) + 25% jitter
CODE:    Use tenacity (Python) / axios-retry (JS) / resilience4j (Java)
```

---

## 📊 KEY TIMEOUT SETTINGS BY PLATFORM

| Platform | Setting | Default | Recommended | Where |
|----------|---------|---------|-------------|-------|
| **nginx** | `proxy_read_timeout` | 60s | **300s** | `location / {}` |
| **nginx** | `proxy_send_timeout` | 60s | **300s** | `location / {}` |
| **nginx** | `proxy_connect_timeout` | 60s | **10s** | `location / {}` |
| **ALB** | Idle timeout | 60s | **300s** | Console → Attributes |
| **ALB** | Target response timeout | — | **300s** | Target group settings |
| **Cloudflare** | Origin timeout | 100s | **100s** (max free) | Rules → Origin |
| **Cloudflare** | Proxy read timeout | 100s | **600s** (Ent) | Workers/Tunnels |
| **aiohttp** | `sock_read` | None | **60s** | `ClientTimeout()` |
| **aiohttp** | `total` | None | **120s** | `ClientTimeout()` |
| **httpx** | `read` | None | **60s** | `Timeout()` |
| **httpx** | `connect` | None | **10s** | `Timeout()` |
| **Go http** | `IdleConnTimeout` | 90s | **120s** | `Transport{}` |
| **Java HttpClient** | `responseTimeout` | ∞ | **60s** | `.timeout()` |
| **Node fetch** | `timeout` | ∞ | **60s** | AbortController |
| **K8s Ingress** | `proxy-read-timeout` | 60s | **300s** | Annotation |

---

## 🔍 OBSERVABILITY CHECKLIST (prevent recurrence)

**Deploy THIS WEEK:**

- [ ] **Request ID propagation**: `X-Request-ID` header through entire chain
- [ ] **Upstream latency histogram**: `http.server.duration` per route (Prometheus)
- [ ] **Gateway→Upstream latency**: `nginx.upstream.response_time` vs `$request_time`
- [ ] **Connection pool metrics**: `pool.active`, `pool.idle`, `pool.wait_time`
- [ ] **Slow query alert**: DB queries > 1s → page
- [ ] **Timeout budget dashboard**: `p99 latency < gateway_idle_timeout * 0.7`
- [ ] **Synthetic canary**: GET `/health` every 10s from outside, alert on >5s

**Log format (JSON, one line):**
```json
{
  "ts": "2026-10-11T08:00:00Z",
  "request_id": "abc123",
  "route": "/api/analyze",
  "upstream": "pipeline-api:8000",
  "gateway_latency_ms": 45,
  "upstream_latency_ms": 2800,
  "status": 504,
  "retry_attempt": 0
}
```

---

## 🚨 ESCALATION PATH

| Time | Action |
|------|--------|
| T+0  | Apply gateway timeout increase (above) |
| T+5  | If upstream still slow: scale replicas / restart pods |
| T+10 | If DB: check `pg_stat_activity` / `SHOW PROCESSLIST` |
| T+15 | Page oncall with: request_id, upstream, latency, mitigation tried |
| T+30 | Incident channel: runbook link, timeline, customer impact |

---

## 📋 ONE-PAGE QUICK REFERENCE (PRINT THIS)

```
┌────────────────────────────────────────────────────────────────┐
│ UPSTREAM IDLE TIMEOUT — QUICK REFERENCE                        │
├────────────────────────────────────────────────────────────────┤
│ 1. IDENTIFY                                                    │
│    □ 504/502/503 from gateway?                                 │
│    □ curl direct to upstream — works?                          │
│    □ Idempotent request?                                       │
├────────────────────────────────────────────────────────────────┤
│ 2. MITIGATE (pick one)                                         │
│    □ nginx:     proxy_read_timeout 300s; reload                │
│    □ ALB:       Idle timeout → 300s                            │
│    □ Cloudflare: Origin timeout → 100s (or gray-cloud)         │
│    □ Client:    sock_read=60s, total=120s                      │
├────────────────────────────────────────────────────────────────┤
│ 3. RETRY?                                                      │
│    ✅ GET/HEAD/OPTIONS/PUT/DELETE                              │
│    ✅ POST + Idempotency-Key                                   │
│    ❌ POST without key                                         │
│    Backoff: 1s, 2s, 4s + 25% jitter (max 3)                   │
├────────────────────────────────────────────────────────────────┤
│ 4. OBSERVE (must have)                                         │
│    □ X-Request-ID end-to-end                                   │
│    □ upstream_latency_ms histogram                             │
│    □ gateway vs upstream latency gap alert                     │
│    □ Connection pool saturation alert                          │
├────────────────────────────────────────────────────────────────┤
│ 5. COMMON ROOT CAUSES                                          │
│    • DB missing index / lock contention                        │
│    • External API (LLM, payments) > 60s                        │
│    • Connection pool exhaustion                                │
│    • Gateway idle timeout < upstream p99                       │
│    • Streaming response with gaps                              │
└────────────────────────────────────────────────────────────────┘
```

---

## ❌ COMMON MISTAKES TO AVOID

| Mistake | Why It's Wrong | Correct Approach |
|---------|----------------|------------------|
| Retry POST without idempotency key | Double-charge, duplicate orders | Generate idempotency key client-side |
| Only increase `total` timeout | Doesn't fix idle read gaps | Set `sock_read` / `read` timeout explicitly |
| Set gateway timeout > 5 min | Masks upstream problems | Cap at 300s; fix upstream instead |
| No jitter in backoff | Thundering herd on recovery | Always add 25-50% jitter |
| No request ID correlation | Can't trace across services | Middleware: generate + propagate `X-Request-ID` |
| Alert on 5xx count only | Misses latency degradation | Alert on `p99 latency > threshold` |

---

## 📝 INCIDENT TEMPLATE (copy-paste)

```
**INCIDENT**: Upstream Idle Timeout
**START**: <timestamp>
**REQUEST_ID**: <x-request-id from logs>
**GATEWAY**: nginx / ALB / Cloudflare / Vercel
**UPSTREAM**: <service:port>
**SYMPTOM**: 504 after <X>s (gateway idle timeout: <Y>s)
**MITIGATION APPLIED**: <timeout increase / scale / restart>
**ROOT CAUSE HYPOTHESIS**: <DB / external API / pool / code>
**NEXT STEPS**: <scale / query fix / async offload>
**OWNER**: @oncall
```