import requests
import smtplib
import sqlite3
import os
import time
import schedule
from datetime import datetime, timezone
from email.message import EmailMessage
from dotenv import load_dotenv

load_dotenv()

# ─── Configuration ────────────────────────────────────────────────────────────
WEBSITES = [
    "https://sourcecode.academy",
    # Aur websites yahan add karo
]

EMAIL_ADDRESS      = os.environ.get('SENDER_EMAIL')
EMAIL_PASSWORD     = os.environ.get('EMAIL_PASS')
RECEIVER_EMAIL     = os.environ.get('RECEIVER_EMAIL')

TIMEOUT_SECONDS    = 15
FAILURE_THRESHOLD  = 3
DB_PATH            = os.environ.get('DB_PATH', 'monitor.db')
CHECK_INTERVAL_MIN = 10
# ──────────────────────────────────────────────────────────────────────────────


# ─── Database Setup ───────────────────────────────────────────────────────────
def init_db() -> None:
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS checks (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                url              TEXT    NOT NULL,
                status           TEXT    NOT NULL,
                status_code      INTEGER,
                response_time_ms INTEGER,
                error            TEXT,
                checked_at       TEXT    NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS site_state (
                url           TEXT PRIMARY KEY,
                last_status   TEXT    NOT NULL,
                failure_count INTEGER NOT NULL DEFAULT 0,
                alert_sent    INTEGER NOT NULL DEFAULT 0,
                last_alert_at TEXT
            )
        """)
        conn.commit()


def save_check(result: dict) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            INSERT INTO checks (url, status, status_code, response_time_ms, error, checked_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            result["url"],
            result["status"],
            result["status_code"],
            result["response_time_ms"],
            result["error"],
            result["checked_at"],
        ))
        conn.commit()


def get_site_state(url: str) -> dict:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT last_status, failure_count, alert_sent, last_alert_at FROM site_state WHERE url = ?",
            (url,)
        ).fetchone()

    if row:
        return {
            "last_status":   row[0],
            "failure_count": row[1],
            "alert_sent":    row[2],
            "last_alert_at": row[3],
        }
    return {"last_status": "UP", "failure_count": 0, "alert_sent": 0, "last_alert_at": None}


def update_site_state(url: str, status: str, failure_count: int, alert_sent: int) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            INSERT INTO site_state (url, last_status, failure_count, alert_sent, last_alert_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                last_status   = excluded.last_status,
                failure_count = excluded.failure_count,
                alert_sent    = excluded.alert_sent,
                last_alert_at = excluded.last_alert_at
        """, (url, status, failure_count, alert_sent, now))
        conn.commit()
# ──────────────────────────────────────────────────────────────────────────────


# ─── Email ────────────────────────────────────────────────────────────────────
def send_email(subject: str, body: str) -> None:
    if not all([EMAIL_ADDRESS, EMAIL_PASSWORD, RECEIVER_EMAIL]):
        print("❌ Email credentials missing!")
        return

    msg = EmailMessage()
    msg.set_content(body)
    msg["Subject"] = subject
    msg["From"]    = EMAIL_ADDRESS
    msg["To"]      = RECEIVER_EMAIL

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            smtp.send_message(msg)
        print(f"📧 Email sent → {RECEIVER_EMAIL}")
    except Exception as e:
        print(f"❌ Failed to send email: {e}")


def build_down_email(result: dict, failure_count: int) -> tuple[str, str]:
    url    = result["url"]
    status = result["status"]
    ts     = result["checked_at"]

    if status == "DOWN":
        subject = f"🔴 ALERT: Website Down — {url}"
        body = (
            f"Your website is DOWN!\n\n"
            f"URL           : {url}\n"
            f"Status Code   : {result['status_code']}\n"
            f"Failed checks : {failure_count} consecutive\n"
            f"Detected At   : {ts}\n\n"
            f"Please investigate immediately."
        )
    elif status == "TIMEOUT":
        subject = f"⏱️ ALERT: Website Timeout — {url}"
        body = (
            f"Your website is not responding!\n\n"
            f"URL           : {url}\n"
            f"Error         : {result['error']}\n"
            f"Failed checks : {failure_count} consecutive\n"
            f"Detected At   : {ts}\n\n"
            f"Server may be overloaded."
        )
    else:
        subject = f"🚫 ALERT: Website Unreachable — {url}"
        body = (
            f"Your website is UNREACHABLE!\n\n"
            f"URL           : {url}\n"
            f"Error         : {result['error']}\n"
            f"Failed checks : {failure_count} consecutive\n"
            f"Detected At   : {ts}\n\n"
            f"Check your server / DNS settings."
        )
    return subject, body


