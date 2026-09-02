"""Create vasps, vasp_addresses, sahyog_submissions, reports, audit_logs,
system_alerts, typology_definitions tables; add deferred FK on attributions.

Implements the VASP registry, report storage, SAHYOG tracking, and
immutable audit-trail schema required by:
  - Req 7.1  — VASP registry (vasps, vasp_addresses)
  - Req 11.6 — Investigation report persistence (reports)
  - Req 12.3 — SAHYOG Portal submission tracking (sahyog_submissions)
  - Req 14.1 — Comprehensive audit log (audit_logs)
  - Req 14.2 — INSERT-only audit log; UPDATE/DELETE revoked from PUBLIC
  - Req 14.3 — System health alerts (system_alerts)

Table creation order (respects FK dependencies):
  1. Create enum types: vasp_category, audit_action
  2. vasps
  3. vasp_addresses         (FK → vasps)
  4. Add FK attributions.vasp_id → vasps.id  (deferred from migration 004)
  5. sahyog_submissions     (FK → cases)
  6. reports                (FK → cases, trace_jobs, users)
  7. audit_logs             — then REVOKE UPDATE, DELETE from PUBLIC
  8. system_alerts
  9. typology_definitions   (FK → users nullable)

Revision ID: 0005
Revises: 0004
Create Date: 2024-01-05 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# ---------------------------------------------------------------------------
# Revision metadata
# ---------------------------------------------------------------------------

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # ------------------------------------------------------------------
    # 1. Custom ENUM types
    # ------------------------------------------------------------------
    # 1. Custom ENUM types (safe DO blocks prevent duplicate errors)
    # ------------------------------------------------------------------
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE vasp_category AS ENUM ('CEX','DEX','mixer','bridge','darknet','other');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE audit_action AS ENUM (
                'user_login','user_logout','user_login_failed','token_refresh',
                'case_created','case_updated','case_deleted','case_status_changed',
                'wallet_submitted','trace_started','trace_completed',
                'report_generated','report_signed','sahyog_submitted',
                'vasp_created','vasp_updated','vasp_deactivated',
                'user_created','user_updated','role_changed',
                'config_changed','audit_export'
            );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)

    # ------------------------------------------------------------------
    # 2. vasps
    # ------------------------------------------------------------------
    op.create_table(
        "vasps",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "name",
            sa.String(length=255),
            nullable=False,
            comment="Full legal / commonly-known name of the VASP",
        ),
        sa.Column(
            "category",
            postgresql.ENUM(
                "CEX",
                "DEX",
                "mixer",
                "bridge",
                "darknet",
                "other",
                name="vasp_category",
                create_type=False,
            ),
            nullable=False,
            comment="CEX | DEX | mixer | bridge | darknet | other",
        ),
        sa.Column(
            "jurisdiction",
            sa.String(length=2),
            nullable=False,
            comment="ISO 3166-1 alpha-2 country code",
        ),
        sa.Column(
            "operational_status",
            sa.Text(),
            nullable=False,
            comment="active | inactive | sanctioned",
        ),
        sa.Column(
            "last_updated",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
            comment="Timestamp of last registry update",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_vasps")),
    )
    op.create_index(op.f("ix_vasps_name"), "vasps", ["name"], unique=False)

    # ------------------------------------------------------------------
    # 3. vasp_addresses
    # ------------------------------------------------------------------
    op.create_table(
        "vasp_addresses",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "vasp_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="Parent VASP record",
        ),
        sa.Column(
            "chain",
            sa.Text(),
            nullable=False,
            comment="Blockchain identifier: BTC | ETH | TRX | BSC | SOL | MATIC",
        ),
        sa.Column(
            "address",
            sa.Text(),
            nullable=False,
            comment="On-chain address string",
        ),
        sa.Column(
            "added_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
            comment="Timestamp when this address was added to the registry",
        ),
        sa.ForeignKeyConstraint(
            ["vasp_id"],
            ["vasps.id"],
            name=op.f("fk_vasp_addresses_vasp_id_vasps"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_vasp_addresses")),
        sa.UniqueConstraint(
            "chain",
            "address",
            name="uq_vasp_addresses_chain_address",
        ),
    )
    op.create_index(
        op.f("ix_vasp_addresses_vasp_id"),
        "vasp_addresses",
        ["vasp_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_vasp_addresses_chain"),
        "vasp_addresses",
        ["chain"],
        unique=False,
    )

    # ------------------------------------------------------------------
    # 4. Add deferred FK: attributions.vasp_id → vasps.id
    #    (intentionally omitted from migration 004; vasps now exists)
    # ------------------------------------------------------------------
    op.create_foreign_key(
        "fk_attributions_vasp_id_vasps",
        "attributions",
        "vasps",
        ["vasp_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    # ------------------------------------------------------------------
    # 5. sahyog_submissions
    # ------------------------------------------------------------------
    op.create_table(
        "sahyog_submissions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "case_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="Case this submission belongs to",
        ),
        sa.Column(
            "request_type",
            sa.Text(),
            nullable=False,
            comment="disclosure | freeze",
        ),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'pending'"),
            comment="pending | acknowledged | rejected | failed",
        ),
        sa.Column(
            "portal_reference_number",
            sa.Text(),
            nullable=True,
            comment="Reference number returned by the SAHYOG portal",
        ),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
            comment="UTC timestamp of initial submission",
        ),
        sa.Column(
            "last_updated",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
            comment="UTC timestamp of last status update",
        ),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["cases.id"],
            name=op.f("fk_sahyog_submissions_case_id_cases"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sahyog_submissions")),
    )
    op.create_index(
        op.f("ix_sahyog_submissions_case_id"),
        "sahyog_submissions",
        ["case_id"],
        unique=False,
    )

    # ------------------------------------------------------------------
    # 6. reports
    # ------------------------------------------------------------------
    op.create_table(
        "reports",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "case_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="Case this report belongs to",
        ),
        sa.Column(
            "trace_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="Trace job the report was generated from",
        ),
        sa.Column(
            "generated_by",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="User who triggered report generation",
        ),
        sa.Column(
            "format",
            sa.Text(),
            nullable=False,
            comment="pdf | json",
        ),
        sa.Column(
            "s3_key",
            sa.Text(),
            nullable=True,
            comment="Object-storage key for PDF reports; NULL for JSON-only",
        ),
        sa.Column(
            "json_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="Full ReportModel JSON payload; NULL for PDF-only reports",
        ),
        sa.Column(
            "content_hash",
            sa.Text(),
            nullable=False,
            comment="SHA-256 hex of the report payload for tamper detection",
        ),
        sa.Column(
            "supervisor_signature",
            sa.Text(),
            nullable=True,
            comment="Supervisor approval: {user_id}:{iso_timestamp}:{content_hash}",
        ),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'draft'"),
            comment="draft | supervisor-approved",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["cases.id"],
            name=op.f("fk_reports_case_id_cases"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["trace_id"],
            ["trace_jobs.id"],
            name=op.f("fk_reports_trace_id_trace_jobs"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["generated_by"],
            ["users.id"],
            name=op.f("fk_reports_generated_by_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reports")),
    )
    op.create_index(op.f("ix_reports_case_id"), "reports", ["case_id"], unique=False)
    op.create_index(op.f("ix_reports_trace_id"), "reports", ["trace_id"], unique=False)
    op.create_index(
        op.f("ix_reports_generated_by"), "reports", ["generated_by"], unique=False
    )

    # ------------------------------------------------------------------
    # 7. audit_logs — INSERT-only; revoke UPDATE/DELETE after creation
    # ------------------------------------------------------------------
    op.create_table(
        "audit_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
            comment="UTC event timestamp; server-generated",
        ),
        sa.Column(
            "actor_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="User who triggered the action; NULL for system-generated events",
        ),
        sa.Column(
            "action_type",
            postgresql.ENUM(
                "user_login",
                "user_logout",
                "user_login_failed",
                "token_refresh",
                "case_created",
                "case_updated",
                "case_deleted",
                "case_status_changed",
                "wallet_submitted",
                "trace_started",
                "trace_completed",
                "report_generated",
                "report_signed",
                "sahyog_submitted",
                "vasp_created",
                "vasp_updated",
                "vasp_deactivated",
                "user_created",
                "user_updated",
                "role_changed",
                "config_changed",
                "audit_export",
                name="audit_action",
                create_type=False,
            ),
            nullable=False,
            comment="Categorised event type (Req 14.1)",
        ),
        sa.Column(
            "resource_type",
            sa.Text(),
            nullable=False,
            comment="Entity type affected, e.g. 'case', 'user', 'vasp'",
        ),
        sa.Column(
            "resource_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="Primary key of the affected resource row",
        ),
        sa.Column(
            "before_state",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="JSON snapshot of resource state before the action",
        ),
        sa.Column(
            "after_state",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="JSON snapshot of resource state after the action",
        ),
        sa.Column(
            "source_ip",
            sa.Text(),
            nullable=False,
            comment="Client IP address from the HTTP request",
        ),
        sa.Column(
            "session_id",
            sa.Text(),
            nullable=True,
            comment="JWT jti claim identifying the session, if available",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_logs")),
    )
    op.create_index(
        op.f("ix_audit_logs_timestamp"), "audit_logs", ["timestamp"], unique=False
    )
    op.create_index(
        op.f("ix_audit_logs_actor_user_id"),
        "audit_logs",
        ["actor_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_audit_logs_action_type"),
        "audit_logs",
        ["action_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_audit_logs_resource_id"),
        "audit_logs",
        ["resource_id"],
        unique=False,
    )

    # Enforce INSERT-only semantics (Req 14.2): revoke UPDATE and DELETE
    # from PUBLIC so no application role can modify or erase audit records.
    op.execute("REVOKE UPDATE, DELETE ON audit_logs FROM PUBLIC;")

    # ------------------------------------------------------------------
    # 8. system_alerts
    # ------------------------------------------------------------------
    op.create_table(
        "system_alerts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "alert_type",
            sa.Text(),
            nullable=False,
            comment="Machine-readable alert category",
        ),
        sa.Column(
            "message",
            sa.Text(),
            nullable=False,
            comment="Human-readable alert description",
        ),
        sa.Column(
            "severity",
            sa.Text(),
            nullable=False,
            comment="info | warning | critical",
        ),
        sa.Column(
            "resolved",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            comment="True once the alert has been resolved",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "resolved_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="UTC timestamp when the alert was resolved; NULL if still open",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_system_alerts")),
    )
    op.create_index(
        op.f("ix_system_alerts_resolved"), "system_alerts", ["resolved"], unique=False
    )

    # ------------------------------------------------------------------
    # 9. typology_definitions
    # ------------------------------------------------------------------
    op.create_table(
        "typology_definitions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "typology_name",
            sa.Text(),
            nullable=False,
            comment="Unique typology identifier, e.g. 'layering', 'peel_chain'",
        ),
        sa.Column(
            "definition_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="Full classifier definition as JSON",
        ),
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
            comment="Incremented on each upload of the same typology",
        ),
        sa.Column(
            "uploaded_by",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="Admin user who uploaded this definition; NULL for seeded rows",
        ),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
            comment="UTC timestamp of this definition version upload",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by"],
            ["users.id"],
            name=op.f("fk_typology_definitions_uploaded_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_typology_definitions")),
        sa.UniqueConstraint(
            "typology_name",
            name=op.f("uq_typology_definitions_typology_name"),
        ),
    )
    op.create_index(
        op.f("ix_typology_definitions_typology_name"),
        "typology_definitions",
        ["typology_name"],
        unique=True,
    )


def downgrade() -> None:
    bind = op.get_bind()

    # Drop in reverse dependency order

    # 9. typology_definitions
    op.drop_index(
        op.f("ix_typology_definitions_typology_name"),
        table_name="typology_definitions",
    )
    op.drop_table("typology_definitions")

    # 8. system_alerts
    op.drop_index(op.f("ix_system_alerts_resolved"), table_name="system_alerts")
    op.drop_table("system_alerts")

    # 7. audit_logs  (re-grant before drop for clean teardown)
    op.execute("GRANT UPDATE, DELETE ON audit_logs TO PUBLIC;")
    op.drop_index(op.f("ix_audit_logs_resource_id"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_action_type"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_actor_user_id"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_timestamp"), table_name="audit_logs")
    op.drop_table("audit_logs")

    # 6. reports
    op.drop_index(op.f("ix_reports_generated_by"), table_name="reports")
    op.drop_index(op.f("ix_reports_trace_id"), table_name="reports")
    op.drop_index(op.f("ix_reports_case_id"), table_name="reports")
    op.drop_table("reports")

    # 5. sahyog_submissions
    op.drop_index(
        op.f("ix_sahyog_submissions_case_id"), table_name="sahyog_submissions"
    )
    op.drop_table("sahyog_submissions")

    # 4. Remove deferred FK on attributions.vasp_id
    op.drop_constraint(
        "fk_attributions_vasp_id_vasps",
        "attributions",
        type_="foreignkey",
    )

    # 3. vasp_addresses
    op.drop_index(op.f("ix_vasp_addresses_chain"), table_name="vasp_addresses")
    op.drop_index(op.f("ix_vasp_addresses_vasp_id"), table_name="vasp_addresses")
    op.drop_table("vasp_addresses")

    # 2. vasps
    op.drop_index(op.f("ix_vasps_name"), table_name="vasps")
    op.drop_table("vasps")

    # 1. Drop custom ENUM types
    postgresql.ENUM(name="audit_action").drop(bind, checkfirst=True)
    postgresql.ENUM(name="vasp_category").drop(bind, checkfirst=True)
