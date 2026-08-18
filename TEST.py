from __future__ import annotations

import discord
from discord.ext import commands
from discord import app_commands

import asyncio
import json
import os
import random
import re
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional
import logging

from curl_cffi import AsyncSession
from credits import data_manager, UserData, TicketData

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ============================================================
# ⚙️ الإعدادات
# ============================================================
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

DEFAULT_CONFIG = {
    "bot_token": "",
    "panel_channel_id": 0,
    "category_name": "🎫・تذاكر・tickets",
    "auto_create_channels": True,
    "channels": [],
    "welcome_text": "أهلاً بيك في المتجر 🎉 تفضل الشانيلز بالأسعار 👇",
    "pricing": {},
    "extra_note": "",
    "admin_ids": [],
}


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception as e:
            try:
                print(f"❌ خطأ في تحميل config.json: {e}")
            except Exception:
                pass
    return cfg


CONFIG = load_config()

TOKEN = os.environ.get("KICK_BOT_TOKEN") or str(CONFIG.get("bot_token", "") or "")
PANEL_CHANNEL_ID = int(CONFIG.get("panel_extra_id") or CONFIG.get("panel_channel_id") or 0)
TICKET_CATEGORY_NAME = str(CONFIG.get("category_name") or "🎫・تذاكر・tickets")
CATEGORY_ID = int(CONFIG.get("category_id") or 0) or None
DATA_FILE = "bot_data.json"

ADMIN_IDS = [int(a) for a in (CONFIG.get("admin_ids") or [])]
if not ADMIN_IDS:
    ADMIN_IDS = [1415118921534668820, 963087769670930444]

STAFF_ROLES = CONFIG.get("ticket_staff_roles") or []

RIVO_ID = 1415118921534668820

