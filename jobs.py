"""WiCS opportunities: Python standard library only; no bot token needed."""
import html
from datetime import datetime, timezone
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
    value = re.sub(r'</?br\s*/?>', ', ', value, flags=re.I)
    return html.unescape(re.sub(r'<[^>]+>', '', value)).strip().strip('*')

def age_days(value):
    """Use the source's age/date; unknown dates sort last."""
    value = plain(value).lower()
    if value in ('today', 'just posted'):
        return 0
    if value == 'yesterday':
        return 1
    match = re.fullmatch(r'(\d+)\s*(d|days?|h|hours?|w|weeks?)', value)
    if match:
        amount, unit = int(match[1]), match[2]
        return amount / 24 if unit.startswith('h') else amount * 7 if unit.startswith('w') else amount
    for fmt in ('%b %d, %Y', '%Y-%m-%d', '%b %d'):
        try:
            now = datetime.now(timezone.utc)
            date = datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
            if fmt == '%b %d':
                date = date.replace(year=now.year)
                if date.date() > now.date():
                    date = date.replace(year=now.year - 1)
            return max(0, (now.date() - date.date()).days)
        except ValueError:
            continue
    return float('inf')

def role_tags(title):
    """Title-based hints, not verified eligibility or source categories."""
    rules = [
        ('SWE', r'\b(software|swe|full[ -]?stack|frontend|front[ -]end|backend|back[ -]end|ios|android)\b'),
        ('AI / Data', r'\b(ai|ml|machine learning|data|analytics|artificial intelligence)\b'),
        ('Product', r'\b(product manager|product management|apm)\b'),
        ('Quant', r'\b(quant|quantitative|trader|trading)\b'),
        ('Security', r'\b(security|cybersecurity)\b'),
        ('Cloud / Infrastructure', r'\b(cloud|infrastructure|devops|sre|site reliability)\b'),
        ('Hardware', r'\b(hardware|electrical|embedded|firmware|silicon)\b'),
    ]
    return [tag for tag, pattern in rules if re.search(pattern, title, re.I)] or ['Other Tech']

def newest_first(jobs):
    return sorted(jobs, key=lambda job: age_days(job.get('source_age', '')))

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
                     'location': plain(cells[2]), 'url': url,
                     'source_age': plain(cells[-1]) if len(cells) > 4 else ''}
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
                           'description': f"**Company:** {job['company'][:400]}\n**Location:** {job['location'][:500]}\n**Tags (from title):** {' · '.join(role_tags(job['title']))}\n**Source age/date:** {job.get('source_age') or 'Not listed'}",
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
        pending = newest_first([job for url, job in jobs.items() if url not in seen])
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
