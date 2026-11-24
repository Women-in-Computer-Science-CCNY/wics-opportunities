import html
import json
import os
import re
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone

from bs4 import BeautifulSoup


# ============================================================
# CONFIGURATION
# ============================================================

HACKHQ_URL = (
    "https://raw.githubusercontent.com/"
    "Hack-HQ/hackhq/main/.github/scripts/listings.json"
)

DEVPOST_URL = "https://devpost.com/api/hackathons"

WEBHOOK_URL = os.environ["DISCORD_HACKATHONS_WEBHOOK"]

STATE_FILE = "posted_hackathons.json"

# Prevent a large Discord flood if many new events appear at once.
MAX_POSTS = 10


# ============================================================
# HTTP HELPERS
# ============================================================

def request_json(url):
    """
    Fetch JSON from a URL.
    """

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "WiCS-CCNY-Hackathon-Bot/3.0",
            "Accept": "application/json",
        },
    )

    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def request_text(url):
    """
    Fetch HTML/text from a URL.
    """

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "WiCS-CCNY-Hackathon-Bot/3.0",
            "Accept": "text/html",
        },
    )

    with urllib.request.urlopen(req, timeout=30) as response:
        return response.read().decode(
            "utf-8",
            errors="replace",
        )


def post_discord(payload):
    """
    Send one Discord webhook message.
    """

    data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        WEBHOOK_URL,
        data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "WiCS-CCNY-Hackathon-Bot/3.0",
        },
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=30):
        pass


# ============================================================
# STATE
# ============================================================

def load_posted():
    """
    Load the IDs/keys of hackathons we've already seen.
    """

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))

    except (
        FileNotFoundError,
        json.JSONDecodeError,
    ):
        return set()


def save_posted(posted):
    """
    Save the IDs/keys we've already seen.
    """

    with open(
        STATE_FILE,
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            sorted(posted),
            f,
            indent=2,
        )


# ============================================================
# GENERAL HELPERS
# ============================================================

def clean_text(value):
    """
    Remove HTML markup, decode entities, and normalize spaces.
    """

    if not value:
        return ""

    value = re.sub(
        r"<[^>]+>",
        "",
        str(value),
    )

    value = html.unescape(value)

    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    return value.strip()


def slug(value):
    """
    Turn a title into a normalized string for deduplication.
    """

    return re.sub(
        r"[^a-z0-9]+",
        "-",
        value.lower(),
    ).strip("-")


def canonical_key(event):
    """
    Source-independent key.

    This allows:

    Devpost -> Hackathon X
    MLH     -> Hackathon X
    HackHQ  -> Hackathon X

    to be treated as one event.
    """

    return f"v2:{slug(event['title'])}"


def high_school_only(event):
    """
    Reject events that appear to be specifically for high-school
    or teen participants.
    """

    text = " ".join(
        [
            event.get("title", ""),
            event.get("host", ""),
            event.get("audience", ""),
        ]
    ).lower()

    phrases = [
        "high school",
        "high-school",
        "highschool",
        "ages 13-18",
        "ages 13–18",
        "ages 13-17",
        "ages 13–17",
        "teen hackathon",
        "teen game jam",
    ]

    return any(
        phrase in text
        for phrase in phrases
    )


def should_post(event):
    """
    Determine whether an event belongs in the WiCS feed.
    """

    if not event.get("title"):
        return False

    if not event.get("url"):
        return False

    if event.get("invite_only"):
        return False

    if high_school_only(event):
        return False

    status = (
        event.get("status", "")
        .lower()
        .strip()
    )

    if status not in (
        "open",
        "upcoming",
        "opens_soon",
    ):
        return False

    # Reject events that clearly already ended.
    end_date = event.get("end_date")

    if end_date:
        try:
            parsed_end = date.fromisoformat(
                end_date[:10]
            )

            if parsed_end < date.today():
                return False

        except ValueError:
            pass

    return True


# ============================================================
# HACKHQ
# ============================================================

