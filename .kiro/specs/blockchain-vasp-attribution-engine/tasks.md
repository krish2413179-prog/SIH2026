# Implementation Plan: Blockchain Intelligence & VASP Attribution Engine

## Overview

Implement the full-stack Blockchain Intelligence & VASP Attribution Engine using Python 3.11+ / FastAPI for the backend and React / Next.js for the frontend. The implementation proceeds in layers: infrastructure and data models first, then core backend services (auth, cases, wallets, adapters, graph, clustering, risk, typology), then reporting and integrations, then the frontend UI, and finally the async task infrastructure wiring everything together.

---

## Tasks

- [x] 1. Project scaffold and infrastructure setup
  - Initialize Python project with `pyproject.toml` (FastAPI, SQLAlchemy, Alembic, Celery, Redis, passlib, python-jose, pydantic v2, httpx, networkx, weasyprint, hypothesis, pytest, slowapi, orjson)
  - Initialize Next.js project under `frontend/` with TypeScript, Tailwind CSS, Cytoscape.js, and React Query
  - Write `docker-compose.yml` for PostgreSQL 15, Redis 7, and the app services (api, worker, frontend)
  - Create Alembic migration environment and initial `alembic.ini`
  - Configure Nginx `nginx.conf` enforcing HTTPS redirect and upstream proxy to FastAPI
  - Set up pgcrypto extension migration and `DB_ENCRYPTION_KEY` env-var plumbing
  - _Requirements: 15, 16.2_

- [x] 2. Database schema migrations
  - [x] 2.1 Create initial Alembic migration for `users`, `org_units`, `jwt_keys` tables
    - Include bcrypt `password_hash` column, `role` enum, `org_unit_id` FK
    - Add `failed_login_attempts` int and `locked_until` timestamptz columns
    - _Requirements: 1.1, 1.4, 16.1, 16.6_
  - [x] 2.2 Create Alembic migration for `cases`, `case_wallets`, `wallet_addresses` tables
    - Include pgcrypto `pgp_sym_encrypt` on sensitive `wallet_addresses.address`
    - Add `deleted_at` nullable timestamp for soft-delete, `status` enum, full-text search index on `title || description`
    - _Requirements: 2.2, 2.3, 2.4, 3.7_
  - [x] 2.3 Create Alembic migration for `trace_jobs`, `trace_graphs`, `clusters`, `attributions`, `typology_tags`, `risk_scores` tables
    - Include JSONB columns for `graph_data`, `addresses`, `sub_graph`
    - Add generated column `low_confidence` on `attributions`
    - _Requirements: 5.5, 6.9, 9.4_
  - [x] 2.4 Create Alembic migration for `vasps`, `vasp_addresses`, `sahyog_submissions`, `reports`, `audit_logs`, `system_alerts`, `typology_definitions` tables
    - `audit_logs` — INSERT-only via PostgreSQL role grants; no UPDATE/DELETE
    - `sahyog_submissions` status enum; `reports` S3 key + JSON payload
    - _Requirements: 7.1, 11.6, 12.3, 14.3_