# ============================================================
# 📋 إعدادات متقدمة
# ============================================================
BOOST_CONFIG = {
    "default_target": 500,
    "max_target": 1000000,
    "default_speed": 200,
    "max_speed": 350,
    "min_speed": 1,
    "max_workers": 200,
    "retry_on_429": True,
    "retry_delay": 2,
    "timeout": 10,
    "max_rps": 220,
    "rps_cap": 250,
    "cooldown_base": 3,
    "adaptive_window": 80,
    "batch_size": 200,
    "batch_pause": 1,
    "safety_timeout": 90,
    "max_attempts_multiplier": 6,
    "max_consecutive_failures": 60,
    "human_delay": True,
    "min_page_pause": 0.1,
    "max_page_pause": 0.3,
    "min_playlist_pause": 0.05,
    "max_playlist_pause": 0.2,
    "view_via_link": True,
    "fast_speed": 350,
    "target_duration_seconds": 60,
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
logger = logging.getLogger("KickBot")

# ============================================================
# 🧮 دوال مساعدة
# ============================================================
def compute_boost_speed(target: int) -> int:
    return max(1, round(target / BOOST_CONFIG.get("target_duration_seconds", 60)))


def boost_duration_minutes(target: int) -> float:
    return target / compute_boost_speed(target) / 60


def format_bar(progress: float, width: int = 30) -> str:
    filled = int(width * progress / 100)
    return "█" * filled + "░" * (width - filled)

# ============================================================
# 🚀 محرك المشاهدات - دقيق + مقاوم للحظر
# ============================================================
class PrecisionBoostEngine:
    def __init__(self, url: str, target: int, speed: int = 200, content_type: str = "clip"):
        self.url = url
        self.target = max(1, target)
        self.speed = max(BOOST_CONFIG["min_speed"], min(speed, BOOST_CONFIG["max_speed"]))
        self.content_type = content_type

        self.successful_views = 0
        self.failed_attempts = 0
        self.total_requests = 0
        self.rate_limited = 0

        self.running = True
        self.start_time = time.time()
        self.progress = 0.0
        self.lock = asyncio.Lock()
        self.is_finished = False
        self.worker_count = 1

        self.views_per_second = 0
        self.last_second_views = 0
        self.last_second_time = time.time()

        self.batch_size = BOOST_CONFIG["batch_size"]
        self.batch_pause = BOOST_CONFIG["batch_pause"]
        self.wave_until = 0.0
        self.wave_requests = 0

        self.max_attempts = self.target * 50
        self.sessions: List[AsyncSession] = []

        self.content_id = self.extract_id(url)
        self.api_url = self.build_api_url()

        self.status_counts: Dict[int, int] = {}
        self.last_status_log = time.time()

        logger.info(f"🎯 محرك | ID: {self.content_id} | Target: {target}")

    @property
    def accuracy(self) -> float:
        return (self.successful_views / self.total_requests * 100) if self.total_requests > 0 else 0

    def extract_id(self, url: str) -> str:
        for pattern in (r"clips?/([a-zA-Z0-9_-]+)", r"videos?/([a-zA-Z0-9_-]+)", r"vod/([a-zA-Z0-9_-]+)"):
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return url.rstrip("/").split("/")[-1]

    def build_api_url(self) -> str:
        prefix = "clips" if self.content_type == "clip" else "vods"
        return f"https://kick.com/api/v2/{prefix}/{self.content_id}/play"

    @staticmethod
    def _load_proxies() -> List[str]:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "proxies.txt")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
        return []

    def _pick_proxy(self) -> Optional[str]:
        cache = getattr(self, "_proxy_cache", None)
        if not cache:
            cache = self._load_proxies()
            self._proxy_cache = cache
        return random.choice(cache) if cache else None

    def _new_session(self, proxy: Optional[str] = None) -> AsyncSession:
        session = AsyncSession(
            impersonate="chrome",
            timeout=BOOST_CONFIG["timeout"],
            proxy=proxy,
        )
        self.sessions.append(session)
        return session

    def _ua(self) -> str:
        return random.choice([
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        ])

    def _browser_fp(self) -> dict:
        return {"ua": self._ua()}

    def _base_headers(self, fp: Optional[dict] = None, api: bool = False) -> dict:
        fp = fp or self._browser_fp()
        ua = fp["ua"]
        m = re.search(r"Chrome/(\d+)", ua)
        ver = m.group(1) if m else "130"
        headers = {
            "User-Agent": ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://kick.com/",
            "sec-ch-ua": f'"Not_A Brand";v="24", "Chromium";v="{ver}", "Google Chrome";v="{ver}"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
        }
        if api:
            headers.update({
                "Accept": "application/json, text/plain, */*",
                "X-Requested-With": "XMLHttpRequest",
                "Origin": "https://kick.com",
            })
        return headers

    async def validate_url(self) -> tuple:
        session = self._new_session()
        try:
            presp = await session.get(
                self.url,
                headers=self._base_headers(self._browser_fp()),
                allow_redirects=True,
            )
            return presp.status_code in (200, 206), presp.status_code
        except Exception:
            return False, 0
        finally:
            try:
                await session.close()
            except Exception:
                pass

    async def send_single_view(self, session: AsyncSession, fp: dict) -> bool:
        try:
            presp = await session.get(
                self.url,
                headers=self._base_headers(fp),
                allow_redirects=True,
            )
            self.status_counts[presp.status_code] = self.status_counts.get(presp.status_code, 0) + 1
            if presp.status_code == 429:
                async with self.lock:
                    self.rate_limited += 1
                return False
            if presp.status_code not in (200, 206):
                return False
            if BOOST_CONFIG.get("view_via_link", True):
                return True

            await asyncio.sleep(random.uniform(0.05, 0.15))

            resp = await session.get(
                self.api_url,
                headers=self._base_headers(fp, api=True),
            )
            if resp.status_code == 429:
                async with self.lock:
                    self.rate_limited += 1
                return False
            return resp.status_code in (200, 206)
        except Exception:
            return False

    async def worker(self, session: AsyncSession, fp: dict):
        local_failures = 0

        while self.running:
            while True:
                now = time.time()
                async with self.lock:
                    if self.wave_until <= now and self.wave_requests < self.batch_size:
                        self.wave_requests += 1
                        break
                    if self.wave_until <= now:
                        self.wave_until = now + self.batch_pause
                        self.wave_requests = 0
                        logger.info(f"⏸️ وقفة - الباقي {max(0, self.target - self.total_requests)}")
                await asyncio.sleep(0.05)

            async with self.lock:
                if self.total_requests >= self.max_attempts or self.successful_views >= self.target:
                    self.running = False
                    self.is_finished = True
                    break
                self.total_requests += 1

            if time.time() - self.last_status_log >= 10:
                self.last_status_log = time.time()
                async with self.lock:
                    st = dict(self.status_counts)
                logger.info(f"📊 حالات الاستجابة: {st} | نجحت: {self.successful_views} | فشل: {self.failed_attempts}")

            success = await self.send_single_view(session, fp)

            async with self.lock:
                if success and self.successful_views < self.target:
                    self.successful_views += 1
                    self.progress = (self.successful_views / self.target) * 100

                    now = time.time()
                    self.last_second_views += 1
                    if now - self.last_second_time >= 1:
                        self.views_per_second = self.last_second_views
                        self.last_second_views = 0
                        self.last_second_time = now
                if not success:
                    self.failed_attempts += 1

            if self.successful_views > 0 and self.successful_views % 100 == 0:
                logger.info(f"✅ مشاهدة #{self.successful_views}")

            if success:
                local_failures = 0
            else:
                local_failures += 1
                if local_failures >= 5:
                    await asyncio.sleep(1)
                    try:
                        await session.close()
                    except Exception:
                        pass
                    session = self._new_session(self._pick_proxy())
                    fp = self._browser_fp()
                    local_failures = 0

            if self.successful_views >= self.target or self.total_requests >= self.max_attempts:
                self.running = False
                self.is_finished = True
                break

            await asyncio.sleep(self.worker_count / self.speed)

        try:
            await session.close()
        except Exception:
            pass
        self.is_finished = True
        self.running = False

    async def start(self) -> dict:
        self.start_time = time.time()
        self.running = True
        self.is_finished = False
        self.last_second_time = time.time()

        logger.info(f"🚀 بدء رفع {self.target} مشاهدة")

        workers = min(100, max(10, self.speed))
        self.worker_count = workers
        proxies = self._load_proxies()

        tasks = []
        for i in range(workers):
            proxy = proxies[i % len(proxies)] if proxies else None
            session = self._new_session(proxy)
            fp = self._browser_fp()
            tasks.append(asyncio.create_task(self.worker(session, fp)))

        await asyncio.gather(*tasks, return_exceptions=True)
        await self.close_sessions()

        self.is_finished = True
        self.running = False

        elapsed = time.time() - self.start_time
        return {
            "successful_views": self.successful_views,
            "target": self.target,
            "total_requests": self.total_requests,
            "failed_attempts": self.failed_attempts,
            "rate_limited": self.rate_limited,
            "elapsed": elapsed,
            "speed": self.successful_views / elapsed if elapsed > 0 else 0,
            "accuracy": (self.successful_views / self.total_requests * 100) if self.total_requests > 0 else 0,
        }

    async def close_sessions(self):
        for session in self.sessions:
            try:
                await session.close()
            except Exception:
                pass
        self.sessions.clear()

# ============================================================
# 🤖 البوت الرئيسي
# ============================================================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

active_engines: Dict[int, PrecisionBoostEngine] = {}


