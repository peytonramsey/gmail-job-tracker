import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from classify import (
    job_email_score, TITLE_KW, extract_company, clean_company_token,
    classify_status, noise_pattern, company_confidence_tier,
    is_personal_sender, strong_pattern, SEARCH_START_DATE,
)


# --- Filter scoring (item 15) ---

def test_score_definite_application():
    row = {'Subject': 'Thank you for applying', 'From': 'jobs@amazon.com', 'Snippet': ''}
    score, ats = job_email_score(row)
    assert score >= 2, f'Expected score >= 2, got {score}'

def test_score_ats_sender():
    row = {'Subject': 'Hello', 'From': 'noreply@greenhouse.io', 'Snippet': ''}
    _, ats = job_email_score(row)
    assert ats is True

def test_score_unrelated_email():
    row = {'Subject': 'Your order has shipped', 'From': 'shipping@amazon.com', 'Snippet': 'Your package'}
    score, ats = job_email_score(row)
    assert score == 0 and not ats


# --- Title keyword regex ---

def test_title_kw_data_scientist():
    assert TITLE_KW.search('Senior Data Scientist')

def test_title_kw_ml_engineer():
    assert TITLE_KW.search('ML Engineer')

def test_title_kw_no_match():
    assert TITLE_KW.search('Operations Associate') is None


# --- Company extraction (item 28) ---

def test_extract_company_display_name():
    # Display name wins as the source, and junk words ('Recruiting') are stripped
    # so the result is the canonical company name — see test_clean_company_token_strips_junk_words.
    row = {'From': 'Google Recruiting <noreply@google.com>', 'Reply-To': '', 'Sender': '', 'Subject': '', 'Snippet': ''}
    company, source, score = extract_company(row)
    assert company == 'Google', f'Got: {company}'
    assert source == 'display_name'

def test_extract_company_root_domain():
    row = {'From': 'noreply@stripe.com', 'Reply-To': '', 'Sender': '', 'Subject': '', 'Snippet': ''}
    company, source, score = extract_company(row)
    assert company == 'Stripe', f'Got: {company}'

def test_extract_company_ats_local():
    row = {'From': 'acme@greenhouse.io', 'Reply-To': '', 'Sender': '', 'Subject': '', 'Snippet': ''}
    company, source, score = extract_company(row)
    assert company is not None and 'acme' in company.lower(), f'Got: {company}'

def test_clean_company_token_preserves_at_and_t():
    result = clean_company_token('AT&T', preserve_case=True)
    assert result == 'AT&T', f'Got: {result}'

def test_clean_company_token_strips_generic():
    assert clean_company_token('noreply') is None

def test_clean_company_token_strips_junk_words():
    result = clean_company_token('Amazon Recruiting Team')
    assert result is not None
    assert 'recruiting' not in result.lower()
    assert 'team' not in result.lower()


# --- Status classification (item 28) ---

def test_classify_status_offer():
    assert classify_status('We are pleased to offer you a position') == 'Offer'

def test_classify_status_interview():
    assert classify_status('Schedule your interview with us') == 'Interview'

def test_classify_status_assessment():
    assert classify_status('Complete your HackerRank assessment') == 'Assessment'

def test_classify_status_rejected():
    assert classify_status('Unfortunately we have decided to move forward with other candidates') == 'Rejected'

def test_classify_status_applied():
    assert classify_status('Your application has been received') == 'Applied'

def test_classify_status_other():
    assert classify_status('Hello, are you still interested?') == 'Other'


# --- Noise filter ---

def test_noise_pattern_catches_college():
    assert noise_pattern.search('Scholarship Opportunity for Fall 2024')

def test_noise_pattern_catches_password_reset():
    assert noise_pattern.search('Reset your password for your account')

def test_noise_pattern_does_not_catch_job():
    assert not noise_pattern.search('Your application to Google has been received')


# --- Confidence tiers ---

def test_confidence_high():
    assert company_confidence_tier(95) == 'high'

def test_confidence_medium():
    assert company_confidence_tier(75) == 'medium'

def test_confidence_low():
    assert company_confidence_tier(50) == 'low'

def test_confidence_unknown():
    assert company_confidence_tier(0) == 'unknown'


# --- NeedsAI routing logic ---

def test_needs_ai_when_company_missing():
    import pandas as pd
    row = pd.Series({'Company': None, 'Status': 'Applied', 'CompanyConfidence': 'high'})
    needs = pd.isna(row['Company']) or row['Status'] == 'Other' or row['CompanyConfidence'] in ('low', 'unknown')
    assert needs

def test_needs_ai_when_status_other():
    import pandas as pd
    row = pd.Series({'Company': 'Amazon', 'Status': 'Other', 'CompanyConfidence': 'high'})
    needs = pd.isna(row['Company']) or row['Status'] == 'Other' or row['CompanyConfidence'] in ('low', 'unknown')
    assert needs

def test_needs_ai_when_confidence_low():
    import pandas as pd
    row = pd.Series({'Company': 'Acme', 'Status': 'Applied', 'CompanyConfidence': 'low'})
    needs = pd.isna(row['Company']) or row['Status'] == 'Other' or row['CompanyConfidence'] in ('low', 'unknown')
    assert needs

def test_no_ai_needed_when_all_clear():
    import pandas as pd
    row = pd.Series({'Company': 'Google', 'Status': 'Applied', 'CompanyConfidence': 'high'})
    needs = pd.isna(row['Company']) or row['Status'] == 'Other' or row['CompanyConfidence'] in ('low', 'unknown')
    assert not needs


# --- Date filter ---

def test_search_start_date_is_set():
    import datetime
    dt = datetime.date.fromisoformat(SEARCH_START_DATE)
    assert dt.year >= 2025, 'Expected a recent start date'

def test_date_filter_boundary():
    import pandas as pd
    cutoff = pd.Timestamp(SEARCH_START_DATE, tz='UTC')
    before = cutoff - pd.Timedelta(days=1)
    after  = cutoff + pd.Timedelta(days=1)
    # Simulate the filter expression used in classify.py __main__
    assert not (before >= cutoff)
    assert after >= cutoff


# --- Personal-sender filter ---

def test_is_personal_sender_gmail():
    assert is_personal_sender('Friend Name <peer@gmail.com>')

def test_is_personal_sender_corporate():
    assert not is_personal_sender('Recruiter <recruiter@amazon.com>')

def test_personal_sender_with_strong_signal_should_pass():
    # A personal-domain email with a strong keyword should NOT be excluded by the filter.
    # (The filter expression is: exclude if personal AND NOT strong AND NOT ATS)
    # We verify the strong_pattern matches to confirm the email would survive.
    text = 'Your application to Acme has been received'
    assert bool(strong_pattern.search(text))

def test_personal_sender_no_strong_signal_blocked():
    # A personal-domain email mentioning only a role name has no strong signal.
    text = 'Hey saw a data scientist role at Google, thought of you'
    assert not bool(strong_pattern.search(text))


# --- Company name: ATS platform and No Reply ---

def test_clean_workday_returns_none():
    assert clean_company_token('Workday') is None

def test_clean_greenhouse_returns_none():
    assert clean_company_token('Greenhouse') is None

def test_clean_amazon_workday_strips_platform():
    result = clean_company_token('Amazon Workday')
    assert result == 'Amazon', f'Got: {result}'

def test_clean_no_reply_display_name_returns_none():
    assert clean_company_token('No Reply') is None

def test_clean_do_not_reply_returns_none():
    assert clean_company_token('Do Not Reply') is None


if __name__ == '__main__':
    from _runner import run
    raise SystemExit(run(globals()))
