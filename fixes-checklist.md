# Gmail Job Tracker Fixes

- [x] Add `if __name__ == '__main__':` guards to `fetch.py`, `classify.py`, `extract.py`, `report.py`, and `pipeline.py` so each file can be imported and tested without running side effects immediately. 

- [x] Move Gmail authentication into a shared helper such as `auth.py` because both `fetch.py` and `extract.py` build Gmail credentials separately and this duplicates setup logic. 

- [x] Keep the sequential phase structure in `pipeline.py`, but add logging or structured error output so it is easier to debug failures when one phase exits early. 

- [x] Add comments or constants for the Gmail search query in `fetch.py` because the current query is long, tightly coupled to recruiting language, and will be easier to tune if it is broken into named parts. 

- [x] Consider storing the raw Gmail query string in one place so classification rules and fetch rules stay aligned over time. 

- [x] Keep checkpointing in `fetch.py`, but move the save interval into a named constant so the batch size is easier to change and test. 

- [x] Add a small wrapper function around Gmail metadata extraction in `fetch.py` so header parsing and row creation are isolated from the fetch loop. 

- [x] Remove the duplicated ATS local part candidate logic in `classify.py` because `ats_local_part` is added once at score 85 and then effectively added again in a later branch, which makes the scoring harder to reason about. 

- [x] Expand company extraction to use `Snippet` as a fallback in `classify.py` because the current text extraction only uses `Subject`, even though `fetch.py` already collects a snippet for every message. 

- [x] Return the extraction source along with `Company` and `ExtractScore` in `classify.py` so you can audit whether the value came from the display name, root domain, subdomain, ATS local part, or text pattern. 

- [x] Add a confidence tier such as high, medium, and low for company extraction so you can manually review the weakest guesses before they affect deduplication. 

- [x] Improve `clean_company_token` in `classify.py` to handle edge cases like stylized company names because `.title()` will distort names such as `AT&T`. 

- [x] Add `Assessment` to the regex based status logic in `classify.py` so the non AI path can represent that state consistently. 

- [x] Keep the noise filter in `classify.py`, but move the patterns into grouped constants so false positive cleanup is easier to expand and review. 

- [x] Write tests for the filter scoring logic in `classify.py` because the current definite and maybe thresholds are sensible but easy to break when new keywords are added. 

- [x] Split AI setup, regex title extraction, Gmail body fetching, and deduplication into separate functions in `extract.py` so the file is easier to test and maintain. 

- [x] Move Groq key loading out of `.yaml` parsing inside `extract.py` and into a shared config helper or environment based setup so secrets management is clearer. 

- [x] Preserve and inspect `evidence_snippets` from the AI output in a saved column or debug file because you already validate them and they would help explain why a row was classified a certain way. 

- [x] Reparse `Date` consistently after reading CSV files in `extract.py` because the file sorts by `Date` after a CSV round trip and that can become fragile if formats shift. 

- [x] Add a fallback deduplication rule for rows with a known company but missing job title because `extract.py` only deduplicates rows where both `Company` and `JobTitle` are present. 

- [x] Add `Assessment` to `status_rank` in `extract.py` so that assessment emails are ranked correctly during deduplication. 

- [x] Consider storing `MsgId` in the final export or a separate audit file because it is useful for tracing output rows back to source emails during debugging. 

- [x] Read `job_tracker.csv` once in `report.py` and derive the follow up view and analytics from that same DataFrame so the reporting phase does not duplicate I/O unnecessarily. 

- [x] Write the weekly markdown report to a real `.md` file in `report.py` because it is currently printed to stdout instead of being saved as an artifact. 

- [x] Add `Assessment` to the funnel ordering in `report.py` so the chart matches the statuses produced by the extraction phase. 

- [x] Save a follow up CSV in `report.py` for applications that need attention because the overdue logic is already computed and would be useful outside the console output. 

- [x] Consider exporting image files instead of only HTML charts in `report.py` if you want artifacts that are easier to share in a portfolio or weekly review. 

- [x] Add basic unit tests for company extraction, title extraction, status assignment, and deduplication because those are the core behaviors that drive the final tracker output. 

- [x] Add a clear README section for required files such as `credentials.json`, `token.json`, and the Groq key source because the pipeline depends on them across multiple phases. 

- [x] Consider introducing a small schema or dataclass for intermediate records so column expectations stay explicit across `fetch.py`, `classify.py`, `extract.py`, and `report.py`. 
