import os
import sys
import pymysql

DB_USER = "appuser"
DB_NAME = "hw5"
DB_PASS = os.environ.get("DB_PASS")

def show(cur, table, n):
    cur.execute(f"SELECT COUNT(*) FROM {table}")
    total = cur.fetchone()[0]
    print(f"\n===== {table}(total rows: {total}, showing last {n} =====)")

    cur.execute(f"SELECT * FROM {table} ORDER BY id DESC LIMIT %s", (n,))
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    print(" | ".join(cols))
    for row in reversed(rows):
        print(" | ".join(str(v) for v in row))

def main():
    if len(sys.argv) < 2 or not DB_PASS:
        print("Usage: DB_PASS=<password> python3 show_tables.py <DB_IP> [rows]")
        sys.exit(1)
    db_host = sys.argv[1]
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 5

    conn = pymysql.connect(host=db_host, user=DB_USER, password=DB_PASS, database=DB_NAME)
    try:
        with conn.cursor() as cur:
            show(cur, "requests", n)
            show(cur, "failed_requests", n)
    finally:
        conn.close()

if __name__ == "__main__":
    main()