"""Hard-reset the database to a clean state for fresh migrations."""
import psycopg

conn = psycopg.connect("postgresql://postgres:postgres@db:5432/vasp_engine")
conn.autocommit = True
cur = conn.cursor()

# Drop alembic_version so migrations restart from scratch
cur.execute("DROP TABLE IF EXISTS alembic_version CASCADE")
print("Dropped alembic_version")

# Drop all custom types
for t in ["user_role", "case_status", "vasp_category", "audit_action"]:
    cur.execute(f"DROP TYPE IF EXISTS {t} CASCADE")
    print(f"Dropped type {t}")

# Confirm clean state
cur.execute("SELECT typname FROM pg_type WHERE typname IN ('user_role','case_status','vasp_category','audit_action')")
remaining = cur.fetchall()
print("Remaining types:", remaining)

cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")
tables = [r[0] for r in cur.fetchall()]
print("Tables:", tables)

conn.close()
print("Done — DB is clean")
