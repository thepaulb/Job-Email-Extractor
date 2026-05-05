#!/usr/bin/env python3
"""
Job Link Extractor
Connects to Gmail, finds emails with a specified label,
extracts links, filters by keywords, and writes a daily markdown report.
"""

import os
import sys
import json
import re
import base64
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse, unquote, urlencode, parse_qs

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from bs4 import BeautifulSoup

# Gmail API read-only scope
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

# Paths relative to this script's location
SCRIPT_DIR = Path(__file__).parent.resolve()
CREDENTIALS_FILE = SCRIPT_DIR / "credentials.json"
TOKEN_FILE = SCRIPT_DIR / "token.json"
CONFIG_FILE = SCRIPT_DIR / "config.json"


def load_config():
    """Load configuration from config.json."""
    with open(CONFIG_FILE, "r") as f:
        config = json.load(f)
    return config


def authenticate():
    """Authenticate with Gmail API using OAuth2."""
    creds = None

    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_FILE.exists():
                print(f"ERROR: {CREDENTIALS_FILE} not found.")
                print("Follow GMAIL_API_SETUP.md to download your OAuth credentials.")
                sys.exit(1)
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
            creds = flow.run_local_server(port=0)

        with open(TOKEN_FILE, "w") as token:
            token.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def get_label_id(service, label_name):
    """Find the Gmail label ID by name (case-insensitive)."""
    results = service.users().labels().list(userId="me").execute()
    labels = results.get("labels", [])
    for label in labels:
        if label["name"].lower() == label_name.lower():
            return label["id"]
    return None


def fetch_emails(service, label_id, after_date):
    """Fetch emails with a given label received after a specific date."""
    # Gmail query: label + date filter
    query = f"after:{after_date}"
    messages = []
    page_token = None

    while True:
        results = (
            service.users()
            .messages()
            .list(
                userId="me",
                labelIds=[label_id],
                q=query,
                pageToken=page_token,
            )
            .execute()
        )
        messages.extend(results.get("messages", []))
        page_token = results.get("nextPageToken")
        if not page_token:
            break

    return messages


def get_email_details(service, msg_id):
    """Get the sender, date, subject, and body of an email."""
    msg = (
        service.users()
        .messages()
        .get(userId="me", id=msg_id, format="full")
        .execute()
    )

    headers = msg.get("payload", {}).get("headers", [])
    sender = ""
    date_str = ""
    subject = ""

    for header in headers:
        name = header["name"].lower()
        if name == "from":
            sender = header["value"]
        elif name == "date":
            date_str = header["value"]
        elif name == "subject":
            subject = header["value"]

    # Extract the body (handle multipart and plain messages)
    body_html = ""
    body_text = ""
    payload = msg.get("payload", {})

    def extract_parts(part):
        nonlocal body_html, body_text
        mime_type = part.get("mimeType", "")
        if mime_type == "text/html":
            data = part.get("body", {}).get("data", "")
            if data:
                body_html += base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        elif mime_type == "text/plain":
            data = part.get("body", {}).get("data", "")
            if data:
                body_text += base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        for sub_part in part.get("parts", []):
            extract_parts(sub_part)

    extract_parts(payload)

    return {
        "sender": sender,
        "date": date_str,
        "subject": subject,
        "body_html": body_html,
        "body_text": body_text,
    }


def extract_links(email_details):
    """Extract all HTTP(S) links from email body."""
    links = set()

    # Extract from HTML
    if email_details["body_html"]:
        soup = BeautifulSoup(email_details["body_html"], "html.parser")
        for a_tag in soup.find_all("a", href=True):
            # Skip links nested inside another link (e.g. LinkedIn Job Alerts)
            if a_tag.find_parent("a"):
                continue
            href = a_tag["href"].strip()
            if href.startswith(("http://", "https://")):
                link_text = a_tag.get_text(separator=", ", strip=True) or ""
                links.add((href, link_text))

    # Also extract URLs from plain text as fallback
    if email_details["body_text"]:
        url_pattern = re.compile(r'https?://[^\s<>"\')\]]+')
        for url in url_pattern.findall(email_details["body_text"]):
            # Only add if not already captured from HTML
            if not any(url == existing_url for existing_url, _ in links):
                links.add((url, ""))

    return list(links)


def matches_keywords(url, link_text, keywords):
    """Check if a URL or its link text matches any of the keywords."""
    # Decode the URL for better matching
    decoded_url = unquote(url).lower()
    text_lower = link_text.lower()

    for keyword in keywords:
        kw = keyword.lower()
        if kw in decoded_url or kw in text_lower:
            return True
    return False


def normalize_url(url):
    """Normalize a URL for deduplication by stripping tracking parameters.
    For LinkedIn job URLs, extract just the job ID."""
    parsed = urlparse(url)
    # LinkedIn job links: extract the job ID from the path
    linkedin_match = re.search(r'/jobs/view/(\d+)', parsed.path)
    if linkedin_match:
        return f"linkedin-job:{linkedin_match.group(1)}"
    # For other URLs, strip common tracking params
    tracking_params = {
        'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
        'trackingId', 'refId', 'trk', 'trkEmail', 'midToken', 'midSig',
        'lipi', 'eid', 'otpToken',
    }
    qs = parse_qs(parsed.query, keep_blank_values=True)
    cleaned_qs = {k: v for k, v in qs.items() if k not in tracking_params}
    cleaned_url = parsed._replace(query=urlencode(cleaned_qs, doseq=True)).geturl()
    return cleaned_url


