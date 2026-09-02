-- ─────────────────────────────────────────────────────────────
--  PostgreSQL initialization script
--  Runs once when the postgres container is first created.
-- ─────────────────────────────────────────────────────────────

-- Enable pgcrypto for column-level AES-256 encryption
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Enable uuid-ossp for gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Set default search path
ALTER DATABASE vasp_engine SET search_path TO public;

-- ── Application roles ─────────────────────────────────────────
-- audit_writer: INSERT-only on audit_logs (enforced in migration 0001)
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'audit_writer') THEN
        CREATE ROLE audit_writer;
    END IF;

    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'audit_reader') THEN
        CREATE ROLE audit_reader;
    END IF;
END
$$;
