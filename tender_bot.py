"""
Tender Bot — watches xarid.uzex.uz auctions for robotics-related purchases
and sends alerts to Telegram.

Usage:
  python tender_bot.py --test        # send a test message to Telegram
  python tender_bot.py               # check once
  python tender_bot.py --loop 30     # check every 30 minutes (keep running)
  python tender_bot.py --dry-run     # check once, print matches, don't send
"""
import argparse
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

try:
    import truststore; truststore.inject_into_ssl()
except ImportError:
    pass
from playwright.sync_api import sync_playwright

# ---------------- SETTINGS ----------------
BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config.json"
SEEN_FILE = BASE_DIR / "seen_lots.json"
BASE_URL = "https://xarid.uzex.uz"
LIST_URL = BASE_URL + "/auction/list"
MAX_PAGES = 60  # safety limit (20 lots per page)

# Words that mean "robotics-related". Lowercase. Edit freely.
# (Generic words like "sensor" or "датчик" are left out: they match cameras,
#  gas meters, car batteries etc. and cause false alarms.)
KEYWORDS = [
    # Uzbek (latin + cyrillic) / Russian
    "robot", "робот", "robototexnika", "робототехник", "robotexnika",
    "mikrokontroller", "микроконтроллер", "mexatronika", "мехатрони",
    "квадрокоптер", "kvadrokopter", "беспилотн",
    "образовательный набор", "учебный набор", "o'quv to'plam", "o‘quv to‘plam",
    # Brands / boards
    "arduino", "ардуино", "raspberry", "lego", "лего", "mindstorms",
    "makeblock", "mbot", "esp32", "micro:bit", "microbit", "rev robotics",
    # Related equipment
    "3d printer", "3d-printer", "3d принтер", "3d-принтер", "3д принтер",
    "лазерный станок", "станок с чпу", "фрезерный станок",
]
# These must match as whole words only (so "конструктор" doesn't match
# "конструкторская документация").
WHOLE_WORDS = ["конструктор", "konstruktor", "stem", "steam", "vex",
               "spike", "dji", "tello", "дрон", "dron", "cnc", "чпу"]

# Only open lot details for these categories (saves time). Lowercase substrings.
# Set to [] to check every lot (slower).
CATEGORY_FILTER = [
    "компьютерн", "электронн", "оптическ", "оборудование электрическ",
    "машины и оборудование", "изделия готовые прочие", "игр",
    "образован", "обучен", "услуги", "приборы",
]

# Words that cause false alarms (e.g. "датчик" in water meters). Lowercase.
EXCLUDE = ["счетчик воды", "газовый счетчик", "датчик пожар"]
# ------------------------------------------


CHAT_ID_FILE = BASE_DIR / "chat_id.txt"


def load_config():
    cfg = {}
    if CONFIG_FILE.exists():
        cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    token = (os.getenv("TELEGRAM_TOKEN") or cfg.get("telegram_token", "")).strip()
    chat_id = (os.getenv("TELEGRAM_CHAT_ID") or str(cfg.get("chat_id", ""))).strip()
    if (not chat_id or chat_id.startswith("PASTE")) and CHAT_ID_FILE.exists():
        chat_id = CHAT_ID_FILE.read_text().strip()
    if token and (not chat_id or chat_id.startswith("PASTE")):
        chat_id = find_chat_id(token)
        if chat_id:
            CHAT_ID_FILE.write_text(chat_id)
            print("Found your chat ID:", chat_id)
    return token, chat_id


def find_chat_id(token):
    """Read the last message someone sent to the bot and use that chat."""
    try:
        with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/getUpdates", timeout=30) as r:
            data = json.loads(r.read())
    except Exception as e:
        print("Could not reach Telegram:", e)
        return ""
    for u in reversed(data.get("result", [])):
        chat = (u.get("message") or {}).get("chat") or {}
        if chat.get("id"):
            return str(chat["id"])
    print("No chat ID yet: open your bot in Telegram, press Start, then run again.")
    return ""


