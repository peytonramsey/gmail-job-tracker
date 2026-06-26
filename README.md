# Gmail Job Tracker

This projects goal is to help track job application by sifting through your gmail inbox and extracting relevant information.

It aims to automate the process of tracking applications rather than using a 3rd party tool or manually tracking them. 

## How it works

This program uses a mix of regex patterns and AI (Pydantic AI), a hybrid approach was chosen to balance accuracy, complexity, and cost. 

First, the program soley used regex patterns and functions to find each application by searching for words like "application", "job", "position", etc. in the email subject and body. Then, after some testing, it was found this regex approach was missing some emails. So, rather than listing every single possible word that could be used in an email subject or body, AI was used to help identify applications. 

Most significantly, using Pydantic AI allowed for the creation of an 'extraction_agent' that could be used to extract the company_name and status of each application. 

## Later on

I plan to include a filtering system prior to the loading, this is something I learned from my data engineering experience when you are pulling in large amounts of unsupervised data. Rather than pulling in 10k emails and then filtering them, I want to filter them as I pull them in to reduce the amount of data processed.

## Current trouble areas

I'm having a difficult time with the AI agent not properly extracting some of the company_names (only a handful of these are incorrect, where they are pulling in the 'do not reply' instead). 

But, most importantly, I'm having a difficult time with pulling in the job_title for each application. First, I tried a regex approach, then I tried using a seperate agent, and now I reverted to a hybrid approach where if the 'extraction_agent' sees the job_title in the Subject line, it'll extract it, otherwise it'll use the regex approach to find it in the body the email. 

## Setup for the required files

These files are **not committed to the repo** (see `.gitignore`) and must be created locally before running the pipeline.

### `credentials.json`
OAuth 2.0 client credentials from the [Google Cloud Console](https://console.cloud.google.com/).

1. Create a project → enable the Gmail API → create an OAuth 2.0 Desktop client
2. Download the JSON and save it as `credentials.json` in the project root

### `token.json`
Created automatically on first run when `fetch.py` opens a browser OAuth consent screen. Do not create this manually — just run `python pipeline.py` and authenticate when prompted. It is refreshed automatically on subsequent runs.

### `.yaml`
Holds your Gmail address and Groq API key. Create this file in the project root:

```yaml
user: "your.email@gmail.com"
password: "your-gmail-app-password"
groq_api_key: "gsk_..."
```

Get a free Groq API key at [console.groq.com](https://console.groq.com). The free tier allows 500k tokens/day which is sufficient for most job searches. The key resets daily at midnight UTC.

### Install dependencies

```bash
python -m pip install google-auth-httplib2 google-auth-oauthlib google-api-python-client \
    pandas pydantic-ai pyyaml numpy plotly tldextract nest_asyncio
```

## Running

```bash
python pipeline.py
```

This runs all four phases in order and produces:
- `job_tracker.csv` — deduplicated application list
- `weekly_report.md` — markdown summary
- `followup_needed.csv` — applications with no reply in 7–90 days
- `report_roles.html`, `report_funnel.html`, `report_months.html` — interactive charts

## Running tests

```bash
python tests/test_classify.py
python tests/test_extract.py
```

