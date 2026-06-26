# Phase II: loads checkpoint, filters + extracts, saves job_emails.csv

import re
import pandas as pd
from email.utils import parseaddr

from patterns import TITLE_KW, ATS_PATTERN, ATS_ROOTS

try:
    import tldextract
except ImportError:
    tldextract = None

# Earliest email date for the current job search cycle. Emails before this date
# are dropped before any scoring — they're from a past cycle or college.
SEARCH_START_DATE = '2025-06-01'

# Personal/freemail domains. Emails from these senders are excluded unless they
# contain a strong job signal (application/interview/offer/rejection keywords)
# or come from a known ATS. Blocks peer emails mentioning role names.
PERSONAL_DOMAINS = {
    'gmail.com', 'yahoo.com', 'outlook.com', 'hotmail.com',
    'icloud.com', 'me.com', 'live.com', 'msn.com',
}


def is_personal_sender(from_str: str) -> bool:
    _, addr = parseaddr(str(from_str or ''))
    if '@' not in addr:
        return False
    return addr.split('@', 1)[1].lower() in PERSONAL_DOMAINS


# Email filter patterns
strong_pattern = re.compile(
    r'\b(application|interview|offer|rejection|assessment|background\s+check|'
    r'reference\s+check|phone\s*screen|candidate\s+survey|thank\s+you\s+for\s+apply\w*)\b',
    re.I
)
medium_pattern = re.compile(
    r'\b(job|role|position|opportunity|candidate|candidacy|hiring|'
    r'recruit(?:er|ing|ment)?|availability|schedule|reschedule|'
    r'next\s+steps|status\s+update|interest)\b',
    re.I
)


def job_email_score(row):
    subject = str(row.get('Subject', ''))
    from_ = str(row.get('From', ''))
    snippet = str(row.get('Snippet', ''))
    text = f"{subject} {snippet}"
    strong = bool(strong_pattern.search(text))
    medium_count = len(medium_pattern.findall(text))
    ats = bool(ATS_PATTERN.search(from_))
    score = (2 if strong else 0) + medium_count + (1 if ats else 0)
    return score, ats


# Company extraction.
# Two disjoint word sets, each listed once:
#   JUNK_WORDS   — descriptor words stripped out of multi-word names
#                  ("Amazon Recruiting Team" -> "Amazon").
#   ADDRESS_JUNK — mailbox/address tokens that are never part of a real company
#                  name, only useful as a whole-token reject ("noreply", "gmail").
# A candidate equal to ANY of these (GENERIC_TOKENS, the union) is rejected
# outright; only JUNK_WORDS are stripped word-by-word from longer names.
JUNK_WORDS = {
    'careers', 'career', 'jobs', 'job', 'recruiting', 'recruiter',
    'talent', 'team', 'notifications', 'notification', 'mail',
    'mailer', 'support', 'info', 'hello', 'hr', 'people',
    'hiring', 'updates',
    # ATS platform names — the sender platform, never the actual company
    'workday', 'greenhouse', 'lever', 'taleo', 'icims', 'jobvite', 'smartrecruiters',
}
ADDRESS_JUNK = {
    'noreply', 'no-reply', 'donotreply', 'do-not-reply',
    'bounce', 'postmaster', 'email', 'gmail',
}
GENERIC_TOKENS = JUNK_WORDS | ADDRESS_JUNK


def clean_company_token(token: str, preserve_case: bool = False):
    """Clean a candidate company name.
    preserve_case=True keeps the original capitalisation for display names
    so brands like AT&T or IBM are not distorted by .title().
    """
    if not token:
        return None

    original = token.strip()
    lower = original.lower()
    lower = re.sub(r'[^a-z0-9&.\- ]+', ' ', lower)
    lower = re.sub(r'\s+', ' ', lower).strip()

    if not lower or lower in GENERIC_TOKENS:
        return None

    # Catch "No Reply", "Do Not Reply" etc. — they don't match ADDRESS_JUNK
    # token-by-token but normalize to a matching token when spaces/hyphens removed.
    if re.sub(r'[\s\-]', '', lower) in ADDRESS_JUNK:
        return None

    parts_lower = [p for p in re.split(r'[\s._\-]+', lower) if p and p not in JUNK_WORDS]
    if not parts_lower:
        return None

    cleaned_lower = ' '.join(parts_lower)
    if len(cleaned_lower) < 2:
        return None

    if preserve_case:
        # Strip junk from original casing — preserves AT&T, IBM, JPMorgan, etc.
        orig_parts = [p for p in re.split(r'\s+', original) if p.lower() not in GENERIC_TOKENS]
        result = ' '.join(orig_parts).strip()
        return result if len(result) >= 2 else cleaned_lower.title()

    return cleaned_lower.title()


