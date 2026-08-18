import asyncio
import json
import os
import random
import re
import sys
import time
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands
from curl_cffi import AsyncSession
import logging


# =========================================================
# OUTPUT ENCODING
# =========================================================

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


# =========================================================
# CONFIG
# =========================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(BASE_DIR, "config.json"), "r", encoding="utf-8") as f:
    CFG = json.load(f)

TOKEN = os.environ.get("KICK_BOT_TOKEN") or str(CFG.get("bot_token") or "")
PANEL_ID = int(CFG.get("panel_channel_id") or 0)
PANEL_EXTRA_ID = int(CFG.get("panel_extra_id") or 0) or None
PANEL_EXTRA_NAME = str(CFG.get("panel_extra_name") or "")
ADMIN_IDS = [int(a) for a in (CFG.get("admin_ids") or [])]
STAFF_ROLES = CFG.get("ticket_staff_roles") or []
RECONNECT_TRY = 5

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
logger = logging.getLogger("ViewsBot")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)


# =========================================================
# BOOST SETTINGS
# =========================================================

BOOST_CONFIG = {
    "max_speed": 350,
    "min_speed": 1,
    "timeout": 10,
    "batch_size": 200,
    "batch_pause": 1,
    "view_via_link": True,
    "target_duration_seconds": 60,
}


def compute_boost_speed(target: int) -> int:
    return max(1, round(target / BOOST_CONFIG.get("target_duration_seconds", 60)))


def format_bar(progress: float, width: int = 30) -> str:
    filled = int(width * progress / 100)
    return "█" * filled + "░" * (width - filled)


def is_admin(member) -> bool:
    if hasattr(member, "id") and member.id in ADMIN_IDS:
        return True
    if hasattr(member, "roles"):
        user_roles = {r.name for r in member.roles}
        if user_roles & set(STAFF_ROLES):
            return True
    return False


# =========================================================
# DATA
# =========================================================

from credits import data_manager, DataManager


# =========================================================
# PRECISION BOOST ENGINE
# =========================================================

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
        self.sessions: list = []

    @property
    def accuracy(self) -> float:
        return (self.successful_views / self.total_requests * 100) if self.total_requests > 0 else 0

    def _new_session(self) -> AsyncSession:
        session = AsyncSession(impersonate="chrome", timeout=BOOST_CONFIG["timeout"])
        self.sessions.append(session)
        return session

    def _ua(self) -> str:
        return random.choice([
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        ])

    def _base_headers(self) -> dict:
        ua = self._ua()
        m = re.search(r"Chrome/(\d+)", ua)
        ver = m.group(1) if m else "130"
        return {
            "User-Agent": ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://kick.com/",
            "sec-ch-ua": f'"Not_A Brand";v="24", "Chromium";v="{ver}", "Google Chrome";v="{ver}"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
        }

    async def validate_url(self) -> tuple:
        session = self._new_session()
        try:
            presp = await session.get(self.url, headers=self._base_headers(), allow_redirects=True)
            return presp.status_code in (200, 206), presp.status_code
        except Exception:
            return False, 0
        finally:
            try:
                await session.close()
            except Exception:
                pass

    async def send_single_view(self, session: AsyncSession) -> bool:
        try:
            presp = await session.get(self.url, headers=self._base_headers(), allow_redirects=True)
            if presp.status_code == 429:
                async with self.lock:
                    self.rate_limited += 1
                return False
            if presp.status_code not in (200, 206):
                return False
            return True
        except Exception:
            return False

    async def worker(self, session: AsyncSession):
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
                await asyncio.sleep(0.05)

            async with self.lock:
                if self.total_requests >= self.max_attempts or self.successful_views >= self.target:
                    self.running = False
                    self.is_finished = True
                    break
                self.total_requests += 1

            success = await self.send_single_view(session)

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

            if success:
                local_failures = 0
            else:
                local_failures += 1
                if local_failures >= 5:
                    await asyncio.sleep(0.5)
                    try:
                        await session.close()
                    except Exception:
                        pass
                    session = self._new_session()
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

        workers = min(100, max(10, self.speed))
        self.worker_count = workers
        tasks = []
        for i in range(workers):
            session = self._new_session()
            tasks.append(asyncio.create_task(self.worker(session)))

        await asyncio.gather(*tasks, return_exceptions=True)

        for session in self.sessions:
            try:
                await session.close()
            except Exception:
                pass
        self.sessions.clear()

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
            "accuracy": self.accuracy,
        }