def build_recovery_email(url: str, response_time_ms: int, ts: str) -> tuple[str, str]:
    subject = f"✅ RECOVERED: Website is back UP — {url}"
    body = (
        f"Good news! Your website is back online.\n\n"
        f"URL           : {url}\n"
        f"Response Time : {response_time_ms}ms\n"
        f"Recovered At  : {ts}\n\n"
        f"All systems normal."
    )
    return subject, body
# ──────────────────────────────────────────────────────────────────────────────


# ─── Core Check ───────────────────────────────────────────────────────────────
def check_website(url: str) -> dict:
    result = {
        "url":              url,
        "status":           "unknown",
        "status_code":      None,
        "response_time_ms": None,
        "error":            None,
        "checked_at":       datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    }

    try:
        start      = time.time()
        response   = requests.get(url, timeout=TIMEOUT_SECONDS)
        elapsed_ms = round((time.time() - start) * 1000)

        result["status_code"]      = response.status_code
        result["response_time_ms"] = elapsed_ms

        if response.status_code == 200:
            result["status"] = "UP"
            print(f"✅ {url} → UP  |  {elapsed_ms}ms  |  {result['checked_at']}")
        else:
            result["status"] = "DOWN"
            print(f"🔴 {url} → DOWN  |  Status: {response.status_code}  |  {result['checked_at']}")

    except requests.exceptions.Timeout:
        result["status"] = "TIMEOUT"
        result["error"]  = f"Request timed out after {TIMEOUT_SECONDS}s"
        print(f"⏱️  {url} → TIMEOUT  |  {result['checked_at']}")

    except requests.exceptions.ConnectionError as e:
        result["status"] = "UNREACHABLE"
        result["error"]  = str(e)
        print(f"🚫 {url} → UNREACHABLE  |  {result['checked_at']}")

    except Exception as e:
        result["status"] = "ERROR"
        result["error"]  = str(e)
        print(f"❓ {url} → ERROR: {e}  |  {result['checked_at']}")

    return result


def process_result(result: dict) -> None:
    url    = result["url"]
    status = result["status"]
    state  = get_site_state(url)

    if status == "UP":
        if state["alert_sent"] == 1:
            subject, body = build_recovery_email(url, result["response_time_ms"], result["checked_at"])
            send_email(subject, body)
            print(f"💚 Recovery alert sent for {url}")
        update_site_state(url, "UP", failure_count=0, alert_sent=0)

    else:
        new_failure_count = state["failure_count"] + 1
        print(f"⚠️  Failure count for {url}: {new_failure_count}/{FAILURE_THRESHOLD}")

        if new_failure_count >= FAILURE_THRESHOLD and state["alert_sent"] == 0:
            subject, body = build_down_email(result, new_failure_count)
            send_email(subject, body)
            update_site_state(url, status, failure_count=new_failure_count, alert_sent=1)

        elif state["alert_sent"] == 1:
            print(f"🔕 Alert already sent for {url}, skipping duplicate.")
            update_site_state(url, status, failure_count=new_failure_count, alert_sent=1)

        else:
            update_site_state(url, status, failure_count=new_failure_count, alert_sent=0)
# ──────────────────────────────────────────────────────────────────────────────


# ─── Main ─────────────────────────────────────────────────────────────────────
def run_checks() -> None:
    print(f"\n{'='*55}")
    print(f"  Website Monitor — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"{'='*55}")

    for url in WEBSITES:
        result = check_website(url)
        save_check(result)
        process_result(result)

    print(f"{'='*55}\n")


if __name__ == "__main__":
    init_db()
    print("🚀 Website Monitor started on Railway!")
    print(f"⏰ Checking every {CHECK_INTERVAL_MIN} minutes — exact time pe!")

    # Pehla check turant karo
    run_checks()

    # Phir har 10 min pe automatically
    schedule.every(CHECK_INTERVAL_MIN).minutes.do(run_checks)

    while True:
        schedule.run_pending()
        time.sleep(30)