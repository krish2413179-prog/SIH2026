# Design Document

## Blockchain Intelligence & VASP Attribution Engine

---

## Overview

The Blockchain Intelligence & VASP Attribution Engine is a Python/FastAPI backend with a React/Next.js frontend. It ingests suspect cryptocurrency wallet addresses from authenticated LEA investigators, traces multi-hop fund flows across six supported blockchains using free public APIs, clusters addresses using on-chain heuristics, attributes clusters to known VASPs via a managed registry, computes risk scores, detects laundering typologies, and generates investigation-ready reports. Cases and all derived artifacts are managed under a JWT+RBAC security model and integrated with the SAHYOG Portal for disclosure and freeze routing. All user actions are written to a tamper-evident Audit Log.

---

## Architecture

### High-Level Component Map

```
┌─────────────────────────────────────────────────────────────────────┐
│                        React / Next.js SPA                          │
│  Dashboard │ Case Manager │ Graph Viewer │ Report Builder │ Admin   │
└────────────────────────┬────────────────────────────────────────────┘
                         │ HTTPS (JWT bearer)
┌────────────────────────▼────────────────────────────────────────────┐
│                     FastAPI (async, Python 3.11+)                    │
│  Auth  │  Cases  │  Wallets  │  Traces  │  Reports  │  Admin        │
│                   Audit Middleware (all routes)                      │
└───┬────────┬──────────────────────┬──────────────┬───────────────── ┘
    │        │                      │              │
  PostgreSQL Redis              Celery Workers  SAHYOG API
  (primary  (cache +             (trace jobs)   (external)
   store)    task queue)
    │        │
    └────────┴──► NetworkX (graph analytics, in-worker process)
                  Blockchain Data Adapters (per-chain, in-worker)
                  Report Renderer (WeasyPrint PDF + Pydantic JSON)
```

### Deployment Topology

- **API Server**: FastAPI application served with Uvicorn/Gunicorn, horizontally scalable behind a load balancer.
- **Worker Pool**: Celery workers consuming from Redis broker; separate queue priorities for trace jobs vs. report generation.
- **Database**: PostgreSQL 15+ with pgcrypto extension for AES-256 column-level encryption on sensitive fields.
- **Cache / Broker**: Redis 7+ serving dual purpose — raw blockchain data cache (TTL-keyed) and Celery task broker.
- **Static Assets / Frontend**: Next.js build served via CDN or Nginx.
- **Object Storage**: S3-compatible store (e.g., MinIO on-prem) for generated PDF reports.
- **Reverse Proxy**: Nginx enforcing HTTPS, HTTP→HTTPS redirect, and upstream connection to FastAPI.

---

## Core Modules

### 1. Authentication & Authorization (`auth`)

**Token flow:**

```python
# Simplified token pair creation
def create_token_pair(user_id: str, role: str, secret: str, expiry_hours: int = 8) -> TokenPair:
    now = datetime.utcnow()
    access_payload = {
        "sub": user_id,
        "role": role,
        "iat": now,
        "exp": now + timedelta(hours=expiry_hours),
        "jti": str(uuid4()),
    }
    refresh_payload = {
        "sub": user_id,
        "type": "refresh",
        "iat": now,
        "exp": now + timedelta(days=30),
        "jti": str(uuid4()),
    }
    return TokenPair(
        access_token=jwt.encode(access_payload, secret, algorithm="HS256"),
        refresh_token=jwt.encode(refresh_payload, secret, algorithm="HS256"),
    )
```

**RBAC permission matrix:**

| Permission | investigator | supervisor | admin |
|---|---|---|---|
| Create/read own cases | ✓ | ✓ | ✓ |
| Read all org cases | ✗ | ✓ | ✓ |
| Submit wallets | ✓ | ✓ | ✓ |
| Initiate trace | ✓ | ✓ | ✓ |
| Generate report | ✓ | ✓ | ✓ |
| Approve/sign report | ✗ | ✓ | ✓ |
| Route SAHYOG request | ✗ | ✓ | ✓ |
| Manage users/roles | ✗ | ✗ | ✓ |
| Manage VASP DB | ✗ | ✗ | ✓ |
| View audit log | ✗ | ✗ | ✓ |
| System config | ✗ | ✗ | ✓ |

**Password storage:** bcrypt with `rounds=12` minimum via `passlib[bcrypt]`.

**Account lockout:** Redis counter per `user_id`; incremented on failed login; TTL reset to 15 minutes at 5th failure; subsequent auth attempts return 403 until TTL expires.

**Key rotation:** JWT signing keys stored in a `jwt_keys` table with `valid_from`, `valid_until`, and `is_current` columns. The verification routine tries all keys with `is_current=True` or `valid_until > now` so in-flight tokens survive rotation.

---

### 2. Case Management (`cases`)

**State machine:**

```
open ──► under_review ──► closed
  ▲            │
  └────────────┘ (supervisor reopen)
```

Soft-delete sets `deleted_at` timestamp; all queries default-filter `deleted_at IS NULL`. Associated wallets, traces, and reports remain but gain `archived=True`.

**Data model (PostgreSQL):**

```python
class Case(Base):
    __tablename__ = "cases"
    id: UUID  # PK, gen_random_uuid()
    title: str
    description: str | None
    status: CaseStatus  # Enum: open, under_review, closed
    created_by: UUID  # FK → users
    supervisor_id: UUID | None  # FK → users
    org_unit_id: UUID  # FK → org_units
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
    # m2m with wallet_addresses via case_wallets join table
```

**Search:** PostgreSQL full-text search via `to_tsvector` on `title || description`; filter indexes on `status`, `created_by`, `created_at`.

---

### 3. Wallet Address Submission & Chain Detection (`wallets`)

**Address format validators** (regex + length, per chain):

| Chain | Validation |
|---|---|
| Bitcoin (BTC) | P2PKH (`1…`), P2SH (`3…`), bech32 (`bc1…`) |
| Ethereum (ETH) | EIP-55 checksum hex, 42 chars |
| Tron (TRX) | Base58 starting with `T`, 34 chars |
| BNB Chain (BSC) | Same regex as ETH (EVM-compatible) |
| Polygon (MATIC) | Same regex as ETH |
| Solana (SOL) | Base58 string, 32–44 chars |

