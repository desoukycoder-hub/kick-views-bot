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
CLIPS_ID = "1538678610653749350"
BOT_ID = "1538677588619296768"
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
    pricing = CFG.get("pricing") or {}
    price_lines = []
    for key, p in pricing.items():
        if isinstance(p, dict):
            label = p.get("label") or p.get("label_en") or p.get("name") or "Package"
            price_lines.append(f"• {label}")
        else:
            price_lines.append(f"• {p}")

    desc = (
        f"**أهلاً بيك في بوت مشاهدات كليبات كيك 🎉**\n\n"
        f"🚀 **ارفع مشاهدات كيك كليبتك بسرعة**\n\n"
        f"💰 **الأسعار:**\n" + ("\n".join(price_lines) if price_lines else "`لا توجد أسعار`") + "\n\n"
        f"📌 **ازاي تشتغل:**\n"
        f"1️⃣ اضغط **🚀 رفع مشاهدات كليبات** واختار العدد\n"
        f"2️⃣ ابعت لينك الكليب من kick.com\n"
        f"3️⃣ المحرك بيرفع المشاهدات تلقائياً ✅\n\n"
        f"👁️ **كل المشاهدات حقيقية** ✅\n"
        f"⚠️ **اللينك لازم يكون شكله:** `kick.com/username/clips/xxxxx`\n"
        f"\n**اختار من الأزرار:**"
    )

    return {
        "title": "🎯 بوت مشاهدات كليبات كيك",
        "description": desc,
        "color": 0x2ECC71,
        "footer": {"text": f"⚡ سرعة عالية | 🎯 دقة 100% | {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}"},
    }


def build_components():
    return [
        {
            "type": 1,
            "components": [
                {"type": 2, "style": 3, "label": "💰 رصيدي", "custom_id": "shop_balance_ar"},
                {"type": 2, "style": 1, "label": "🚀 رفع مشاهدات كليبات", "custom_id": "shop_boost_clips"},
            ],
        },
    ]


def main():
    if not TOKEN:
        print("NO TOKEN")
        return

    print(f"=== cleaning CLIPS #{CLIPS_ID} (bot messages) ===")
    delete_all_messages(CLIPS_ID, only_bot=True)

    print("=== posting TEST panel in CLIPS ===")
    code, res = req("POST", f"{API}/channels/{CLIPS_ID}/messages", {
        "embeds": [build_embed()],
        "components": build_components(),
    })
    print(f"POST -> {code}")
    if isinstance(res, dict) and res.get("id"):
        print(f"TEST PANEL SENT: message {res['id']}")


if __name__ == "__main__":
    main()