def fetch_hackhq():
    """
    Fetch maintained HackHQ listings.
    """

    raw = request_json(HACKHQ_URL)

    events = []

    for item in raw:

        if not item.get("active", False):
            continue

        if item.get("is_visible") is False:
            continue

        state = (
            item.get("state", "")
            .lower()
            .strip()
        )

        if state not in (
            "open",
            "opens_soon",
        ):
            continue

        locations = (
            item.get("locations")
            or []
        )

        events.append(
            {
                "source": "HackHQ",
                "title": clean_text(
                    item.get("title")
                ),
                "url": item.get("url"),
                "host": (
                    clean_text(
                        item.get("company_name")
                    )
                    or "Organizer"
                ),
                "location": (
                    ", ".join(locations)
                    if locations
                    else "See event page"
                ),
                "format": (
                    item.get("format")
                    or "See event page"
                ),
                "prize": (
                    item.get("prize")
                    or "TBA"
                ),
                "status": state,
                "deadline": item.get(
                    "deadline"
                ),
                "date_label": None,
                "start_date": item.get(
                    "startDate"
                ),
                "end_date": item.get(
                    "endDate"
                ),
                "invite_only": False,
                "audience": "",
            }
        )

    print(
        f"HackHQ: {len(events)} candidate events"
    )

    return events


# ============================================================
# DEVPOST
# ============================================================

def fetch_devpost():
    """
    Fetch directly from Devpost's JSON endpoint.

    We request both open and upcoming hackathons.
    """

    events = []

    for status in (
        "open",
        "upcoming",
    ):

        for page in range(1, 13):

            params = urllib.parse.urlencode(
                {
                    "status[]": status,
                    "per_page": 40,
                    "page": page,
                    "order_by": "deadline",
                }
            )

            url = (
                f"{DEVPOST_URL}?{params}"
            )

            data = request_json(url)

            batch = data.get(
                "hackathons",
                [],
            )

            if not batch:
                break

            for item in batch:

                displayed_location = (
                    item.get(
                        "displayed_location"
                    )
                    or {}
                )

                location = (
                    displayed_location.get(
                        "location"
                    )
                )

                if isinstance(
                    location,
                    dict,
                ):
                    location = (
                        location.get("name")
                        or location.get(
                            "location"
                        )
                    )

                location = clean_text(
                    location
                )

                icon = (
                    displayed_location.get(
                        "icon"
                    )
                )

                if (
                    icon == "globe"
                    or location.lower()
                    == "online"
                ):
                    format_type = "Virtual"
                    location = "Online"

                else:
                    format_type = "In-Person"

                themes = []

                for theme in (
                    item.get("themes")
                    or []
                ):

                    if isinstance(
                        theme,
                        dict,
                    ):
                        name = theme.get(
                            "name"
                        )

                        if name:
                            themes.append(
                                str(name)
                            )

                events.append(
                    {
                        "source": "Devpost",
                        "title": clean_text(
                            item.get("title")
                        ),
                        "url": item.get("url"),
                        "host": (
                            clean_text(
                                item.get(
                                    "organization_name"
                                )
                            )
                            or "Organizer"
                        ),
                        "location": (
                            location
                            or "See event page"
                        ),
                        "format": format_type,
                        "prize": (
                            clean_text(
                                item.get(
                                    "prize_amount"
                                )
                            )
                            or "TBA"
                        ),
                        "status": status,
                        "deadline": (
                            clean_text(
                                item.get(
                                    "time_left_to_submission"
                                )
                            )
                            or None
                        ),
                        "date_label": (
                            clean_text(
                                item.get(
                                    "submission_period_dates"
                                )
                            )
                            or None
                        ),
                        "start_date": None,
                        "end_date": None,
                        "invite_only": bool(
                            item.get(
                                "invite_only"
                            )
                        ),
                        "audience": " ".join(
                            themes
                        ),
                    }
                )

            meta = (
                data.get("meta")
                or {}
            )

            total = (
                meta.get(
                    "total_count",
                    0,
                )
                or 0
            )

            per_page = (
                meta.get(
                    "per_page",
                    40,
                )
                or 40
            )

            if (
                total
                and page * per_page
                >= total
            ):
                break

    print(
        f"Devpost: {len(events)} candidate events"
    )

    return events


# ============================================================
# MLH
# ============================================================

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


MLH_DATE_PATTERN = re.compile(
    r"\b("
    r"JAN|FEB|MAR|APR|MAY|JUN|"
    r"JUL|AUG|SEP|OCT|NOV|DEC"
    r")\s+(\d{1,2})"
    r"(?:\s*-\s*"
    r"(?:(JAN|FEB|MAR|APR|MAY|JUN|"
    r"JUL|AUG|SEP|OCT|NOV|DEC)\s+)?"
    r"(\d{1,2}))?",
    re.I,
)