def send_telegram(token, chat_id, text):
    data = urllib.parse.urlencode({
        "chat_id": chat_id, "text": text, "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def load_seen():
    if SEEN_FILE.exists():
        return set(json.loads(SEEN_FILE.read_text(encoding="utf-8")))
    return set()


def save_seen(seen):
    SEEN_FILE.write_text(json.dumps(sorted(seen)), encoding="utf-8")


def parse_cards(page):
    """Read lot cards on the current list page."""
    return page.evaluate("""() => {
        const out = [];
        document.querySelectorAll('a[href^="/auction/detail/"]').forEach(a => {
            let card = a;
            for (let i = 0; i < 8 && card; i++) {
                card = card.parentElement;
                if (card && card.innerText.includes('Lot raqami')) break;
            }
            out.push({ href: a.getAttribute('href'), text: card ? card.innerText : '' });
        });
        return out;
    }""")


def field(text, label):
    m = re.search(re.escape(label) + r"\s*:?\s*\n?\s*([^\n]+)", text)
    return m.group(1).strip() if m else ""


def collect_lots(page):
    lots, seen_ids = [], set()
    page.goto(LIST_URL, wait_until="networkidle", timeout=90000)
    for _ in range(MAX_PAGES):
        page.wait_for_selector('a[href^="/auction/detail/"]', timeout=60000)
        cards = parse_cards(page)
        new_on_page = 0
        for c in cards:
            lot_id = c["href"].rstrip("/").split("/")[-1]
            if lot_id in seen_ids:
                continue
            seen_ids.add(lot_id)
            new_on_page += 1
            t = c["text"]
            lots.append({
                "id": lot_id,
                "url": BASE_URL + c["href"],
                "number": field(t, "Lot raqami"),
                "price": field(t, "Boshlang‘ich narx"),
                "category": field(t, "Toifa"),
                "deadline": field(t, "Tugash muddati"),
                "region": next((l for l in t.split("\n") if "област" in l or "город" in l or "Республика" in l), ""),
            })
        if new_on_page == 0:
            break
        # go to next page ("›" button)
        nxt = page.locator("a, button, li").filter(has_text=re.compile(r"^\s*›\s*$")).last
        try:
            parent_disabled = nxt.evaluate("e => (e.closest('li')||e).className.includes('disabled')")
        except Exception:
            break
        if parent_disabled:
            break
        first_before = cards[0]["href"] if cards else ""
        nxt.click()
        try:
            page.wait_for_function(
                "h => { const a = document.querySelector('a[href^=\"/auction/detail/\"]'); return a && a.getAttribute('href') !== h; }",
                arg=first_before, timeout=30000)
        except Exception:
            break
    return lots


def lot_details(page, url):
    page.goto(url, wait_until="domcontentloaded", timeout=90000)
    try:
        # wait until product rows are rendered
        page.wait_for_function(
            "() => /Tovar soni|Количество|Товар сони/.test(document.body.innerText)", timeout=30000)
    except Exception:
        pass
    return page.inner_text("main") if page.locator("main").count() else page.inner_text("body")


def find_keywords(text):
    low = text.lower()
    if any(x in low for x in EXCLUDE):
        return []
    hits = []
    for k in KEYWORDS:
        if k in low:
            hits.append(k)
    for k in WHOLE_WORDS:
        if re.search(r"(?<!\w)" + re.escape(k) + r"(?!\w)", low):
            hits.append(k)
    return hits


def product_lines(details):
    # product names look like "Веб-камера (26.30.30.000-00006)"
    names = re.findall(r"^\s*(.+?\(\d{2}\.\d{2}\.\d{2}\.\d{3}-\d{5}\))\s*$", details, re.M)
    return names[:6]


def format_alert(lot, hits, products):
    lines = ["🤖 <b>Robotics lot found</b> (Auksion)"]
    if products:
        lines.append("📦 " + html.escape("; ".join(products), quote=False)[:600])
    lines += [
        f"🏷 {html.escape(lot['category'], quote=False)}",
        f"💰 Start price: {html.escape(lot['price'], quote=False)}",
        f"📍 {html.escape(lot['region'], quote=False)}",
        f"⏰ Ends: {html.escape(lot['deadline'], quote=False)}",
        f"🔎 Matched: {html.escape(', '.join(hits[:5]), quote=False)}",
        f"🔗 <a href=\"{lot['url']}\">Lot {html.escape(lot['number'] or lot['id'], quote=False)}</a>",
    ]
    return "\n".join(lines)


def run_once(token, chat_id, dry_run=False):
    seen = load_seen()
    found = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(locale="uz-UZ")
        lots = collect_lots(page)
        new_lots = [l for l in lots if l["id"] not in seen]
        print(f"[{datetime.now():%H:%M}] {len(lots)} open lots, {len(new_lots)} new")
        for lot in new_lots:
            cat = lot["category"].lower()
            quick_hits = find_keywords(lot["category"])
            if CATEGORY_FILTER and not quick_hits and not any(c in cat for c in CATEGORY_FILTER):
                seen.add(lot["id"])
                continue
            checked = locals().get("checked", 0) + 1
            if checked % 10 == 0:
                print(f"  checked {checked} lots...", flush=True)
            try:
                details = lot_details(page, lot["url"])
            except Exception as e:
                print("  could not open", lot["url"], e)
                continue  # retry next time
            hits = find_keywords(details)
            if hits:
                found += 1
                msg = format_alert(lot, hits, product_lines(details))
                print("  MATCH:", lot["url"], hits)
                if not dry_run:
                    send_telegram(token, chat_id, msg)
                    time.sleep(1)
            seen.add(lot["id"])
            time.sleep(0.5)  # be polite to the website
        browser.close()
    if not dry_run:
        save_seen(seen)
    print(f"  done, {found} robotics lots")
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", type=int, default=0, help="repeat every N minutes")
    ap.add_argument("--test", action="store_true", help="send a test message")
    ap.add_argument("--dry-run", action="store_true", help="don't send, just print")
    a = ap.parse_args()

    token, chat_id = load_config()
    if not a.dry_run and (not token or not chat_id):
        sys.exit("Set telegram_token and chat_id in config.json first.")
    if a.test:
        send_telegram(token, chat_id, "✅ Tender bot is connected. I'll message you about robotics lots.")
        print("Test message sent.")
        return

    while True:
        try:
            run_once(token, chat_id, a.dry_run)
        except Exception as e:
            print("Error:", e)
            if token and chat_id and not a.dry_run:
                try:
                    send_telegram(token, chat_id, f"⚠️ Tender bot error: {html.escape(str(e), quote=False)[:300]}")
                except Exception:
                    pass
        if not a.loop:
            break
        time.sleep(a.loop * 60)


if __name__ == "__main__":
    main()
