# Column contracts for each CSV hand-off between phases

from typing import TypedDict, Optional

# fetch.py -> email_df_checkpoint.csv
EmailRecord = TypedDict('EmailRecord', {
    'MsgId': str,
    'Date': str,
    'From': str,
    'Subject': str,
    'Reply-To': str,
    'Sender': str,
    'Snippet': str,
})

# classify.py -> job_emails.csv
class JobEmailRecord(TypedDict):
    MsgId: str
    Date: str
    From: str
    Subject: str
    Snippet: str
    FilterScore: int
    IsATS: bool
    Company: Optional[str]
    ExtractSource: Optional[str]
    ExtractScore: Optional[float]
    CompanyConfidence: str
    Status: str

# extract.py -> job_tracker.csv
class TrackerRecord(TypedDict):
    MsgId: str
    Date: str
    Company: Optional[str]
    JobTitle: Optional[str]
    Subject: str
    Status: str
    Confidence: Optional[float]
    EvidenceSnippets: Optional[str]