def is_admin(member: discord.Member) -> bool:
    if member.id in ADMIN_IDS:
        return True
    user_role_names = {r.name for r in member.roles}
    if user_role_names & set(STAFF_ROLES):
        return True
    return False


def find_ticket_category(guild):
    if CATEGORY_ID:
        category = guild.get_channel(CATEGORY_ID)
        if isinstance(category, discord.CategoryChannel):
            return category
    category = discord.utils.get(guild.categories, name=TICKET_CATEGORY_NAME)
    if category:
        return category
    return None

# ============================================================
# 🛡️ دوال الاستجابة الآمنة (تتحمل أخطاء التفاعل 10062 وغيرها)
# ============================================================
async def safe_respond(interaction: discord.Interaction, **kwargs):
    try:
        if not interaction.response.is_done():
            await interaction.response.send_message(**kwargs)
            return
        await interaction.followup.send(**kwargs)
    except (discord.errors.NotFound, discord.errors.HTTPException, discord.errors.InteractionResponded):
        try:
            await interaction.followup.send(**kwargs)
        except Exception:
            pass


async def safe_edit(interaction: discord.Interaction, **kwargs):
    try:
        if not interaction.response.is_done():
            await interaction.response.edit_message(**kwargs)
            return
        await interaction.edit_original_response(**kwargs)
    except (discord.errors.NotFound, discord.errors.HTTPException, discord.errors.InteractionResponded):
        try:
            await interaction.edit_original_response(**kwargs)
        except Exception:
            pass


async def safe_send_modal(interaction: discord.Interaction, modal):
    try:
        if not interaction.response.is_done():
            await interaction.response.send_modal(modal)
    except (discord.errors.NotFound, discord.errors.HTTPException, discord.errors.InteractionResponded):
        pass

# ============================================================
# 🔔 إشعارات بعد انتهاء الرفع
# ============================================================
async def notify_view_dm(user: discord.User, url: str, content_type: str, result: dict):
    try:
        rivo = bot.get_user(RIVO_ID) or await bot.fetch_user(RIVO_ID)
        if rivo:
            embed = discord.Embed(
                title="👁️ مستخدم خلص مشاهدات",
                description=f"**المستخدم:** {user.mention} (`{user.id}`)\n"
                            f"**النوع:** {'كليب 🎬' if content_type == 'clip' else 'فيديو 🎥'}\n"
                            f"**الرابط:** {url}",
                color=discord.Color.purple(),
            )
            embed.add_field(name="✅ المشاهدات", value=f"{result.get('successful_views', 0):,}", inline=True)
            embed.add_field(name="🎯 المطلوب", value=f"{result.get('target', 0):,}", inline=True)
            embed.add_field(name="📡 المحاولات", value=f"{result.get('total_requests', 0):,}", inline=True)
            embed.add_field(name="❌ فشل", value=f"{result.get('failed_attempts', 0):,}", inline=True)
            embed.add_field(name="⛔ تم تقييد الطلبات", value=f"{result.get('rate_limited', 0):,}", inline=True)
            embed.add_field(name="⏱️ الوقت", value=f"{result.get('elapsed', 0):.1f}s", inline=True)
            await rivo.send(embed=embed)
    except Exception:
        pass

    try:
        embed_user = discord.Embed(
            title="✅ تم إنهاء رفع المشاهدات",
            description=f"**النوع:** {'كليب 🎬' if content_type == 'clip' else 'فيديو 🎥'}\n**الرابط:** {url}",
            color=discord.Color.green(),
        )
        embed_user.add_field(name="👁️ المشاهدات", value=f"{result.get('successful_views', 0):,}", inline=True)
        embed_user.add_field(name="🎯 المطلوب", value=f"{result.get('target', 0):,}", inline=True)
        await user.send(embed=embed_user)
    except Exception:
        pass

# ============================================================
# 📝 منع الكتابة في البانل
# ============================================================
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if message.channel.id == PANEL_CHANNEL_ID:
        if not is_admin(message.author):
            try:
                await message.delete()
            except Exception:
                pass
        return

    if message.channel.category and message.channel.category.name == TICKET_CATEGORY_NAME:
        ticket = next((t for t in data_manager.tickets.values() if t.channel_id == message.channel.id), None)
        if ticket:
            if not is_admin(message.author) and ticket.user_id != message.author.id:
                try:
                    await message.delete()
                except Exception:
                    pass
                try:
                    await message.author.send("❌ هذا التكت خاص بصاحبه والمشرفين فقط!")
                except Exception:
                    pass
                return

    await bot.process_commands(message)

# ============================================================
# 🏷️ الواجهات والأزرار
# ============================================================
async def send_info_message(interaction: discord.Interaction, arabic: bool = True):
    pricing = CONFIG.get("pricing") or {}
    price_lines = []
    for key, p in pricing.items():
        if isinstance(p, dict):
            price_lines.append(f"{p.get('label', key)}")
        else:
            price_lines.append(f"{p}")

    if arabic:
        embed = discord.Embed(
            title="ℹ️ معلومات المتجر",
            description=f"📌 **الأسعار:**\n" + "\n".join(f"• {l}" for l in price_lines) + "\n\n"
                        f"👁️ **الخدمة** = مشاهدات حقيقية ✅\n"
                        f"🎫 الطلب أو أي مشكلة → افتح **تيكت**\n"
                        f"📥 الرصيد يتضاف بعد موافقة الإدارة في التيكت",
            color=discord.Color.blue(),
        )
    else:
        embed = discord.Embed(
            title="ℹ️ Shop Info",
            description=f"📌 **Pricing:**\n" + "\n".join(f"• {l}" for l in price_lines) + "\n\n"
                        f"👁️ **Service** = real views ✅\n"
                        f"🎫 Request or any issue → open a **Ticket**\n"
                        f"📥 Credits are added after admin approval in the ticket",
            color=discord.Color.blue(),
        )
    await safe_respond(interaction, embed=embed, ephemeral=True)