- [x] 3. Authentication & authorization module (`app/auth/`)
  - [x] 3.1 Implement `create_token_pair`, `verify_token`, and `refresh_access_token` functions
    - Use `python-jose` with HS256; configurable secret and expiry; `jwt_keys` table multi-key lookup for rotation support
    - _Requirements: 1.1, 1.2, 1.3, 16.7_
  - [x]* 3.2 Write property test for token pair creation and rejection (Properties 1, 2)
    - **Property 1: Valid login always returns a token pair**
    - **Property 2: Invalid or expired tokens are always rejected**
    - **Validates: Requirements 1.2, 1.3**
  - [x] 3.3 Implement `RBAC` dependency (FastAPI `Depends`) and permission matrix for investigator / supervisor / admin roles
    - Raise HTTP 403 with descriptive message on unauthorized actions
    - _Requirements: 1.4, 1.5, 1.6, 1.7, 1.8_
  - [ ]* 3.4 Write property test for RBAC exhaustiveness (Property 3)
    - **Property 3: Role permission enforcement is exhaustive**
    - **Validates: Requirements 1.4, 1.5, 1.6, 1.7, 1.8**
  - [x] 3.5 Implement login, refresh, and logout endpoints (`POST /auth/login`, `POST /auth/refresh`, `POST /auth/logout`)
    - Store bcrypt hash with `rounds=12`; Redis counter for failed attempts; lock account for 15 min at 5th failure
    - _Requirements: 1.1, 1.2, 16.1, 16.6_
  - [ ]* 3.6 Write property test for account lockout after 5 consecutive failures (Property 39)
    - **Property 39: Account lockout after 5 consecutive failures**
    - **Validates: Requirements 16.6**
  - [ ]* 3.7 Write property test for password hashing (Property 37)
    - **Property 37: Password hashing uses bcrypt with cost ≥ 12**
    - **Validates: Requirements 16.1**
  - [x] 3.8 Implement `AuditMiddleware` FastAPI middleware that logs auth and all mutating requests post-response
    - _Requirements: 1.9, 14.1, 14.2_
  - [ ]* 3.9 Write property test for audit log on every auth event (Property 4)
    - **Property 4: Every authentication event produces an audit log entry**
    - **Validates: Requirements 1.9, 14.1, 14.2**

- [x] 4. Case management module (`app/cases/`)
  - [x] 4.1 Implement `Case` SQLAlchemy model, Pydantic schemas, and CRUD service
    - Soft-delete via `deleted_at`; state-machine transitions (open → under_review → closed); audit log on every status change
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.6_
  - [ ]* 4.2 Write property test for case creation invariant (Property 5)
    - **Property 5: Case creation invariant**
    - **Validates: Requirements 2.2, 2.3**
  - [ ]* 4.3 Write property test for soft-delete preserves associated data (Property 6)
    - **Property 6: Case soft-delete preserves associated data**
    - **Validates: Requirements 2.4**
  - [x] 4.4 Implement case REST endpoints (`POST /cases`, `GET /cases`, `GET /cases/{id}`, `PATCH /cases/{id}`, `DELETE /cases/{id}`)
    - Role-filtered list; supervisor can see all org-unit cases; under-review blocks investigator modifications (HTTP 403)
    - _Requirements: 2.1, 2.5, 2.7_
  - [x]* 4.5 Write property test for under-review blocking (Property 7)
    - **Property 7: Under-review cases block investigator modifications**
    - **Validates: Requirements 2.5**
  - [x]* 4.6 Write property test for case status change audit entries (Property 8)
    - **Property 8: Case status changes produce audit entries**
    - **Validates: Requirements 2.6**
  - [x]* 4.7 Write property test for case search filter consistency (Property 9)
    - **Property 9: Case search filter consistency**
    - **Validates: Requirements 2.7**

- [x] 5. Checkpoint — Ensure all tests pass for auth and case modules
  - Ensure all unit and property tests pass for modules 3 and 4; ask the user if questions arise.

- [x] 6. Wallet address submission module (`app/wallets/`)
  - [x] 6.1 Implement per-chain address format validators (regex + length) for BTC, ETH, TRX, BSC, SOL, MATIC
    - Return `detected_chains` list for multi-chain matching (EVM-compatible overlap)
    - _Requirements: 3.2, 3.3_
  - [ ]* 6.2 Write property test for address format validation correctness (Property 10)
    - **Property 10: Address format validation correctness**
    - **Validates: Requirements 3.2, 3.3**
  - [x] 6.3 Implement wallet submission endpoint (`POST /cases/{id}/wallets`) with batch support (up to 50 addresses)
    - Deduplication check against `trace_jobs` within 24 hours; return existing `trace_id` if found
    - Enqueue Celery trace job for each validated address/chain pair
    - _Requirements: 3.1, 3.4, 3.5, 3.6, 3.7_
  - [ ]* 6.4 Write property test for batch size invariant (Property 12)
    - **Property 12: Batch size invariant**
    - **Validates: Requirements 3.5**
  - [ ]* 6.5 Write property test for submission idempotency within 24 hours (Property 13)
    - **Property 13: Submission idempotency within 24 hours**
    - **Validates: Requirements 3.6**
  - [ ]* 6.6 Write property test for trace enqueue on valid wallet submission (Property 11)
    - **Property 11: Trace enqueue on valid wallet submission**
    - **Validates: Requirements 3.4**

