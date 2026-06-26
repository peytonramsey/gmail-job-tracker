# Phase III: loads job_emails.csv, runs regex then targeted AI, saves job_tracker.csv
#
# Extraction order per row:
#   1. Regex on Subject+Snippet  (free, runs on every row)
#   2. AI                        (only if Company/JobTitle still missing, Status weak, or NeedsAI flag)
#   3. Body fetch + regex        (last resort — only rows still null after step 2)

import asyncio
import re
import base64
import json
import time
import anthropic
import pandas as pd
from pydantic import BaseModel, Field, ValidationError
from typing import Literal
from pydantic_ai import Agent
from config import load_anthropic_key
from auth import get_gmail_service
from patterns import TITLE_KW

# Anthropic model for the targeted AI extraction pass. ANTHROPIC_MODEL_ID is the
# bare id for the raw SDK (batch path); pydantic-ai wants the 'anthropic:' prefix.
ANTHROPIC_MODEL_ID = 'claude-haiku-4-5-20251001'
ANTHROPIC_MODEL = f'anthropic:{ANTHROPIC_MODEL_ID}'

# Extraction transport. Batch API = 50% cheaper but ASYNCHRONOUS: this script
# submits every prompt at once, then polls until the batch finishes (usually
# minutes, up to 24h). Flip USE_BATCH = False for the synchronous pydantic-ai
# path (instant, full price) when iterating locally.
USE_BATCH = True
BATCH_POLL_SECONDS = 10
BATCH_MAX_TOKENS = 512
EXTRACTION_TOOL_NAME = 'record_job_details'

# System prompt shared by both transports.
SYSTEM_PROMPT = (
    'Extract job application details from recruiting emails.\n'
    'Focus on job_title and status — company is usually already known.\n'
    'Rules:\n'
    '- job_title: the specific role applied for, or null if absent.\n'
    '- status: the current application stage, not just keywords.\n'
    '- company_name: only if it appears verbatim in the text, else null.\n'
    '- evidence_snippets: at most ONE short exact substring from the email.\n'
    '- Return null rather than guessing.'
)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

class JobEmailDetails(BaseModel):
    company_name: str | None = Field(default=None)
    job_title: str | None = Field(default=None)
    status: Literal[
        "applied", "interview", "assessment", "offer",
        "rejected", "withdrawn", "unknown"
    ] = "unknown"
    confidence: float = Field(ge=0, le=1)
    evidence_snippets: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Title extraction (regex — no tokens)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Body fetching helpers
# ---------------------------------------------------------------------------

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


def fetch_body_with_retry(service, msg_id, retries=3):
    for attempt in range(retries):
        try:
            full_msg = service.users().messages().get(
                userId='me', id=msg_id, format='full'
            ).execute()
            return extract_body_text(full_msg.get('payload', {}))
        except Exception:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    return ''


# ---------------------------------------------------------------------------
# Phase functions
# ---------------------------------------------------------------------------

def run_regex_pass(job_emails):
    """Regex title extraction on ALL rows from Subject+Snippet. Free — no tokens used.
    Sets ExtractionMethod='regex' for any row where a title is found.
    """
    job_emails = job_emails.copy()
    found = 0
    for idx, row in job_emails[job_emails['JobTitle'].isna()].iterrows():
        title = extract_title_from_text(f"{row['Subject']} {row['Snippet']}")
        if title:
            job_emails.loc[idx, 'JobTitle'] = title
            job_emails.loc[idx, 'ExtractionMethod'] = 'regex'
            found += 1
    print(f'Regex pass:  {found} titles found  |  {job_emails["JobTitle"].notna().sum()} / {len(job_emails)} total')
    return job_emails


def _postprocess(details, source):
    """Validate AI output against the source email: keep only verbatim evidence
    (capped at one snippet — output tokens are the costly side) and drop a
    company name the model didn't actually see in the text."""
    if details is None:
        return None
    details.evidence_snippets = [s for s in details.evidence_snippets if s.lower() in source.lower()][:1]
    if details.company_name and details.company_name.lower() not in source.lower():
        details.company_name = None
    return details


async def _run_sync_async(prompts, agent, concurrency=20):
    semaphore = asyncio.Semaphore(concurrency)
    results = {}

    async def one(prompt):
        async with semaphore:
            try:
                result = await agent.run(prompt)
                results[prompt] = result.output
            except Exception as e:
                print(f'  AI error: {e}')
                results[prompt] = None

    await asyncio.gather(*[one(p) for p in prompts])
    return results