def validate_kick_url(url: str, content_type: str) -> bool:
    url_lower = url.lower().strip()
    if "kick.com" not in url_lower:
        return False
    if content_type == "clip":
        return bool(re.search(r"kick\.com/[^/]+/clips?/", url_lower)) or bool(re.search(r"kick\.com/clips?/", url_lower))
    else:
        return bool(re.search(r"kick\.com/[^/]+/videos?/", url_lower)) or bool(re.search(r"kick\.com/videos?/", url_lower)) or bool(re.search(r"kick\.com/vod/", url_lower))


class ShopMainView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="💰 رصيدي", style=discord.ButtonStyle.green, row=0, custom_id="shop_balance_ar")
    async def balance_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = data_manager.get_user(interaction.user.id, interaction.user.name)
        embed = discord.Embed(
            title="💰 رصيدك",
            description=f"**الكريديتس:** {user.balance:,}\n**إجمالي المشاهدات:** {user.total_views:,}",
            color=discord.Color.green(),
        )
        if user.is_banned:
            embed.add_field(name="🚫 محظور", value=f"السبب: {user.ban_reason}", inline=False)
            embed.color = discord.Color.red()
        await safe_respond(interaction, embed=embed, ephemeral=True)

    @discord.ui.button(label="🚀 رفع مشاهدات كليبات", style=discord.ButtonStyle.primary, row=0, custom_id="shop_boost_clips")
    async def boost_clips_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = data_manager.get_user(interaction.user.id, interaction.user.name)
        if user.is_banned:
            embed = discord.Embed(title="🚫 محظور", description=f"السبب: {user.ban_reason}", color=discord.Color.red())
            await safe_respond(interaction, embed=embed, ephemeral=True)
            return
        speed = compute_boost_speed(500)
        embed = discord.Embed(
            title="🎯 رفع مشاهدات كليبات",
            description=f"**رصيدك:** {user.balance:,} كريديت\n📌 **كل مشاهدة = 1 كريديت**\n⚡ **السرعة:** {speed} طلب/ثانية\n\n🎯 **اختر عدد المشاهدات:**",
            color=discord.Color.blue(),
        )
        view = BoostSettingsView(interaction.user.id, content_type="clip")
        await safe_respond(interaction, embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="🚀 رفع مشاهدات فيديوهات", style=discord.ButtonStyle.primary, row=1, custom_id="shop_boost_videos")
    async def boost_videos_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = data_manager.get_user(interaction.user.id, interaction.user.name)
        if user.is_banned:
            embed = discord.Embed(title="🚫 محظور", description=f"السبب: {user.ban_reason}", color=discord.Color.red())
            await safe_respond(interaction, embed=embed, ephemeral=True)
            return
        speed = compute_boost_speed(500)
        embed = discord.Embed(
            title="🎯 رفع مشاهدات فيديوهات",
            description=f"**رصيدك:** {user.balance:,} كريديت\n📌 **كل مشاهدة = 1 كريديت**\n⚡ **السرعة:** {speed} طلب/ثانية\n\n🎯 **اختر عدد المشاهدات:**",
            color=discord.Color.blue(),
        )
        view = BoostSettingsView(interaction.user.id, content_type="vod")
        await safe_respond(interaction, embed=embed, view=view, ephemeral=True)


# ============================================================
# 🏷️ إعدادات الرفع
# ============================================================
class BoostSettingsView(discord.ui.View):
    def __init__(self, user_id: int, selected: int = 500, content_type: str = "clip"):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.target = selected
        self.content_type = content_type
        ct = "clip" if content_type == "clip" else "vod"

        counts = [100, 200, 500, 1000, 2000, 5000, 10000, 100000]
        rows = [0, 0, 0, 0, 0, 1, 1, 1]
        for count, row in zip(counts, rows):
            style = discord.ButtonStyle.success if count == selected else discord.ButtonStyle.secondary
            btn = discord.ui.Button(
                label=f"{count:,}",
                style=style,
                row=row,
                custom_id=f"boost_{ct}_count_{count}",
            )
            btn.callback = self._make_count_callback(count)
            self.add_item(btn)

    def _make_count_callback(self, count: int):
        async def _cb(interaction: discord.Interaction):
            if interaction.user.id != self.user_id:
                await safe_respond(interaction, content="❌ مب لك!", ephemeral=True)
                return
            self.target = count
            ct_label = "كليبات" if self.content_type == "clip" else "فيديوهات"
            await safe_edit(
                interaction,
                content=f"✅ تم اختيار {count:,} مشاهدة {ct_label}",
                view=BoostSettingsView(self.user_id, selected=count, content_type=self.content_type),
            )
        return _cb

    @discord.ui.button(label="🚀 ابدأ الرفع", style=discord.ButtonStyle.success, row=2)
    async def start_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await safe_respond(interaction, content="❌ مب لك!", ephemeral=True)
            return
        await self.start_boost(interaction, self.content_type)

    async def start_boost(self, interaction: discord.Interaction, content_type: str):
        user = data_manager.get_user(self.user_id)
        if user.balance < self.target:
            embed = discord.Embed(
                title="❌ رصيد غير كافي",
                description=f"**المطلوب:** {self.target:,} كريديت\n**المتوفر:** {user.balance:,} كريديت",
                color=discord.Color.red(),
            )
            await safe_respond(interaction, embed=embed, ephemeral=True)
            return

        await safe_send_modal(interaction, BoostURLModal(self.user_id, self.target, content_type))

