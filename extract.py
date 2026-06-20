# Phase III: loads job_emails.csv, runs AI + regex, saves job_tracker.csv

import asyncio
import re
import base64
import yaml
import os
import time
import pandas as pd
from pydantic import BaseModel, Field
from typing import Literal
from pydantic_ai import Agent
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# Load credentials
with open('.yaml') as f:
    _cfg = yaml.safe_load(f)
os.environ['GROQ_API_KEY'] = _cfg['groq_api_key']

# Gmail service (token.json written by fetch.py)
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']
creds = Credentials.from_authorized_user_file('token.json', SCOPES)
if creds.expired and creds.refresh_token:
    creds.refresh(Request())
service = build('gmail', 'v1', credentials=creds)

# PydanticAI setup
class JobEmailDetails(BaseModel):
    company_name: str | None = Field(default=None)
    job_title: str | None = Field(default=None)
    status: Literal[
        "applied", "interview", "assessment", "offer",
        "rejected", "withdrawn", "unknown"
    ] = "unknown"
    confidence: float = Field(ge=0, le=1)
    evidence_snippets: list[str] = Field(default_factory=list)

extraction_agent = Agent('groq:llama-3.1-8b-instant', output_type=JobEmailDetails,
system_prompt="""Extract job application details from recruiting emails.
Rules:
- Only extract company_name if it appears verbatim in the provided text.
- evidence_snippets must be exact substrings copied from the email text.
- Return null rather than guessing.
- status reflects the current application stage, not just keywords."""
)

# Job title regex patterns
TITLE_KW = re.compile(
    r'\b((?:senior|junior|lead|principal|staff|associate)\s+)?'
    r'(data\s+(?:scientist|analyst|engineer|science|architect)|'
    r'machine\s+learning(?:\s+engineer)?|ml\s+engineer|ai\s+engineer|'
    r'software\s+(?:engineer|developer)|research\s+scientist|applied\s+scientist|'
    r'(?:backend|front[\s\-]?end|full[\s\-]?stack)\s+(?:engineer|developer)|'
    r'analytics\s+engineer|platform\s+engineer|cloud\s+engineer|'
    r'devops\s+engineer|quantitative\s+analyst|business\s+analyst|'
    r'product\s+(?:manager|analyst))\b',
    re.I
)

TITLE_PHRASE_PATS = [
    re.compile(
        r'(?:applied\s+for|application\s+for|applying\s+for|your\s+application\s+(?:for|to))'
        r'\s+(?:the\s+)?(?:position\s+of\s+)?([A-Za-z][A-Za-z0-9 ,\-/()]{3,70})'
        r'(?=\s+(?:at|with|position|role)|[,.\n]|$)', re.I),
    re.compile(
        r'(?:position|role|job\s+title|title|opening)\s*[:\-]\s*'
        r'([A-Za-z][A-Za-z0-9 ,\-/()]{3,70})(?=[,.\n]|$)', re.I),
]

def extract_title_from_text(text):
    for pat in TITLE_PHRASE_PATS:
        m = pat.search(text)
        if m:
            candidate = m.group(1).strip()
            if TITLE_KW.search(candidate):
                return candidate.title()
    m = TITLE_KW.search(text)
    if m:
        return m.group(0).strip().title()
    return None

# Load data from Phase II
job_emails = pd.read_csv('job_emails.csv')

# Build index -> MsgId map from DataFrame column (written by fetch.py, passed through classify.py)
msg_id_map = {}
if 'MsgId' in job_emails.columns:
    msg_id_map = dict(zip(job_emails.index, job_emails['MsgId']))
    print(f"MsgId map built from DataFrame: {len(msg_id_map)} entries")
else:
    print("Warning: MsgId column not found — body fetching will be skipped")

## Run AI extraction
async def process_batch(rows, concurrency=20):
    semaphore = asyncio.Semaphore(concurrency)
    results = {}

    async def process_one(idx, row):
        source = f"{row['From']} {row['Subject']} {row['Snippet']}"
        prompt = f"From: {row['From']}\nSubject: {row['Subject']}\nSnippet: {row['Snippet']}"
        async with semaphore:
            try:
                result = await extraction_agent.run(prompt)
                d = result.output
                d.evidence_snippets = [s for s in d.evidence_snippets if s.lower() in source.lower()]
                if d.company_name and d.company_name.lower() not in source.lower():
                    d.company_name = None
                results[idx] = d
            except Exception as e:
                print(f"Error on row {idx}: {e}")
                results[idx] = None

    await asyncio.gather(*[process_one(idx, row) for idx, row in rows.iterrows()])
    return results

