import html
import json
import os
import re
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone

HACKHQ_URL = (
    "https://raw.githubusercontent.com/"
    "Hack-HQ/hackhq/main/.github/scripts/listings.json"
)

DEVPOST_URL = "https://devpost.com/api/hackathons"

WEBHOOK_URL = os.environ["DISCORD_HACKATHONS_WEBHOOK"]
STATE_FILE = "posted_hackathons.json"

MAX_POSTS = 10


# --------------------------------------------------
# HTTP
# --------------------------------------------------

def request_json(url):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "WiCS-CCNY-Hackathon-Bot/2.0",
            "Accept": "application/json",
        },
    )

    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def request_text(url):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "WiCS-CCNY-Hackathon-Bot/2.0",
            "Accept": "text/html",
        },
    )

    with urllib.request.urlopen(req, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def post_discord(payload):
    data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        WEBHOOK_URL,
        data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "WiCS-CCNY-Hackathon-Bot/2.0",
        },
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=30):
        pass


# --------------------------------------------------
# STATE
# --------------------------------------------------

def load_posted():
    try:
        with open(STATE_FILE, "r") as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def save_posted(posted):
    with open(STATE_FILE, "w") as f:
        json.dump(sorted(posted), f, indent=2)


# --------------------------------------------------
# HELPERS
# --------------------------------------------------

def clean_text(value):
    if not value:
        return ""

    value = re.sub(r"<[^>]+>", "", str(value))
    return html.unescape(value).strip()


def slug(value):
    return re.sub(
        r"[^a-z0-9]+",
        "-",
        value.lower()
    ).strip("-")


def canonical_key(event):
    """
    Source-independent key so the same event from HackHQ,
    Devpost, and MLH doesn't get posted multiple times.
    """
    return f"v2:{slug(event['title'])}"


def high_school_only(event):
    text = " ".join([
        event.get("title", ""),
        event.get("host", ""),
        event.get("audience", ""),
    ]).lower()

    phrases = [
        "high school",
        "high-school",
        "ages 13-18",
        "ages 13–18",
        "teen hackathon",
        "teen game jam",
    ]

    return any(x in text for x in phrases)


def should_post(event):
    if not event.get("title"):
        return False

    if not event.get("url"):
        return False

    if event.get("invite_only"):
        return False

    if high_school_only(event):
        return False

    status = event.get("status", "").lower()

    if status not in ("open", "upcoming", "opens_soon"):
        return False

    # Reject clearly expired events
    end = event.get("end_date")

    if end:
        try:
            if date.fromisoformat(end[:10]) < date.today():
                return False
        except ValueError:
            pass

    return True


# --------------------------------------------------
# HACKHQ
# --------------------------------------------------

def fetch_hackhq():
    raw = request_json(HACKHQ_URL)

    events = []

    for item in raw:
        if not item.get("active", False):
            continue

        if item.get("is_visible") is False:
            continue

        state = item.get("state", "").lower()

        if state not in ("open", "opens_soon"):
            continue

        locations = item.get("locations") or []

        events.append({
            "source": "HackHQ",
            "title": item.get("title"),
            "url": item.get("url"),
            "host": item.get("company_name") or "Organizer",
            "location": ", ".join(locations) if locations else "See event page",
            "format": item.get("format") or "See event page",
            "prize": item.get("prize") or "TBA",
            "status": state,
            "deadline": item.get("deadline"),
            "start_date": item.get("startDate"),
            "end_date": item.get("endDate"),
            "invite_only": False,
            "audience": "",
        })

    print(f"HackHQ: {len(events)} candidate events")

    return events


# --------------------------------------------------
# DEVPOST
# --------------------------------------------------