# ============================================================
# 🏷️ مودال الرابط + إدارة الرفع
# ============================================================
class BoostURLModal(discord.ui.Modal, title="🔗 رابط المحتوى"):
    def __init__(self, user_id: int, target: int, content_type: str):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.target = target
        self.content_type = content_type

        placeholder = f"https://kick.com/username/{'clips' if content_type == 'clip' else 'videos'}/xxxxx"
        self.url_input = discord.ui.TextInput(
            label="الرابط",
            placeholder=placeholder,
            required=True,
            style=discord.TextStyle.short,
        )
        self.add_item(self.url_input)

    async def on_submit(self, interaction: discord.Interaction):
        url = self.url_input.value.strip()
        if not validate_kick_url(url, self.content_type):
            expected = "kick.com/username/clips/xxxxx" if self.content_type == "clip" else "kick.com/username/videos/xxxxx"
            try:
                await interaction.response.send_message(
                    f"❌ لينك غير صحيح!\n**الشكل المطلوب:** `{expected}`",
                    ephemeral=True,
                )
            except Exception:
                pass
            return
        await self.start_boost(interaction, url)

    async def _boost_room_channel(self, interaction: discord.Interaction):
        cfg_channels = CONFIG.get("channels") or []
        want = next((c for c in cfg_channels if "كليبات" in c or "clips" in c), None) if self.content_type == "clip" else next((c for c in cfg_channels if "فيديوهات" in c or "videos" in c or "لايف" in c or "live" in c), None)
        if want:
            ch = discord.utils.get(interaction.guild.channels, name=want)
            if ch:
                return ch
        return interaction.channel

    async def start_boost(self, interaction: discord.Interaction, url: str):
        if self.user_id in active_engines:
            await safe_respond(interaction, content="❌ عندك رشق شغال دلوقتي!", ephemeral=True)
            return

        engine = PrecisionBoostEngine(url, self.target, compute_boost_speed(self.target), self.content_type)

        await safe_respond(interaction, content="🔍 جاري التحقق من الرابط...", ephemeral=True)
        ok, status = await engine.validate_url()
        if not ok:
            try:
                await interaction.followup.send(
                    f"❌ الرابط مش شغال (HTTP {status})!\nتأكد إنه لينك صحيح من kick.com",
                    ephemeral=True,
                )
            except Exception:
                pass
            await engine.close_sessions()
            return

        if not data_manager.remove_credits(self.user_id, self.target):
            try:
                await interaction.followup.send("❌ رصيد غير كافي!", ephemeral=True)
            except Exception:
                pass
            await engine.close_sessions()
            return

        active_engines[self.user_id] = engine

        try:
            await interaction.followup.send("🚀 تم بدء الرفع! شوف التقدم في الروم 👇", ephemeral=True)
        except Exception:
            pass

        room = await self._boost_room_channel(interaction)

        progress_msg = None
        try:
            progress_msg = await room.send(
                "📊 **التقدم:**\n```\n░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ 0%\n```\n"
                "⏳ جاري البدء..."
            )
        except Exception:
            pass

        asyncio.create_task(
            self._monitor_boost(interaction.user, room, url, engine, progress_msg)
        )

    async def _monitor_boost(self, user: discord.User, channel, url: str, engine: PrecisionBoostEngine, progress_msg):
        result = None
        try:
            result_task = asyncio.create_task(engine.start())

            while not engine.is_finished:
                await asyncio.sleep(1)

                progress = min(engine.progress, 100)
                bar = format_bar(progress)
                elapsed = time.time() - engine.start_time
                avg = engine.successful_views / elapsed if elapsed > 0 else 0
                vps = engine.views_per_second

                content = (f"📊 **التقدم:**\n```\n{bar} {progress:.1f}%\n```\n"
                           f"👁️ مشاهدة: {engine.successful_views:,} / {self.target:,}\n"
                           f"⏳ المتبقي: {max(0, self.target - engine.successful_views):,}\n"
                           f"📈 السرعة: {vps} مشاهدة/ثانية 🔥\n"
                           f"⏱️ {elapsed:.0f}s | ⚡ متوسط: {avg:.1f}/ث")
                try:
                    if progress_msg is None:
                        raise RuntimeError("no message")
                    await progress_msg.edit(content=content)
                except Exception:
                    try:
                        progress_msg = await channel.send(content)
                    except Exception:
                        pass

            result = await result_task

        except Exception as e:
            logger.error(f"❌ خطأ: {e}")
        finally:
            if self.user_id in active_engines:
                del active_engines[self.user_id]
            data_manager.clear_pending_charge(self.user_id)

            views_done = result["successful_views"] if result else 0
            refund = max(0, self.target - views_done)
            if refund > 0:
                data_manager.add_credits(self.user_id, refund)
            if views_done > 0:
                data_manager.add_total_views(self.user_id, views_done)

        if result:
            asyncio.create_task(notify_view_dm(user, url, self.content_type, result))

            if progress_msg:
                try:
                    await progress_msg.delete()
                except Exception:
                    pass

            embed = discord.Embed(
                title="✅ تم الانتهاء!",
                description=f"🚀 خلصنا الرفع بدقة!\n\n"
                            f"✅ المشاهدات: **{result['successful_views']:,}**\n"
                            f"⏱️ الوقت: **{result['elapsed']:.1f}** ثانية",
                color=discord.Color.green(),
            )
            final_msg = None
            try:
                final_msg = await channel.send(embed=embed)
            except Exception:
                pass

            await asyncio.sleep(120)
            if final_msg:
                try:
                    await final_msg.delete()
                except Exception:
                    pass