def clean_sender(sender):
    """Extract a readable name from the From header."""
    # "John Doe <john@example.com>" → "John Doe"
    match = re.match(r'^"?([^"<]+)"?\s*<', sender)
    if match:
        return match.group(1).strip()
    return sender


def parse_email_date(date_str):
    """Parse email date header into a readable format."""
    # Try common email date formats
    for fmt in [
        "%a, %d %b %Y %H:%M:%S %z",
        "%d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
    ]:
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            return dt.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            continue
    # Fallback: return raw string, trimmed
    return date_str.strip()[:25]


def generate_markdown(date_label, entries, output_folder):
    """Write the filtered job links to a daily markdown file."""
    output_dir = SCRIPT_DIR / output_folder
    output_dir.mkdir(exist_ok=True)

    # Version control: increment if file already exists for today
    base_filepath = output_dir / f"jobs_{date_label}.md"
    if not base_filepath.exists():
        filepath = base_filepath
    else:
        version = 2
        while True:
            filepath = output_dir / f"jobs_{date_label}_v{version}.md"
            if not filepath.exists():
                break
            version += 1

    with open(filepath, "w") as f:
        f.write(f"# Job Opportunities — {date_label}\n\n")

        if not entries:
            f.write("No matching job links found for this date.\n")
        else:
            f.write(f"**{len(entries)} link(s) found**\n\n---\n\n")
            
            for i, entry in enumerate(entries, 1):
                desc = None
                title = entry["title"] if entry["title"] else "Untitled Link"
                # Format title if Indeed text contains source 
                # info (e.g. "Indeed, Software Engineer at XYZ")
                if "Indeed" in entry['source'] or "LinkedIn" in entry['source']:
                    title, *desc = title.split(", ", 1)
                    desc = desc[0].lstrip() if desc else None
  
                f.write(f"### {i}. {title}\n\n")
                f.write(f"**Description:** {desc}\n\n") if desc else "\n\n"
                f.write(f"- **Source:** {entry['source']}\n")
                f.write(f"- **Link:** [{title}]({entry['url']})\n"
                        if len(entry['url']) > 80
                        else f"- **Link:** [{entry['url']}]({entry['url']})\n")
                f.write(f"- **Date:** {entry['date']}\n")
                f.write(f"- **Matched keyword:** {entry['matched_keyword']}\n")
                f.write("\n---\n\n")
    return filepath


def main():
    config = load_config()
    label_name = config["gmail_label"]
    keywords = config["keywords"]
    output_folder = config.get("output_folder", "daily_jobs")
    lookback_days = config.get("lookback_days", 1)

    # Calculate date range
    target_date = datetime.now() - timedelta(days=lookback_days)
    after_date = target_date.strftime("%Y/%m/%d")
    date_label = datetime.now().strftime("%Y-%m-%d")

    print(f"Job Link Extractor")
    print(f"==================")
    print(f"Label: {label_name}")
    print(f"Keywords: {', '.join(keywords)}")
    print(f"Looking for emails after: {after_date}")
    print()

    # Authenticate
    print("Authenticating with Gmail...")
    service = authenticate()

    # Find label
    label_id = get_label_id(service, label_name)
    if not label_id:
        print(f"ERROR: Label '{label_name}' not found in your Gmail.")
        print("Make sure the label exists (labels are case-sensitive in Gmail).")
        sys.exit(1)
    print(f"Found label '{label_name}' (ID: {label_id})")

    # Fetch emails
    print("Fetching emails...")
    messages = fetch_emails(service, label_id, after_date)
    print(f"Found {len(messages)} email(s) with label '{label_name}'")

    # Process each email
    all_entries = []
    seen_urls = set()

    for msg in messages:
        details = get_email_details(service, msg["id"])
        links = extract_links(details)

        sender = clean_sender(details["sender"])
        email_date = parse_email_date(details["date"])

        for url, link_text in links:
            # Skip duplicates (using normalized URL for comparison)
            norm_url = normalize_url(url)
            if norm_url in seen_urls:
                continue

            # Check keyword match
            for keyword in keywords:
                if matches_keywords(url, link_text, [keyword]):
                    seen_urls.add(norm_url)
                    all_entries.append({
                        "title": link_text or details["subject"],
                        "url": url,
                        "source": sender,
                        "date": email_date,
                        "matched_keyword": keyword,
                    })
                    break  # One match is enough

    print(f"\nFiltered to {len(all_entries)} link(s) matching keywords")

    # Generate output
    filepath = generate_markdown(date_label, all_entries, output_folder)
    print(f"Report saved to: {filepath}")


if __name__ == "__main__":
    main()
