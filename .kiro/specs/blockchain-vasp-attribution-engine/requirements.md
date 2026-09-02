# Requirements Document

## Introduction

The Blockchain Intelligence & VASP Attribution Engine (hereafter "the Engine") is an automated investigation platform integrated with the SAHYOG Portal for Law Enforcement Agencies (LEAs). It enables investigators to submit suspect cryptocurrency wallet addresses, automatically trace blockchain transaction paths across multiple chains, attribute fund flows to Virtual Asset Service Providers (VASPs) or centralized exchanges with confidence scoring, detect laundering typologies, and generate investigation-ready reports. The platform provides a full LEA dashboard with RBAC-controlled case management, audit trails, and workflow integration for disclosure and freeze requests via the SAHYOG Portal.

---

## Glossary

- **Engine**: The Blockchain Intelligence & VASP Attribution Engine described in this document.
- **SAHYOG Portal**: The Indian government LEA coordination portal into which the Engine integrates for routing disclosure and freeze requests.
- **LEA**: Law Enforcement Agency — the primary end-user organization.
- **Investigator**: An authenticated LEA user with the "investigator" RBAC role who submits wallets and manages cases.
- **Supervisor**: An authenticated LEA user with the "supervisor" RBAC role who reviews investigation findings and routes requests.
- **Admin**: An authenticated LEA user with the "admin" RBAC role who manages users, roles, and system configuration.
- **VASP**: Virtual Asset Service Provider — a regulated entity such as a centralized cryptocurrency exchange.
- **Wallet Address**: A public blockchain address submitted for investigation.
- **Case**: A named investigation record that groups one or more Wallet Addresses, traces, reports, and actions.
- **Trace**: An automated blockchain path analysis run against a Wallet Address.
- **Graph**: A directed transaction graph produced by tracing, where nodes are addresses and edges are transactions.
- **Cluster**: A group of addresses attributed to the same entity via heuristic analysis.
- **Attribution**: The process of assigning a Cluster or address to a known VASP or entity with a confidence score.
- **Risk Score**: A numeric score (0–100) expressing the probability that a Wallet Address is associated with illicit activity.
- **Typology**: A classified laundering or illicit-finance pattern (e.g., layering, mixer use, peel chain, bridge abuse, darknet market, ransomware, terrorism financing, fraud).
- **Confidence Score**: A percentage (0–100%) expressing certainty of an attribution decision.
- **VASP Database**: An internal registry of known VASP addresses, clusters, and metadata.
- **Blockchain Data Adapter**: A pluggable component that fetches on-chain data from a specific chain's public API.
- **Supported Chains**: Bitcoin (BTC), Ethereum (ETH), Tron (TRX), BNB Chain (BSC), Solana (SOL), Polygon (MATIC).
- **Report**: A structured document (PDF or JSON) summarizing a Trace, attributions, risk scores, and recommended actions.
- **Audit Log**: An immutable chronological record of all user actions and system events.
- **JWT**: JSON Web Token used for stateless authentication.
- **RBAC**: Role-Based Access Control.
- **API Rate Limit**: The request frequency ceiling imposed by a Blockchain Data Adapter's upstream provider.

---

## Requirements

### Requirement 1 — User Authentication and Authorization

**User Story:** As an LEA user, I want secure JWT-based login with role-based access control so that only authorized personnel can access investigation data.

#### Acceptance Criteria

1. THE Engine SHALL authenticate users via JWT tokens signed with a configurable secret, with a configurable expiry (default 8 hours).
2. WHEN a user submits valid credentials, THE Engine SHALL return a signed JWT and a refresh token.
3. WHEN a JWT expires or is invalid, THE Engine SHALL return HTTP 401 and reject the request.
4. THE Engine SHALL enforce three RBAC roles: "investigator", "supervisor", and "admin", each with distinct permission sets.
5. WHILE a user holds the "investigator" role, THE Engine SHALL permit wallet submission, case creation, trace initiation, and report generation for cases assigned to that user.
6. WHILE a user holds the "supervisor" role, THE Engine SHALL permit all investigator actions plus review, approval, and routing of disclosure and freeze requests across all cases in the user's organizational unit.
7. WHILE a user holds the "admin" role, THE Engine SHALL permit all supervisor actions plus user management, role assignment, VASP database management, and system configuration.
8. IF a user attempts an action outside their role's permission set, THEN THE Engine SHALL return HTTP 403 with a descriptive error message.
9. THE Engine SHALL record every authentication event (login, logout, token refresh, failed login) in the Audit Log with timestamp, user ID, and source IP.

---

### Requirement 2 — Case Management