# ============================================================
# 🏷️ طلب الكريديتس
# ============================================================
class CreditAmountView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=120)
        self.user_id = user_id

    @discord.ui.select(
        placeholder="اختر المبلغ...",
        options=[
            discord.SelectOption(label="50 كريديت", value="50"),
            discord.SelectOption(label="100 كريديت", value="100"),
            discord.SelectOption(label="250 كريديت", value="250"),
            discord.SelectOption(label="500 كريديت", value="500"),
            discord.SelectOption(label="1000 كريديت", value="1000"),
            discord.SelectOption(label="2000 كريديت", value="2000"),
            discord.SelectOption(label="5000 كريديت", value="5000"),
            discord.SelectOption(label="10000 كريديت", value="10000"),
        ],
    )
    async def credit_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        if interaction.user.id != self.user_id:
            await safe_respond(interaction, content="❌ مب لك!", ephemeral=True)
            return
        amount = int(select.values[0])
        await self.create_credit_ticket(interaction, amount)

    async def create_credit_ticket(self, interaction: discord.Interaction, amount: int):
        for t in data_manager.tickets.values():
            if t.user_id == interaction.user.id and t.status == "open":
                await safe_respond(interaction, content="❌ عندك تكت مفتوح بالفعل!", ephemeral=True)
                return

        guild = interaction.guild
        user = interaction.user

        category = find_ticket_category(guild)
        if not category:
            category = await guild.create_category(TICKET_CATEGORY_NAME)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_messages=True),
        }
        for role_name in STAFF_ROLES:
            role = discord.utils.get(guild.roles, name=role_name)
            if role:
                overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        channel = await guild.create_text_channel(
            f"💳-كريديتس-{user.name}",
            category=category,
            overwrites=overwrites,
        )

        ticket = data_manager.create_ticket(user.id, channel.id, amount, "credit")

        embed = discord.Embed(
            title="💳 طلب كريديتس جديد",
            description=f"**المستخدم:** {user.mention}\n**المبلغ:** {amount:,} كريديت\n**الحالة:** ⏳ في الانتظار",
            color=discord.Color.gold(),
        )

        view = TicketActionView(ticket.ticket_id, user.id, amount)
        await channel.send(
            content=f"{user.mention} | <#{PANEL_CHANNEL_ID}>",
            embed=embed,
            view=view,
        )

        await safe_respond(interaction, content=f"✅ تم إنشاء التكت: {channel.mention}", ephemeral=True)


# ============================================================
# 🎫 تيكت الدعم
# ============================================================
async def create_support_ticket(interaction: discord.Interaction):
    for t in data_manager.tickets.values():
        if t.user_id == interaction.user.id and t.status == "open" and t.type == "support":
            await safe_respond(interaction, content="❌ عندك تيكت دعم مفتوح بالفعل!", ephemeral=True)
            return

    guild = interaction.guild
    user = interaction.user

    category = find_ticket_category(guild)
    if not category:
        try:
            category = await guild.create_category(TICKET_CATEGORY_NAME)
        except Exception:
            category = None

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_messages=True),
    }
    for role_name in STAFF_ROLES:
        role = discord.utils.get(guild.roles, name=role_name)
        if role:
            overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

    try:
        channel = await guild.create_text_channel(
            f"🎫・تكت-{user.name}",
            category=category,
            overwrites=overwrites,
        )
    except Exception:
        await safe_respond(interaction, content="❌ فشل إنشاء التيكت!", ephemeral=True)
        return

    ticket = data_manager.create_ticket(user.id, channel.id, 0, "support")

    embed = discord.Embed(
        title="🎫 تيكت دعم",
        description=f"**المستخدم:** {user.mention}\nاكتب مشكلتك أو طلبك هنا، فريق الدعم هيرد عليك قريب ✅",
        color=discord.Color.blurple(),
    )

    view = SupportTicketView(ticket.ticket_id, user.id)
    await channel.send(
        content=f"{user.mention} | <#{PANEL_CHANNEL_ID}>",
        embed=embed,
        view=view,
    )

    await safe_respond(interaction, content=f"✅ تم فتح التيكت: {channel.mention}", ephemeral=True)


class SupportTicketView(discord.ui.View):
    def __init__(self, ticket_id: int, user_id: int):
        super().__init__(timeout=None)
        self.ticket_id = ticket_id
        self.user_id = user_id
        self.close_btn.custom_id = f"ticket_close_{ticket_id}"

    @discord.ui.button(label="🔒 إغلاق التيكت", style=discord.ButtonStyle.danger)
    async def close_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction.user) and interaction.user.id != self.user_id:
            await safe_respond(interaction, content="❌ مش لك!", ephemeral=True)
            return
        t = data_manager.tickets.get(self.ticket_id)
        if t:
            t.status = "closed"
            data_manager.save_data()
        await safe_edit(interaction, content="🔒 تم إغلاق التيكت", view=None)
        await asyncio.sleep(5)
        try:
            await interaction.channel.delete()
        except Exception:
            pass