- [ ] 7. Blockchain data adapters (`app/adapters/`)
  - [ ] 7.1 Implement `BlockchainAdapter` abstract base class with `get_transactions`, `get_address_info`, `health_check`
    - Implement `_fetch_with_retry` mixin: exponential backoff (base 1s, max 60s), 5 retries, `RateLimitedError` / `DataUnavailableError`
    - _Requirements: 4.2, 4.4, 4.5_
  - [ ]* 7.2 Write property test for retry backoff sequence correctness (Property 14)
    - **Property 14: Retry backoff sequence correctness**
    - **Validates: Requirements 4.4, 4.5**
  - [ ] 7.3 Implement Redis cache layer in the adapter base: key `blockchain:{chain}:{address}:{page}`, TTL config (default 1800s), `cache_age_seconds` metadata
    - _Requirements: 4.6, 4.7_
  - [ ]* 7.4 Write property test for cache age always reported for cached responses (Property 15)
    - **Property 15: Cache age is always reported for cached responses**
    - **Validates: Requirements 4.7**
  - [x] 7.5 Implement concrete adapters: `MempoolAdapter` (BTC), `EtherscanAdapter` (ETH), `TronscanAdapter` (TRX), `BscScanAdapter` (BSC), `SolscanAdapter` (SOL), `PolygonscanAdapter` (MATIC)
    - Adapter registry dict `ADAPTER_REGISTRY = {chain: adapter_class}` populated from config
    - _Requirements: 4.1, 4.2_

- [x] 8. Transaction graph construction module (`app/graph/`)
  - [x] 8.1 Implement `build_graph` function using NetworkX `DiGraph`
    - BFS traversal up to `max_hops` (default 5, max 10); per-node metrics (in-degree, out-degree, total_inflow, total_outflow, first_seen, last_seen); cross-chain bridge edge tagging
    - Memory guard: `GraphSizeWarning` at 10k nodes; prune low-value edges (10th percentile) above 50k edges
    - _Requirements: 5.1, 5.2, 5.3, 5.4_
  - [ ]* 8.2 Write property test for graph node metrics completeness (Property 16)
    - **Property 16: Graph node metrics completeness**
    - **Validates: Requirements 5.1, 5.4**
  - [x] 8.3 Implement graph persistence: serialize with NetworkX `node_link_data` to JSONB in `trace_graphs` table; implement `get_graph` retrieval by trace ID
    - _Requirements: 5.5_
  - [ ]* 8.4 Write property test for graph construction round-trip (Property 17)
    - **Property 17: Graph construction round-trip**
    - **Validates: Requirements 5.5**
  - [x] 8.5 Wire `build_graph` into Celery trace task: fetch via adapter → build graph → persist → advance to clustering
    - Expose `GET /traces/{trace_id}/graph` endpoint
    - _Requirements: 5.5, 15.4_

- [x] 9. Checkpoint — Ensure all tests pass for adapters and graph modules
  - Ensure all unit and property tests pass for modules 7 and 8; ask the user if questions arise.

