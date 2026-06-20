# Phase II: loads checkpoint, filters + extracts, saves job_emails.csv

import re
import pandas as pd
from email.utils import parseaddr

try:
    import tldextract
except ImportError:
    tldextract = None

email_df = pd.read_csv('email_df_checkpoint.csv')

# Job title keywords used to confirm borderline emails
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

## Filter
strong_pattern = re.compile(
    r'\b(application|interview|offer|rejection|assessment|background\s+check|reference\s+check|phone\s*screen|candidate\s+survey|thank\s+you\s+for\s+apply\w*)\b',
    re.I
)
medium_pattern = re.compile(
    r'\b(job|role|position|opportunity|candidate|candidacy|hiring|recruit(?:er|ing|ment)?|availability|schedule|reschedule|next\s+steps|status\s+update|interest)\b',
    re.I
)
ats_pattern = re.compile(
    r'workday|greenhouse|lever|taleo|icims|jobvite|smartrecruiters',
    re.I
)

def job_email_score(row):
    subject = str(row.get('Subject', ''))
    from_ = str(row.get('From', ''))
    snippet = str(row.get('Snippet', ''))
    text = f"{subject} {snippet}"
    strong = bool(strong_pattern.search(text))
    medium_count = len(medium_pattern.findall(text))
    ats = bool(ats_pattern.search(from_))
    score = (2 if strong else 0) + medium_count + (1 if ats else 0)
    return score, ats

email_df[['FilterScore', 'IsATS']] = email_df.apply(
    lambda row: pd.Series(job_email_score(row)), axis=1
)

definite = email_df[email_df['FilterScore'] >= 2].copy()
maybe = email_df[(email_df['FilterScore'] == 1) | ((email_df['FilterScore'] == 0) & email_df['IsATS'])].copy()
print(f'Definite: {len(definite)} | Maybe (borderline): {len(maybe)}')

confirmed_maybe = maybe[maybe.apply(
    lambda row: bool(TITLE_KW.search(f"{row['Subject']} {row['Snippet']}")), axis=1
)].copy()

job_emails = pd.concat([definite, confirmed_maybe]).copy()
print(f'After filter: {len(job_emails)} job emails ({len(confirmed_maybe)} confirmed from maybe tier)')

## Company extraction
GENERIC_TOKENS = {
    'noreply', 'no-reply', 'donotreply', 'do-not-reply', 'notifications',
    'notification', 'hiring', 'jobs', 'job', 'careers', 'career', 'bounce',
    'mailer', 'postmaster', 'info', 'support', 'hello', 'team', 'recruiting',
    'recruiter', 'talent', 'hr', 'people', 'mail', 'email', 'updates', 'gmail'
}

ATS_ROOTS = {
    'workday', 'myworkday', 'myworkdayjobs',
    'greenhouse', 'lever', 'taleo', 'icims',
    'jobvite', 'smartrecruiters'
}


def clean_company_token(token: str):
    if not token:
        return None

    token = token.strip().lower()
    token = re.sub(r'[^a-z0-9&.\- ]+', ' ', token)
    token = re.sub(r'\s+', ' ', token).strip()

    if not token or token in GENERIC_TOKENS:
        return None

    junk_words = {
        'careers', 'career', 'jobs', 'job', 'recruiting', 'recruiter',
        'talent', 'team', 'notifications', 'notification', 'mail',
        'mailer', 'support', 'info', 'hello', 'hr', 'people'
    }
    parts = [p for p in re.split(r'[\s._\-]+', token) if p and p not in junk_words]
    if not parts:
        return None

    cleaned = " ".join(parts)
    if len(cleaned) < 2:
        return None

    return cleaned.title()


def get_domain_parts(domain: str):
    domain = domain.lower().strip()

    if tldextract:
        ext = tldextract.extract(domain)
        root = ext.domain
        subdomains = [p for p in ext.subdomain.split('.') if p]
        suffix = ext.suffix
        return root, subdomains, suffix

    parts = domain.split('.')
    if len(parts) >= 2:
        root = parts[-2]
        subdomains = parts[:-2]
        suffix = parts[-1]
        return root, subdomains, suffix

    return domain, [], ''


