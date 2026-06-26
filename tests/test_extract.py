import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import json
import pandas as pd
from extract import extract_title_from_text, run_regex_pass, run_dedup


# --- Title extraction (item 28) ---

def test_title_phrase_pattern():
    text = 'Your application for the Data Scientist position at Acme Corp has been received.'
    title = extract_title_from_text(text)
    assert title is not None
    assert 'data scientist' in title.lower(), f'Got: {title}'

def test_title_keyword_match():
    title = extract_title_from_text("We'd love to talk about our Machine Learning Engineer opening.")
    assert title is not None
    assert 'machine learning' in title.lower() or 'engineer' in title.lower(), f'Got: {title}'

def test_title_no_match():
    title = extract_title_from_text('Thank you for reaching out. We will be in touch.')
    assert title is None

def test_title_with_level_prefix():
    title = extract_title_from_text('Position: Senior Data Analyst')
    assert title is not None
    assert 'data analyst' in title.lower(), f'Got: {title}'


# --- Regex pass ---

def test_regex_pass_fills_null_title():
    df = pd.DataFrame([
        {'Subject': 'Your Data Scientist application', 'Snippet': '', 'JobTitle': None, 'ExtractionMethod': 'unresolved'},
        {'Subject': 'General inquiry', 'Snippet': '', 'JobTitle': 'Software Engineer', 'ExtractionMethod': 'regex'},
    ])
    result = run_regex_pass(df)
    assert pd.notna(result.loc[0, 'JobTitle']), 'Expected title to be filled'
    assert result.loc[0, 'ExtractionMethod'] == 'regex', 'ExtractionMethod should be set to regex'
    assert result.loc[1, 'JobTitle'] == 'Software Engineer', 'Should not overwrite existing title'

def test_regex_pass_sets_extraction_method():
    df = pd.DataFrame([
        {'Subject': 'ML Engineer role', 'Snippet': '', 'JobTitle': None, 'ExtractionMethod': 'unresolved'},
    ])
    result = run_regex_pass(df)
    assert result.loc[0, 'ExtractionMethod'] == 'regex'

def test_regex_pass_leaves_unresolved_when_no_match():
    df = pd.DataFrame([
        {'Subject': 'Hello from our team', 'Snippet': '', 'JobTitle': None, 'ExtractionMethod': 'unresolved'},
    ])
    result = run_regex_pass(df)
    assert pd.isna(result.loc[0, 'JobTitle'])
    assert result.loc[0, 'ExtractionMethod'] == 'unresolved'


# --- Deduplication (item 28) ---

def test_dedup_keeps_highest_status():
    df = pd.DataFrame([
        {'Company': 'Google', 'JobTitle': 'Data Scientist', 'Status': 'Applied',   'Date': '2024-01-01'},
        {'Company': 'Google', 'JobTitle': 'Data Scientist', 'Status': 'Interview', 'Date': '2024-01-05'},
    ])
    result = run_dedup(df)
    assert len(result) == 1
    assert result.iloc[0]['Status'] == 'Interview'

def test_dedup_different_roles_kept():
    df = pd.DataFrame([
        {'Company': 'Amazon', 'JobTitle': 'Data Scientist',  'Status': 'Applied', 'Date': '2024-01-01'},
        {'Company': 'Amazon', 'JobTitle': 'Data Analyst',    'Status': 'Applied', 'Date': '2024-01-03'},
    ])
    result = run_dedup(df)
    assert len(result) == 2

def test_dedup_company_only_fallback():
    df = pd.DataFrame([
        {'Company': 'Amazon', 'JobTitle': None, 'Status': 'Applied',   'Date': '2024-01-01'},
        {'Company': 'Amazon', 'JobTitle': None, 'Status': 'Rejected',  'Date': '2024-01-10'},
    ])
    result = run_dedup(df)
    amazon_rows = result[result['Company'] == 'Amazon']
    assert len(amazon_rows) == 1
    assert amazon_rows.iloc[0]['Status'] == 'Rejected'

def test_dedup_assessment_rank():
    df = pd.DataFrame([
        {'Company': 'Meta', 'JobTitle': 'ML Engineer', 'Status': 'Applied',    'Date': '2024-01-01'},
        {'Company': 'Meta', 'JobTitle': 'ML Engineer', 'Status': 'Assessment', 'Date': '2024-01-05'},
    ])
    result = run_dedup(df)
    assert len(result) == 1
    assert result.iloc[0]['Status'] == 'Assessment'


# --- Lossless pre-AI dedup ---

