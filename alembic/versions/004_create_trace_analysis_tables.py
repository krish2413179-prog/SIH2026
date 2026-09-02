"""Create trace_jobs, trace_graphs, clusters, attributions, typology_tags, risk_alerts.

Implements the trace-analysis schema required by:
  - Req 5.5  — Blockchain graph construction and persistence
  - Req 6.9  — Address clustering and VASP attribution pipeline
  - Req 9.4  — Typology detection results and risk alert records

Table creation order (respects FK dependencies):
  1. trace_jobs       (FK → cases)
  2. trace_graphs     (FK → trace_jobs, cases)
  3. clusters         (FK → trace_jobs)
  4. attributions     (FK → clusters)
              ↑ Note: attributions.vasp_id has NO FK constraint here.
                The vasps table does not exist yet; the FK is added in
                migration 005 after the vasps table is created.
  5. typology_tags    (FK → trace_jobs)
  6. risk_alerts      (FK → trace_jobs, cases)

Revision ID: 0004
Revises: 0003
Create Date: 2024-01-04 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# ---------------------------------------------------------------------------
# Revision metadata
# ---------------------------------------------------------------------------

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. trace_jobs
    # ------------------------------------------------------------------
    op.create_table(
        "trace_jobs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "case_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("wallet_address", sa.Text(), nullable=False),
        sa.Column("chain", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'queued'"),
            comment="queued | running | completed | failed | rate-limited",
        ),
        sa.Column("celery_task_id", sa.Text(), nullable=True),
        sa.Column(
            "current_hop",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "max_hops",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("5"),
        ),
        sa.Column("estimated_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column(
            "enqueued_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "needs_reattribution",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            comment="Flipped by VASP-update trigger; signals stale attributions (Req 6.9)",
        ),
        sa.Column("risk_score", sa.Integer(), nullable=True),
        sa.Column("risk_score_prev", sa.Integer(), nullable=True),
        sa.Column("risk_band", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["cases.id"],
            name=op.f("fk_trace_jobs_case_id_cases"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trace_jobs")),
    )
    op.create_index(op.f("ix_trace_jobs_case_id"), "trace_jobs", ["case_id"], unique=False)
    op.create_index(op.f("ix_trace_jobs_status"), "trace_jobs", ["status"], unique=False)

    # ------------------------------------------------------------------
    # 2. trace_graphs
    # ------------------------------------------------------------------
    op.create_table(
        "trace_graphs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "trace_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "case_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("wallet_address", sa.Text(), nullable=False),
        sa.Column("chain", sa.Text(), nullable=False),
        sa.Column(
            "graph_data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="networkx.node_link_data(G) serialised as JSONB",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["trace_id"],
            ["trace_jobs.id"],
            name=op.f("fk_trace_graphs_trace_id_trace_jobs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["cases.id"],
            name=op.f("fk_trace_graphs_case_id_cases"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trace_graphs")),
    )
    op.create_index(op.f("ix_trace_graphs_trace_id"), "trace_graphs", ["trace_id"], unique=False)
    op.create_index(op.f("ix_trace_graphs_case_id"), "trace_graphs", ["case_id"], unique=False)

    # ------------------------------------------------------------------
    # 3. clusters
    # ------------------------------------------------------------------
    op.create_table(
        "clusters",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "trace_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("chain", sa.Text(), nullable=False),
        sa.Column(
            "addresses",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="JSON array of address strings belonging to this cluster",
        ),
        sa.Column(
            "cluster_method",
            sa.Text(),
            nullable=False,
            comment="cio | deposit_pattern",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["trace_id"],
            ["trace_jobs.id"],
            name=op.f("fk_clusters_trace_id_trace_jobs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_clusters")),
    )
    op.create_index(op.f("ix_clusters_trace_id"), "clusters", ["trace_id"], unique=False)

    # ------------------------------------------------------------------
    # 4. attributions
    #    Note: vasp_id has NO FK constraint — vasps table created in 005.
    # ------------------------------------------------------------------
    op.create_table(
        "attributions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "cluster_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "vasp_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="FK → vasps(id) added in migration 005",
        ),
        sa.Column(
            "confidence_score",
            sa.Numeric(5, 2),
            nullable=False,
            comment="Overall attribution confidence 0.00–100.00",
        ),
        sa.Column(
            "low_confidence",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            comment="True when confidence_score < 40; set by application layer",
        ),
        sa.Column("address_match_ratio", sa.Numeric(5, 4), nullable=True),
        sa.Column("volume_similarity", sa.Numeric(5, 4), nullable=True),
        sa.Column("behavioral_similarity", sa.Numeric(5, 4), nullable=True),
        sa.Column("temporal_proximity", sa.Numeric(5, 4), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["cluster_id"],
            ["clusters.id"],
            name=op.f("fk_attributions_cluster_id_clusters"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_attributions")),
    )
    op.create_index(op.f("ix_attributions_cluster_id"), "attributions", ["cluster_id"], unique=False)
    op.create_index(op.f("ix_attributions_vasp_id"), "attributions", ["vasp_id"], unique=False)

    # ------------------------------------------------------------------
    # 5. typology_tags
    # ------------------------------------------------------------------
    op.create_table(
        "typology_tags",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "trace_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column(
            "typology",
            sa.Text(),
            nullable=False,
            comment=(
                "layering | peel_chain | mixer | bridge_abuse"
                " | darknet | ransomware | fraud_aggregation"
            ),
        ),
        sa.Column(
            "match_confidence",
            sa.Numeric(5, 4),
            nullable=False,
            comment="Detector confidence 0.0000–1.0000; only ≥ 0.60 are persisted",
        ),
        sa.Column(
            "sub_graph",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="networkx.node_link_data of the triggering sub-graph fragment",
        ),
        sa.Column(
            "detected_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["trace_id"],
            ["trace_jobs.id"],
            name=op.f("fk_typology_tags_trace_id_trace_jobs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_typology_tags")),
    )
    op.create_index(op.f("ix_typology_tags_trace_id"), "typology_tags", ["trace_id"], unique=False)

    # ------------------------------------------------------------------
    # 6. risk_alerts
    # ------------------------------------------------------------------
    op.create_table(
        "risk_alerts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "trace_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "case_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("wallet_address", sa.Text(), nullable=False),
        sa.Column(
            "risk_score",
            sa.Integer(),
            nullable=False,
            comment="Risk score at alert time (0–100; ≥ 70 for high band)",
        ),
        sa.Column(
            "risk_band",
            sa.Text(),
            nullable=False,
            comment="low | medium | high",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("notified_supervisor_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["trace_id"],
            ["trace_jobs.id"],
            name=op.f("fk_risk_alerts_trace_id_trace_jobs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["cases.id"],
            name=op.f("fk_risk_alerts_case_id_cases"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_risk_alerts")),
    )
    op.create_index(op.f("ix_risk_alerts_trace_id"), "risk_alerts", ["trace_id"], unique=False)
    op.create_index(op.f("ix_risk_alerts_case_id"), "risk_alerts", ["case_id"], unique=False)


def downgrade() -> None:
    # Drop in reverse dependency order
    op.drop_index(op.f("ix_risk_alerts_case_id"), table_name="risk_alerts")
    op.drop_index(op.f("ix_risk_alerts_trace_id"), table_name="risk_alerts")
    op.drop_table("risk_alerts")

    op.drop_index(op.f("ix_typology_tags_trace_id"), table_name="typology_tags")
    op.drop_table("typology_tags")

    op.drop_index(op.f("ix_attributions_vasp_id"), table_name="attributions")
    op.drop_index(op.f("ix_attributions_cluster_id"), table_name="attributions")
    op.drop_table("attributions")

    op.drop_index(op.f("ix_clusters_trace_id"), table_name="clusters")
    op.drop_table("clusters")

    op.drop_index(op.f("ix_trace_graphs_case_id"), table_name="trace_graphs")
    op.drop_index(op.f("ix_trace_graphs_trace_id"), table_name="trace_graphs")
    op.drop_table("trace_graphs")

    op.drop_index(op.f("ix_trace_jobs_status"), table_name="trace_jobs")
    op.drop_index(op.f("ix_trace_jobs_case_id"), table_name="trace_jobs")
    op.drop_table("trace_jobs")
