import datetime
import json
import os
import sys
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(BASE_DIR, "config.json"), "r", encoding="utf-8") as f:
    CFG = json.load(f)

TOKEN = os.environ.get("KICK_BOT_TOKEN") or str(CFG.get("bot_token") or "")

GUILD_ID = "1538530169583575101"
BOT_ID = "1538677588619296768"
MARKET_ID = str(CFG.get("panel_channel_id") or "1538677300034408590")

API = "https://discord.com/api/v10"


def req(method, url, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    r = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bot {TOKEN}",
        "Content-Type": "application/json",
        "User-Agent": "ViewsBotPanel/1.0",
    })
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            raw = resp.read()
            try:
                return resp.status, json.loads(raw)
            except Exception:
                return resp.status, raw.decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        return e.code, raw


def delete_all_messages(channel_id, only_bot=False):
    after = None
    total = 0
    while True:
        url = f"{API}/channels/{channel_id}/messages"
        if after:
            url += f"?limit=100&before={after}"
        else:
            url += "?limit=100"
        code, msgs = req("GET", url)
        if code != 200 or not isinstance(msgs, list) or not msgs:
            break
        for m in msgs:
            if only_bot and str(m.get("author", {}).get("id")) != BOT_ID:
                continue
            mc = req("DELETE", f"{API}/channels/{channel_id}/messages/{m['id']}")
            print(f"  deleted: {m['id']} -> {mc[0]}")
            total += 1
        after = msgs[-1]["id"]
    print(f"deleted {total} messages")
    return total


def build_embed():
    welcome = str(CFG.get("welcome_text") or "أهلاً وسهلاً بيك في المتجر 🎉")

    code, channels = req("GET", f"{API}/guilds/{GUILD_ID}/channels")
    name_to_id = {c.get("name"): str(c.get("id")) for c in channels if isinstance(c, dict)} if code == 200 else {}
    channel_lines = []
    for name in (CFG.get("channels") or []):
        cid = name_to_id.get(name)
        channel_lines.append(f"• <#{cid}>" if cid else f"• `{name}`")

    price_lines = []
    pricing = CFG.get("pricing") or {}
    for p in pricing.values():
        if isinstance(p, dict):
            label = p.get("label") or p.get("label_en") or p.get("name") or "Package"
            value = p.get("credits_per_view")
            price_lines.append(f"• {label}" if value is None else f"• {label}")
        else:
            price_lines.append(f"• {p}")

    note = str(CFG.get("extra_note") or "")

    desc = (
        f"**{welcome}**\n\n"
        f"📌 **الشانيلز:**\n"
        f"{chr(10).join(channel_lines) if channel_lines else '`لا توجد شانيلز`'}\n\n"
        f"💰 **الأسعار:**\n"
        f"{chr(10).join(price_lines) if price_lines else '`لا توجد أسعار`'}\n\n"
        f"🛒 **ازاي تحصل على المشاهدات:**\n"
        f"1️⃣ اضغط **💳 طلب كريديتس** واختار المبلغ\n"
        f"2️⃣ الستاف هيوافق على طلبك وتتضاف الكريديتس لرصيدك\n"
        f"3️⃣ ابعت الرابط للمشرفين وهيرفعوا المشاهدات ✅\n\n"
        f"👁️ **كل المشاهدات حقيقية** ✅\n"
    )
    if note:
        desc += f"\n{note}\n"
    desc += "\n**اختار من الأزرار:**"

    return {
        "title": "🎯 بوت المشاهدات",
        "description": desc,
        "color": 0x2ECC71,
        "footer": {"text": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")},
    }


def build_components():
    return [
        {
            "type": 1,
            "components": [
                {"type": 2, "style": 1, "label": "💳 طلب كريديتس", "custom_id": "pv_credits"},
                {"type": 2, "style": 2, "label": "ℹ️ معلومات", "custom_id": "pv_info"},
                {"type": 2, "style": 3, "label": "💰 رصيدي", "custom_id": "pv_balance"},
            ],
        },
    ]


def main():
    if not TOKEN:
        print("NO TOKEN")
        return

    print(f"=== purging MARKET #{MARKET_ID} ===")
    delete_all_messages(MARKET_ID, only_bot=False)

    print("=== posting panel in MARKET ===")
    code, res = req("POST", f"{API}/channels/{MARKET_ID}/messages", {
        "embeds": [build_embed()],
        "components": build_components(),
    })
    print(f"POST MARKET -> {code}")
    if isinstance(res, dict) and res.get("id"):
        print(f"PANEL SENT to MARKET: message {res['id']}")


if __name__ == "__main__":
    main()