def add_candidate(candidates, value, score, source):
    cleaned = clean_company_token(value)
    if cleaned:
        candidates.append((cleaned, score, source))


def extract_from_headers(header_value, candidates):
    display_name, addr = parseaddr(str(header_value or ''))

    if display_name and '@' not in display_name:
        add_candidate(candidates, display_name, 100, 'display_name')

    if not addr or '@' not in addr:
        return

    local, domain = addr.lower().split('@', 1)
    root, subdomains, _ = get_domain_parts(domain)

    if root and root not in ATS_ROOTS:
        add_candidate(candidates, root, 90, 'root_domain')

    if root in ATS_ROOTS:
        add_candidate(candidates, local, 85, 'ats_local_part')

    for sub in reversed(subdomains):
        if sub not in ATS_ROOTS and sub not in GENERIC_TOKENS:
            add_candidate(candidates, sub, 75, 'subdomain')

    if local not in GENERIC_TOKENS and root in ATS_ROOTS:
        add_candidate(candidates, local, 80, 'ats_local_part')
    elif local not in GENERIC_TOKENS and '.' not in local:
        add_candidate(candidates, local, 40, 'local_part')


def extract_from_text(text, candidates, base_score):
    text = str(text or '')

    patterns = [
        r'(?:position|role)\s+[A-Za-z0-9\s\,]+\s+at\s+([A-Z][A-Za-z0-9&.\'\- ]{1,40})',
        r'(?:application|interview|opportunity|position|role|update|next steps|candidacy)\s+(?:at|with|for|from)\s+([A-Z][A-Za-z0-9&.\'\- ]{1,40})',
        r'(?:to|from|with|at)\s+([A-Z][A-Za-z0-9&.\'\- ]{1,40})(?:\s*[,!:\-]|$)',
        r'your application to\s+([A-Z][A-Za-z0-9&.\'\- ]{1,40})',
        r'thank you for applying to\s+([A-Z][A-Za-z0-9&.\'\- ]{1,40})',
        r'interest in\s+([A-Z][A-Za-z0-9&.\'\- ]{1,40})'
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
    candidates = []

    for field in ['From', 'Reply-To', 'Sender']:
        extract_from_headers(row.get(field, ''), candidates)

    extract_from_text(row.get('Subject', ''), candidates, 70)

    company, source, score = choose_best_candidate(candidates)
    return company, score

job_emails[['Company', 'ExtractScore']] = job_emails.apply(
    lambda row: pd.Series(extract_company(row)), axis=1
)
job_emails['Date'] = pd.to_datetime(job_emails['Date'], errors='coerce', utc=True)
job_emails['Status'] = job_emails['Subject'].apply(lambda x: (
    'Offer'     if any(w in x.lower() for w in ['offer', 'pleased to', 'congratulations']) else
    'Interview' if any(w in x.lower() for w in ['interview', 'schedule', 'next steps']) else
    'Rejected'  if any(w in x.lower() for w in ['unfortunately', 'other candidates', 'not moving forward', 'not selected']) else
    'Applied'   if any(w in x.lower() for w in ['application', 'applied', 'received', 'thank you for applying']) else
    'Other'
))

noise_pattern = re.compile(
    r'\b('
    r'reset\s+your\s+password|verify\s+your\s+(email|account)|security\s+alert'
    r'|confirm\s+your\s+email|email\s+verification|unsubscribe\s+confirmation'
    r'|scholarship|college\s+appli\w*|university\s+appli\w*|admission(?:s)?'
    r'|enrollment|tuition|campus|semester|freshman|financial\s+aid'
    r'|application\s+(?:deadline|fee|portal)|apply\s+to\s+college'
    r'|cross\s+country|track\s+and\s+field|athletic(?:s)?'
    r'|don.t\s+miss\s+out|last\s+chance\s+to\s+apply|spots?\s+(?:are\s+)?filling'
    r')\b',
    re.I
)
before = len(job_emails)
job_emails = job_emails[~job_emails['Subject'].str.contains(noise_pattern, na=False)].copy()
print(f'Removed {before - len(job_emails)} false-positive emails')
print(f'{len(job_emails)} job emails ready for extraction')

job_emails.to_csv('job_emails.csv', index=False)
print('Saved to job_emails.csv')
