# WiCS Opportunities

Free GitHub Actions + Python + Discord webhooks. Checks SimplifyJobs' Summer2027-Internships and New-Grad-Positions README tables every six hours. Includes all categories and locations from those lists; these are not exclusively NYC roles. Source attribution appears in every message. No paid API or Python packages.

## Setup

1. Create Discord text channels `internships` and `new-grad-roles`.
2. In each channel: Edit Channel → Integrations → Webhooks → New Webhook. Name it WiCS Opportunities, select the correct channel, and copy its webhook URL. You need Manage Webhooks permission.
3. Create a **public**, empty GitHub repository named `wics-opportunities` (under WiCS or your account). Standard GitHub-hosted runners in public repositories are free. Keep webhook URLs in Secrets, never in code.
4. Download and unzip this package. Upload `jobs.py`, `seen_jobs.json`, and `README.md` at the repository root. GitHub's file picker may hide `.github`: create a file on GitHub with the exact name `.github/workflows/jobs.yml`, then paste the supplied workflow contents into it. Commit to the default branch.
5. Repository → Settings → Secrets and variables → Actions → New repository secret. Add:

   | Name | Value |
   | --- | --- |
   | `INTERNSHIP_WEBHOOK` | Webhook URL for internships |
   | `NEW_GRAD_WEBHOOK` | Webhook URL for new-grad-roles |

6. Open Actions → WiCS Opportunities → Run workflow. The first successful run only saves current listings; it intentionally posts no old jobs. Check the logs for `initialized` for both channels.
7. Later runs post newly discovered open application links, up to 15 per channel per run. Remaining new listings are queued for later runs while still open. No laptop needs to stay on.

## Maintenance and limitations

- GitHub schedules are approximate and can be delayed. Public schedules can be disabled after 60 days without repository activity; automatic state commits provide activity when new jobs appear. If dormant, re-enable the workflow in Actions.
- Do not reset `seen_jobs.json`; it remembers posted URLs. The workflow needs permission to push that file. Branch protection or organization rules may block the push: inspect the Save posted links step if a run fails.
- Listings depend on the upstream repositories. The README parser supports HTML and Markdown tables, but a source redesign may require an update. The internship source is seasonal; update SOURCES in jobs.py next recruiting season.
- Closed listings are skipped based on the source's application cell, but openings can expire between checks. Students should verify eligibility and availability on the application page. Graduation windows and deadlines are not inferred.
- URLs are the deduplication key. Changed URLs can appear as new. A runner crash between Discord delivery and saving/pushing state can cause a repeat; this is not exactly-once delivery.
- No everyone/role pings are enabled. Automatic reactions and edits to closed posts are not included.
- If a webhook leaks, delete/recreate it in Discord and replace the GitHub secret.

## Local checks

Run `python -m unittest -v` to test parsing and initialization without Discord access. Live source fetching and channel delivery must be checked with the first GitHub run.

Sources: https://github.com/SimplifyJobs/Summer2027-Internships and https://github.com/SimplifyJobs/New-Grad-Positions
GitHub pricing: https://docs.github.com/en/billing/managing-billing-for-github-actions/about-billing-for-github-actions