def parse_mlh_date(
    date_text,
    season_year,
):
    """
    Convert MLH text such as:

    NOV 28 - 29
    JAN 08 - 10
    FEB 27 - MAR 01

    into ISO start/end dates.

    MLH seasons span calendar years.

    Example:
    2027 season:
        NOV/DEC = 2026
        JAN-JUN  = 2027
    """

    match = MLH_DATE_PATTERN.search(
        date_text or ""
    )

    if not match:
        return None, None

    start_month_name = (
        match.group(1).upper()
    )

    start_month = MONTHS.get(
        start_month_name
    )

    if not start_month:
        return None, None

    start_day = int(
        match.group(2)
    )

    end_month_name = (
        match.group(3)
    )

    if end_month_name:
        end_month = MONTHS.get(
            end_month_name.upper(),
            start_month,
        )
    else:
        end_month = start_month

    end_day = (
        int(match.group(4))
        if match.group(4)
        else start_day
    )

    # MLH season YYYY begins during the previous
    # calendar year's fall semester.
    if start_month >= 7:
        start_year = (
            season_year - 1
        )
    else:
        start_year = (
            season_year
        )

    # Handle rare ranges crossing New Year.
    if end_month < start_month:
        end_year = (
            start_year + 1
        )
    elif end_month >= 7:
        end_year = (
            season_year - 1
        )
    else:
        end_year = (
            season_year
        )

    try:
        start = date(
            start_year,
            start_month,
            start_day,
        )

        end = date(
            end_year,
            end_month,
            end_day,
        )

        return (
            start.isoformat(),
            end.isoformat(),
        )

    except ValueError:
        return None, None


def extract_mlh_location_and_name(
    text,
    date_match,
):
    """
    MLH currently renders event cards approximately like:

    Toronto, Ontario Hack Canada 2027
    JAN 08 - 10
    Toronto, Ontario, CA In-Person Hardware

    We use the repeated location after the date
    to separate location from the event name.
    """

    before_date = clean_text(
        text[:date_match.start()]
    )

    after_date = clean_text(
        text[date_match.end():]
    )

    # Remove MLH metadata tags from the part
    # after the date.
    after_clean = re.sub(
        r"\b("
        r"In-Person|"
        r"Digital|"
        r"Virtual|"
        r"Online|"
        r"Diversity|"
        r"Hardware|"
        r"High school"
        r")\b",
        "",
        after_date,
        flags=re.I,
    )

    after_clean = re.sub(
        r"\s+",
        " ",
        after_clean,
    ).strip(" ,")

    # MLH appends country codes such as:
    # Toronto, Ontario, CA
    # Washington, DC, US
    #
    # Remove only the final two-letter country code.
    location = re.sub(
        r",\s*[A-Z]{2}\s*$",
        "",
        after_clean,
    ).strip(" ,")

    name = before_date

    # The location is repeated before the name.
    # Remove that prefix when possible.
    if (
        location
        and before_date.lower().startswith(
            location.lower()
        )
    ):
        name = before_date[
            len(location):
        ].strip(" ,-")

    return (
        clean_text(location),
        clean_text(name),
    )


