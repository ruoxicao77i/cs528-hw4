import pymysql
import sys

# ===== Configurations =====
DB_USER = "appuser"
DB_PASS = "Hw5App2026"
DB_NAME = "hw5"
# ========================

CREATE_REQUESTS = """
CREATE TABLE IF NOT EXISTS requests (
    id INT AUTO_INCREMENT PRIMARY KEY,
    country VARCHAR(64),
    client_ip VARCHAR(45),
    gender VARCHAR(16),
    age VARCHAR(16),
    income VARCHAR(32),
    is_banned BOOLEAN,
    time_of_day DATETIME,
    requested_file VARCHAR(255)
)
"""

CREATE_FAILED = """
CREATE TABLE IF NOT EXISTS failed_requests (
    id INT AUTO_INCREMENT PRIMARY KEY,
    time_of_request DATETIME,
    requested_file VARCHAR(255),
    error_code INT
)
"""

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 setup_schema.py <DB_IP>")
        sys.exit(1)
    db_host = sys.argv[1]

    conn = pymysql.connect(
        host=db_host,
        user=DB_USER,
        password=DB_PASS,
        database=DB_NAME,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(CREATE_REQUESTS)
            cur.execute(CREATE_FAILED)
            conn.commit()
            cur.execute("SHOW TABLES")
            print("Tables:", cur.fetchall())
    finally:
        conn.close()

if __name__ == "__main__":
    main()