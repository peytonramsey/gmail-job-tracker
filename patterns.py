# Shared matching patterns and role taxonomy — single source of truth so the
# pipeline phases (fetch/classify/extract) and the reporting layer (report/app)
# can't drift apart.

import re
import pandas as pd

# Job title keywords — used by classify.py (to confirm borderline emails) and
# extract.py (to validate/extract titles). Must stay identical in both.
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

# Canonical ATS provider list — fetch.py uses it to build the Gmail query,
# classify.py derives its sender pattern and domain-root set from it.
ATS_PROVIDERS = (
    'workday', 'greenhouse', 'lever', 'taleo', 'icims', 'jobvite', 'smartrecruiters',
)
# Matches an ATS provider anywhere in a From header (e.g. noreply@greenhouse.io).
ATS_PATTERN = re.compile('|'.join(ATS_PROVIDERS), re.I)
# Domain roots to skip when extracting a company name, plus Workday host aliases.
ATS_ROOTS = set(ATS_PROVIDERS) | {'myworkday', 'myworkdayjobs'}

# Role clustering for analytics — used by report.py and app.py. Later entries win
# (assign_role iterates in reverse), so order from most-general to most-specific.
ROLE_CONDITIONS = [
    ('Data Science / ML',    r'data scientist|machine learning|ml engineer|ai engineer|research scientist'),
    ('Software Engineering', r'software engineer|backend|frontend|full.?stack|developer'),
    ('Analytics',            r'data analyst|analytics engineer|business analyst|quantitative'),
    ('Product',              r'product manager|product analyst'),
    ('Data Engineering',     r'data engineer|platform engineer|cloud engineer|devops'),
]


def assign_role(title_series: pd.Series) -> pd.Series:
    """Map a Series of job titles to role clusters, defaulting to 'Other'."""
    title = title_series.str.lower().fillna('')
    result = pd.Series('Other', index=title_series.index)
    for role, pattern in reversed(ROLE_CONDITIONS):
        result[title.str.contains(pattern, na=False, regex=True)] = role
    return result