- [ ] 10. VASP database module (`app/vasp_db/`)
  - [x] 10.1 Implement `VASP` and `VASPAddress` SQLAlchemy models and CRUD admin endpoints
    - `PATCH /admin/vasps/{id}` triggers `pg_notify('vasp_updated:{vasp_id}', ...)` and marks affected traces `needs_reattribution=True`
    - _Requirements: 7.1, 7.2, 7.3_
  - [ ]* 10.2 Write property test for VASP update cache invalidation (Property 22)
    - **Property 22: VASP update invalidates related cache**
    - **Validates: Requirements 7.3**
  - [ ] 10.3 Implement bulk CSV import endpoint (`POST /admin/vasps/import`)
    - Stream with `csv.DictReader`; Pydantic per-row validation; commit in batches of 500; return per-row error list
    - _Requirements: 7.4, 7.5_
  - [ ]* 10.4 Write property test for CSV import partial failure tolerance (Property 23)
    - **Property 23: CSV import partial failure tolerance**
    - **Validates: Requirements 7.4, 7.5**
  - [ ] 10.5 Implement read-only VASP search endpoint (`GET /admin/vasps/search`) accessible to all authenticated roles
    - _Requirements: 7.6_
  - [ ]* 10.6 Write property test for VASP search accessible to all authenticated users (Property 24)
    - **Property 24: VASP search accessible to all authenticated users**
    - **Validates: Requirements 7.6**

- [ ] 11. Address clustering and entity attribution module (`app/clustering/`)
  - [x] 11.1 Implement Common-Input Ownership (CIO) heuristic for Bitcoin using Union-Find on co-spent inputs
    - Implement deposit-address pattern heuristic for EVM chains, TRX, SOL (≥10 unique senders within 24h)
    - _Requirements: 6.1, 6.2_
  - [ ] 11.2 Implement attribution pipeline: cluster → VASP DB lookup → `compute_confidence_score` → emit `Attribution` records
    - Formula: `(0.4 * addr_ratio + 0.3 * vol_sim + 0.2 * behav_sim + 0.1 * temp_prox) * 100`
    - Flag `low_confidence=True` when score < 40; apply mixer/bridge typology tags from VASP category
    - Persist clusters, attributions, scores linked to `trace_id`
    - _Requirements: 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.9_
  - [ ]* 11.3 Write property test for confidence score formula correctness (Property 19)
    - **Property 19: Confidence score formula correctness**
    - **Validates: Requirements 6.5**
  - [ ]* 11.4 Write property test for VASP match triggers attribution (Property 18)
    - **Property 18: VASP match triggers attribution**
    - **Validates: Requirements 6.3, 6.4**
  - [ ]* 11.5 Write property test for low-confidence attribution classification (Property 20)
    - **Property 20: Low-confidence attribution classification**
    - **Validates: Requirements 6.6, 11.4**
  - [ ]* 11.6 Write property test for special typology flags for known entities (Property 21)
    - **Property 21: Special typology flags for known entities**
    - **Validates: Requirements 6.7, 6.8**
  - [ ] 11.7 Expose `GET /traces/{trace_id}/attributions` endpoint
    - _Requirements: 6.9_

- [x] 12. Risk scoring engine (`app/risk/`)
  - [x] 12.1 Implement `compute_risk_score` and `classify_risk_band` functions
    - Formula: `round((0.35*de + 0.20*ie + 0.20*vc + 0.15*tf + 0.10*va) * 100)`, clamped to [0, 100]
    - Bands: Low 0–39, Medium 40–69, High 70–100
    - _Requirements: 8.1, 8.2, 8.3_
  - [ ]* 12.2 Write property test for risk score range and band classification (Properties 25, 26)
    - **Property 25: Risk score is always in [0, 100]**
    - **Property 26: Risk band classification correctness**
    - **Validates: Requirements 8.1, 8.2, 8.3**
  - [x] 12.3 Implement high-risk alert creation: on score ≥ 70 create `RiskAlert` record and push WebSocket notification to supervisor channel via Redis pub/sub
    - Implement score-change tracking (delta > 10): write audit entry + notify investigator
    - _Requirements: 8.4, 8.6_
  - [ ]* 12.4 Write property test for high-risk score triggers alert (Property 27)
    - **Property 27: High-risk score triggers alert creation**
    - **Validates: Requirements 8.4**
  - [ ]* 12.5 Write property test for significant risk score change is audited (Property 28)
    - **Property 28: Significant risk score change is audited and notified**
    - **Validates: Requirements 8.6**
  - [x] 12.6 Wire risk scoring into Celery trace task post-attribution; expose `GET /traces/{trace_id}/risk` endpoint
    - _Requirements: 8.1, 15.4_

