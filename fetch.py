# Phase I: hits Gmail API, saves email_df_checkpoint.csv

## Imports
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import os
import pandas as pd

## Authenticate with Gmail API
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

creds = None
if os.path.exists('token.json'):
    creds = Credentials.from_authorized_user_file('token.json', SCOPES)

if not creds or not creds.valid:
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
        creds = flow.run_local_server(port=0)
    with open('token.json', 'w') as token:
        token.write(creds.to_json())

service = build('gmail', 'v1', credentials=creds)

## Fetch all Primary inbox message IDs
messages = []
page_token = None

while True:
    results = service.users().messages().list(
        userId='me',
        q='in:inbox category:primary (interview OR "offer letter" OR "job offer" OR "background check" OR "phone screen" OR "thank you for applying" OR "your application" OR assessment OR recruiter OR recruiting OR workday OR greenhouse OR lever OR taleo OR icims OR jobvite OR smartrecruiters)',
        maxResults=500,
        pageToken=page_token
    ).execute()
    messages.extend(results.get('messages', []))
    page_token = results.get('nextPageToken')
    if not page_token:
        break

print(f'Found {len(messages)} messages')

## Fetch message details and build DataFrame
import time
import socket
from ssl import SSLEOFError

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

rows = []
for i, msg_meta in enumerate(messages):
    msg = fetch_message(service, msg_meta['id'])
    headers = {h['name']: h['value'] for h in msg['payload']['headers']}
    rows.append({
        'MsgId': msg_meta['id'],
        'Date': headers.get('Date', ''),
        'From': headers.get('From', ''),
        'Subject': headers.get('Subject', ''),
        'Reply-To': headers.get('Reply-To', ''),
        'Sender': headers.get('Sender', ''),
        'Snippet': msg.get('snippet', ''),
    })
    if i % 100 == 0:
        print(f'Processed {i}/{len(messages)}')
        pd.DataFrame(rows).to_csv('email_df_checkpoint.csv', index=False)

email_df = pd.DataFrame(rows)
email_df.to_csv('email_df_checkpoint.csv', index=False)
print(f'Done. {len(email_df)} emails loaded.')
