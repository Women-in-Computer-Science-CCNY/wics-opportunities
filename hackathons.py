import json
import os
import urllib.request
from datetime import date

FEED_URL = (
    "https://raw.githubusercontent.com/"
    "Hack-HQ/hackhq/main/.github/scripts/listings.json"
)

WEBHOOK_URL = os.environ["DISCORD_HACKATHONS_WEBHOOK"]
STATE_FILE = "posted_hackathons.json"
MAX_POSTS = 10


def get_json(url):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "WiCS-CCNY-Hackathon-Bot/1.0"}
    )

    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def post_discord(payload):
    data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        WEBHOOK_URL,
        data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "WiCS-CCNY-Hackathon-Bot/1.0"
        },
        method="POST"
    )

    with urllib.request.urlopen(req, timeout=30):
        pass


def load_posted():
    try:
        with open(STATE_FILE, "r") as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def save_posted(posted):
    with open(STATE_FILE, "w") as f:
        json.dump(sorted(posted), f, indent=2)


def event_key(event):
    return event.get("id") or event.get("url")


def is_high_school_only(event):
    text = " ".join([
        event.get("title", ""),
        event.get("company_name", ""),
        event.get("source", "")
    ]).lower()

    high_school_phrases = [
        "high school",
        "ages 13–18",
        "ages 13-18",
        "ages 13–17",
        "ages 13-17",
        "teen hackathon",
        "teen game jam",
    ]

    return any(phrase in text for phrase in high_school_phrases)


def should_post(event):
    if not event.get("active", False):
        return False

    if not event.get("is_visible", True):
        return False

    state = event.get("state", "").lower()

    if state not in ("open", "opens_soon"):
        return False

    if is_high_school_only(event):
        return False

    url = event.get("url")
    if not url:
        return False

    # Extra protection against events that already ended
    end_date = event.get("endDate")
    if end_date:
        try:
            if date.fromisoformat(end_date) < date.today():
                return False
        except ValueError:
            pass

    deadline = event.get("deadline")
    if deadline:
        try:
            if date.fromisoformat(deadline) < date.today():
                return False
        except ValueError:
            pass

    return True


def format_date_range(event):
    start = event.get("startDate")
    end = event.get("endDate")

    if start and end:
        if start == end:
            return start
        return f"{start} → {end}"

    if start:
        return start

    return "Check event page"


def main():
    events = get_json(FEED_URL)

    eligible = [
        event for event in events
        if should_post(event)
    ]

    posted = load_posted()

    # FIRST RUN:
    # Remember existing listings without flooding Discord.
    if not posted:
        initial_ids = {
            event_key(event)
            for event in eligible
            if event_key(event)
        }

        save_posted(initial_ids)

        print(
            f"Initial setup complete. "
            f"Marked {len(initial_ids)} existing hackathons as seen."
        )
        return

    new_events = [
        event for event in eligible
        if event_key(event) not in posted
    ]

    # Oldest/newest source ordering can vary, so limit Discord volume.
    new_events = new_events[:MAX_POSTS]

    for event in new_events:
        key = event_key(event)

        title = event.get("title", "Hackathon")
        url = event.get("url")
        host = event.get("company_name", "Organizer")

        locations = event.get("locations") or []
        location = ", ".join(locations) if locations else "See event page"

        format_type = event.get("format", "See event page")
        prize = event.get("prize", "TBA")
        deadline = event.get("deadline", "Check event page")
        dates = format_date_range(event)

        state = event.get("state", "open")

        if state == "opens_soon":
            status = "⏳ Opens Soon"
        else:
            status = "✅ Open"

        description = (
            f"**Hosted by:** {host}\n"
            f"📅 **Dates:** {dates}\n"
            f"⏰ **Deadline:** {deadline}\n"
            f"📍 **Location:** {location}\n"
            f"💻 **Format:** {format_type}\n"
            f"🏆 **Prize:** {prize}\n"
            f"📌 **Status:** {status}\n\n"
            f"🔗 **[View / Apply]({url})**\n\n"
            f"💬 Looking for teammates? "
            f"Start a thread on this post!\n\n"
            f"*Always verify eligibility and deadlines "
            f"on the official event page.*"
        )

        payload = {
            "username": "WiCS Hackathons",
            "embeds": [
                {
                    "title": f"🏆 {title}",
                    "url": url,
                    "description": description
                }
            ]
        }

        post_discord(payload)

        posted.add(key)

        print(f"Posted: {title}")

    save_posted(posted)

    print(f"Found {len(eligible)} eligible hackathons.")
    print(f"Posted {len(new_events)} new hackathons.")


if __name__ == "__main__":
    main()