**Chain auto-detection:** A submitted address is run through each validator in priority order. If it matches multiple (e.g., ETH/BSC/MATIC all share the same format), a `detected_chains` list is returned and traces are enqueued for each chain separately.

**Deduplication:** On submission, a DB lookup checks for an existing `wallet_traces` row matching `(case_id, address, chain)` with `enqueued_at > now() - interval '24 hours'`. If found, the existing `trace_id` is returned with HTTP 200.

**Batch endpoint:** `POST /cases/{case_id}/wallets` accepts a JSON array of up to 50 addresses. Items beyond 50 receive a 400 error; partial-batch failures return per-item results in the response body.

---

### 4. Blockchain Data Adapters (`adapters`)

**Common interface:**

```python
from abc import ABC, abstractmethod
from typing import Protocol

class BlockchainAdapter(ABC):
    chain: str  # BTC | ETH | TRX | BSC | SOL | MATIC

    @abstractmethod
    async def get_transactions(
        self,
        address: str,
        *,
        page: int = 1,
        page_size: int = 100,
    ) -> list[RawTransaction]:
        ...

    @abstractmethod
    async def get_address_info(self, address: str) -> AddressInfo:
        ...
```

**Adapter registry:** A dict mapping `chain → adapter_class`; populated at startup from config. Swapping to a commercial provider requires only adding a new class and updating the config key.

**Retry / backoff logic (shared mixin):**

```python
async def _fetch_with_retry(self, url: str, **kwargs) -> dict:
    delay = 1.0
    for attempt in range(5):
        try:
            resp = await self._http_client.get(url, **kwargs)
            resp.raise_for_status()
            return resp.json()
        except RateLimitError:
            await asyncio.sleep(min(delay, 60.0))
            delay *= 2
        except (httpx.HTTPError, asyncio.TimeoutError):
            if attempt == 4:
                raise DataUnavailableError(url)
    raise RateLimitedError(url)
```

**Cache layer:** Redis key `blockchain:{chain}:{address}:{page}`, serialized with `orjson`. TTL defaults to 1800 seconds (30 min), configurable per chain. Cache hits include `cache_age_seconds` in the returned metadata.

**Per-chain endpoints:**

| Chain | Primary API | Key endpoints used |
|---|---|---|
| BTC | Mempool.space | `/api/address/{addr}/txs` |
| ETH | Etherscan | `?module=account&action=txlist` |
| TRX | Tronscan | `/api/transaction-info` |
| BSC | BscScan | `?module=account&action=txlist` |
| SOL | Solscan | `/account/transactions` |
| MATIC | Polygonscan | `?module=account&action=txlist` |

---

### 5. Transaction Graph Construction (`graph`)

**Technology:** NetworkX `DiGraph` constructed in the Celery worker process.

**Node attributes:**
- `address: str`
- `chain: str`
- `in_degree: int`
- `out_degree: int`
- `total_inflow: Decimal` (native currency)
- `total_outflow: Decimal`
- `first_seen: datetime`
- `last_seen: datetime`
- `entity_type: str` (unknown | vasp | flagged | mixer | bridge)

**Edge attributes:**
- `tx_hash: str`
- `amount: Decimal`
- `fee: Decimal`
- `timestamp: datetime`
- `chain: str`
- `is_bridge: bool`
- `bridge_protocol: str | None`

**Graph traversal algorithm:**

```python
async def build_graph(
    seed_address: str,
    chain: str,
    adapter: BlockchainAdapter,
    max_hops: int = 5,
) -> nx.DiGraph:
    G = nx.DiGraph()
    frontier = {seed_address}
    visited = set()

    for hop in range(max_hops):
        next_frontier = set()
        for addr in frontier - visited:
            txs = await adapter.get_transactions(addr)
            for tx in txs:
                G.add_node(tx.from_addr, chain=chain)
                G.add_node(tx.to_addr, chain=chain)
                G.add_edge(tx.from_addr, tx.to_addr, **tx.edge_attrs())
                next_frontier.add(tx.to_addr)
            visited.add(addr)
        frontier = next_frontier
        if not frontier:
            break

    _compute_node_metrics(G)
    return G
```

**Cross-chain bridges:** When a transaction's `to_address` is in the known bridge contract registry, the edge is tagged `is_bridge=True` and the resulting sub-graph on the destination chain is connected via a virtual bridge node with `chain=bridge:{src}-{dst}`.

**Memory management:** Graphs exceeding 10,000 nodes trigger a `GraphSizeWarning`; above 50,000 edges, the trace worker emits a metric and limits further expansion by pruning low-value edges (below the 10th percentile of edge amounts).

**Persistence:** Graph is serialized to JSON (NetworkX `node_link_data` format) and stored in the `trace_graphs` table with `case_id`, `trace_id`, `wallet_address`, `chain`, and `graph_data` (JSONB column) for retrieval and re-use.

---

### 6. Address Clustering & Entity Attribution (`clustering`)

**Heuristic implementations:**

_Common-Input Ownership (CIO) — Bitcoin:_
For each transaction, if multiple input addresses share the same transaction, they are assigned to the same cluster (Union-Find / disjoint set data structure). Implemented with `networkx`-based connected component analysis on the input co-spend graph.

_Deposit Address Pattern — EVM chains + TRX + SOL:_
Identifies "hub-and-spoke" patterns: a central address receiving from many unique addresses within a short time window → likely exchange deposit cluster. Threshold: ≥10 unique senders within 24 hours.

**Confidence Score formula:**

```python
def compute_confidence_score(
    address_match_ratio: float,    # matched addresses / total cluster size
    volume_similarity: float,      # 0-1 cosine similarity of volume vectors
    behavioral_similarity: float,  # 0-1 pattern match score
    temporal_proximity: float,     # 0-1 recency weight
) -> float:
    return (
        0.4 * address_match_ratio
        + 0.3 * volume_similarity
        + 0.2 * behavioral_similarity
        + 0.1 * temporal_proximity
    ) * 100  # returns 0-100
```

**Attribution pipeline:**