- [x] 13. Typology detection module (`app/typology/`)
  - [x] 13.1 Implement `TypologyDetector` protocol and seven concrete detector classes
    - Layering, Peel chain, Mixer/tumbler, Bridge abuse, Darknet market, Ransomware, Fraud aggregation
    - Threshold: `match_confidence >= 0.60` required to emit `TypologyTag`
    - _Requirements: 9.1, 9.2, 9.3_
  - [x] 13.2 Implement `TypologyClassifier` orchestrator running all detectors concurrently via `asyncio.gather`
    - Persist `TypologyTag` records (including `sub_graph` JSONB) linked to `trace_id`
    - _Requirements: 9.2, 9.3, 9.4_
  - [ ]* 13.3 Write property test for typology detections above threshold are tagged (Property 29)
    - **Property 29: Typology detections above threshold are tagged**
    - **Validates: Requirements 9.2, 9.3, 9.4**
  - [x] 13.4 Implement hot-reload: typology definitions stored in `typology_definitions` table; worker polls Redis version counter every 60s; Admin upload endpoint `POST /admin/typology-definitions`
    - _Requirements: 9.5_

- [x] 14. Checkpoint — Ensure all tests pass for clustering, risk, and typology modules
  - Ensure all unit and property tests pass for modules 11, 12, and 13; ask the user if questions arise.

- [x] 15. Report generation module (`app/reports/`)
  - [x] 15.1 Implement `ReportModel` Pydantic model and `PydanticJSONRenderer`
    - Compute SHA-256 content hash before storage; include all required sections
    - _Requirements: 11.1, 11.2, 11.3, 11.5_
  - [x] 15.2 Implement `WeasyPrintPDFRenderer` with Jinja2 HTML template matching all required report sections
    - Store PDF in S3-compatible object storage at `reports/{case_id}/{trace_id}/{report_id}.pdf`
    - _Requirements: 11.2, 11.3_
  - [ ]* 15.3 Write property test for report content completeness (Property 30)
    - **Property 30: Report content completeness**
    - **Validates: Requirements 11.3**
  - [ ]* 15.4 Write property test for report content hash integrity (Property 31)
    - **Property 31: Report content hash integrity**
    - **Validates: Requirements 11.5**
  - [x] 15.5 Implement report endpoints: `POST /traces/{trace_id}/reports`, `GET /reports/{id}`, `POST /reports/{id}/sign`
    - Supervisor sign: set `supervisor_signature = {user_id}:{timestamp}:{report_hash}`; mark `supervisor-approved`
    - Audit log on every generation and approval event
    - _Requirements: 11.1, 11.2, 11.6, 11.7_
  - [ ]* 15.6 Write property test for report generation is always audited (Property 32)
    - **Property 32: Report generation is always audited**
    - **Validates: Requirements 11.6, 14.1**