# =========================================================
# SAFE INTERACTION EDIT / RESPOND
# =========================================================

async def safe_edit(interaction: discord.Interaction, **kwargs):
    try:
        if not interaction.response.is_done():
            await interaction.response.edit_message(**kwargs)
        else:
            await interaction.edit_original_response(**kwargs)
    except Exception:
        try:
            await interaction.edit_original_response(**kwargs)
        except Exception:
            pass


async def safe_respond(interaction: discord.Interaction, **kwargs):
    try:
        if not interaction.response.is_done():
            await interaction.response.send_message(**kwargs)
            return
        await interaction.followup.send(**kwargs)
    except Exception:
        try:
            await interaction.followup.send(**kwargs)
        except Exception:
            pass


async def safe_send_modal(interaction: discord.Interaction, modal):
    try:
        if not interaction.response.is_done():
            await interaction.response.send_modal(modal)
    except Exception:
        pass


# =========================================================
# PANEL BUILDERS
# =========================================================

def get_channel_mentions(guild):
    mentions = []
    for name in (CFG.get("channels") or []):
        channel = discord.utils.get(guild.channels, name=name)
        mentions.append(channel.mention if channel else f"`{name}`")
    return mentions


def get_price_lines(arabic: bool = True):
    pricing = CFG.get("pricing") or {}
    lines = []
    for price in pricing.values():
        if isinstance(price, dict):
            label = str(
                (price.get("label") if arabic else price.get("label_en"))
                or price.get("label_en")
                or price.get("label")
                or price.get("name")
                or "Package"
            )
            value = price.get("price")
            lines.append(f"• {label}: `{value}`" if value is not None else f"• {label}")
        else:
            lines.append(f"• {price}")
    return lines


def build_arabic_embed(guild):
    welcome = str(CFG.get("welcome_text") or "أهلاً وسهلاً بيك في المتجر 🎉")
    channels = get_channel_mentions(guild)
    prices = get_price_lines(arabic=True)
    note = str(CFG.get("extra_note") or "")

    description = (
        f"**{welcome}**\n\n"
        f"📌 **الشانيلز:**\n"
        f"{chr(10).join(f'• {c}' for c in channels) if channels else '`لا توجد شانيلز`'}\n\n"
        f"💰 **الأسعار:**\n"
        f"{chr(10).join(prices) if prices else '`لا توجد أسعار`'}\n\n"
        f"🛒 **ازاي تحصل على المشاهدات:**\n"
        f"1️⃣ اضغط **💳 طلب كريديتس** واختار المبلغ\n"
        f"2️⃣ الستاف هيوافق على طلبك وتتضاف الكريديتس لرصيدك\n"
        f"3️⃣ ابعت الرابط للمشرفين وهيرفعوا المشاهدات ✅\n\n"
        f"👁️ **كل المشاهدات حقيقية** ✅\n"
    )
    if note:
        description += f"\n{note}\n"
    description += "\n**اختار من الأزرار:**"

    embed = discord.Embed(title="🎯 بوت المشاهدات", description=description, color=discord.Color.green())
    embed.set_footer(text=datetime.now().strftime("%Y-%m-%d %H:%M"))
    return embed



# =========================================================
# PANEL BUTTONS
# =========================================================

class TicketStaffView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="✅ قبول", style=discord.ButtonStyle.green, custom_id="ticket_accept")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction.user):
            await safe_respond(interaction, content="❌ مسموح للستاف بس يقبل أو يرفض", ephemeral=True)
            return
        data = data_manager.pending_tickets.get(interaction.channel.id)
        if not data:
            await safe_respond(interaction, content="❌ بيانات الطلب مش موجودة", ephemeral=True)
            return
        data_manager.add_credits(data["user_id"], data["amount"])
        member = interaction.guild.get_member(data["user_id"])
        if member:
            try:
                await member.send(f"✅ تم قبول طلبك في **{interaction.guild.name}**! تم إضافة **{data['amount']:,} كريديت** لرصيدك.")
            except Exception:
                pass
        del data_manager.pending_tickets[interaction.channel.id]
        data_manager._save()
        embed = discord.Embed(
            title="✅ تم القبول",
            description=f"تم إضافة **{data['amount']:,} كريديت** لـ <@{data['user_id']}>",
            color=discord.Color.green(),
        )
        await interaction.message.edit(embed=embed, view=None)
        await interaction.channel.delete(reason="ticket accepted")

    @discord.ui.button(label="❌ رفض", style=discord.ButtonStyle.red, custom_id="ticket_reject")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction.user):
            await safe_respond(interaction, content="❌ مسموح للستاف بس يقبل أو يرفض", ephemeral=True)
            return
        data = data_manager.pending_tickets.get(interaction.channel.id)
        if data:
            member = interaction.guild.get_member(data["user_id"])
            if member:
                try:
                    await member.send(f"❌ تم رفض طلبك في **{interaction.guild.name}**.")
                except Exception:
                    pass
            del data_manager.pending_tickets[interaction.channel.id]
            data_manager._save()
        embed = discord.Embed(
            title="❌ تم رفض الطلب",
            color=discord.Color.red(),
        )
        await interaction.message.edit(embed=embed, view=None)
        await interaction.channel.delete(reason="ticket rejected")