**User Story:** As an Investigator, I want to create and manage investigation cases so that all wallet submissions, traces, and reports are organized under a named investigation record.

#### Acceptance Criteria

1. THE Engine SHALL support creation, retrieval, update, and soft-deletion of Cases by authenticated users with at least the "investigator" role.
2. WHEN a Case is created, THE Engine SHALL assign a unique Case ID, record the creating user, and set the status to "open".
3. THE Engine SHALL store the following fields per Case: Case ID, title, description, assigned investigator(s), supervisor, status (open, under review, closed), creation timestamp, last-modified timestamp, and associated Wallet Addresses.
4. WHEN a Case is soft-deleted, THE Engine SHALL retain all associated Wallet Addresses, Traces, and Reports and mark them as archived.
5. WHILE a Case has status "under review", THE Engine SHALL prevent modification of Traces and Reports by Investigators until a Supervisor sets the status back to "open" or "closed".
6. THE Engine SHALL record every Case state change in the Audit Log with user ID, timestamp, previous status, and new status.
7. THE Engine SHALL support searching and filtering Cases by title, status, assigned investigator, date range, and associated Wallet Address.

---

### Requirement 3 — Wallet Address Submission

**User Story:** As an Investigator, I want to submit cryptocurrency wallet addresses to a case so that the Engine can automatically initiate blockchain tracing.

#### Acceptance Criteria

1. THE Engine SHALL accept Wallet Address submissions linked to an existing Case via a REST API endpoint authenticated with a valid JWT.
2. WHEN a Wallet Address is submitted, THE Engine SHALL validate the address format against the address schema of each Supported Chain.
3. IF a submitted Wallet Address fails format validation for all Supported Chains, THEN THE Engine SHALL return HTTP 400 with a message specifying the validation failure.
4. WHEN a valid Wallet Address is accepted, THE Engine SHALL auto-detect the applicable chain(s) and immediately enqueue a Trace job.
5. THE Engine SHALL allow multiple Wallet Addresses to be submitted in a single batch request (up to 50 addresses per request).
6. IF a Wallet Address is submitted to a Case where the same address already exists and has a Trace in progress or completed within the last 24 hours, THEN THE Engine SHALL return the existing Trace ID rather than initiating a duplicate Trace.
7. THE Engine SHALL record each Wallet Address submission in the Audit Log with Case ID, address, chain, submitting user, and timestamp.

---

### Requirement 4 — Multi-Chain Blockchain Data Retrieval

**User Story:** As an Investigator, I want the Engine to retrieve on-chain data from all Supported Chains automatically so that I do not need to query multiple explorers manually.

#### Acceptance Criteria

1. THE Engine SHALL implement a separate Blockchain Data Adapter for each Supported Chain using the following default free/public APIs: Mempool.space for Bitcoin, Etherscan for Ethereum, Tronscan for Tron, BscScan for BNB Chain, Solscan for Solana, and Polygonscan for Polygon.
2. THE Engine SHALL implement each Blockchain Data Adapter behind a common interface so that a commercial data provider can replace any adapter without changes to the tracing or attribution logic.
3. WHEN a Trace is initiated, THE Engine SHALL retrieve transaction history for the Wallet Address up to a configurable hop depth (default 5 hops, maximum 10 hops).
4. IF an API Rate Limit is reached during data retrieval, THEN THE Engine SHALL apply exponential backoff (base 1 second, maximum 60 seconds) and retry up to 5 times before marking the partial result as "rate-limited".
5. IF a Blockchain Data Adapter returns an error or timeout after all retries are exhausted, THEN THE Engine SHALL mark the affected Trace segment as "data-unavailable" and continue tracing available paths.
6. THE Engine SHALL cache raw transaction data per address per chain with a configurable TTL (default 30 minutes) to reduce redundant API calls.
7. WHEN cached data is used for a Trace, THE Engine SHALL include a cache-age indicator in the Trace result metadata.

---

### Requirement 5 — Transaction Graph Construction

**User Story:** As an Investigator, I want the Engine to build a directed transaction graph from retrieved blockchain data so that fund flow paths are visible and analyzable.

#### Acceptance Criteria

1. WHEN raw transaction data is retrieved for a Wallet Address, THE Engine SHALL construct a directed Graph where each node represents a unique address and each directed edge represents a transaction with amount, timestamp, transaction hash, and fee as edge attributes.
2. THE Engine SHALL represent cross-chain bridge transactions as edges that span two chain-specific sub-graphs, linked by a bridge contract or protocol identifier.
3. THE Engine SHALL support Graph construction for Graphs containing up to 10,000 nodes and 50,000 edges without exceeding a memory footprint of 2 GB per Trace job.
4. WHEN a Graph is constructed, THE Engine SHALL compute and store the following per-node metrics: in-degree, out-degree, total inflow (native currency), total outflow (native currency), first-seen timestamp, and last-seen timestamp.
5. THE Engine SHALL persist constructed Graphs in a database associated with the originating Case and Wallet Address for subsequent re-use and visualization.