- [x] 16. SAHYOG Portal integration module (`app/sahyog/`)
  - [x] 16.1 Implement `SAHYOGConfig` encrypted storage (Admin-managed) and `SAHYOGClient` with REST/SOAP support
    - Admin config endpoints: `GET/POST /admin/config`
    - _Requirements: 12.1, 12.6_
  - [x] 16.2 Implement `POST /reports/{id}/submit-sahyog` endpoint and Celery submission task
    - Retry 3× with 30s countdown; on final failure queue for manual resubmission and notify supervisor
    - Update `sahyog_submissions` with status and portal reference number; update case status
    - _Requirements: 12.2, 12.3, 12.4, 12.5_
  - [ ]* 16.3 Write property test for SAHYOG submission status always recorded (Property 33)
    - **Property 33: SAHYOG submission status always recorded**
    - **Validates: Requirements 12.3**

- [ ] 17. Audit trail module (`app/audit/`)
  - [x] 17.1 Implement `AuditLogEntry` SQLAlchemy model with INSERT-only PostgreSQL role, `AuditAction` enum covering all loggable events
    - All fields non-null: id, UTC timestamp (ms precision), actor_user_id, action_type, resource_type, resource_id, source_ip
    - _Requirements: 14.1, 14.2_
  - [ ]* 17.2 Write property test for audit log entry schema completeness (Property 35)
    - **Property 35: Audit log entry schema completeness**
    - **Validates: Requirements 14.2**
  - [ ]* 17.3 Write property test for audit log entries are immutable (Property 34)
    - **Property 34: Audit log entries are immutable**
    - **Validates: Requirements 14.3**
  - [x] 17.4 Implement audit log export endpoint (`GET /admin/audit-logs/export`) with date-range, user, action-type, resource-id filters and CSV/JSON output
    - Background export job for > 100,000 rows; storage capacity alert at 80% utilization (APScheduler/Celery beat)
    - _Requirements: 14.4, 14.5_

- [x] 18. Async task queue and performance infrastructure (`app/tasks/`)
  - [x] 18.1 Implement Celery configuration (`celery_config.py`) with Redis broker, separate queues (`traces`, `reports`, `sahyog`), and worker concurrency settings
    - _Requirements: 15.4_
  - [x] 18.2 Implement queue-depth guard FastAPI middleware: check `LLEN traces` via Redis before accepting trace submissions; return HTTP 429 with `Retry-After` header when depth > 100
    - _Requirements: 15.5_
  - [ ]* 18.3 Write property test for queue depth cap enforces HTTP 429 (Property 36)
    - **Property 36: Queue depth cap enforces HTTP 429**
    - **Validates: Requirements 15.5**
  - [x] 18.4 Implement `slowapi` rate limiter middleware: 100 req/min per authenticated `user_id`; HTTP 429 with `X-RateLimit-*` headers
    - _Requirements: 16.4_
  - [ ]* 18.5 Write property test for per-user API rate limiting (Property 38)
    - **Property 38: Per-user API rate limiting**
    - **Validates: Requirements 16.4**
  - [x] 18.6 Implement WebSocket notification handler at `/ws/notifications/{user_id}`: subscribe to Redis pub/sub `notifications:{user_id}` channel and forward events to connected clients
    - Implement `GET /traces/{trace_id}/status` polling endpoint; workers update `trace_jobs` Redis hash every 10s
    - _Requirements: 13.2, 13.5, 15.4_

- [ ] 19. Checkpoint — Ensure all tests pass for reports, SAHYOG, audit, and task queue modules
  - Ensure all unit and property tests pass for modules 15–18; ask the user if questions arise.

- [x] 20. Frontend — Project setup and shared components (`frontend/`)
  - [x] 20.1 Set up Next.js app router structure with TypeScript, Tailwind CSS, React Query, and axios interceptor for JWT bearer attachment + 401 redirect
    - Implement `NotificationProvider` React context with persistent WebSocket connection to `/ws/notifications/{userId}`
    - _Requirements: 13.1, 16.2_
  - [x] 20.2 Implement auth pages (login form), JWT storage (httpOnly cookie or memory), and route guards enforcing RBAC roles client-side
    - _Requirements: 1.1, 1.2_