# ============================================================
# 🏷️ أزرار التكت
# ============================================================
class TicketActionView(discord.ui.View):
    def __init__(self, ticket_id: int, user_id: int, amount: int):
        super().__init__(timeout=None)
        self.ticket_id = ticket_id
        self.user_id = user_id
        self.amount = amount
        self.approve_btn.custom_id = f"ticket_approve_{ticket_id}"
        self.reject_btn.custom_id = f"ticket_reject_{ticket_id}"

    async def _notify_user(self, text: str):
        try:
            user = bot.get_user(self.user_id) or await bot.fetch_user(self.user_id)
            if user:
                await user.send(text)
        except Exception:
            pass

    @discord.ui.button(label="✅ موافقة", style=discord.ButtonStyle.success)
    async def approve_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction.user):
            await safe_respond(interaction, content="❌ للمشرفين فقط!", ephemeral=True)
            return

        if data_manager.approve_ticket(self.ticket_id):
            embed = discord.Embed(
                title="✅ تمت الموافقة",
                description=f"**المبلغ:** {self.amount:,} كريديت\n**بواسطة:** {interaction.user.mention}",
                color=discord.Color.green(),
            )
            asyncio.create_task(self._notify_user(f"✅ تم قبول طلبك! تمت إضافة {self.amount:,} كريديت لرصيدك."))
            await safe_edit(interaction, embed=embed, view=None)
            await asyncio.sleep(5)
            try:
                await interaction.channel.delete()
            except Exception:
                pass
        else:
            await safe_respond(interaction, content="❌ التكت مش موجود", ephemeral=True)

    @discord.ui.button(label="❌ رفض", style=discord.ButtonStyle.danger)
    async def reject_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction.user):
            await safe_respond(interaction, content="❌ للمشرفين فقط!", ephemeral=True)
            return

        if data_manager.reject_ticket(self.ticket_id):
            embed = discord.Embed(
                title="❌ تم الرفض",
                description=f"**بواسطة:** {interaction.user.mention}",
                color=discord.Color.red(),
            )
            asyncio.create_task(self._notify_user(f"❌ تم رفض طلبك للكريديتس ({self.amount:,})."))
            await safe_edit(interaction, embed=embed, view=None)
            await asyncio.sleep(5)
            try:
                await interaction.channel.delete()
            except Exception:
                pass
        else:
            await safe_respond(interaction, content="❌ التكت مش موجود", ephemeral=True)


# ============================================================
# 🚀 أوامر المشرفين
# ============================================================
@bot.tree.command(name="panel", description="إعادة إنشاء البانل")
async def panel_cmd(interaction: discord.Interaction):
    if not is_admin(interaction.user):
        await safe_respond(interaction, content="❌ للمشرفين فقط!", ephemeral=True)
        return
    await create_panel()
    await safe_respond(interaction, content="✅ تم إعادة إنشاء البانل", ephemeral=True)


@bot.tree.command(name="addcredits", description="إضافة كريديتس لمستخدم")
@app_commands.describe(user="المستخدم", amount="المبلغ")
async def addcredits_cmd(interaction: discord.Interaction, user: discord.User, amount: int):
    if not is_admin(interaction.user):
        await safe_respond(interaction, content="❌ للمشرفين فقط!", ephemeral=True)
        return
    data_manager.add_credits(user.id, amount)
    await safe_respond(interaction, content=f"✅ تمت إضافة {amount:,} كريديت لـ {user.mention}", ephemeral=True)


@bot.tree.command(name="removecredits", description="خصم كريديتس من مستخدم")
@app_commands.describe(user="المستخدم", amount="المبلغ")
async def removecredits_cmd(interaction: discord.Interaction, user: discord.User, amount: int):
    if not is_admin(interaction.user):
        await safe_respond(interaction, content="❌ للمشرفين فقط!", ephemeral=True)
        return
    if data_manager.remove_credits(user.id, amount):
        await safe_respond(interaction, content=f"✅ تم خصم {amount:,} كريديت من {user.mention}", ephemeral=True)
    else:
        await safe_respond(interaction, content=f"❌ رصيد {user.mention} غير كافي", ephemeral=True)


@bot.tree.command(name="banuser", description="حظر مستخدم")
@app_commands.describe(user="المستخدم", reason="السبب")
async def banuser_cmd(interaction: discord.Interaction, user: discord.User, reason: str = "بدون سبب"):
    if not is_admin(interaction.user):
        await safe_respond(interaction, content="❌ للمشرفين فقط!", ephemeral=True)
        return
    u = data_manager.get_user(user.id)
    u.is_banned = True
    u.ban_reason = reason
    data_manager.save_data()
    await safe_respond(interaction, content=f"🚫 تم حظر {user.mention}\nالسبب: {reason}", ephemeral=True)


@bot.tree.command(name="unbanuser", description="إلغاء حظر مستخدم")
@app_commands.describe(user="المستخدم")
async def unbanuser_cmd(interaction: discord.Interaction, user: discord.User):
    if not is_admin(interaction.user):
        await safe_respond(interaction, content="❌ للمشرفين فقط!", ephemeral=True)
        return
    u = data_manager.get_user(user.id)
    u.is_banned = False
    u.ban_reason = ""
    data_manager.save_data()
    await safe_respond(interaction, content=f"✅ تم إلغاء حظر {user.mention}", ephemeral=True)


@bot.tree.command(name="stats", description="إحصائيات البوت")
async def stats_cmd(interaction: discord.Interaction):
    if not is_admin(interaction.user):
        await safe_respond(interaction, content="❌ للمشرفين فقط!", ephemeral=True)
        return

    total_users = len(data_manager.users)
    banned = sum(1 for u in data_manager.users.values() if u.is_banned)
    total_views = sum(u.total_views for u in data_manager.users.values())
    total_balance = sum(u.balance for u in data_manager.users.values())
    open_tickets = sum(1 for t in data_manager.tickets.values() if t.status == "open")

    embed = discord.Embed(title="📊 إحصائيات البوت", color=discord.Color.blue())
    embed.add_field(name="👥 إجمالي المستخدمين", value=f"{total_users:,}", inline=True)
    embed.add_field(name="🚫 محظورين", value=f"{banned:,}", inline=True)
    embed.add_field(name="👁️ إجمالي المشاهدات", value=f"{total_views:,}", inline=True)
    embed.add_field(name="💰 إجمالي الرصيد", value=f"{total_balance:,}", inline=True)
    embed.add_field(name="🎫 تكتات مفتوحة", value=f"{open_tickets:,}", inline=True)
    embed.add_field(name="🔧 محرك نشط", value=f"{len(active_engines)}", inline=True)

    await safe_respond(interaction, embed=embed, ephemeral=True)