1. Run clustering heuristics → produce `Cluster` objects (set of addresses + chain).
2. Query VASP Database for seed address overlap.
3. If overlap found, compute `ConfidenceScore`.
4. Emit `Attribution(cluster_id, vasp_id, confidence_score, low_confidence=score < 40)`.
5. Persist all clusters, attributions, and scores linked to `trace_id`.

**Special flags:**
- Mixer / coinjoin addresses: matched against a maintained set in the VASP DB with `category = "mixer"`.
- Bridge contracts: matched against `category = "bridge"`.
- Both result in dedicated typology tags without requiring a full VASP attribution.

---

### 7. VASP Database (`vasp_db`)

**Data model:**

```python
class VASP(Base):
    __tablename__ = "vasps"
    id: UUID
    name: str
    category: VASPCategory  # CEX | DEX | mixer | bridge | darknet | other
    jurisdiction: str  # ISO 3166-1 alpha-2
    operational_status: str  # active | inactive | sanctioned
    last_updated: datetime

class VASPAddress(Base):
    __tablename__ = "vasp_addresses"
    id: UUID
    vasp_id: UUID  # FK → vasps
    chain: str
    address: str
    added_at: datetime
    # Unique constraint: (chain, address)
```

**Bulk CSV import:** Streamed with `csv.DictReader`; each row validated via Pydantic before insert. Failed rows accumulate in an `ImportError` list returned in the response; successful rows are committed in batches of 500.

**Cache invalidation on update:** When a `VASPAddress` row is modified or deleted, a PostgreSQL trigger publishes a notification on channel `vasp_updated:{vasp_id}`. The FastAPI process (or a dedicated listener worker) invalidates Redis keys matching `attribution:*:{vasp_id}:*` and marks affected traces with `needs_reattribution=True`.

---

### 8. Risk Scoring Engine (`risk`)

**Score formula:**

```python
def compute_risk_score(
    direct_exposure: float,      # 0-1, ratio of flagged direct neighbors
    indirect_exposure: float,    # 0-1, within 3 hops
    vasp_risk_category: float,   # 0-1, from VASP risk tier table
    typology_flags: float,       # 0-1, normalized count of active typology flags
    volume_anomaly: float,       # 0-1, z-score normalized
) -> int:
    raw = (
        0.35 * direct_exposure
        + 0.20 * indirect_exposure
        + 0.20 * vasp_risk_category
        + 0.15 * typology_flags
        + 0.10 * volume_anomaly
    ) * 100
    return max(0, min(100, round(raw)))
```

**Risk bands:**

| Band | Range | Action |
|---|---|---|
| Low | 0–39 | Monitor |
| Medium | 40–69 | Investigate |
| High | 70–100 | Alert + escalate |

**High-risk alert:** On score ≥ 70, a `RiskAlert` record is created and a WebSocket event is pushed to the Supervisor's notification channel within the 30-second SLA (Celery task → Redis pub/sub → FastAPI WebSocket handler).

**Score change tracking:** Previous score stored on `wallet_traces.risk_score_prev`. After recalculation, if `abs(new - prev) > 10`, an audit log entry is written and the assigned Investigator receives a notification.

---

### 9. Typology Detection (`typology`)

**Architecture:** Each typology is implemented as a stateless `TypologyDetector` class with a `detect(G: nx.DiGraph, address: str) -> DetectionResult | None` method. A `TypologyClassifier` orchestrates all detectors concurrently using `asyncio.gather`.

**Detector implementations:**

| Typology | Detection Logic |
|---|---|
| **Layering** | Path length > 4, each hop changes address within 60 min, no address reuse |
| **Peel chain** | Linear path where each hop's output ≤ 80% of input, min 5 hops |
| **Mixer/tumbler** | Fan-out ≥ 10 destinations with equal (±2%) output amounts |
| **Bridge abuse** | Cross-chain bridge edge from/to chain in high-risk chain set |
| **Darknet market** | Address in known darknet seed set OR structural match to known patterns |
| **Ransomware** | Address in known ransomware wallet set OR matches consolidation pattern |
| **Fraud aggregation** | Hub node receiving from ≥ 50 unique addresses within 7 days |

**Confidence threshold:** Detectors return a `match_confidence` float. Only detections with `match_confidence >= 0.60` produce a `TypologyTag`.

**Hot-reload:** Classifier definitions are stored as JSON in the `typology_definitions` table. On Admin upload, definitions are parsed and loaded into the in-process cache. Workers poll for definition changes every 60 seconds using a Redis version counter.

---

### 10. Graph Visualization (Frontend — `components/GraphViewer`)