- [x] 21. Frontend — LEA Dashboard (`frontend/app/dashboard/`)
  - [x] 21.1 Implement Dashboard page consuming `GET /dashboard/summary`, `GET /dashboard/alerts`, `GET /dashboard/pending-approvals`
    - Case statistics widgets (open, by-status, high-risk, pending SAHYOG)
    - Notification panel surfacing high-risk alerts within 30s via WebSocket
    - _Requirements: 13.1, 13.2, 13.3_
  - [x] 21.2 Implement real-time Trace progress indicator consuming WebSocket `trace_progress` events (updated every 10s)
    - Full-text search bar wired to `GET /cases?q=...` with filter controls
    - _Requirements: 13.4, 13.5, 13.6_

- [x] 22. Frontend — Case Manager (`frontend/app/cases/`)
  - [x] 22.1 Implement Case list page with search/filter (title, status, investigator, date range, wallet address) and case creation form
    - _Requirements: 2.7, 13.6_
  - [x] 22.2 Implement Case detail page: wallet submission form (batch up to 50 addresses), trace job list with status badges, related reports list, and SAHYOG submission button (supervisor)
    - _Requirements: 2.3, 3.1, 3.5, 12.2_

- [x] 23. Frontend — Graph Viewer (`frontend/components/GraphViewer/`)
  - [x] 23.1 Implement `GraphViewer` React component using Cytoscape.js
    - Node color coding (VASP blue, unknown gray, flagged red, mixer purple, bridge amber); edge thickness `log(amount + 1)`
    - Expand/collapse nodes; Attribution label + Confidence Score tooltips on VASP nodes
    - _Requirements: 10.1, 10.2, 10.3_
  - [x] 23.2 Implement progressive rendering for graphs > 500 nodes (fcose force-directed layout; top-100 value paths first; target render < 5s)
    - Export PNG (`cy.png()`) and JSON (`GET /api/traces/{trace_id}/graph`)
    - _Requirements: 10.6, 10.5_
  - [x] 23.3 Implement `RiskPanel` component: risk score badge, band classification, active typology tags (fetched from `GET /traces/{trace_id}/risk`)
    - Wire `GraphViewer` and `RiskPanel` into the Case detail page
    - _Requirements: 10.4, 10.1_

- [x] 24. Frontend — Report Builder and Admin (`frontend/app/reports/`, `frontend/app/admin/`)
  - [x] 24.1 Implement report generation form (format selector PDF/JSON), report download, and supervisor sign/submit-to-SAHYOG actions
    - _Requirements: 11.1, 11.2, 11.7, 12.2_
  - [x] 24.2 Implement Admin pages: user management, VASP database CRUD, CSV import with per-row error display, typology definitions upload, system config
    - Audit log viewer with filters and CSV/JSON export
    - _Requirements: 7.1, 7.2, 7.4, 9.5, 14.4_

- [x] 25. Security hardening and input validation (`app/security/`)
  - [x] 25.1 Ensure Pydantic v2 strict mode on all request bodies and query parameters; verify SQLAlchemy ORM parameterized queries are used exclusively (no raw string interpolation)
    - Add `Strict-Transport-Security` header in FastAPI middleware; verify Nginx HTTPS redirect config
    - _Requirements: 16.2, 16.3_
  - [ ]* 25.2 Write property test for input sanitization prevents injection (Property 40)
    - **Property 40: Input sanitization prevents injection**
    - **Validates: Requirements 16.3**
  - [x] 25.3 Implement JWT key rotation: `jwt_keys` table with `valid_from`, `valid_until`, `is_current`; verification tries all valid keys; scheduled rotation task (default 90-day interval)
    - _Requirements: 16.7_