def fetch_mlh():
    """
    Fetch current and next MLH season schedules.

    The parser intentionally relies mostly on visible
    event-card text rather than fragile CSS classes.
    """

    events = []

    current_year = datetime.now(
        timezone.utc
    ).year

    # Current season + next season.
    #
    # Example in Nov 2026:
    # /seasons/2026/events
    # /seasons/2027/events
    for season_year in (
        current_year,
        current_year + 1,
    ):

        url = (
            "https://www.mlh.com/"
            f"seasons/{season_year}/events"
        )

        try:
            page = request_text(url)

        except Exception as exc:
            print(
                f"MLH {season_year}: "
                f"failed ({exc})"
            )
            continue

        soup = BeautifulSoup(
            page,
            "html.parser",
        )

        season_events = []

        for link in soup.find_all(
            "a",
            href=True,
        ):

            href = (
                link.get("href", "")
                .strip()
            )

            if not href:
                continue

            # Build one clean line from all visible
            # text in the event card.
            card_text = " ".join(
                link.stripped_strings
            )

            card_text = clean_text(
                card_text
            )

            if not card_text:
                continue

            date_match = (
                MLH_DATE_PATTERN.search(
                    card_text
                )
            )

            # Non-event navigation links won't contain
            # MLH's date format.
            if not date_match:
                continue

            date_text = (
                date_match.group(0)
                .upper()
            )

            location, name = (
                extract_mlh_location_and_name(
                    card_text,
                    date_match,
                )
            )

            if not name:
                continue

            # Ignore clearly internal MLH navigation.
            if href.startswith("/"):
                href = urllib.parse.urljoin(
                    "https://www.mlh.com",
                    href,
                )

            # Most real event links point to the
            # hackathon's own site.
            if (
                "mlh.com/seasons/"
                in href.lower()
            ):
                continue

            start_date, end_date = (
                parse_mlh_date(
                    date_text,
                    season_year,
                )
            )

            # If we know the event ended already,
            # don't include it.
            if end_date:
                try:
                    if (
                        date.fromisoformat(
                            end_date
                        )
                        < date.today()
                    ):
                        continue

                except ValueError:
                    pass

            high_school = bool(
                re.search(
                    r"\bhigh\s*school\b",
                    card_text,
                    re.I,
                )
            )

            digital = bool(
                re.search(
                    r"\b("
                    r"digital|"
                    r"online|"
                    r"virtual|"
                    r"worldwide|"
                    r"everywhere"
                    r")\b",
                    card_text,
                    re.I,
                )
            )

            if start_date:
                try:
                    start_obj = (
                        date.fromisoformat(
                            start_date
                        )
                    )

                    status = (
                        "upcoming"
                        if start_obj
                        > date.today()
                        else "open"
                    )

                except ValueError:
                    status = "upcoming"

            else:
                status = "upcoming"

            season_events.append(
                {
                    "source": "MLH",
                    "title": name,
                    "url": href,
                    "host": (
                        "Major League Hacking"
                    ),
                    "location": (
                        "Online"
                        if digital
                        else (
                            location
                            or "See event page"
                        )
                    ),
                    "format": (
                        "Virtual"
                        if digital
                        else "In-Person"
                    ),
                    "prize": (
                        "See event page"
                    ),
                    "status": status,
                    "deadline": None,
                    "date_label": date_text,
                    "start_date": start_date,
                    "end_date": end_date,
                    "invite_only": False,
                    "audience": (
                        "high school"
                        if high_school
                        else "university"
                    ),
                }
            )

        # Remove duplicate URLs inside a season.
        unique = {}

        for event in season_events:
            unique[event["url"]] = event

        season_events = list(
            unique.values()
        )

        print(
            f"MLH {season_year}: "
            f"{len(season_events)} "
            f"candidate events"
        )

        events.extend(
            season_events
        )

    # Remove duplicates that might appear across
    # consecutive season pages.
    unique_all = {}

    for event in events:
        unique_all[event["url"]] = event

    return list(
        unique_all.values()
    )


# ============================================================
# DEDUPLICATION
# ============================================================