**Technology:** React + [Cytoscape.js](https://js.cytoscape.org/) for interactive graph rendering.

**Node color coding:**
- Known VASP: `#3B82F6` (blue)
- Unknown: `#9CA3AF` (gray)
- Flagged / high-risk: `#EF4444` (red)
- Mixer / obfuscation: `#8B5CF6` (purple)
- Bridge contract: `#F59E0B` (amber)

**Edge thickness:** Mapped to `log(amount + 1)` for visual balance across large value ranges.

**Large graph handling (> 500 nodes):** Force-directed layout (`fcose` algorithm) with progressive rendering — top-100 highest-value paths rendered in first pass, remaining nodes added incrementally. Target: initial render < 5 seconds.

**Export:**
- PNG: `cy.png()` → download blob.
- JSON: `GET /api/traces/{trace_id}/graph` → `application/json`.

**Side panel:** Displays risk score badge, band classification, and active typology tags fetched from `GET /api/traces/{trace_id}/risk`.

---

### 11. Report Generation (`reports`)

**PDF generation:** WeasyPrint renders a Jinja2 HTML template to PDF. Template sections correspond to required report sections.

**JSON generation:** Pydantic `ReportModel` serialized with `model.model_dump_json(indent=2)`.

**Report structure:**

```python
class ReportModel(BaseModel):
    report_id: UUID
    generated_at: datetime
    generated_by: str
    case_metadata: CaseMetadata
    wallets: list[WalletSummary]
    chains_analyzed: list[str]
    trace_summary: TraceSummary
    attributed_vasps: list[VASPAttribution]
    risk_assessment: RiskAssessment
    typologies: list[TypologyFinding]
    fund_flow_timeline: list[TimelineEvent]
    recommended_action: Literal["monitor", "disclose", "freeze"]
    low_confidence_attributions: list[LowConfidenceAttribution] | None
    content_hash: str  # SHA-256 hex
    supervisor_signature: str | None
```

**Content hash:** `hashlib.sha256(json_bytes).hexdigest()` computed before storage; appended to report metadata.

**Supervisor signing:** `POST /reports/{report_id}/sign` — verifies calling user has `supervisor` role, sets `supervisor_signature = {user_id}:{timestamp}:{report_hash}`, updates `status = "supervisor-approved"`.

**Storage:** PDF stored in object storage at `reports/{case_id}/{trace_id}/{report_id}.pdf`. DB row stores S3 key, JSON payload, content hash, and audit metadata.

---

### 12. SAHYOG Portal Integration (`sahyog`)

**Configuration (Admin-managed, stored encrypted):**

```python
class SAHYOGConfig(BaseModel):
    endpoint_url: str
    auth_type: Literal["api_key", "oauth2"]
    api_key: str | None
    oauth2_client_id: str | None
    oauth2_client_secret: str | None
    oauth2_token_url: str | None
    timeout_seconds: int = 30
```

**Submission payload:**

```python
class SAHYOGSubmissionPayload(BaseModel):
    request_type: Literal["disclosure", "freeze"]
    case_id: str
    case_title: str
    wallet_addresses: list[str]
    report_id: str
    report_hash: str
    report_pdf_base64: str
    evidence_summary: str
    submitted_by: str
    submitted_at: datetime
```

**Retry logic:** Celery task with `max_retries=3`, `countdown=30`. On final failure, `sahyog_submissions.status = "failed"` and Supervisor notification sent.

**Status tracking:** `sahyog_submissions` table records `submission_id`, `case_id`, `request_type`, `status` (pending | acknowledged | rejected | failed), `portal_reference_number`, `submitted_at`, `last_updated`.

---

### 13. LEA Dashboard (`dashboard`)

**API endpoints backing the dashboard:**

| Endpoint | Description |
|---|---|
| `GET /dashboard/summary` | Case stats, active traces count, alert count |
| `GET /dashboard/alerts` | Recent high-risk alerts for current user's scope |
| `GET /dashboard/pending-approvals` | Supervisor queue (supervisor role only) |
| `GET /traces/{id}/progress` | Real-time trace progress (polling or WebSocket) |

**Real-time updates:** FastAPI WebSocket endpoint at `/ws/notifications/{user_id}`. Celery workers push events to Redis pub/sub channel `notifications:{user_id}`; a FastAPI background task subscribes and forwards to connected WebSocket clients.

**Progress calculation:** Trace workers update `trace_jobs.current_hop` and `trace_jobs.estimated_pct` in Redis every 10 seconds. The WebSocket handler reads these and pushes `{"type": "trace_progress", "trace_id": "...", "hop": N, "pct": X}` events.

---

### 14. Audit Trail (`audit`)

**Immutable design:** `audit_logs` table has no `UPDATE` or `DELETE` grants for any application role. Only `INSERT` is permitted. Row-level security ensures no role can modify rows. Admin export is a `SELECT`-only operation.

**Log entry model:**

```python
class AuditLogEntry(Base):
    __tablename__ = "audit_logs"
    id: UUID  # gen_random_uuid()
    timestamp: datetime  # UTC, server-generated, millisecond precision
    actor_user_id: UUID
    action_type: AuditAction  # Enum covering all loggable events
    resource_type: str
    resource_id: UUID
    before_state: dict | None  # JSONB
    after_state: dict | None   # JSONB
    source_ip: str
    session_id: str | None
```

**Middleware:** `AuditMiddleware` is a FastAPI middleware that intercepts all mutating requests and writes log entries post-response. Auth events are logged by the auth service directly.

**Storage alert:** A scheduled task (APScheduler or Celery beat) checks `pg_database_size()` against `AUDIT_MAX_SIZE_BYTES` config. At 80% utilization, an alert is created in `system_alerts` and Admin users are notified.

**Export:** `GET /admin/audit-logs/export?from=&to=&user_id=&action_type=&resource_id=&format=csv|json`. Paginated response for large date ranges; background export job for > 100,000 rows.

---

### 15. Async Task Queue (`tasks`)

**Celery configuration:**

```python
# celery_config.py
CELERY_BROKER_URL = "redis://redis:6379/0"
CELERY_RESULT_BACKEND = "redis://redis:6379/1"
CELERY_TASK_SERIALIZER = "json"
CELERY_ROUTES = {
    "tasks.trace.*": {"queue": "traces"},
    "tasks.report.*": {"queue": "reports"},
    "tasks.sahyog.*": {"queue": "sahyog"},
}
CELERY_WORKER_CONCURRENCY = 8  # per worker node
```

**Queue depth guard (Req 15.5):** FastAPI middleware checks `celery.inspect().active()` + queue length via `LLEN traces` Redis command before accepting new trace submissions. If depth > 100, returns HTTP 429 with `Retry-After: {estimated_seconds}`.

**Job status endpoint:** `GET /traces/{trace_id}/status` returns `{status, current_hop, estimated_pct, started_at, completed_at}`. Workers update status fields in a `trace_jobs` Redis hash.

---

### 16. Security (`security`)

**Input validation:** All request bodies validated by Pydantic v2 with strict mode; all query parameters type-checked. SQL queries use SQLAlchemy ORM (parameterized); no raw string interpolation.

**Rate limiting:** `slowapi` (FastAPI-compatible) with Redis backend; limit `100/minute` per authenticated `user_id`; returns HTTP 429 with `X-RateLimit-*` headers.

**HTTPS enforcement:** Nginx config redirects all HTTP → HTTPS (301). FastAPI sets `Strict-Transport-Security: max-age=31536000; includeSubDomains`.

**Encryption at rest:** PostgreSQL columns for `wallet_addresses.address`, `cases.*`, `audit_logs.*`, and `reports.*` are encrypted using pgcrypto `pgp_sym_encrypt` with the key sourced from environment variable `DB_ENCRYPTION_KEY`. PDF reports in object storage use server-side AES-256 encryption.

---

## Data Models

### Entity Relationship Diagram (summary)

```
users ──► cases ──► case_wallets ──► wallet_addresses
  │           │                            │
  │           ▼                            ▼
  │     audit_logs                    trace_jobs
  │                                        │
  │                                        ▼
  │                               trace_graphs (JSONB)
  │                                        │
  │                               ┌────────┴────────┐
  │                            clusters         attributions
  │                                │                  │
  │                            vasp_addresses ◄── vasps
  │                                               risk_scores
  │                                               typology_tags
  │
  └──► reports ──► sahyog_submissions
```

### Key Table Schemas

```sql
-- Wallet trace jobs
CREATE TABLE trace_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id UUID NOT NULL REFERENCES cases(id),
    wallet_address TEXT NOT NULL,
    chain TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',  -- queued|running|completed|failed|rate-limited
    celery_task_id TEXT,
    current_hop INT DEFAULT 0,
    max_hops INT DEFAULT 5,
    estimated_pct NUMERIC(5,2),
    enqueued_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    needs_reattribution BOOLEAN DEFAULT FALSE,
    risk_score INT,
    risk_score_prev INT,
    risk_band TEXT
);

-- Address clusters
CREATE TABLE clusters (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trace_id UUID NOT NULL REFERENCES trace_jobs(id),
    chain TEXT NOT NULL,
    addresses JSONB NOT NULL,  -- array of address strings
    cluster_method TEXT NOT NULL,  -- cio | deposit_pattern
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- VASP attributions
CREATE TABLE attributions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cluster_id UUID NOT NULL REFERENCES clusters(id),
    vasp_id UUID NOT NULL REFERENCES vasps(id),
    confidence_score NUMERIC(5,2) NOT NULL,
    low_confidence BOOLEAN GENERATED ALWAYS AS (confidence_score < 40) STORED,
    address_match_ratio NUMERIC(5,4),
    volume_similarity NUMERIC(5,4),
    behavioral_similarity NUMERIC(5,4),
    temporal_proximity NUMERIC(5,4),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Typology detection results
CREATE TABLE typology_tags (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trace_id UUID NOT NULL REFERENCES trace_jobs(id),
    address TEXT NOT NULL,
    typology TEXT NOT NULL,
    match_confidence NUMERIC(5,4) NOT NULL,
    sub_graph JSONB,  -- NetworkX node_link_data of triggering sub-graph
    detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

---

## API Design

### Authentication Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/auth/login` | — | Submit credentials, receive token pair |
| POST | `/auth/refresh` | Refresh token | Exchange refresh token for new access token |
| POST | `/auth/logout` | Bearer | Invalidate refresh token |

### Case Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/cases` | investigator+ | Create case |
| GET | `/cases` | investigator+ | List/search cases (role-filtered) |
| GET | `/cases/{id}` | investigator+ | Get case details |
| PATCH | `/cases/{id}` | investigator+ | Update case |
| DELETE | `/cases/{id}` | investigator+ | Soft-delete case |

### Wallet & Trace Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/cases/{id}/wallets` | investigator+ | Submit wallet(s) |
| GET | `/cases/{id}/wallets` | investigator+ | List wallets in case |
| GET | `/traces/{trace_id}/status` | investigator+ | Poll trace job status |
| GET | `/traces/{trace_id}/graph` | investigator+ | Retrieve graph JSON |
| GET | `/traces/{trace_id}/risk` | investigator+ | Risk score + typology tags |
| GET | `/traces/{trace_id}/attributions` | investigator+ | VASP attributions |

### Report Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/traces/{trace_id}/reports` | investigator+ | Generate report |
| GET | `/reports/{id}` | investigator+ | Download report (PDF/JSON) |
| POST | `/reports/{id}/sign` | supervisor+ | Supervisor sign |
| POST | `/reports/{id}/submit-sahyog` | supervisor+ | Route to SAHYOG Portal |

### Admin Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| GET/POST/PATCH | `/admin/users` | admin | User management |
| GET/POST/PATCH/DELETE | `/admin/vasps` | admin | VASP DB management |
| POST | `/admin/vasps/import` | admin | Bulk CSV import |
| GET | `/admin/vasps/search` | authenticated | VASP search (read-only) |
| GET | `/admin/audit-logs/export` | admin | Export audit logs |
| POST | `/admin/typology-definitions` | admin | Upload classifier definitions |
| GET/POST | `/admin/config` | admin | System configuration |

### WebSocket

| Path | Description |
|---|---|
| `/ws/notifications/{user_id}` | Real-time alerts and trace progress |

---

## Error Handling

| Scenario | HTTP Code | Response Body |
|---|---|---|
| Invalid JWT / expired | 401 | `{"detail": "Token invalid or expired"}` |
| Insufficient role | 403 | `{"detail": "Action not permitted for role {role}"}` |
| Validation failure | 400 | `{"detail": [{field, msg}]}` (Pydantic format) |
| Resource not found | 404 | `{"detail": "{Resource} not found"}` |
| Rate limit (user) | 429 | `{"detail": "Rate limit exceeded"}` + `Retry-After` header |
| Queue depth exceeded | 429 | `{"detail": "Trace queue full", "retry_after": N}` |
| Adapter data unavailable | 202 | Trace accepted, segment marked `data-unavailable` |
| SAHYOG submission failure | — | Queued for retry; Supervisor notified asynchronously |
| Internal server error | 500 | `{"detail": "Internal error", "error_id": uuid}` (no stack trace exposed) |

---

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

---

### Property 1: Valid login always returns a token pair

*For any* valid (username, password) credential pair registered in the system, submitting them to the login endpoint SHALL return a response containing both a signed JWT access token and a refresh token with non-null, non-empty values.

**Validates: Requirements 1.2**

---

### Property 2: Invalid or expired tokens are always rejected

*For any* request to a protected endpoint carrying a token that is expired, malformed, or signed with a wrong key, the system SHALL return HTTP 401 and SHALL NOT process the request.

**Validates: Requirements 1.3**

---

### Property 3: Role permission enforcement is exhaustive

*For any* authenticated user with a given role and *for any* API action, if that action is not in the role's permitted set, the system SHALL return HTTP 403. Conversely, if that action is in the role's permitted set, the system SHALL NOT return HTTP 403 for that action alone.

**Validates: Requirements 1.4, 1.5, 1.6, 1.7, 1.8**

---

### Property 4: Every authentication event produces an audit log entry

*For any* authentication event (successful login, failed login, token refresh, logout), the audit log SHALL contain an entry with the correct actor user ID, timestamp, action type, and source IP within the same request lifecycle.

**Validates: Requirements 1.9, 14.1, 14.2**

---

### Property 5: Case creation invariant

*For any* valid case creation request by an authenticated investigator, the created case SHALL have a unique Case ID not matching any existing case, the `created_by` field SHALL equal the requesting user's ID, and `status` SHALL be "open".

**Validates: Requirements 2.2, 2.3**

---

### Property 6: Case soft-delete preserves associated data

*For any* case with associated wallet addresses, traces, and reports, performing a soft-delete on that case SHALL NOT remove any associated records; all such records SHALL remain retrievable and SHALL be marked `archived=True`.

**Validates: Requirements 2.4**

---

### Property 7: Under-review cases block investigator modifications

*For any* case with `status = "under_review"`, any attempt by a user with the "investigator" role to modify traces or reports associated with that case SHALL return HTTP 403.

**Validates: Requirements 2.5**

---

### Property 8: Case status changes produce audit entries

*For any* transition between case statuses, the audit log SHALL contain an entry recording the actor user ID, timestamp, previous status, and new status.

**Validates: Requirements 2.6**

---

### Property 9: Case search filter consistency

*For any* combination of filter parameters (title keyword, status, assigned investigator, date range, wallet address), the set of cases returned by the search endpoint SHALL consist exclusively of cases that satisfy ALL provided filter predicates.

**Validates: Requirements 2.7**

---

### Property 10: Address format validation correctness

*For any* string submitted as a wallet address, the validation logic SHALL accept it if and only if it matches the canonical format of at least one Supported Chain. Any string that does not match any chain's format SHALL be rejected with HTTP 400.

**Validates: Requirements 3.2, 3.3**

---

### Property 11: Trace enqueue on valid wallet submission

*For any* validated wallet address submitted to an existing case, a trace job SHALL be enqueued in the task queue with the correct chain identifier and SHALL be linked to the submitting case.

**Validates: Requirements 3.4**

---

### Property 12: Batch size invariant

*For any* batch submission of wallet addresses, the system SHALL accept all addresses if the batch size is in [1, 50] and SHALL reject the entire batch with HTTP 400 if the batch size exceeds 50.

**Validates: Requirements 3.5**

---

### Property 13: Submission idempotency within 24 hours

*For any* wallet address that has an existing trace job that was enqueued or completed within the last 24 hours in the same case, re-submitting that address SHALL return the existing trace ID and SHALL NOT enqueue a new trace job.

**Validates: Requirements 3.6**

---

### Property 14: Retry backoff sequence correctness

*For any* blockchain adapter call that receives a rate-limit response, the sequence of retry delays SHALL be exponential starting at 1 second with a cap of 60 seconds, and the adapter SHALL make no more than 5 retry attempts before marking the segment as "rate-limited" or "data-unavailable".

**Validates: Requirements 4.4, 4.5**

---

### Property 15: Cache age is always reported for cached responses

*For any* trace segment where the underlying blockchain data was served from cache rather than a live API call, the trace result metadata SHALL include a non-null `cache_age_seconds` value greater than zero.

**Validates: Requirements 4.7**

---

### Property 16: Graph node metrics completeness

*For any* constructed transaction graph, every node in the graph SHALL have non-null values for all six required metrics: in-degree, out-degree, total inflow, total outflow, first-seen timestamp, and last-seen timestamp.

**Validates: Requirements 5.1, 5.4**

---

### Property 17: Graph construction round-trip

*For any* constructed graph that is persisted to the database, retrieving that graph by trace ID SHALL produce a graph with the same set of nodes, the same set of directed edges, and identical edge attributes as the originally constructed graph.

**Validates: Requirements 5.5**

---

### Property 18: VASP match triggers attribution

*For any* cluster containing at least one address that exists in the VASP Database's seed address set, the attribution pipeline SHALL produce an `Attribution` record linked to that cluster and the matching VASP, with a non-null confidence score in [0, 100].

**Validates: Requirements 6.3, 6.4**

---

### Property 19: Confidence score formula correctness

*For any* set of four attribution input scores (address match ratio, volume similarity, behavioral similarity, temporal proximity), each in [0, 1], the computed confidence score SHALL equal `(0.4 * r + 0.3 * v + 0.2 * b + 0.1 * t) * 100` rounded to two decimal places, and SHALL be in [0, 100].

**Validates: Requirements 6.5**

---

### Property 20: Low-confidence attribution classification

*For any* attribution whose computed confidence score is strictly less than 40, the attribution SHALL be marked `low_confidence=True` and SHALL appear in the "low-confidence attributions" section of any generated report for that trace.

**Validates: Requirements 6.6, 11.4**

---

### Property 21: Special typology flags for known entities

*For any* address that exists in the VASP Database with `category = "mixer"` or `category = "bridge"`, the attribution pipeline SHALL assign the corresponding typology tag ("obfuscation service" or "cross-chain bridge") to that address regardless of confidence score.

**Validates: Requirements 6.7, 6.8**

---

### Property 22: VASP update invalidates related cache

*For any* update to a VASP record's address set, all cached attributions that reference addresses from that VASP SHALL be invalidated, and the affected trace jobs SHALL be marked `needs_reattribution=True`.

**Validates: Requirements 7.3**

---

### Property 23: CSV import partial failure tolerance

*For any* CSV import file containing a mix of valid and invalid rows, the import SHALL successfully create records for all valid rows and SHALL produce an error entry for each invalid row, without aborting the entire import.

**Validates: Requirements 7.4, 7.5**

---

### Property 24: VASP search accessible to all authenticated users

*For any* authenticated user regardless of role, a request to the VASP search endpoint SHALL return HTTP 200 (or 404 for no results) and SHALL NOT return HTTP 403.

**Validates: Requirements 7.6**

---

### Property 25: Risk score is always in [0, 100]

*For any* completed trace, the computed risk score SHALL be an integer value in the closed interval [0, 100].

**Validates: Requirements 8.1, 8.2**

---

### Property 26: Risk band classification correctness

*For any* risk score value s, the assigned band SHALL be "Low" if s ∈ [0, 39], "Medium" if s ∈ [40, 69], and "High" if s ∈ [70, 100].

**Validates: Requirements 8.3**

---

### Property 27: High-risk score triggers alert creation

*For any* wallet address whose computed risk score is ≥ 70, the system SHALL create a `RiskAlert` record linked to the parent case and SHALL deliver a notification to the assigned supervisor via the in-platform notification system.

**Validates: Requirements 8.4**

---

### Property 28: Significant risk score change is audited and notified

*For any* wallet address whose risk score changes by more than 10 points due to updated data, the system SHALL write an audit log entry recording the old and new scores, and SHALL send a notification to the assigned investigator.

**Validates: Requirements 8.6**

---

### Property 29: Typology detections above threshold are tagged

*For any* typology detection result with `match_confidence >= 0.60`, the corresponding address or sub-graph SHALL receive the associated typology label and confidence score as a persisted `TypologyTag` record linked to the trace.

**Validates: Requirements 9.2, 9.3, 9.4**

---

### Property 30: Report content completeness

*For any* generated report (PDF or JSON), the report SHALL contain all required sections: case metadata, wallet addresses, chains analyzed, trace summary, attributed VASPs with confidence scores, risk assessment, typologies with supporting descriptions, fund flow timeline, and recommended action.

**Validates: Requirements 11.3**

---

### Property 31: Report content hash integrity

*For any* generated report, the SHA-256 hash stored in the report metadata SHALL equal `sha256(report_content_bytes)`. Any modification to the report content after generation SHALL produce a hash mismatch detectable by recomputation.

**Validates: Requirements 11.5**

---

### Property 32: Report generation is always audited

*For any* report generation event, the audit log SHALL contain an entry recording the report ID, generating user ID, case ID, trace ID, and timestamp.

**Validates: Requirements 11.6, 14.1**

---

### Property 33: SAHYOG submission status always recorded

*For any* SAHYOG Portal API response (acknowledged, rejected, or error), the submission status in the `sahyog_submissions` table SHALL be updated to reflect the portal's response, and the portal-assigned reference number (if provided) SHALL be stored.

**Validates: Requirements 12.3**

---

### Property 34: Audit log entries are immutable

*For any* audit log entry, any attempt by any user role (including admin) to delete or modify that entry via any API endpoint SHALL be rejected with a non-2xx HTTP response.

**Validates: Requirements 14.3**

---

### Property 35: Audit log entry schema completeness

*For any* audit log entry, all required fields SHALL be non-null: entry ID, UTC timestamp with millisecond precision, actor user ID, action type, resource type, resource ID, and source IP address.

**Validates: Requirements 14.2**

---

### Property 36: Queue depth cap enforces HTTP 429

*For any* new trace submission request when the task queue depth exceeds 100 pending jobs, the system SHALL return HTTP 429 with a `Retry-After` header containing a positive integer representing the estimated wait time in seconds.

**Validates: Requirements 15.5**

---

### Property 37: Password hashing uses bcrypt with cost ≥ 12

*For any* stored password hash in the system, the hash SHALL be a valid bcrypt hash with a cost factor of at least 12. No plaintext passwords SHALL be stored or logged.

**Validates: Requirements 16.1**

---

### Property 38: Per-user API rate limiting

*For any* authenticated user who sends more than 100 requests within any 60-second window, all requests beyond the 100th SHALL receive HTTP 429 responses with `Retry-After` and `X-RateLimit-*` headers.

**Validates: Requirements 16.4**

---

### Property 39: Account lockout after 5 consecutive failures

*For any* user account, after exactly 5 consecutive failed login attempts, the account SHALL be locked and all subsequent authentication attempts for that account SHALL return a non-200 response for at least 15 minutes, after which normal authentication SHALL be permitted again.

**Validates: Requirements 16.6**

---

### Property 40: Input sanitization prevents injection

*For any* user-supplied input string containing SQL injection patterns, XSS payloads, or command injection characters, the system SHALL sanitize or reject the input such that no injected content is executed against the database, HTML renderer, or shell.

**Validates: Requirements 16.3**

---

## Components and Interfaces

### Backend Component Interfaces

#### `BlockchainAdapter` (Abstract Base Class)

```python
class BlockchainAdapter(ABC):
    chain: str  # Chain identifier: BTC | ETH | TRX | BSC | SOL | MATIC

    @abstractmethod
    async def get_transactions(
        self,
        address: str,
        *,
        page: int = 1,
        page_size: int = 100,
    ) -> list[RawTransaction]:
        """Fetch paginated transaction list for the given address."""

    @abstractmethod
    async def get_address_info(self, address: str) -> AddressInfo:
        """Fetch balance and basic metadata for the given address."""

    async def health_check(self) -> bool:
        """Verify the upstream API is reachable. Default implementation attempts get_address_info on a known address."""
        ...
```

Concrete implementations: `MempoolAdapter`, `EtherscanAdapter`, `TronscanAdapter`, `BscScanAdapter`, `SolscanAdapter`, `PolygonscanAdapter`.

#### `TypologyDetector` (Protocol)

```python
class TypologyDetector(Protocol):
    typology_name: str

    def detect(
        self,
        G: nx.DiGraph,
        address: str,
    ) -> DetectionResult | None:
        """
        Evaluate the subgraph around `address` for typology patterns.
        Returns DetectionResult with match_confidence in [0, 1],
        or None if no match.
        """
```

#### `RiskScorer` Interface

```python
class RiskScorer(Protocol):
    def compute(
        self,
        trace_id: UUID,
        address: str,
        graph: nx.DiGraph,
        attributions: list[Attribution],
        typology_tags: list[TypologyTag],
    ) -> RiskScoreResult:
        """
        Compute integer risk score [0–100] and band for the given address.
        """
```

#### `ReportRenderer` Interface

```python
class ReportRenderer(Protocol):
    def render(
        self,
        report_model: ReportModel,
        format: Literal["pdf", "json"],
    ) -> bytes:
        """Render the report to bytes in the requested format."""
```

Implementations: `WeasyPrintPDFRenderer`, `PydanticJSONRenderer`.

#### `SAHYOGClient` Interface

```python
class SAHYOGClient(Protocol):
    async def submit(
        self,
        payload: SAHYOGSubmissionPayload,
    ) -> SAHYOGSubmissionResponse:
        """
        Transmit a disclosure or freeze request to the SAHYOG Portal.
        Raises SAHYOGAPIError on non-2xx response.
        """
```

### Frontend Component Interfaces

#### `GraphViewer` (React Component)

Props:
```typescript
interface GraphViewerProps {
  traceId: string;
  onNodeSelect?: (nodeId: string, metadata: NodeMetadata) => void;
  onExport?: (format: "png" | "json") => void;
  progressiveRenderThreshold?: number; // default: 500 nodes
}
```

#### `RiskPanel` (React Component)

Props:
```typescript
interface RiskPanelProps {
  traceId: string;
  riskScore: number;
  band: "Low" | "Medium" | "High";
  typologyTags: TypologyTag[];
}
```

#### `NotificationProvider` (React Context)

Manages a persistent WebSocket connection to `/ws/notifications/{userId}` and exposes:
```typescript
interface NotificationContext {
  alerts: Alert[];
  traceProgress: Record<string, TraceProgress>;
  markRead: (alertId: string) => void;
}
```

### Service-to-Service Interfaces

| Producer | Consumer | Transport | Schema |
|---|---|---|---|
| FastAPI routes | Celery workers | Redis broker | Celery task JSON |
| Celery workers | FastAPI WebSocket handler | Redis pub/sub | `notifications:{user_id}` channel |
| PostgreSQL NOTIFY | Adapter listener | `pg_notify` | `vasp_updated:{vasp_id}` channel |
| FastAPI | SAHYOG Portal | HTTPS REST/SOAP | `SAHYOGSubmissionPayload` |

---

## Testing Strategy

### Unit Tests (pytest)

**Scope:** Pure logic — validators, scorers, formatters, serializers.

Key unit test areas:
- Address format validators for all six chains (valid and invalid examples per chain)
- Confidence score formula (`compute_confidence_score`) with boundary inputs
- Risk score formula (`compute_risk_score`) with boundary inputs and band classification
- Risk band classification at thresholds (39/40, 69/70)
- Report content hash: compute hash, mutate content, verify mismatch
- CSV import row validation (missing columns, invalid address, valid row)
- Audit log middleware: verify entry fields are populated correctly for each event type

### Property-Based Tests (Hypothesis)

Property tests implement the correctness properties defined in the Correctness Properties section. Each test uses `@given` strategies to generate inputs.

**Configuration:** Minimum 100 examples per property (`settings(max_examples=100)`).

Key property tests:

```python
# Property 10: Address format validation correctness
@given(st.text())
def test_address_validation_is_consistent(address: str):
    result = validate_wallet_address(address)
    if result.valid:
        assert any(validate_for_chain(address, chain) for chain in SUPPORTED_CHAINS)
    else:
        assert all(not validate_for_chain(address, chain) for chain in SUPPORTED_CHAINS)

# Property 19: Confidence score formula correctness
@given(
    st.floats(0, 1), st.floats(0, 1), st.floats(0, 1), st.floats(0, 1)
)
def test_confidence_score_formula(r, v, b, t):
    expected = round((0.4*r + 0.3*v + 0.2*b + 0.1*t) * 100, 2)
    result = compute_confidence_score(r, v, b, t)
    assert abs(result - expected) < 0.01
    assert 0 <= result <= 100

# Property 25 + 26: Risk score range and band
@given(
    st.floats(0, 1), st.floats(0, 1), st.floats(0, 1),
    st.floats(0, 1), st.floats(0, 1)
)
def test_risk_score_range_and_band(de, ie, vc, tf, va):
    score = compute_risk_score(de, ie, vc, tf, va)
    assert isinstance(score, int)
    assert 0 <= score <= 100
    band = classify_risk_band(score)
    if score <= 39:
        assert band == "Low"
    elif score <= 69:
        assert band == "Medium"
    else:
        assert band == "High"

# Property 16: Graph node metrics completeness
@given(generate_transaction_dataset())
def test_graph_node_metrics_completeness(transactions):
    G = build_graph_from_transactions(transactions)
    for node in G.nodes:
        attrs = G.nodes[node]
        assert attrs["in_degree"] is not None
        assert attrs["out_degree"] is not None
        assert attrs["total_inflow"] is not None
        assert attrs["total_outflow"] is not None
        assert attrs["first_seen"] is not None
        assert attrs["last_seen"] is not None

# Property 13: Submission idempotency
@given(generate_wallet_submission())
def test_resubmission_returns_existing_trace(wallet_data):
    trace_id_1 = submit_wallet(wallet_data)
    trace_id_2 = submit_wallet(wallet_data)  # within 24 hours
    assert trace_id_1 == trace_id_2

# Property 34: Audit log immutability
@given(generate_audit_log_entry())
def test_audit_log_immutable(entry):
    entry_id = write_audit_log(entry)
    with pytest.raises(PermissionError):
        delete_audit_log(entry_id)
    with pytest.raises(PermissionError):
        update_audit_log(entry_id, {"action_type": "tampered"})
```

### Integration Tests

Integration tests run against a test PostgreSQL + Redis stack (Docker Compose):

- End-to-end trace execution with mocked blockchain adapters returning fixture data
- VASP database bulk import with mixed valid/invalid CSV rows
- SAHYOG Portal submission with mock server (WireMock or `respx`)
- Audit log completeness: perform each auditable action, verify log entry exists
- Retry backoff: mock rate-limited adapter, verify retry count and delay sequence

### Performance Tests (locust or pytest-benchmark)

- Dashboard API response time under 10,000 cases dataset
- Graph construction memory footprint for graphs of 1k, 5k, and 10k nodes
- Concurrent trace job throughput (20 simultaneous jobs)

### Security Tests

- Penetration test inputs for SQL injection, XSS, and path traversal via Pydantic validation
- JWT signature verification: tampered tokens must return 401
- Account lockout: verify 5-failure lockout and 15-minute recovery
- Rate limit: verify 429 after 100 requests/minute per user