def run_sync(prompts):
    """Synchronous transport: pydantic-ai fan-out. Instant, full price.
    Returns {prompt: JobEmailDetails | None}."""
    agent = Agent(ANTHROPIC_MODEL, output_type=JobEmailDetails, system_prompt=SYSTEM_PROMPT)
    return asyncio.run(_run_sync_async(prompts, agent))


def run_batch(prompts):
    """Batch transport: Anthropic Message Batches. ~50% cheaper, asynchronous.
    Forces one tool call per request so the model returns JobEmailDetails-shaped
    JSON. Returns {prompt: JobEmailDetails | None}."""
    client = anthropic.Anthropic()
    tool = {
        'name': EXTRACTION_TOOL_NAME,
        'description': 'Record the extracted job application details.',
        'input_schema': JobEmailDetails.model_json_schema(),
    }
    ids = [f'row-{i}' for i in range(len(prompts))]
    requests = [{
        'custom_id': cid,
        'params': {
            'model': ANTHROPIC_MODEL_ID,
            'max_tokens': BATCH_MAX_TOKENS,
            'system': SYSTEM_PROMPT,
            'messages': [{'role': 'user', 'content': prompt}],
            'tools': [tool],
            'tool_choice': {'type': 'tool', 'name': EXTRACTION_TOOL_NAME},
        },
    } for cid, prompt in zip(ids, prompts)]

    batch = client.messages.batches.create(requests=requests)
    print(f'Batch:       submitted {len(requests)} requests (id {batch.id}); polling every {BATCH_POLL_SECONDS}s...')
    while True:
        batch = client.messages.batches.retrieve(batch.id)
        if batch.processing_status == 'ended':
            break
        time.sleep(BATCH_POLL_SECONDS)

    id_to_prompt = dict(zip(ids, prompts))
    results = {}
    succeeded = errored = 0
    for entry in client.messages.batches.results(batch.id):
        prompt = id_to_prompt.get(entry.custom_id)
        details = None
        if entry.result.type == 'succeeded':
            block = next((b for b in entry.result.message.content if b.type == 'tool_use'), None)
            if block is not None:
                try:
                    details = JobEmailDetails.model_validate(block.input)
                    succeeded += 1
                except ValidationError as e:
                    print(f'  validate error {entry.custom_id}: {e}')
                    errored += 1
            else:
                errored += 1
        else:
            errored += 1
        results[prompt] = details
    print(f'Batch:       {succeeded} succeeded, {errored} errored')
    return results


def run_ai_extraction(job_emails, mask, runner=None):
    """Run AI only on rows where mask is True, via `runner` (run_batch or run_sync).

    Groups rows by exact prompt so identical emails cost one call. Updates
    Company (only if the rules left it blank), JobTitle (if still null), Status,
    Confidence, EvidenceSnippets. Sets UsedAI=True on masked rows and
    ExtractionMethod='ai' wherever AI fills a null title.
    """
    job_emails = job_emails.copy()
    rows_to_process = job_emails[mask]

    if len(rows_to_process) == 0:
        print('AI pass:     0 rows needed (all resolved by regex)')
        return job_emails

    if runner is None:
        runner = run_batch if USE_BATCH else run_sync

    # Group identical prompts (templated ATS mail is common): one call, fanned out.
    prompt_to_indices = {}
    prompt_to_source = {}
    for idx, row in rows_to_process.iterrows():
        prompt = f"From: {row['From']}\nSubject: {row['Subject']}\nSnippet: {row['Snippet']}"
        prompt_to_indices.setdefault(prompt, []).append(idx)
        prompt_to_source.setdefault(prompt, f"{row['From']} {row['Subject']} {row['Snippet']}")

    pct = len(rows_to_process) / len(job_emails)
    print(f'AI pass:     {len(rows_to_process)} / {len(job_emails)} rows ({pct:.1%}) - skipping {len(job_emails) - len(rows_to_process)} clear rows')
    n_unique = len(prompt_to_indices)
    if n_unique < len(rows_to_process):
        print(f'             {len(rows_to_process)} rows -> {n_unique} unique prompts ({len(rows_to_process) - n_unique} duplicate calls saved)')

    raw = runner(list(prompt_to_indices))

    job_emails.loc[mask, 'UsedAI'] = True

    for prompt, indices in prompt_to_indices.items():
        details = _postprocess(raw.get(prompt), prompt_to_source[prompt])
        if details is None:
            continue
        for idx in indices:
            # Only fill company if the rules left it blank — the rule-based
            # extractor is right ~99.9% of the time, so never let AI overwrite a
            # good value (this was the README's "do not reply" company bug).
            if details.company_name and pd.isna(job_emails.loc[idx, 'Company']):
                job_emails.loc[idx, 'Company'] = details.company_name
            # Only overwrite title if regex left it blank
            if details.job_title and pd.isna(job_emails.loc[idx, 'JobTitle']):
                job_emails.loc[idx, 'JobTitle'] = details.job_title
                job_emails.loc[idx, 'ExtractionMethod'] = 'ai'
            if details.status != 'unknown':
                job_emails.loc[idx, 'Status'] = details.status.capitalize()
            job_emails.loc[idx, 'Confidence'] = details.confidence
            if details.evidence_snippets:
                job_emails.loc[idx, 'EvidenceSnippets'] = json.dumps(details.evidence_snippets)

    # Count titles AI actually filled (ExtractionMethod=='ai'), not every
    # non-null title on masked rows — many were already filled by the regex pass.
    ai_filled = (job_emails.loc[mask, 'ExtractionMethod'] == 'ai').sum()
    print(f'           AI filled {ai_filled} titles on those rows')
    return job_emails