job_emails['JobTitle'] = None
job_emails['Confidence'] = None

print(f'Sending {len(job_emails)} rows to extraction_agent...')
ai_results = asyncio.run(process_batch(job_emails))

for idx, details in ai_results.items():
    if details is None:
        continue
    if details.company_name:
        job_emails.loc[idx, 'Company'] = details.company_name
    job_emails.loc[idx, 'JobTitle'] = details.job_title
    if details.status != 'unknown':
        job_emails.loc[idx, 'Status'] = details.status.capitalize()
    job_emails.loc[idx, 'Confidence'] = details.confidence

# Regex pass: fill null titles from Subject+Snippet (no tokens used)
for idx, row in job_emails[job_emails['JobTitle'].isna()].iterrows():
    title = extract_title_from_text(f"{row['Subject']} {row['Snippet']}")
    if title:
        job_emails.loc[idx, 'JobTitle'] = title

print(f'After AI + regex Subject pass: {job_emails["JobTitle"].notna().sum()} / {len(job_emails)} titles found')

## Fetch bodies for null-JobTitle rows
def extract_body_text(payload, max_chars=3000):
    mime_type = payload.get('mimeType', '')
    if mime_type == 'text/plain':
        data = payload.get('body', {}).get('data', '')
        if data:
            return base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')[:max_chars]
    elif mime_type.startswith('multipart/'):
        for part in payload.get('parts', []):
            text = extract_body_text(part, max_chars)
            if text:
                return text
    return ''

null_title = job_emails[job_emails['JobTitle'].isna() & job_emails['Company'].notna()]
print(f"Null-JobTitle rows with known company: {len(null_title)}")

def fetch_body_with_retry(msg_id, retries=3):
    for attempt in range(retries):
        try:
            full_msg = service.users().messages().get(
                userId='me', id=msg_id, format='full'
            ).execute()
            return extract_body_text(full_msg.get('payload', {}))
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    return ''

# Sequential body fetch (httplib2 is not thread-safe)
bodies = {}
for i, (idx, row) in enumerate(null_title.iterrows()):
    if i % 100 == 0:
        print(f"  Fetching body {i}/{len(null_title)}...")
    msg_id = msg_id_map.get(idx)
    if not msg_id:
        continue
    body = fetch_body_with_retry(msg_id)
    if body:
        bodies[idx] = body

print(f"Fetched {len(bodies)} / {len(null_title)} bodies")

# Regex pass on body text — no AI, no token cost
updated = 0
for idx, body in bodies.items():
    title = extract_title_from_text(body[:1000])
    if title:
        job_emails.loc[idx, 'JobTitle'] = title
        updated += 1

print(f"Body regex pass: updated {updated} / {len(null_title)} rows")
fill_rate = job_emails['JobTitle'].notna().mean()
print(f"Total fill rate: {job_emails['JobTitle'].notna().sum()} / {len(job_emails)} ({fill_rate:.1%})")

## Merge and deduplicate
status_rank = {'Offer': 4, 'Interview': 3, 'Rejected': 2, 'Applied': 1, 'Other': 0, 'Unknown': 0}
job_emails['StatusRank'] = job_emails['Status'].map(status_rank).fillna(0)

known = job_emails[job_emails['Company'].notna() & job_emails['JobTitle'].notna()]
known = known.sort_values('StatusRank', ascending=False).drop_duplicates(subset=['Company', 'JobTitle'], keep='first')
unknown = job_emails[job_emails['Company'].isna() | job_emails['JobTitle'].isna()]

job_emails = (
    pd.concat([known, unknown])
      .drop(columns='StatusRank')
      .sort_values('Date', ascending=False)
)

print(f'{len(job_emails)} unique applications after deduplication')

## Export
job_emails[['Date', 'Company', 'JobTitle', 'Subject', 'Status', 'Confidence']].to_csv('job_tracker.csv', index=False)
print('Saved to job_tracker.csv')