---

### Requirement 6 — Address Clustering and Entity Attribution

**User Story:** As an Investigator, I want the Engine to cluster related addresses and attribute them to known VASPs or entities so that I can identify who controls the funds.

#### Acceptance Criteria

1. THE Engine SHALL apply common-input ownership heuristics to Bitcoin transaction graphs to group co-spent inputs into Clusters representing a single controlling entity.
2. THE Engine SHALL apply deposit address pattern heuristics to Ethereum, BNB Chain, Tron, Polygon, and Solana graphs to identify exchange deposit address clusters.
3. WHEN a Cluster is identified, THE Engine SHALL compare it against the VASP Database to determine whether any addresses in the Cluster match a known VASP seed address.
4. WHEN a Cluster matches a known VASP, THE Engine SHALL assign an Attribution with the matched VASP name, VASP category (e.g., CEX, DEX, mixer, bridge), and a Confidence Score.
5. THE Engine SHALL compute the Confidence Score for each Attribution using a weighted combination of: address match ratio (weight 0.4), transaction volume similarity (weight 0.3), behavioral pattern similarity (weight 0.2), and temporal proximity (weight 0.1).
6. THE Engine SHALL surface Attributions with Confidence Score below 40% as "low-confidence" and require Supervisor review before inclusion in an official Report.
7. THE Engine SHALL flag addresses that match known mixer contracts, tornado-cash-style pools, or coinjoin coordinators as "obfuscation service" with a dedicated Typology tag.
8. THE Engine SHALL flag addresses identified as DeFi bridge contracts (e.g., cross-chain bridge routers) with a "cross-chain bridge" Typology tag.
9. WHEN Attribution processing completes for a Wallet Address, THE Engine SHALL store all resulting Clusters, Attributions, and Confidence Scores linked to the originating Trace.

---

### Requirement 7 — VASP Database Management

**User Story:** As an Admin, I want to maintain a registry of known VASP addresses and metadata so that the attribution engine has accurate reference data.

#### Acceptance Criteria

1. THE Engine SHALL maintain a VASP Database containing: VASP name, VASP category, jurisdiction, known seed addresses per chain, operational status, and last-updated timestamp.
2. THE Engine SHALL allow Admin users to create, update, and deactivate VASP records via a secured API endpoint.
3. WHEN a VASP record is updated, THE Engine SHALL invalidate cached Attributions that referenced that VASP's previous address set and mark the affected Traces for re-attribution.
4. THE Engine SHALL support bulk import of VASP seed addresses via a CSV file upload with mandatory columns: vasp_name, chain, address, category, jurisdiction.
5. IF a CSV import row fails validation (missing mandatory columns, invalid address format), THEN THE Engine SHALL skip that row, record the error, and continue importing valid rows.
6. THE Engine SHALL expose a read-only VASP search endpoint accessible to all authenticated users for lookup during investigation.

---

### Requirement 8 — Risk Scoring

**User Story:** As an Investigator, I want each wallet address to receive a risk score so that I can prioritize high-risk cases for immediate action.

#### Acceptance Criteria

1. THE Engine SHALL compute a Risk Score (integer 0–100) for each Wallet Address after Trace completion.
2. THE Engine SHALL compute the Risk Score using a weighted model combining: direct exposure to flagged addresses (weight 0.35), indirect exposure within 3 hops (weight 0.20), attributed VASP risk category (weight 0.20), detected Typology flags (weight 0.15), and transaction volume anomaly score (weight 0.10).
3. THE Engine SHALL classify Risk Scores into three bands: Low (0–39), Medium (40–69), High (70–100).
4. WHEN a Wallet Address receives a Risk Score of 70 or above, THE Engine SHALL automatically create a high-risk alert linked to the Case and notify the assigned Supervisor via the in-platform notification system.
5. THE Engine SHALL associate the following Typology flags with elevated Risk Score contributions: ransomware, darknet market, terrorism financing, fraud, mixer/tumbler use, peel chain, layering, and bridge abuse.
6. WHEN the Risk Score for a Wallet Address changes by more than 10 points due to updated Trace data or VASP Database changes, THE Engine SHALL record the change in the Audit Log and notify the assigned Investigator.

---

### Requirement 9 — Laundering Typology Detection