def get_domain_parts(domain: str):
    domain = domain.lower().strip()

    if tldextract:
        ext = tldextract.extract(domain)
        return ext.domain, [p for p in ext.subdomain.split('.') if p], ext.suffix

    parts = domain.split('.')
    if len(parts) >= 2:
        return parts[-2], parts[:-2], parts[-1]

    return domain, [], ''


def add_candidate(candidates, value, score, source, preserve_case=False):
    cleaned = clean_company_token(value, preserve_case=preserve_case)
    if cleaned:
        candidates.append((cleaned, score, source))


def extract_from_headers(header_value, candidates):
    display_name, addr = parseaddr(str(header_value or ''))

    if display_name and '@' not in display_name:
        add_candidate(candidates, display_name, 100, 'display_name', preserve_case=True)

    if not addr or '@' not in addr:
        return

    local, domain = addr.lower().split('@', 1)
    root, subdomains, _ = get_domain_parts(domain)

    if root and root not in ATS_ROOTS:
        add_candidate(candidates, root, 90, 'root_domain')

    # ATS sender: local part (e.g. "stripe" in stripe@greenhouse.io) — added once
    if root in ATS_ROOTS:
        add_candidate(candidates, local, 85, 'ats_local_part')
    elif local not in GENERIC_TOKENS and '.' not in local:
        add_candidate(candidates, local, 40, 'local_part')

    for sub in reversed(subdomains):
        if sub not in ATS_ROOTS and sub not in GENERIC_TOKENS:
            add_candidate(candidates, sub, 75, 'subdomain')


def extract_from_text(text, candidates, base_score):
    text = str(text or '')

    # Prefix keywords match case-insensitively, but the captured company name
    # must start with a capital letter: (?-i:[A-Z]) turns IGNORECASE off for
    # just that char so lowercase filler ("to whom...") is not picked up.
    patterns = [
        r'(?:position|role)\s+[A-Za-z0-9\s\,]+\s+at\s+((?-i:[A-Z])[A-Za-z0-9&.\'\- ]{1,40})',
        r'(?:application|interview|opportunity|position|role|update|next steps|candidacy)\s+(?:at|with|for|from)\s+((?-i:[A-Z])[A-Za-z0-9&.\'\- ]{1,40})',
        r'(?:to|from|with|at)\s+((?-i:[A-Z])[A-Za-z0-9&.\'\- ]{1,40})(?:\s*[,!:\-]|$)',
        r'your application to\s+((?-i:[A-Z])[A-Za-z0-9&.\'\- ]{1,40})',
        r'thank you for applying to\s+((?-i:[A-Z])[A-Za-z0-9&.\'\- ]{1,40})',
        r'interest in\s+((?-i:[A-Z])[A-Za-z0-9&.\'\- ]{1,40})',
    ]

    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            add_candidate(candidates, match.group(1), base_score, 'text_pattern')


def choose_best_candidate(candidates):
    if not candidates:
        return None, None, 0

    best_by_name = {}
    for name, score, source in candidates:
        if name not in best_by_name or score > best_by_name[name][0]:
            best_by_name[name] = (score, source)

    best_name = max(best_by_name.items(), key=lambda x: x[1][0])
    return best_name[0], best_name[1][1], best_name[1][0]


def extract_company(row):
    """Returns (company, source, score). Source tells you where the name came from."""
    candidates = []

    for field in ['From', 'Reply-To', 'Sender']:
        extract_from_headers(row.get(field, ''), candidates)

    extract_from_text(row.get('Subject', ''), candidates, 70)
    extract_from_text(row.get('Snippet', ''), candidates, 60)  # Snippet as fallback

    return choose_best_candidate(candidates)


def company_confidence_tier(score):
    if not score or score == 0:
        return 'unknown'
    if score >= 90:
        return 'high'
    if score >= 70:
        return 'medium'
    return 'low'


# Status keywords (dict keeps ordering and is easier to extend)
STATUS_KEYWORDS = {
    'Offer':       ['offer', 'pleased to', 'congratulations'],
    'Interview':   ['interview', 'schedule', 'next steps'],
    'Assessment':  ['assessment', 'online test', 'coding challenge', 'hackerrank', 'codility'],
    'Rejected':    ['unfortunately', 'other candidates', 'not moving forward', 'not selected'],
    'Applied':     ['application', 'applied', 'received', 'thank you for applying'],
}


