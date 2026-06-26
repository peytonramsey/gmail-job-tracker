# Phase I: hits Gmail API, saves email_df_checkpoint.csv

import time
import socket
from ssl import SSLEOFError
import pandas as pd
from auth import get_gmail_service
from patterns import ATS_PROVIDERS

CHECKPOINT_INTERVAL = 100

# Job-signal keywords; ATS provider names are appended from the shared list.
JOB_QUERY_TERMS = [
    'interview',
    '"offer letter"',
    '"job offer"',
    '"background check"',
    '"phone screen"',
    '"thank you for applying"',
    '"your application"',
    'assessment',
    'recruiter',
    'recruiting',
]
GMAIL_QUERY_TERMS = JOB_QUERY_TERMS + list(ATS_PROVIDERS)
GMAIL_QUERY = f'in:inbox category:primary ({" OR ".join(GMAIL_QUERY_TERMS)})'


def fetch_message(service, msg_id, retries=5):
    for attempt in range(retries):
        try:
            return service.users().messages().get(
                userId='me',
                id=msg_id,
                format='metadata',
                metadataHeaders=['Date', 'From', 'Subject', 'Reply-To', 'Sender']
            ).execute()
        except (SSLEOFError, socket.error, ConnectionResetError, OSError):
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                raise


def parse_message_row(msg_meta, msg):
    headers = {h['name']: h['value'] for h in msg['payload']['headers']}
    return {
        'MsgId':    msg_meta['id'],
        'Date':     headers.get('Date', ''),
        'From':     headers.get('From', ''),
        'Subject':  headers.get('Subject', ''),
        'Reply-To': headers.get('Reply-To', ''),
        'Sender':   headers.get('Sender', ''),
        'Snippet':  msg.get('snippet', ''),
    }


if __name__ == '__main__':
    service = get_gmail_service()

    messages = []
    page_token = None

    while True:
        results = service.users().messages().list(
            userId='me',
            q=GMAIL_QUERY,
            maxResults=500,
            pageToken=page_token
        ).execute()
        messages.extend(results.get('messages', []))
        page_token = results.get('nextPageToken')
        if not page_token:
            break

    print(f'Found {len(messages)} messages')

    rows = []
    for i, msg_meta in enumerate(messages):
        msg = fetch_message(service, msg_meta['id'])
        rows.append(parse_message_row(msg_meta, msg))
        if i % CHECKPOINT_INTERVAL == 0:
            print(f'Processed {i}/{len(messages)}')
            pd.DataFrame(rows).to_csv('email_df_checkpoint.csv', index=False)

    email_df = pd.DataFrame(rows)
    email_df.to_csv('email_df_checkpoint.csv', index=False)
    print(f'Done. {len(email_df)} emails loaded.')