def run_body_fetch(job_emails, service, msg_id_map):
    """Fetch full email bodies and run regex for rows still missing a title.
    This is the last resort — only called when regex+AI both failed.
    Sets ExtractionMethod='ai+body_regex' (these rows always passed through AI first).
    """
    job_emails = job_emails.copy()
    null_title = job_emails[job_emails['JobTitle'].isna() & job_emails['Company'].notna()]

    if len(null_title) == 0:
        print('Body fetch:  skipped (all titles resolved)')
        return job_emails

    print(f'Body fetch:  {len(null_title)} rows still need a title after regex+AI')

    bodies = {}
    for i, (idx, row) in enumerate(null_title.iterrows()):
        if i % 50 == 0 and i > 0:
            print(f'  ...{i}/{len(null_title)}')
        msg_id = msg_id_map.get(idx)
        if not msg_id:
            continue
        body = fetch_body_with_retry(service, msg_id)
        if body:
            bodies[idx] = body

    updated = 0
    for idx, body in bodies.items():
        title = extract_title_from_text(body[:1000])
        if title:
            job_emails.loc[idx, 'JobTitle'] = title
            # Body fetch only runs on rows whose title was still null, which means
            # they were in the AI mask and AI was already tried — hence always 'ai+'.
            job_emails.loc[idx, 'ExtractionMethod'] = 'ai+body_regex'
            updated += 1

    print(f'           Body regex: resolved {updated} / {len(null_title)} remaining')
    fill_rate = job_emails['JobTitle'].notna().mean()
    print(f'           Final title fill rate: {job_emails["JobTitle"].notna().sum()} / {len(job_emails)} ({fill_rate:.1%})')
    return job_emails


def _history_json(group) -> str:
    """Serialize a group of email rows into a JSON list ordered by date."""
    records = []
    for _, row in group.sort_values('Date').iterrows():
        records.append({
            'date': str(row.get('Date', ''))[:10],
            'status': str(row.get('Status', '')),
            'subject': str(row.get('Subject', '')),
        })
    return json.dumps(records)