def classify_status(subject: str) -> str:
    lower = subject.lower()
    for status, keywords in STATUS_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            return status
    return 'Other'


# Noise filter patterns grouped by category
NOISE_ACCOUNT = [
    r'reset\s+your\s+password', r'verify\s+your\s+(email|account)',
    r'security\s+alert', r'confirm\s+your\s+email',
    r'email\s+verification', r'unsubscribe\s+confirmation',
]
NOISE_COLLEGE = [
    r'scholarship', r'college\s+appli\w*', r'university\s+appli\w*',
    r'admission(?:s)?', r'enrollment', r'tuition', r'campus',
    r'semester', r'freshman', r'financial\s+aid',
    r'application\s+(?:deadline|fee|portal)', r'apply\s+to\s+college',
    r'cross\s+country', r'track\s+and\s+field', r'athletic(?:s)?',
]
NOISE_MARKETING = [
    r'don.t\s+miss\s+out', r'last\s+chance\s+to\s+apply',
    r'spots?\s+(?:are\s+)?filling',
]
noise_pattern = re.compile(
    r'\b(' + '|'.join(NOISE_ACCOUNT + NOISE_COLLEGE + NOISE_MARKETING) + r')\b',
    re.I
)


if __name__ == '__main__':
    email_df = pd.read_csv('email_df_checkpoint.csv')

    # Drop emails from before the current job search cycle
    email_df['Date'] = pd.to_datetime(email_df['Date'], errors='coerce', utc=True)
    before_date = len(email_df)
    email_df = email_df[
        email_df['Date'].isna() | (email_df['Date'] >= pd.Timestamp(SEARCH_START_DATE, tz='UTC'))
    ].copy()
    print(f'Date filter: removed {before_date - len(email_df)} emails before {SEARCH_START_DATE}')

    email_df[['FilterScore', 'IsATS']] = email_df.apply(
        lambda row: pd.Series(job_email_score(row)), axis=1
    )

    # Drop personal-domain emails with no strong job signal (blocks peer emails)
    personal = email_df['From'].apply(is_personal_sender)
    has_strong = email_df.apply(
        lambda r: bool(strong_pattern.search(f"{r['Subject']} {r['Snippet']}")), axis=1
    )
    before_personal = len(email_df)
    email_df = email_df[~(personal & ~has_strong & ~email_df['IsATS'])].copy()
    print(f'Personal-sender filter: removed {before_personal - len(email_df)} emails')

    definite = email_df[email_df['FilterScore'] >= 2].copy()
    maybe = email_df[(email_df['FilterScore'] == 1) | ((email_df['FilterScore'] == 0) & email_df['IsATS'])].copy()
    print(f'Definite: {len(definite)} | Maybe (borderline): {len(maybe)}')

    confirmed_maybe = maybe[maybe.apply(
        lambda row: bool(TITLE_KW.search(f"{row['Subject']} {row['Snippet']}")), axis=1
    )].copy()

    job_emails = pd.concat([definite, confirmed_maybe]).copy()
    print(f'After filter: {len(job_emails)} job emails ({len(confirmed_maybe)} confirmed from maybe tier)')

    job_emails[['Company', 'ExtractSource', 'ExtractScore']] = job_emails.apply(
        lambda row: pd.Series(extract_company(row)), axis=1
    )
    job_emails['CompanyConfidence'] = job_emails['ExtractScore'].apply(company_confidence_tier)

    job_emails['Date'] = pd.to_datetime(job_emails['Date'], errors='coerce', utc=True)
    job_emails['Status'] = job_emails['Subject'].apply(classify_status)

    before = len(job_emails)
    job_emails = job_emails[~job_emails['Subject'].str.contains(noise_pattern, na=False)].copy()
    print(f'Removed {before - len(job_emails)} false-positive emails')
    print(f'{len(job_emails)} job emails ready for extraction')

    # Flag rows where regex/rules alone are insufficient — AI will be routed to these in extract.py
    job_emails['NeedsAI'] = (
        job_emails['Company'].isna() |
        (job_emails['Status'] == 'Other') |
        job_emails['CompanyConfidence'].isin(['low', 'unknown'])
    )
    needs_ai_count = job_emails['NeedsAI'].sum()
    clear_count = len(job_emails) - needs_ai_count
    print(f'Clear (no AI needed): {clear_count} | Ambiguous (needs AI): {needs_ai_count} ({needs_ai_count/len(job_emails):.1%})')

    job_emails.to_csv('job_emails.csv', index=False)
    print('Saved to job_emails.csv')
