import json
import os
import urllib.request
from datetime import datetime, timezone

FEED_URL = "https://hackathonsboard.netlify.app/events.json"
WEBHOOK_URL = os.environ["DISCORD_HACKATHONS_WEBHOOK"]
STATE_FILE = "posted_hackathons.json"


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


def format_date(value):
    if not value:
        return "Check event page"

    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.strftime("%b %d, %Y")
    except ValueError:
        return "Check event page"


def should_post(event):
    # Ignore ended events
    if event.get("status") == "ended":
        return False

    # Ignore private/invite-only events
    if event.get("inviteOnly"):
        return False

    # WiCS is a college organization, so skip high-school-only listings
    if event.get("audience") == "high-school":
        return False

    # Keep university and generally open events
    if event.get("audience") not in ("university", "open"):
        return False

    return True


def main():
    feed = get_json(FEED_URL)

    # Warn in logs if one of the upstream sources failed
    for source in feed.get("sources", []):
        if not source.get("ok", True):
            print(f"WARNING: Source unavailable: {source.get('name')}")

    posted = load_posted()

    events = [
        event
        for event in feed.get("events", [])
        if should_post(event)
    ]

    new_events = [
        event for event in events
        if event["id"] not in posted
    ]

    # Prevent flooding Discord on the very first run.
    # Post at most 10 listings per run.
    new_events = new_events[:10]

    for event in new_events:
        title = event.get("title", "Hackathon")
        url = event.get("url")
        organizer = event.get("organizer") or event.get("sourceName") or "Organizer"
        location = event.get("locationLabel") or "Location not listed"
        format_type = (event.get("format") or "Unknown").title()
        audience = (event.get("audience") or "Open").replace("-", " ").title()
        deadline = format_date(event.get("endsAt"))
        event_date = event.get("dateLabel") or "Check event page"

        themes = event.get("themes") or []
        theme_text = ", ".join(themes[:4]) if themes else "Various"

        description = (
            f"**Hosted by:** {organizer}\n"
            f"📅 **Dates:** {event_date}\n"
            f"⏰ **Deadline:** {deadline}\n"
            f"📍 **Location:** {location}\n"
            f"💻 **Format:** {format_type}\n"
            f"🎓 **Eligibility:** {audience}\n"
            f"🧩 **Themes:** {theme_text}\n\n"
            f"🔗 **[View / Apply]({url})**\n\n"
            f"💬 Looking for teammates? Start a thread on this post!"
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
        posted.add(event["id"])
        print(f"Posted: {title}")

    save_posted(posted)

    print(f"Found {len(events)} eligible events.")
    print(f"Posted {len(new_events)} new events.")


if __name__ == "__main__":
    main()