def run_dedup(job_emails, known_only=False):
    """Dedup on (Company, JobTitle); falls back to Company-only for null-title rows.

    known_only=True is the lossless pre-AI pass: it collapses ONLY rows whose
    title is already known (true (Company, JobTitle) duplicates) and leaves
    null-title rows untouched, so distinct roles at one company are never merged
    before the AI can tell them apart. The full pass runs again after extraction.
    """
    job_emails = job_emails.copy()
    status_rank = {
        'Offer': 4, 'Interview': 3, 'Assessment': 2.5,
        'Rejected': 2, 'Applied': 1, 'Other': 0, 'Unknown': 0,
    }
    job_emails['_StatusRank'] = job_emails['Status'].map(status_rank).fillna(0)

    known = job_emails[job_emails['Company'].notna() & job_emails['JobTitle'].notna()].copy()
    if not known.empty:
        known_hist = {k: _history_json(g) for k, g in known.groupby(['Company', 'JobTitle'], sort=False)}
        known = known.sort_values('_StatusRank', ascending=False).drop_duplicates(
            subset=['Company', 'JobTitle'], keep='first'
        ).copy()
        known['EmailHistory'] = known.apply(
            lambda r: known_hist.get((r['Company'], r['JobTitle']), json.dumps([])), axis=1
        )

    company_only = job_emails[job_emails['Company'].notna() & job_emails['JobTitle'].isna()].copy()
    if not known_only:
        # Full pass only: collapse null-title rows to one per company. Skipped in
        # the pre-AI pass because it would merge distinct roles at one company.
        if not company_only.empty:
            co_hist = {k: _history_json(g) for k, g in company_only.groupby('Company', sort=False)}
            company_only = company_only.sort_values('_StatusRank', ascending=False).drop_duplicates(
                subset=['Company'], keep='first'
            ).copy()
            company_only['EmailHistory'] = company_only['Company'].map(co_hist)

    no_company = job_emails[job_emails['Company'].isna()]

    job_emails = (
        pd.concat([known, company_only, no_company])
          .drop(columns='_StatusRank')
          .sort_values('Date', ascending=False)
    )
    if known_only:
        print(f'Pre-AI dedup: {len(job_emails)} rows (lossless: title-present dupes only)')
    else:
        print(f'Dedup:       {len(job_emails)} unique applications')
    return job_emails


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    load_anthropic_key()

    runner = run_batch if USE_BATCH else run_sync
    print(f'Transport:   {"Batch API (async, ~50% cheaper)" if USE_BATCH else "synchronous (full price)"}')

    service = get_gmail_service()

    # --- Load ---
    job_emails = pd.read_csv('job_emails.csv')
    job_emails['Date'] = pd.to_datetime(job_emails['Date'], utc=True, errors='coerce')

    if 'MsgId' in job_emails.columns:
        msg_id_map = dict(zip(job_emails.index, job_emails['MsgId']))
    else:
        msg_id_map = {}
        print('Warning: MsgId column not found - body fetching will be skipped')

    if 'NeedsAI' not in job_emails.columns:
        job_emails['NeedsAI'] = False

    # Initialise tracking columns
    job_emails['JobTitle'] = None
    job_emails['UsedAI'] = False
    job_emails['ExtractionMethod'] = 'unresolved'
    job_emails['Confidence'] = None
    job_emails['EvidenceSnippets'] = None

    print(f'\nLoaded {len(job_emails)} rows from job_emails.csv')
    print('-' * 50)

    # --- Phase 1: regex on every row (free) ---
    job_emails = run_regex_pass(job_emails)

    # --- Lossless dedup BEFORE the AI pass: collapse only TRUE duplicates
    #     (same Company + same regex-found title) so the LLM never runs on them
    #     twice. Null-title rows pass through untouched so distinct roles at one
    #     company are never merged before AI can tell them apart; the full dedup
    #     runs again after extraction. ---
    rows_before = len(job_emails)
    job_emails = run_dedup(job_emails, known_only=True)
    print(f'             (was {rows_before} rows before lossless pre-AI dedup)')

    # --- Phase 2: AI on ambiguous rows only ---
    ambiguous_mask = (
        job_emails['Company'].isna() |
        job_emails['JobTitle'].isna() |
        (job_emails['Status'] == 'Other') |
        job_emails['NeedsAI'].fillna(False)
    )
    job_emails = run_ai_extraction(job_emails, ambiguous_mask, runner)

    # --- Phase 3: body fetch as last resort ---
    job_emails = run_body_fetch(job_emails, service, msg_id_map)

    # --- Final dedup: AI/body-fetch may have filled company/title and created
    #     new (Company, JobTitle) duplicates; collapse them (no API cost). ---
    print('-' * 50)
    job_emails = run_dedup(job_emails)

    # --- Mark rows still needing human review ---
    job_emails['NeedsReview'] = (
        job_emails['Company'].isna() |
        job_emails['JobTitle'].isna() |
        (job_emails['Status'] == 'Other')
    )
    needs_review = job_emails['NeedsReview'].sum()
    print('-' * 50)
    print(f'NeedsReview: {needs_review} rows ({needs_review/len(job_emails):.1%}) still incomplete after all passes')
    print(f'UsedAI:      {job_emails["UsedAI"].sum()} rows sent to LLM')
    token_savings = (~job_emails["UsedAI"]).sum()
    print(f'Saved:       {token_savings} rows skipped LLM entirely')

    # --- Export ---
    export_cols = [
        'MsgId', 'Date', 'Company', 'JobTitle', 'Subject', 'Status',
        'UsedAI', 'ExtractionMethod', 'NeedsReview', 'Confidence', 'EvidenceSnippets',
    ]
    available = [c for c in export_cols if c in job_emails.columns]
    job_emails[available].to_csv('job_tracker.csv', index=False)
    print('\nSaved to job_tracker.csv')
