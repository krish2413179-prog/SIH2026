import psycopg
conn = psycopg.connect("postgresql://postgres:postgres@db:5432/vasp_engine")
conn.autocommit = True
cur = conn.cursor()
cur.execute("SELECT typname FROM pg_type WHERE typname IN ('user_role','case_status','vasp_category','audit_action')")
print("Types:", cur.fetchall())
cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")
print("Tables:", [r[0] for r in cur.fetchall()])
# Drop all
for t in ["user_role","case_status","vasp_category","audit_action"]:
    cur.execute(f"DROP TYPE IF EXISTS {t} CASCADE")
print("Types cleared")
conn.close()