**User Story:** As an Investigator, I want the Engine to automatically classify transaction patterns into known laundering typologies so that I can build stronger legal narratives.

#### Acceptance Criteria

1. THE Engine SHALL implement a typology classifier that evaluates constructed Graphs against pattern definitions for the following typologies: layering (rapid sequential hops to multiple addresses), peel chain (linear chain of diminishing-value transactions), mixer/tumbler use (high fan-in/fan-out with equal output amounts), bridge abuse (cross-chain transfers to high-risk chains), darknet market deposit patterns, ransomware wallet patterns, and fraud aggregation patterns.
2. WHEN a typology pattern is detected with a match confidence of 60% or above, THE Engine SHALL tag the affected address or sub-graph with the corresponding Typology label and match confidence score.
3. THE Engine SHALL support concurrent detection of multiple Typology tags on a single Wallet Address or Cluster.
4. THE Engine SHALL store Typology detection results, including the sub-graph segment that triggered the detection, linked to the originating Trace.
5. WHERE the typology classifier model is updatable, THE Engine SHALL allow Admin users to upload updated classifier definitions without requiring a full system restart.

---

### Requirement 10 — Graph Visualization

**User Story:** As an Investigator, I want an interactive graph visualization of transaction paths so that I can visually explore fund flows and share findings with colleagues.

#### Acceptance Criteria

1. THE Engine SHALL provide an interactive web-based graph visualization rendering the transaction Graph for a given Trace, with nodes color-coded by entity type (known VASP, unknown, flagged, mixer, bridge) and edge thickness proportional to transaction value.
2. THE Engine SHALL allow Investigators to expand or collapse individual nodes in the visualization to reveal or hide downstream transaction paths.
3. THE Engine SHALL display Attribution labels and Confidence Scores as tooltips on VASP-attributed nodes.
4. THE Engine SHALL display Risk Score and active Typology tags in a side panel alongside the graph visualization.
5. THE Engine SHALL allow Investigators to export the currently viewed graph as a PNG image or as a JSON file representing the full graph data structure.
6. WHEN a graph contains more than 500 nodes, THE Engine SHALL apply a force-directed layout with progressive rendering, displaying the highest-value paths first, to maintain an initial render time of under 5 seconds.

---

### Requirement 11 — Report Generation

**User Story:** As an Investigator, I want the Engine to generate structured investigation reports in PDF and JSON formats so that I can submit them to supervisors and attach them to SAHYOG Portal requests.

#### Acceptance Criteria

1. THE Engine SHALL generate a Report for any completed Trace on demand by an authenticated Investigator or Supervisor.
2. THE Engine SHALL produce Reports in both PDF and JSON formats; the user selects the desired format at generation time.
3. THE Engine SHALL include the following sections in every Report: case metadata, wallet address(es) under investigation, chain(s) analyzed, Trace summary (hops, total addresses, total transactions), attributed VASPs with Confidence Scores, Risk Score and classification band, detected Typologies with supporting sub-graph descriptions, timeline of fund flows, and recommended LEA action (monitor, disclose, freeze).
4. IF a Trace contains Attributions with Confidence Score below 40%, THEN THE Engine SHALL include a "low-confidence attributions" section in the Report listing those attributions and their scores, with a disclaimer that Supervisor review is required.
5. THE Engine SHALL append a digitally verifiable hash of the Report content (SHA-256) to the Report metadata to support chain-of-custody requirements.
6. WHEN a Report is generated, THE Engine SHALL store it in persistent storage linked to the Case and Trace and record the generating user and timestamp in the Audit Log.
7. THE Engine SHALL allow Supervisors to digitally sign a Report using their authenticated session, marking it as "supervisor-approved" before submission to the SAHYOG Portal.

---

### Requirement 12 — SAHYOG Portal Integration

**User Story:** As a Supervisor, I want to route approved investigation reports as disclosure or freeze requests directly to the SAHYOG Portal so that LEA workflows are unified.

#### Acceptance Criteria

1. THE Engine SHALL integrate with the SAHYOG Portal via a configurable REST or SOAP API endpoint provided by the SAHYOG Portal operator.
2. WHEN a Supervisor submits a disclosure or freeze request, THE Engine SHALL package the approved Report, case metadata, and supporting evidence and transmit the payload to the SAHYOG Portal API endpoint.
3. THE Engine SHALL record the SAHYOG Portal submission status (pending, acknowledged, rejected) and the Portal-assigned reference number in the Case record.
4. IF the SAHYOG Portal API returns an error or is unreachable, THEN THE Engine SHALL retry up to 3 times with a 30-second interval, queue the request for manual resubmission if all retries fail, and notify the Supervisor of the failure.
5. WHEN a SAHYOG Portal submission is acknowledged, THE Engine SHALL update the Case status to "disclosure-submitted" or "freeze-submitted" accordingly and record the event in the Audit Log.
6. THE Engine SHALL support configuration of SAHYOG Portal API credentials (endpoint URL, API key or OAuth2 client credentials) by Admin users without requiring code changes.

