"""WiCS opportunities: Python standard library only; no bot token needed."""
import html
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from urllib.parse import urlparse

SOURCES = {
    'internships': ('SimplifyJobs/Summer2027-Internships', 'INTERNSHIP_WEBHOOK'),
    'new_grad': ('SimplifyJobs/New-Grad-Positions', 'NEW_GRAD_WEBHOOK'),
}
STATE = Path('seen_jobs.json')

def plain(value):
    value = re.sub(r'<br\s*/?>', ', ', value, flags=re.I)
    return html.unescape(re.sub(r'<[^>]+>', '', value)).strip().strip('*')

def parse_jobs(text):
    """Accept HTML tables and legacy Markdown tables, carrying company names."""
    rows = [re.findall(r'<td\b[^>]*>(.*?)</td>', row, re.S | re.I)
            for row in re.findall(r'<tr\b[^>]*>(.*?)</tr>', text, re.S | re.I)]
    rows += [line.strip().strip('|').split('|') for line in text.splitlines()
             if line.strip().startswith('|')]
    jobs, company = {}, ''
    for cells in rows:
        if len(cells) < 4:
            continue
        name = plain(cells[0])
        if name and name not in ('↳', '↪', '→'):
            company = name
        application = cells[3]
        if '🔒' in application or 'closed' in plain(application).lower():
            continue
        links = re.findall(r'href=["\'](https?://[^"\']+)', application)
        links += re.findall(r'\]\((https?://[^\s)]+)\)', application)
        if not links:
            continue
        direct = [u for u in links if urlparse(html.unescape(u)).hostname not in ('simplify.jobs', 'www.simplify.jobs')]
        url = html.unescape((direct or links)[0])
        jobs[url] = {'company': plain(company), 'title': plain(cells[1]),
                     'location': plain(cells[2]), 'url': url}
    if not jobs:
        raise ValueError('No open jobs parsed; source format may have changed. State preserved.')
    return jobs

def fetch(repo):
    url = f'https://raw.githubusercontent.com/{repo}/dev/README.md'
    with urlopen(Request(url, headers={'User-Agent': 'WiCS-Opportunities'}), timeout=45) as response:
        return parse_jobs(response.read().decode())

def post(webhook, job, kind, repo):
    parsed = urlparse(webhook)
    if parsed.scheme != 'https' or parsed.hostname not in ('discord.com', 'discordapp.com') or not parsed.path.startswith('/api/webhooks/'):
        raise ValueError('Invalid Discord webhook; check the repository secret.')
    payload = {'username': 'WiCS Opportunities', 'allowed_mentions': {'parse': []},
               'embeds': [{'title': job['title'][:256], 'url': job['url'],
                           'description': f"**Company:** {job['company'][:400]}\n**Location:** {job['location'][:500]}",
                           'color': 7506394,
                           'footer': {'text': f'{kind} • Source: {repo} • Verify eligibility on the application page'}}]}
    separator = '&' if '?' in webhook else '?'
    request = Request(webhook + separator + 'wait=true', data=json.dumps(payload).encode(),
                      headers={'Content-Type': 'application/json', 'User-Agent': 'WiCS-Opportunities'})
    for attempt in range(4):
        try:
            with urlopen(request, timeout=30) as response:
                response.read()
            return
        except HTTPError as error:
            if error.code != 429 or attempt == 3:
                raise RuntimeError(f'Discord returned HTTP {error.code}; check secret and permissions.') from None
            retry = json.loads(error.read()).get('retry_after', 2)
            time.sleep(min(float(retry) + 1, 60))

def save(state):
    temporary = STATE.with_suffix('.tmp')
    temporary.write_text(json.dumps(state, indent=2, sort_keys=True) + '\n')
    temporary.replace(STATE)

def main():
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    limit = int(os.getenv('MAX_POSTS_PER_CHANNEL', '15'))
    if limit < 1:
        raise ValueError('MAX_POSTS_PER_CHANNEL must be positive')
    for kind, (repo, secret) in SOURCES.items():
        webhook = os.environ.get(secret)
        if not webhook:
            raise ValueError(f'Missing GitHub secret: {secret}')
        jobs = fetch(repo)
        if kind not in state:
            state[kind] = sorted(jobs)
            save(state)
            print(f'{kind}: initialized {len(jobs)} existing listings; no backlog sent.')
            continue
        seen = set(state[kind])
        pending = [job for url, job in jobs.items() if url not in seen]
        for job in pending[:limit]:
            post(webhook, job, kind, repo)
            seen.add(job['url'])
            state[kind] = sorted(seen)
            save(state)
            time.sleep(1)
        print(f'{kind}: posted {min(len(pending), limit)}; {max(0, len(pending)-limit)} pending.')

if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Do not print exception URLs: webhook URLs are credentials.
        print(f'Run failed ({type(error).__name__}). Check sources, secrets, or network; state preserved.', file=sys.stderr)
        sys.exit(1)
