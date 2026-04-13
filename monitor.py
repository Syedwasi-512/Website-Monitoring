import requests
import smtplib
import os
import time
from datetime import datetime, timezone
from email.message import EmailMessage
from dotenv import load_dotenv

load_dotenv()

# ─── Configuration ────────────────────────────────────────────────────────────
WEBSITES = [
    "https://admin.sourcecode.academy/",
    "https://sourcecode.academy/phpmyadmin",
    # Aur websites add kar sakte ho yahan
]

EMAIL_ADDRESS   = os.environ.get('SENDER_EMAIL')
EMAIL_PASSWORD  = os.environ.get('EMAIL_PASS')
RECEIVER_EMAIL  = os.environ.get('RECEIVER_EMAIL')

TIMEOUT_SECONDS = 15
# ──────────────────────────────────────────────────────────────────────────────


def send_email(subject: str, body: str) -> None:
    """Send alert email via Gmail SMTP."""
    if not all([EMAIL_ADDRESS, EMAIL_PASSWORD, RECEIVER_EMAIL]):
        print("❌ Email credentials missing in environment variables!")
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
        print(f"📧 Alert email sent → {RECEIVER_EMAIL}")
    except Exception as e:
        print(f"❌ Failed to send email: {e}")


def check_website(url: str) -> dict:
    """
    Check a single website.
    Returns a dict with: url, status, status_code, response_time_ms, error
    """
    result = {
        "url": url,
        "status": "unknown",
        "status_code": None,
        "response_time_ms": None,
        "error": None,
        "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    }

    try:
        start = time.time()
        response = requests.get(url, timeout=TIMEOUT_SECONDS)
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


def build_alert_email(result: dict) -> tuple[str, str]:
    """Build subject and body for alert email based on check result."""
    url    = result["url"]
    status = result["status"]
    ts     = result["checked_at"]

    if status == "DOWN":
        subject = f"🔴 ALERT: Website Down — {url}"
        body = (
            f"Your website is DOWN!\n\n"
            f"URL         : {url}\n"
            f"Status Code : {result['status_code']}\n"
            f"Checked At  : {ts}\n\n"
            f"Please investigate immediately."
        )
    elif status == "TIMEOUT":
        subject = f"⏱️ ALERT: Website Timeout — {url}"
        body = (
            f"Your website is not responding (TIMEOUT)!\n\n"
            f"URL        : {url}\n"
            f"Error      : {result['error']}\n"
            f"Checked At : {ts}\n\n"
            f"The server may be overloaded or unreachable."
        )
    else:  # UNREACHABLE / ERROR
        subject = f"🚫 ALERT: Website Unreachable — {url}"
        body = (
            f"Your website is UNREACHABLE!\n\n"
            f"URL        : {url}\n"
            f"Error      : {result['error']}\n"
            f"Checked At : {ts}\n\n"
            f"Check your server / DNS settings."
        )

    return subject, body


def run_checks() -> None:
    """Run checks for all configured websites."""
    print(f"\n{'='*55}")
    print(f"  Website Monitor — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"{'='*55}")

    for url in WEBSITES:
        result = check_website(url)

        if result["status"] != "UP":
            subject, body = build_alert_email(result)
            send_email(subject, body)

    print(f"{'='*55}\n")


if __name__ == "__main__":
    run_checks()