- [ ] 26. Integration tests (`tests/integration/`)
  - [ ]* 26.1 Write end-to-end trace integration test with mocked blockchain adapters
    - Submit wallet → enqueue trace → build graph → cluster → attribute → risk score → detect typologies → generate report
    - _Requirements: 3.4, 4.1, 5.1, 6.1, 8.1, 9.1, 11.1_
  - [ ]* 26.2 Write VASP CSV bulk import integration test (mixed valid/invalid rows against test DB)
    - _Requirements: 7.4, 7.5_
  - [ ]* 26.3 Write SAHYOG Portal submission integration test with `respx` mock server
    - Includes retry backoff verification (3 retries, 30s interval)
    - _Requirements: 12.2, 12.4_
  - [ ]* 26.4 Write audit log completeness integration test
    - Perform each auditable action type; assert corresponding audit log entry exists with all required fields
    - _Requirements: 14.1, 14.2_

- [x] 27. Final checkpoint — Ensure all tests pass and system is wired end-to-end
  - Run full pytest suite (unit + property + integration); fix any failures; verify docker-compose up brings all services healthy; ask the user if questions arise.

---

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP
- Property tests use `hypothesis` with `@given` strategies and `settings(max_examples=100)` minimum
- Unit tests complement property tests — use pytest for boundary examples and error conditions
- All property test tasks reference the corresponding property number from the design's Correctness Properties section for full traceability
- Checkpoints at tasks 5, 9, 14, 19, and 27 ensure incremental validation at each major layer boundary
- The VASP Database and typology definitions hot-reload features can be stubbed initially and completed before final checkpoint
- All sensitive columns must use pgcrypto encryption — verify the `DB_ENCRYPTION_KEY` env var is set before running migrations

---

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["2.1"] },
    { "id": 1, "tasks": ["2.2", "2.3", "2.4"] },
    { "id": 2, "tasks": ["3.1", "3.3", "3.5"] },
    { "id": 3, "tasks": ["3.2", "3.4", "3.6", "3.7", "3.8"] },
    { "id": 4, "tasks": ["3.9", "4.1", "10.1"] },
    { "id": 5, "tasks": ["4.2", "4.3", "4.4", "10.2", "10.3", "10.5"] },
    { "id": 6, "tasks": ["4.5", "4.6", "4.7", "6.1", "10.4", "10.6"] },
    { "id": 7, "tasks": ["6.2", "6.3", "7.1"] },
    { "id": 8, "tasks": ["6.4", "6.5", "6.6", "7.2", "7.3"] },
    { "id": 9, "tasks": ["7.4", "7.5"] },
    { "id": 10, "tasks": ["8.1", "11.1"] },
    { "id": 11, "tasks": ["8.2", "8.3", "11.2"] },
    { "id": 12, "tasks": ["8.4", "8.5", "11.3", "11.4", "11.5", "11.6", "12.1"] },
    { "id": 13, "tasks": ["11.7", "12.2", "12.3", "13.1"] },
    { "id": 14, "tasks": ["12.4", "12.5", "12.6", "13.2"] },
    { "id": 15, "tasks": ["13.3", "13.4", "15.1", "17.1", "18.1"] },
    { "id": 16, "tasks": ["15.2", "15.3", "17.2", "17.3", "18.2", "18.4"] },
    { "id": 17, "tasks": ["15.4", "15.5", "17.4", "18.3", "18.5", "18.6"] },
    { "id": 18, "tasks": ["15.6", "16.1"] },
    { "id": 19, "tasks": ["16.2", "16.3"] },
    { "id": 20, "tasks": ["20.1", "20.2"] },
    { "id": 21, "tasks": ["21.1", "21.2", "22.1"] },
    { "id": 22, "tasks": ["22.2", "23.1"] },
    { "id": 23, "tasks": ["23.2", "23.3", "24.1"] },
    { "id": 24, "tasks": ["24.2", "25.1"] },
    { "id": 25, "tasks": ["25.2", "25.3"] },
    { "id": 26, "tasks": ["26.1", "26.2", "26.3", "26.4"] }
  ]
}
```
