import subprocess
import sys
import time
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  %(levelname)s  %(message)s',
    datefmt='%H:%M:%S'
)
log = logging.getLogger(__name__)

PHASES = [
    ('fetch.py',    'Fetching emails from Gmail'),
    ('classify.py', 'Filtering and classifying emails'),
    ('extract.py',  'Extracting job titles and company names'),
    ('report.py',   'Generating report and charts'),
]


def run_phase(script, description):
    log.info(f'Starting: {description}')
    print(f'\n{"="*50}')
    print(f'{description}...')
    print(f'{"="*50}')
    start = time.time()
    result = subprocess.run([sys.executable, script], check=False)
    elapsed = time.time() - start
    if result.returncode != 0:
        log.error(f'{script} failed with exit code {result.returncode} after {elapsed:.1f}s')
        print(f'\nERROR: {script} failed (exit code {result.returncode}). Pipeline stopped.')
        sys.exit(result.returncode)
    log.info(f'Finished: {description} ({elapsed:.1f}s)')
    print(f'Done in {elapsed:.1f}s')


if __name__ == '__main__':
    total_start = time.time()
    for script, description in PHASES:
        run_phase(script, description)
    total = time.time() - total_start
    log.info(f'Pipeline complete in {total:.1f}s')
    print(f'\nPipeline complete in {total:.1f}s')
    print('Output: job_tracker.csv, followup_needed.csv')
    print('Run:    python app.py   to browse your applications')