def fetch_devpost():
    events = []

    # Devpost exposes open + upcoming separately.
    for status in ("open", "upcoming"):

        for page in range(1, 13):

            params = urllib.parse.urlencode({
                "status[]": status,
                "per_page": 40,
                "page": page,
                "order_by": "deadline",
            })

            url = f"{DEVPOST_URL}?{params}"

            data = request_json(url)

            batch = data.get("hackathons", [])

            if not batch:
                break

            for item in batch:

                displayed_location = (
                    item.get("displayed_location") or {}
                )

                location = displayed_location.get("location")

                if isinstance(location, dict):
                    location = location.get("name")

                location = clean_text(location)

                icon = displayed_location.get("icon")

                if icon == "globe" or location.lower() == "online":
                    format_type = "Virtual"
                    location = "Online"
                else:
                    format_type = "In-Person"

                themes = [
                    theme.get("name", "")
                    for theme in item.get("themes", [])
                ]

                events.append({
                    "source": "Devpost",
                    "title": clean_text(item.get("title")),
                    "url": item.get("url"),
                    "host": clean_text(
                        item.get("organization_name")
                    ) or "Organizer",
                    "location": location or "See event page",
                    "format": format_type,
                    "prize": clean_text(
                        item.get("prize_amount")
                    ) or "TBA",
                    "status": status,
                    "deadline": clean_text(
                        item.get("time_left_to_submission")
                    ),
                    "date_label": clean_text(
                        item.get("submission_period_dates")
                    ),
                    "start_date": None,
                    "end_date": None,
                    "invite_only": bool(
                        item.get("invite_only")
                    ),
                    "audience": " ".join(themes),
                })

            meta = data.get("meta", {})

            total = meta.get("total_count", 0)
            per_page = meta.get("per_page", 40)

            if page * per_page >= total:
                break

    print(f"Devpost: {len(events)} candidate events")

    return events


# --------------------------------------------------
# MLH
# --------------------------------------------------

MONTHS = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}


def extract_class(block, class_name):
    pattern = (
        rf'class="[^"]*{re.escape(class_name)}[^"]*"'
        rf'[^>]*>([\s\S]*?)<'
    )

    match = re.search(pattern, block, re.I)

    if not match:
        return None

    return clean_text(match.group(1))


def parse_mlh_date(text, year):
    if not text:
        return None, None

    match = re.search(
        r"([A-Z]{3})\s*(\d{1,2})"
        r"(?:\s*-\s*(?:([A-Z]{3})\s*)?(\d{1,2}))?",
        text.upper(),
    )

    if not match:
        return None, None

    start_month = MONTHS.get(match.group(1))

    if not start_month:
        return None, None

    start_day = int(match.group(2))

    end_month = (
        MONTHS.get(match.group(3))
        if match.group(3)
        else start_month
    )

    end_day = (
        int(match.group(4))
        if match.group(4)
        else start_day
    )

    try:
        start = date(year, start_month, start_day)
        end = date(year, end_month, end_day)

        return start.isoformat(), end.isoformat()

    except ValueError:
        return None, None


def fetch_mlh():
    events = []

    current_year = datetime.now(timezone.utc).year

    for year in (current_year, current_year + 1):

        url = f"https://mlh.com/seasons/{year}/events"

        try:
            page = request_text(url)

        except Exception as exc:
            print(f"MLH {year}: failed ({exc})")
            continue

        blocks = re.findall(
            r'<a[^>]+href="https?://[^"]+"[^>]*>'
            r'[\s\S]{0,3000}?</a>',
            page,
            re.I,
        )

        count = 0

        for block in blocks:

            href_match = re.search(
                r'href="([^"]+)"',
                block,
                re.I,
            )

            if not href_match:
                continue

            event_url = href_match.group(1)

            # Ignore links back to MLH itself
            if "mlh.com" in event_url:
                continue

            name = (
                extract_class(block, "event-name")
                or extract_class(block, "name")
            )

            date_text = (
                extract_class(block, "event-date")
                or extract_class(block, "date")
            )

            location = (
                extract_class(block, "event-location")
                or extract_class(block, "location")
            )

            if not name or not date_text:
                continue

            start, end = parse_mlh_date(
                date_text,
                year,
            )

            digital = bool(
                re.search(
                    r"digital|online|worldwide|everywhere",
                    f"{location or ''} {block}",
                    re.I,
                )
            )

            high_school = bool(
                re.search(
                    r"HIGH\s*SCHOOL",
                    block,
                    re.I,
                )
            )

            events.append({
                "source": "MLH",
                "title": name,
                "url": event_url,
                "host": "Major League Hacking",
                "location": (
                    "Online"
                    if digital
                    else location or "See event page"
                ),
                "format": (
                    "Virtual"
                    if digital
                    else "In-Person"
                ),
                "prize": "See event page",
                "status": (
                    "upcoming"
                    if start and start > date.today().isoformat()
                    else "open"
                ),
                "deadline": None,
                "date_label": date_text,
                "start_date": start,
                "end_date": end,
                "invite_only": False,
                "audience": (
                    "high school"
                    if high_school
                    else "university"
                ),
            })

            count += 1

        print(f"MLH {year}: {count} candidate events")

    return events


