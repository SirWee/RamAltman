
import base64
from email.message import EmailMessage
from pathlib import Path

import psutil
import requests
from dotenv import get_key
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow


BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"
CLIENT_SECRETS_FILE = BASE_DIR / "credentials.json"
TOKEN_FILE = BASE_DIR / "token.json"
GMAIL_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


def get_gmail_credentials() -> Credentials:
    credentials = None
    if TOKEN_FILE.is_file():
        credentials = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())

    if not credentials or not credentials.valid:
        if not CLIENT_SECRETS_FILE.is_file():
            raise FileNotFoundError(
                f"OAuth client file not found: {CLIENT_SECRETS_FILE}. "
                "Download a Desktop app OAuth client JSON from Google Cloud and "
                "save it as credentials.json."
            )
        flow = InstalledAppFlow.from_client_secrets_file(
            str(CLIENT_SECRETS_FILE), SCOPES
        )
        credentials = flow.run_local_server(port=0)

    TOKEN_FILE.write_text(credentials.to_json(), encoding="utf-8")
    return credentials


def send_email(sender_email: str, recipient_email: str, body: str) -> str:
    message = EmailMessage()
    message["From"] = sender_email
    message["To"] = recipient_email
    message["Subject"] = "Daily Memory Usage Report"
    message.set_content(body)

    raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    credentials = get_gmail_credentials()
    response = requests.post(
        GMAIL_SEND_URL,
        headers={"Authorization": f"Bearer {credentials.token}"},
        json={"raw": raw_message},
        timeout=30,
    )
    try:
        response.raise_for_status()
    except requests.HTTPError as error:
        try:
            api_error = response.json().get("error", {})
        except ValueError:
            api_error = {}

        message = api_error.get("message", response.text)
        reasons = {
            item.get("reason")
            for item in api_error.get("errors", [])
            if item.get("reason")
        }
        guidance = ""
        if reasons.intersection({"accessNotConfigured", "SERVICE_DISABLED"}):
            guidance = (
                " Enable the Gmail API in the Google Cloud project associated "
                "with credentials.json, then retry."
            )
        elif reasons.intersection(
            {"insufficientPermissions", "ACCESS_TOKEN_SCOPE_INSUFFICIENT"}
        ):
            guidance = (
                " The saved OAuth token may lack the gmail.send scope. Delete "
                "token.json and rerun to grant the requested Gmail send permission."
            )

        raise RuntimeError(
            f"Gmail API returned HTTP {response.status_code}: {message}. "
            f"Reason(s): {', '.join(sorted(reasons)) or 'not supplied'}.{guidance}"
        ) from error
    return response.json()["id"]


def main() -> None:
    memory = psutil.virtual_memory()
    email_body = f"""Hello Mr. Altman,

I hope this message finds you well. I wanted to provide you with a quick update on my personal computer's memory usage.
I've also provided a breakdown of what it has been used for.

Usage Summary:
- Total memory: {memory.total / (1024 ** 3):.2f} GB
- Longest daily usage: Consumed approximately 1.5 GB while watching Dragon Ball Z for 5 hours on a separate machine with an estimated 40% idle memory.
- Shortest daily usage: Checking emails for 10 minutes, which consumed approximately 0.1 GB of memory.
- Most memory-intensive task: Playing video games for 3 hours, which consumed approximately 12 GB of memory.

Memory Usage Report:
- Total memory: {memory.total / (1024 ** 3):.2f} GB
- Idle memory: {memory.available / (1024 ** 3):.2f} GB
- Used memory: {memory.used / (1024 ** 3):.2f} GB
- Memory percentage: {memory.percent}%
"""

    sender_email = get_key(str(ENV_FILE), "EMAIL_USER")
    recipient_email = (
        get_key(str(ENV_FILE), "EMAIL_RECIPIENT") or sender_email
    )
    if not sender_email or not recipient_email:
        raise ValueError(
            "Set EMAIL_USER in .env to the Gmail account authorized by OAuth; "
            "optionally set EMAIL_RECIPIENT to a different recipient."
        )

    print(email_body)
    message_id = send_email(sender_email, recipient_email, email_body)
    print(f"Email sent successfully! Gmail message ID: {message_id}")


if __name__ == "__main__":
    main()