def merge_events(events):
    """
    Combine all sources and remove duplicates.

    When the same event exists on multiple sources:

    Devpost > MLH > HackHQ

    Devpost usually contains richer prize and
    application information.
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

        if current is None:
            chosen[key] = event
            continue

        incoming_priority = priority.get(
            event["source"],
            99,
        )

        current_priority = priority.get(
            current["source"],
            99,
        )

        if (
            incoming_priority
            < current_priority
        ):
            chosen[key] = event

    return list(
        chosen.values()
    )


# ============================================================
# DISCORD MESSAGE
# ============================================================

def send_event(event):
    """
    Format and send one hackathon to Discord.
    """

    status = event.get(
        "status",
        "",
    )

    if status in (
        "upcoming",
        "opens_soon",
    ):
        status_text = (
            "⏳ Upcoming / Opens Soon"
        )

    else:
        status_text = "✅ Open"

    if event.get("date_label"):

        dates = event[
            "date_label"
        ]

    elif (
        event.get("start_date")
        and event.get("end_date")
    ):

        if (
            event["start_date"]
            == event["end_date"]
        ):
            dates = event[
                "start_date"
            ]

        else:
            dates = (
                f"{event['start_date']} → "
                f"{event['end_date']}"
            )

    elif event.get("start_date"):

        dates = event[
            "start_date"
        ]

    else:
        dates = (
            "Check event page"
        )

    deadline = (
        event.get("deadline")
        or "Check event page"
    )

    location = (
        event.get("location")
        or "See event page"
    )

    format_type = (
        event.get("format")
        or "See event page"
    )

    prize = (
        event.get("prize")
        or "TBA"
    )

    description = (
        f"**Hosted by:** "
        f"{event.get('host', 'Organizer')}\n"

        f"📅 **Dates:** {dates}\n"

        f"⏰ **Deadline:** "
        f"{deadline}\n"

        f"📍 **Location:** "
        f"{location}\n"

        f"💻 **Format:** "
        f"{format_type}\n"

        f"🏆 **Prize:** "
        f"{prize}\n"

        f"📌 **Status:** "
        f"{status_text}\n"

        f"🔎 **Source:** "
        f"{event.get('source')}\n\n"

        f"🔗 **[View / Apply]"
        f"({event['url']})**\n\n"

        f"💬 **Looking for teammates?** "
        f"Start a thread on this post!\n\n"

        f"*Always verify eligibility, "
        f"travel requirements, dates, and "
        f"deadlines on the official event page.*"
    )

    payload = {
        "username": "WiCS Hackathons",
        "embeds": [
            {
                "title": (
                    f"🏆 {event['title']}"
                ),
                "url": event["url"],
                "description": description,
            }
        ],
    }

    post_discord(payload)


# ============================================================
# MAIN
# ============================================================

def main():

    all_events = []

    sources = [
        (
            "HackHQ",
            fetch_hackhq,
        ),
        (
            "Devpost",
            fetch_devpost,
        ),
        (
            "MLH",
            fetch_mlh,
        ),
    ]

    # Each source is independent.
    #
    # If MLH breaks one day, Devpost and HackHQ
    # should continue working.
    for name, function in sources:

        try:
            events = function()

            all_events.extend(
                events
            )

        except Exception as exc:

            print(
                f"WARNING: "
                f"{name} failed: "
                f"{exc}"
            )

    events = merge_events(
        all_events
    )

    print(
        f"Found {len(events)} "
        f"eligible unique hackathons."
    )

    # Helpful source breakdown in Actions logs.
    source_counts = {}

    for event in events:

        source = event.get(
            "source",
            "Unknown",
        )

        source_counts[source] = (
            source_counts.get(
                source,
                0,
            )
            + 1
        )

    for source, count in sorted(
        source_counts.items()
    ):
        print(
            f"Eligible from "
            f"{source}: {count}"
        )

    posted = load_posted()

    # --------------------------------------------------------
    # V2 MIGRATION
    # --------------------------------------------------------
    #
    # You already ran the V2 migration.
    #
    # Keeping this check means a completely fresh repo
    # still won't dump hundreds of existing hackathons
    # into Discord.
    # --------------------------------------------------------

    if "v2:migrated" not in posted:

        for event in events:

            posted.add(
                canonical_key(
                    event
                )
            )

        posted.add(
            "v2:migrated"
        )

        save_posted(
            posted
        )

        print(
            "V2 migration complete. "
            "Current hackathons "
            "marked as seen."
        )

        return

    # --------------------------------------------------------
    # FIND NEW EVENTS
    # --------------------------------------------------------

    new_events = [
        event
        for event in events
        if canonical_key(event)
        not in posted
    ]

    print(
        f"Found {len(new_events)} "
        f"new hackathons."
    )

    if not new_events:

        print(
            "No Discord posts needed."
        )

        return

    # --------------------------------------------------------
    # POST
    # --------------------------------------------------------

    posted_this_run = 0

    for event in new_events[
        :MAX_POSTS
    ]:

        try:
            send_event(
                event
            )

        except Exception as exc:

            print(
                f"ERROR posting "
                f"{event['title']}: "
                f"{exc}"
            )

            # Do NOT mark it as seen.
            # This lets a later run retry it.
            continue

        posted.add(
            canonical_key(
                event
            )
        )

        posted_this_run += 1

        print(
            f"Posted: "
            f"{event['title']} "
            f"({event['source']})"
        )

    save_posted(
        posted
    )

    print(
        f"Successfully posted "
        f"{posted_this_run} "
        f"hackathons to Discord."
    )

    remaining = (
        len(new_events)
        - posted_this_run
    )

    if remaining > 0:

        print(
            f"{remaining} new "
            f"hackathons remain "
            f"for a future run."
        )


if __name__ == "__main__":
    main()
