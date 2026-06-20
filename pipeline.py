import subprocess
import sys
import time

PHASES = [
    ('fetch.py',    'Fetching emails from Gmail'),
    ('classify.py', 'Filtering and classifying emails'),
    ('extract.py',  'Extracting job titles and company names'),
    ('report.py',   'Generating report and charts'),
]

def run_phase(script, description):
    print(f'\n{"="*50}')
    print(f'{description}...')
    print(f'{"="*50}')
    start = time.time()
    result = subprocess.run([sys.executable, script], check=False)
    elapsed = time.time() - start
    if result.returncode != 0:
        print(f'\nERROR: {script} failed (exit code {result.returncode}). Pipeline stopped.')
        sys.exit(result.returncode)
    print(f'Done in {elapsed:.1f}s')

if __name__ == '__main__':
    total_start = time.time()
    for script, description in PHASES:
        run_phase(script, description)
    print(f'\nPipeline complete in {time.time() - total_start:.1f}s')
    print('Output: job_tracker.csv')
