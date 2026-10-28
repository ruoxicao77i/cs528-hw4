"""
HW5 statistics. Run after both clients finish:

    DB_PASS=<password> python3 stats.py <DB_IP>

Prints each SQL query and its result, so the output can go into the report.
"""
import os
import sys
import pymysql

DB_USER = "appuser"
DB_NAME = "hw5"
DB_PASS = os.environ.get("DB_PASS")

QUERIES = [
    ("Total requests",
     "SELECT COUNT(*) AS total FROM requests"),

    ("1. Successful vs unsuccessful requests",
     """SELECT
            (SELECT COUNT(*) FROM requests) - (SELECT COUNT(*) FROM failed_requests) AS successful,
            (SELECT COUNT(*) FROM failed_requests) AS unsuccessful"""),

    ("   Unsuccessful requests by error code",
     """SELECT error_code, COUNT(*) AS cnt
        FROM failed_requests
        GROUP BY error_code
        ORDER BY cnt DESC"""),

    ("2. Requests from banned countries",
     "SELECT COUNT(*) AS banned FROM requests WHERE is_banned = 1"),

    ("3. Requests by gender",
     """SELECT gender, COUNT(*) AS cnt
        FROM requests
        GROUP BY gender
        ORDER BY cnt DESC"""),

    ("4. Top 5 countries",
     """SELECT country, COUNT(*) AS cnt
        FROM requests
        GROUP BY country
        ORDER BY cnt DESC
        LIMIT 5"""),

    ("5. Requests by age group (most first)",
     """SELECT age, COUNT(*) AS cnt
        FROM requests
        GROUP BY age
        ORDER BY cnt DESC"""),

    ("6. Requests by income group (most first)",
     """SELECT income, COUNT(*) AS cnt
        FROM requests
        GROUP BY income
        ORDER BY cnt DESC"""),
]


def main():
    if len(sys.argv) < 2 or not DB_PASS:
        print("Usage: DB_PASS=<password> python3 stats.py <DB_IP>")
        sys.exit(1)

    conn = pymysql.connect(host=sys.argv[1], user=DB_USER, password=DB_PASS, database=DB_NAME)
    try:
        with conn.cursor() as cur:
            for title, sql in QUERIES:
                print(f"\n===== {title} =====")
                print(" ".join(sql.split()))          # the query, on one line
                cur.execute(sql)
                cols = [d[0] for d in cur.description]
                print("-> " + " | ".join(cols))
                for row in cur.fetchall():
                    print("   " + " | ".join(str(v) for v in row))
    finally:
        conn.close()


if __name__ == "__main__":
    main()