---

### Requirement 13 — LEA Dashboard

**User Story:** As any authenticated LEA user, I want a central dashboard that surfaces my cases, active traces, alerts, and system status so that I can manage my workload efficiently.

#### Acceptance Criteria

1. THE Engine SHALL provide a web-based dashboard accessible to all authenticated users showing: assigned Cases (filtered by role), active Trace jobs with progress indicators, recent high-risk alerts, pending Supervisor approvals (for supervisors), and system health indicators.
2. WHEN a new high-risk alert is generated, THE Engine SHALL surface it in the dashboard notification panel within 30 seconds of alert creation.
3. THE Engine SHALL display Case statistics on the dashboard: total open cases, cases by status, cases with high-risk wallets, and cases pending SAHYOG submission.
4. THE Engine SHALL provide a search bar on the dashboard enabling full-text and filter-based search of Cases and Wallet Addresses accessible to the current user.
5. WHILE a Trace job is in progress, THE Engine SHALL display a real-time progress indicator showing current hop depth and estimated completion percentage, updated at least every 10 seconds.
6. THE Engine SHALL allow Investigators to open a Case directly from the dashboard with a single interaction.

---

### Requirement 14 — Audit Trail

**User Story:** As an Admin, I want a complete, tamper-evident audit trail of all user actions and system events so that investigation integrity can be verified in legal proceedings.

#### Acceptance Criteria

1. THE Engine SHALL record every user action and system event in the Audit Log, including: user authentication events, Case CRUD operations, Wallet Address submissions, Trace initiations and completions, Report generations and approvals, SAHYOG Portal submissions, VASP Database changes, and user/role management changes.
2. THE Engine SHALL store each Audit Log entry with: entry ID, timestamp (UTC, millisecond precision), actor user ID, action type, affected resource type and ID, before-state (for updates), after-state (for updates), and source IP address.
3. THE Engine SHALL prevent deletion or modification of Audit Log entries by any user role, including Admin.
4. THE Engine SHALL allow Admin users to export Audit Log entries filtered by date range, user ID, action type, and resource ID as a CSV or JSON file.
5. WHEN the Audit Log storage reaches 80% of its configured capacity, THE Engine SHALL generate a system alert to Admin users and log the event.

---

### Requirement 15 — System Performance and Scalability

**User Story:** As an LEA system administrator, I want the Engine to meet defined performance benchmarks so that investigations are not delayed by system latency.

#### Acceptance Criteria

1. THE Engine SHALL complete a single-chain Trace of up to 5 hops within 120 seconds under normal operating conditions (excluding API Rate Limit backoff delays).
2. THE Engine SHALL support at least 20 concurrent Trace jobs without degradation of API response times beyond 2x the baseline.
3. THE Engine SHALL return dashboard and Case list API responses within 2 seconds for datasets up to 10,000 Cases.
4. THE Engine SHALL queue Trace jobs using an asynchronous task queue and expose job status via a polling or WebSocket endpoint.
5. WHEN the asynchronous task queue depth exceeds 100 pending jobs, THE Engine SHALL return HTTP 429 on new Trace submission requests and include a "Retry-After" header with an estimated wait time.

---

### Requirement 16 — Security

**User Story:** As an LEA system administrator, I want the Engine to meet security hardening standards so that sensitive investigation data is protected.

#### Acceptance Criteria

1. THE Engine SHALL store all passwords using a bcrypt hash with a minimum cost factor of 12.
2. THE Engine SHALL enforce HTTPS for all API and dashboard communications; HTTP requests SHALL be redirected to HTTPS.
3. THE Engine SHALL validate and sanitize all user-supplied inputs before processing to prevent injection attacks.
4. THE Engine SHALL implement API rate limiting of 100 requests per minute per authenticated user, returning HTTP 429 when the limit is exceeded.
5. THE Engine SHALL encrypt all data at rest for Case records, Wallet Addresses, Traces, Reports, and Audit Logs using AES-256 or an equivalent standard.
6. WHEN a user account records 5 consecutive failed login attempts, THE Engine SHALL lock the account for 15 minutes and record the lockout event in the Audit Log.
7. THE Engine SHALL rotate JWT signing keys on a configurable schedule (default 90 days) without invalidating currently valid tokens during the rotation window.