async def open_credit_ticket(interaction: discord.Interaction, amount: int = 0):
    guild = interaction.guild
    user = interaction.user
    try:
        cat_name = str(CFG.get("category_name") or "طلبات كريديتس")
        category = discord.utils.get(guild.categories, name=cat_name)
        if not category:
            try:
                category = await guild.create_category(name=cat_name)
            except Exception:
                category = None

        for data in data_manager.pending_tickets.values():
            if isinstance(data, dict) and data.get("user_id") == user.id:
                await safe_respond(interaction, content=f"🎫 عندك تيكت مفتوح بالفعل! استنى لحد ما يتم إغلاقه.", ephemeral=True)
                return

        channel_name = str(CFG.get("ticket_channel_name") or "طلب-كريديتس")
        base = channel_name
        n = 2
        while discord.utils.get(guild.channels, name=channel_name):
            channel_name = f"{base}-{n}"
            n += 1

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True, read_message_history=True),
        }
        for role_name in STAFF_ROLES:
            role = discord.utils.get(guild.roles, name=role_name)
            if role:
                overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_messages=True)
        overwrites[user] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, attach_files=True)

        channel = await guild.create_text_channel(name=channel_name, category=category, overwrites=overwrites)

        amount_line = f"\n💳 **المبلغ المطلوب:** {amount:,} كريديت" if amount else ""
        embed = discord.Embed(
            title="🎫 تيكت طلب كريديتس",
            description=(
                f"{user.mention}\n\n"
                f"📝 اكتب هنا تفاصيل الطلب.\n"
                f"⏳ الستاف هيشوف طلبك ويوافق أو يرفض.\n"
                f"{amount_line}"
            ),
            color=discord.Color.gold(),
        )
        data_manager.pending_tickets[channel.id] = {"user_id": user.id, "amount": amount}
        data_manager._save()
        await channel.send(content=f"{user.mention}", embed=embed, view=TicketStaffView())

        try:
            await user.send(f"🎫 اتفتحلك تيكت في {guild.name}: {channel.mention}")
        except Exception:
            pass

        await safe_respond(interaction, content=f"✅ اتفتحلك التيكت: {channel.mention}", ephemeral=True)
    except Exception as e:
        try:
            await safe_respond(interaction, content=f"❌ فشل فتح التيكت: {e}", ephemeral=True)
        except Exception:
            pass


class CreditAmountView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)

    @discord.ui.select(
        placeholder="💳 اختار المبلغ",
        min_values=1,
        max_values=1,
        custom_id="credits_amount_select",
        options=[
            discord.SelectOption(label="500 كريديت", value="500"),
            discord.SelectOption(label="1000 كريديت", value="1000"),
            discord.SelectOption(label="3000 كريديت", value="3000"),
            discord.SelectOption(label="5000 كريديت", value="5000"),
            discord.SelectOption(label="10000 كريديت", value="10000"),
            discord.SelectOption(label="50000 كريديت", value="50000"),
            discord.SelectOption(label="100000 كريديت", value="100000"),
        ],
    )
    async def amount(self, interaction: discord.Interaction, select: discord.ui.Select):
        chosen = int(select.values[0])
        await open_credit_ticket(interaction, chosen)


class PanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="💳 طلب كريديتس", style=discord.ButtonStyle.primary, row=0, custom_id="pv_credits")
    async def credits(self, interaction: discord.Interaction, button: discord.ui.Button):
        await safe_respond(interaction, content="💳 **اختار المبلغ اللي عايزه:**", view=CreditAmountView(), ephemeral=True)

    @discord.ui.button(label="ℹ️ معلومات", style=discord.ButtonStyle.gray, row=0, custom_id="pv_info")
    async def info(self, interaction: discord.Interaction, button: discord.ui.Button):
        prices = get_price_lines(arabic=True)
        embed = discord.Embed(
            title="ℹ️ معلومات المتجر",
            description=(
                f"💰 **الأسعار:**\n"
                f"{chr(10).join(prices) if prices else '`لا توجد أسعار`'}\n\n"
                f"🛒 **ازاي تحصل على المشاهدات:**\n"
                f"1️⃣ اضغط **💳 طلب كريديتس** واختار المبلغ\n"
                f"2️⃣ الستاف هيوافق على طلبك وتتضاف الكريديتس لرصيدك\n"
                f"3️⃣ ابعت الرابط للمشرفين وهيرفعوا المشاهدات ✅"
            ),
            color=discord.Color.blue(),
        )
        await safe_respond(interaction, embed=embed, ephemeral=True)

    @discord.ui.button(label="💰 رصيدي", style=discord.ButtonStyle.green, row=0, custom_id="pv_balance")
    async def balance(self, interaction: discord.Interaction, button: discord.ui.Button):
        u = data_manager.get_user(interaction.user.id, interaction.user.name)
        embed = discord.Embed(
            title="💰 رصيدك",
            description=f"**الكريديتس:** {u.balance:,}\n**إجمالي المشاهدات:** {u.total_views:,}",
            color=discord.Color.green(),
        )
        await safe_respond(interaction, embed=embed, ephemeral=True)


# =========================================================
# ADMIN COMMANDS
# =========================================================

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


# =========================================================
# READY
# =========================================================

async def send_panel_to(channel):
    try:
        async for message in channel.history(limit=100):
            try:
                await message.delete()
            except Exception:
                pass
    except Exception:
        pass
    await channel.send(embed=build_arabic_embed(channel.guild), view=PanelView())


# =========================================================
# LEVEL ROLES -> ACTIVE
# =========================================================

def level_role_names() -> list:
    return [str(v) for v in ((CFG.get("levels_config") or {}).get("roles") or {}).values()]


def active_role_name() -> str:
    return str((CFG.get("levels_config") or {}).get("active_role") or "⭐ Active")


@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    try:
        if set(before.roles) == set(after.roles):
            return
        lvl_names = level_role_names()
        if not any(r.name in lvl_names for r in after.roles):
            return
        active = discord.utils.get(after.guild.roles, name=active_role_name())
        if active and active not in after.roles:
            await after.add_roles(active, reason="Level role -> Active")
            print(f"⭐ Active اتضافت لـ {after.name} ({after.id})", flush=True)
    except Exception:
        pass


@bot.event
async def on_ready():
    print(f"✅ {bot.user} جاهز", flush=True)

    try:
        if data_manager.pending_tickets:
            stale = [cid for cid in data_manager.pending_tickets if not bot.get_channel(cid)]
            for cid in stale:
                del data_manager.pending_tickets[cid]
            if stale:
                data_manager._save()
            print(f"🎫 تم تحميل {len(data_manager.pending_tickets)} تيكت معلق", flush=True)
    except Exception:
        pass

    try:
        bot.add_view(PanelView())
    except Exception:
        pass

    try:
        bot.add_view(TicketStaffView())
    except Exception:
        pass

    try:
        synced = 0
        for g in bot.guilds:
            try:
                await bot.tree.sync(guild=g)
                synced += 1
            except Exception:
                pass
        await bot.tree.sync()
        print(f"✅ مزامنة الأوامر ({synced})", flush=True)
    except Exception as e:
        print(f"❌ فشل المزامنة: {e}", flush=True)

    channel = bot.get_channel(PANEL_ID)
    if not channel:
        print(f"❌ الشانيل {PANEL_ID} مش موجودة", flush=True)
    else:
        try:
            await send_panel_to(channel)
            print("✅ البانل جاهز", flush=True)
        except Exception as e:
            print(f"❌ فشل إرسال البانل: {e}", flush=True)


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":
    if not TOKEN:
        print("❌ Bot token مش موجود في config.json", flush=True)
        sys.exit(1)
    bot.run(TOKEN)