def test_dedup_known_only_preserves_null_title_rows():
    # known_only=True must NOT collapse null-title rows by company — distinct
    # roles at one company stay separate until AI can fill the titles.
    df = pd.DataFrame([
        {'Company': 'Amazon', 'JobTitle': None,             'Status': 'Applied',   'Date': '2024-01-01'},
        {'Company': 'Amazon', 'JobTitle': None,             'Status': 'Rejected',  'Date': '2024-01-10'},
        {'Company': 'Amazon', 'JobTitle': 'Data Scientist', 'Status': 'Applied',   'Date': '2024-01-05'},
        {'Company': 'Amazon', 'JobTitle': 'Data Scientist', 'Status': 'Interview', 'Date': '2024-01-08'},
    ])
    result = run_dedup(df, known_only=True)
    # both null-title rows survive; the two known dupes collapse to one (highest status)
    assert result['JobTitle'].isna().sum() == 2
    known = result[result['JobTitle'].notna()]
    assert len(known) == 1
    assert known.iloc[0]['Status'] == 'Interview'


# --- AI extraction: one call per unique prompt, results fanned to all rows ---

def test_ai_extraction_groups_and_fans_results():
    from extract import run_ai_extraction, JobEmailDetails

    seen = {}
    def fake_runner(prompts):
        seen['prompts'] = list(prompts)
        return {p: JobEmailDetails(company_name=None, job_title='Data Scientist',
                                   status='interview', confidence=0.9, evidence_snippets=[])
                for p in prompts}

    base = {'UsedAI': False, 'ExtractionMethod': 'unresolved', 'Confidence': None, 'EvidenceSnippets': None}
    df = pd.DataFrame([
        {'From': 'a@x.com', 'Subject': 'App received',    'Snippet': 'thanks',   'Company': 'Acme', 'JobTitle': None, 'Status': 'Other', **base},
        {'From': 'a@x.com', 'Subject': 'App received',    'Snippet': 'thanks',   'Company': 'Acme', 'JobTitle': None, 'Status': 'Other', **base},  # identical to row 0
        {'From': 'b@y.com', 'Subject': 'Interview invite', 'Snippet': 'schedule', 'Company': 'Beta', 'JobTitle': None, 'Status': 'Other', **base},
    ])
    mask = pd.Series([True, True, True])

    result = run_ai_extraction(df, mask, runner=fake_runner)

    # runner billed once per UNIQUE prompt (2), not per row (3)
    assert len(seen['prompts']) == 2, f"Expected 2 unique prompts, got {len(seen['prompts'])}"
    # result fanned out to every row sharing a prompt
    assert (result['Status'] == 'Interview').all()
    assert (result['JobTitle'] == 'Data Scientist').all()
    assert result['UsedAI'].all()


def test_ai_extraction_does_not_overwrite_known_company():
    # The README "do not reply" bug: AI returns a bad company that IS verbatim in
    # the email, so the verbatim check passes — the rules-value guard must still win.
    from extract import run_ai_extraction, JobEmailDetails

    def fake_runner(prompts):
        return {p: JobEmailDetails(company_name='Do Not Reply', job_title=None,
                                   status='unknown', confidence=0.5, evidence_snippets=[])
                for p in prompts}

    df = pd.DataFrame([{
        'From': 'noreply@acme.com', 'Subject': 'Update', 'Snippet': 'do not reply',
        'Company': 'Acme', 'JobTitle': 'Data Scientist', 'Status': 'Applied',
        'UsedAI': False, 'ExtractionMethod': 'regex', 'Confidence': None, 'EvidenceSnippets': None,
    }])
    result = run_ai_extraction(df, pd.Series([True]), runner=fake_runner)
    assert result.loc[0, 'Company'] == 'Acme'  # rules value preserved, AI ignored


# --- EmailHistory in run_dedup ---

def test_dedup_builds_email_history_for_collapsed_rows():
    df = pd.DataFrame([
        {'Company': 'Google', 'JobTitle': 'Data Scientist', 'Status': 'Applied',   'Date': '2024-01-01', 'Subject': 'App received'},
        {'Company': 'Google', 'JobTitle': 'Data Scientist', 'Status': 'Interview', 'Date': '2024-01-10', 'Subject': 'Interview invite'},
    ])
    result = run_dedup(df)
    assert len(result) == 1
    hist = json.loads(result.iloc[0]['EmailHistory'])
    assert len(hist) == 2
    subjects = [h['subject'] for h in hist]
    assert 'App received' in subjects
    assert 'Interview invite' in subjects

def test_dedup_single_row_gets_one_item_history():
    df = pd.DataFrame([
        {'Company': 'Stripe', 'JobTitle': 'ML Engineer', 'Status': 'Applied', 'Date': '2024-02-01', 'Subject': 'Thanks for applying'},
    ])
    result = run_dedup(df)
    assert len(result) == 1
    hist = json.loads(result.iloc[0]['EmailHistory'])
    assert len(hist) == 1
    assert hist[0]['subject'] == 'Thanks for applying'


if __name__ == '__main__':
    from _runner import run
    raise SystemExit(run(globals()))