@bot.tree.command(name="sendall", description="إرسال رسالة لكل أعضاء السيرفر")
@app_commands.describe(message="الرسالة")
async def sendall_cmd(interaction: discord.Interaction, message: str):
    if not is_admin(interaction.user):
        await safe_respond(interaction, content="❌ للمشرفين فقط!", ephemeral=True)
        return

    await safe_respond(interaction, content="✅ جاري الإرسال للجميع...", ephemeral=True)

    guild = interaction.guild
    sent = 0
    failed = 0

    for member in guild.members:
        if member.bot:
            continue
        try:
            await member.send(f"{member.mention}\n\n{message}")
            sent += 1
            await asyncio.sleep(0.5)
        except Exception:
            failed += 1

    try:
        await interaction.followup.send(
            f"✅ تم الإرسال!\n"
            f"✅ نجح: {sent}\n"
            f"❌ فشل: {failed}"
        )
    except Exception:
        pass

# ============================================================
# 🚀 البانل
# ============================================================
async def auto_create_channels(guild):
    created = []
    category = find_ticket_category(guild)
    if not category:
        try:
            category = await guild.create_category(TICKET_CATEGORY_NAME)
        except Exception:
            return created
    existing_names = {c.name for c in category.channels}
    for name in (CONFIG.get("channels") or []):
        if not name or name in existing_names:
            continue
        try:
            chan = await guild.create_text_channel(name, category=category)
            created.append(chan)
        except Exception:
            continue
    return created


async def create_panel():
    channel = bot.get_channel(PANEL_CHANNEL_ID)
    if not channel:
        logger.error(f"❌ القناة {PANEL_CHANNEL_ID} مش موجودة")
        return
    guild = channel.guild

    try:
        async for msg in channel.history(limit=50):
            try:
                await msg.delete()
            except Exception:
                pass
    except Exception:
        pass

    pricing = CONFIG.get("pricing") or {}
    price_lines = []
    for key, p in pricing.items():
        if isinstance(p, dict):
            price_lines.append(f"• {p.get('label', key)}")
        else:
            price_lines.append(f"• {p}")

    channels_mentions = []
    for name in (CONFIG.get("channels") or []):
        found = discord.utils.get(guild.channels, name=name)
        channels_mentions.append(found.mention if found else f"`{name}`")

    note = CONFIG.get("extra_note", "") or ""

    desc = (f"**أهلاً بيك في بوت مشاهدات كليبات كيك 🎉**\n\n"
            f"🚀 **ارفع مشاهدات كيك كليبتك بسرعة**\n\n"
            f"💰 **الأسعار:**\n" + ("\n".join(price_lines) if price_lines else "`لا توجد أسعار`") + "\n\n"
            f"📌 **ازاي تشتغل:**\n"
            f"1️⃣ اضغط **🚀 رفع مشاهدات كليبات** واختار العدد\n"
            f"2️⃣ ابعت لينك الكليب من kick.com\n"
            f"3️⃣ المحرك بيرفع المشاهدات تلقائياً ✅\n\n"
            f"👁️ **كل المشاهدات حقيقية** ✅\n"
            f"⚠️ **اللينك لازم يكون شكله:** `kick.com/username/clips/xxxxx`\n"
            f"\n**اختار من الأزرار:**")

    embed = discord.Embed(
        title="🎯 بوت مشاهدات كليبات كيك",
        description=desc,
        color=discord.Color.green(),
    )
    embed.set_footer(text=f"⚡ سرعة عالية | 🎯 دقة 100% | {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    view = ShopMainView()
    await channel.send(embed=embed, view=view)

# ============================================================
# 🤖 إغلاق نظيف
# ============================================================
async def close_all_engines():
    for engine in list(active_engines.values()):
        engine.running = False
        engine.is_finished = True
        await engine.close_sessions()

# ============================================================
# 🚀 تشغيل البوت
# ============================================================
@bot.event
async def on_ready():
    print("=" * 60)
    print("🎯 بوت المشاهدات")
    print(f"✅ البوت جاهز! {bot.user}")
    print(f"👥 مستخدمين: {len(data_manager.users)}")
    print(f"💰 إجمالي الكريديتس: {sum(u.balance for u in data_manager.users.values()):,}")
    print("=" * 60)

    try:
        await bot.tree.sync()
        print("✅ الأوامر متزامنة")
    except Exception as e:
        print(f"❌ خطأ في المزامنة: {e}")

    if CONFIG.get("auto_create_channels"):
        try:
            for guild in bot.guilds:
                created = await auto_create_channels(guild)
                if created:
                    print(f"✅ تم إنشاء {len(created)} شانيل في {guild.name}")
        except Exception as e:
            print(f"❌ خطأ في إنشاء الشانيلز: {e}")

    bot.add_view(ShopMainView())
    for t in data_manager.tickets.values():
        if t.status == "open":
            if t.type == "support":
                bot.add_view(SupportTicketView(t.ticket_id, t.user_id))
            else:
                bot.add_view(TicketActionView(t.ticket_id, t.user_id, t.amount))
    print("✅ الأزرار الدائمة مسجلة")


@bot.event
async def on_close():
    try:
        await close_all_engines()
    except Exception:
        pass


if __name__ == "__main__":
    try:
        bot.run(TOKEN)
    except KeyboardInterrupt:
        pass
