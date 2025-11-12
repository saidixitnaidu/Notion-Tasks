# notion_reminder.py
# Minimal Notion -> Telegram reminder script (no DB)
#
# Behavior:
# - Query Notion DB for pages
# - For each page with due-time and assignee(s):
#   - If Checkbox "Checkbox" is True -> skip
#   - If "Reminder Sent" is True -> skip
#   - If now_ist >= (due - 30min) and now_ist < due -> send reminder to each assignee (if chat id known)
#   - After sending, set Notion "Reminder Sent" checkbox True
#
# Configure via environment variables (GitHub Secrets recommended)

import os, requests, json, datetime, sys
from dateutil import tz

# CONFIG via env
NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
NOTION_DB_ID = os.environ.get("NOTION_DB_ID")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
# ASSIGNEE_MAP as JSON string in env: {"Darshan":1111,"Sai Dixit":2222}
ASSIGNEE_MAP = json.loads(os.environ.get("ASSIGNEE_MAP", "{}"))

# Notion column names (update if yours differ)
PROP_TITLE = "Task"
PROP_ASSIGNEES = "Assigned To"
PROP_DUE = "Due"
PROP_CHECKBOX = "Checkbox"         # mark of completion in your DB
PROP_NID = "ID"                    # your human ID column (optional)
PROP_REM_SENT = "Reminder Sent"    # checkbox we will set after sending

TIMEZONE = os.environ.get("TIMEZONE", "Asia/Kolkata")
REMIND_MINUTES = int(os.environ.get("REMIND_MINUTES", "30"))

if not (NOTION_TOKEN and NOTION_DB_ID and TELEGRAM_BOT_TOKEN):
    print("ERROR: set NOTION_TOKEN, NOTION_DB_ID and TELEGRAM_BOT_TOKEN in environment", file=sys.stderr)
    sys.exit(2)

IST = tz.gettz(TIMEZONE)
NOTION_VERSION = "2022-06-28"

notion_headers = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": NOTION_VERSION,
    "Content-Type": "application/json"
}

def notion_query_all(db_id):
    url = f"https://api.notion.com/v1/databases/{db_id}/query"
    out, payload = [], {"page_size": 100}
    while True:
        r = requests.post(url, headers=notion_headers, json=payload, timeout=30)
        r.raise_for_status()
        data = r.json()
        out += data.get("results", [])
        if not data.get("has_more"):
            break
        payload["start_cursor"] = data.get("next_cursor")
    return out

def get_text_from_rich(prop):
    if not prop: return ""
    return "".join([t.get("plain_text","") for t in (prop or [])]).strip()

def parse_due_to_ist(due_prop):
    # returns (datetime_ist, has_time_bool)
    if not due_prop or due_prop.get("type") != "date": return (None, False)
    dateobj = due_prop.get("date")
    if not dateobj or not dateobj.get("start"): return (None, False)
    iso = dateobj["start"]   # can be date-only or full ISO with timezone/Z
    dt = datetime.datetime.fromisoformat(iso.replace("Z","+00:00"))
    dt_ist = dt.astimezone(IST)
    has_time = not (dt_ist.time() == datetime.time(0,0) and "T" not in iso)
    return dt_ist, has_time

def get_assignees_from_prop(prop):
    if not prop: return []
    t = prop.get("type")
    if t == "people":
        return [ (x.get("name") or x.get("person",{}).get("email","")).strip() for x in prop.get("people",[]) ]
    if t == "multi_select":
        return [ x["name"] for x in prop.get("multi_select",[]) ]
    if t == "select" and prop.get("select"):
        return [ prop["select"]["name"] ]
    return []

def send_telegram_message(chat_id, text, notion_url=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "MarkdownV2",
        "disable_web_page_preview": True
    }
    if notion_url:
        # include an inline URL button via reply_markup (optional)
        payload["reply_markup"] = json.dumps({
            "inline_keyboard": [
                [{"text":"Open in Notion", "url": notion_url}]
            ]
        })
    r = requests.post(url, json=payload, timeout=15)
    r.raise_for_status()
    return r.json()

def set_notion_reminder_sent(page_id):
    url = f"https://api.notion.com/v1/pages/{page_id}"
    body = {"properties": { PROP_REM_SENT: {"checkbox": True} }}
    r = requests.patch(url, headers=notion_headers, json=body, timeout=15)
    r.raise_for_status()

def run_once():
    pages = notion_query_all(NOTION_DB_ID)
    now_ist = datetime.datetime.now(IST)
    now_ts = int(now_ist.timestamp())
    sent_count = 0

    for p in pages:
        props = p.get("properties", {})
        page_id = p.get("id")
        title = get_text_from_rich(props.get(PROP_TITLE, {}))
        assignees = get_assignees_from_prop(props.get(PROP_ASSIGNEES))
        due_dt_ist, has_time = parse_due_to_ist(props.get(PROP_DUE))
        completed = False
        if props.get(PROP_CHECKBOX) and props.get(PROP_CHECKBOX).get("type") == "checkbox":
            completed = bool(props.get(PROP_CHECKBOX).get("checkbox"))
        # check our Reminder Sent flag
        rem_sent = False
        if props.get(PROP_REM_SENT) and props.get(PROP_REM_SENT).get("type") == "checkbox":
            rem_sent = bool(props.get(PROP_REM_SENT).get("checkbox"))

        # skip if no due or no time, or already complete
        if not due_dt_ist or not has_time or completed:
            # if task is complete and Reminder Sent true, optionally clear it (not necessary)
            continue

        # calculate remind window (send if now between due-30min and due)
        remind_dt = due_dt_ist - datetime.timedelta(minutes=REMIND_MINUTES)
        # tiny safety: do not send if remind time is in future
        if now_ist < remind_dt:
            continue
        # if already past due, skip
        if now_ist >= due_dt_ist:
            continue

        # only send if Reminder Sent is false (prevents duplicates)
        if rem_sent:
            continue

        # send to each assignee that we have a chat id for
        for name in assignees:
            chat_id = ASSIGNEE_MAP.get(name)
            if not chat_id:
                print(f"No chat id for '{name}' — skipping send for page {page_id}")
                continue
            # build message (escape markdown lightly)
            title_safe = title.replace("_","\\_").replace("*","\\*")
            due_str = due_dt_ist.strftime("%Y-%m-%d %I:%M %p %Z")
            nid = ""
            # optional read of ID property if present:
            nid_prop = props.get(PROP_NID)
            if nid_prop:
                nid = get_text_from_rich(nid_prop)
            header = f"*Reminder:* {nid} {title_safe}\\n"
            body = f"{header}\\n⏰ *Due:* {due_str}\\nPlease mark completed after you finish."
            # notion page url for convenience (provided in page object 'url')
            notion_url = p.get("url")
            try:
                send_telegram_message(chat_id, body, notion_url=notion_url)
                sent_count += 1
            except Exception as e:
                print("Failed to send to", name, "error:", e)

        # after sending to all, mark Reminder Sent = True in Notion
        try:
            set_notion_reminder_sent(page_id)
        except Exception as e:
            print("Failed to set Reminder Sent on Notion page", page_id, "error:", e)

    print("Done. Reminders sent:", sent_count)

if __name__ == "__main__":
    run_once()