# --------------------------------------------------
# DEDUPE
# --------------------------------------------------

def merge_events(events):
    """
    Prefer direct sources over HackHQ when duplicates exist.

    Priority:
    Devpost > MLH > HackHQ
    """

    priority = {
        "Devpost": 1,
        "MLH": 2,
        "HackHQ": 3,
    }

    chosen = {}

    for event in events:

        if not should_post(event):
            continue

        key = canonical_key(event)

        current = chosen.get(key)

        if (
            current is None
            or priority[event["source"]]
            < priority[current["source"]]
        ):
            chosen[key] = event

    return list(chosen.values())


# --------------------------------------------------
# DISCORD FORMAT
# --------------------------------------------------

def send_event(event):
    status = event.get("status")

    if status in ("upcoming", "opens_soon"):
        status_text = "⏳ Upcoming / Opens Soon"
    else:
        status_text = "✅ Open"

    if event.get("date_label"):
        dates = event["date_label"]

    elif event.get("start_date") and event.get("end_date"):

        if event["start_date"] == event["end_date"]:
            dates = event["start_date"]
        else:
            dates = (
                f"{event['start_date']} → "
                f"{event['end_date']}"
            )

    else:
        dates = "Check event page"

    deadline = (
        event.get("deadline")
        or "Check event page"
    )

    description = (
        f"**Hosted by:** {event.get('host', 'Organizer')}\n"
        f"📅 **Dates:** {dates}\n"
        f"⏰ **Deadline:** {deadline}\n"
        f"📍 **Location:** {event.get('location')}\n"
        f"💻 **Format:** {event.get('format')}\n"
        f"🏆 **Prize:** {event.get('prize')}\n"
        f"📌 **Status:** {status_text}\n"
        f"🔎 **Source:** {event.get('source')}\n\n"
        f"🔗 **[View / Apply]({event['url']})**\n\n"
        f"💬 Looking for teammates? "
        f"Start a thread on this post!\n\n"
        f"*Always verify eligibility, travel requirements, "
        f"and deadlines on the official event page.*"
    )

    payload = {
        "username": "WiCS Hackathons",
        "embeds": [{
            "title": f"🏆 {event['title']}",
            "url": event["url"],
            "description": description,
        }],
    }

    post_discord(payload)


# --------------------------------------------------
# MAIN
# --------------------------------------------------

def main():
    all_events = []

    sources = [
        ("HackHQ", fetch_hackhq),
        ("Devpost", fetch_devpost),
        ("MLH", fetch_mlh),
    ]

    for name, function in sources:

        try:
            events = function()
            all_events.extend(events)

        except Exception as exc:
            # One broken source should not kill the entire bot
            print(f"WARNING: {name} failed: {exc}")

    events = merge_events(all_events)

    print(
        f"Found {len(events)} eligible unique hackathons."
    )

    posted = load_posted()

    # Migration from original HackHQ-only bot.
    #
    # This prevents every Devpost / MLH listing from suddenly
    # flooding Discord after the upgrade.
    if "v2:migrated" not in posted:

        for event in events:
            posted.add(canonical_key(event))

        posted.add("v2:migrated")

        save_posted(posted)

        print(
            "V2 migration complete. "
            "Current hackathons marked as seen."
        )

        return

    new_events = [
        event
        for event in events
        if canonical_key(event) not in posted
    ]

    print(
        f"Found {len(new_events)} new hackathons."
    )

    if not new_events:
        print("No Discord posts needed.")
        return

    for event in new_events[:MAX_POSTS]:

        send_event(event)

        posted.add(
            canonical_key(event)
        )

        print(
            f"Posted: {event['title']} "
            f"({event['source']})"
        )

    save_posted(posted)


if __name__ == "__main__":
    main()
