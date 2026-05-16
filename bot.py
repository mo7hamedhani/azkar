#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
بوت تليجرام لنشر محتوى ديني - صور فقط + لوحة تحكم
"""

import os
import sys
import logging
import random
import sqlite3
import asyncio
import json
import requests
from datetime import datetime, timedelta
from io import BytesIO

from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

# ==================== CONFIGURATION ====================
def load_config():
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    config = {
        "BOT_TOKEN": os.getenv("BOT_TOKEN"),
        "CHANNEL_ID": os.getenv("CHANNEL_ID"),
        "ADMIN_ID": os.getenv("ADMIN_ID"),
        "POST_INTERVAL_HOURS": os.getenv("POST_INTERVAL_HOURS", "3"),
        "POST_AT_SPECIFIC_TIMES": os.getenv("POST_AT_SPECIFIC_TIMES", "false").lower(),
        "SCHEDULED_TIMES": os.getenv("SCHEDULED_TIMES", "05:00,13:00,17:00,21:00"),
    }

    if not config["BOT_TOKEN"]:
        logger.error("BOT_TOKEN not found!")
        sys.exit(1)

    if not config["CHANNEL_ID"]:
        logger.error("CHANNEL_ID not found!")
        sys.exit(1)

    try:
        config["CHANNEL_ID"] = int(config["CHANNEL_ID"])
        config["ADMIN_ID"] = int(config["ADMIN_ID"]) if config["ADMIN_ID"] else 0
        config["POST_INTERVAL_HOURS"] = int(config["POST_INTERVAL_HOURS"])
    except ValueError as e:
        logger.error(f"Error converting numbers: {e}")
        sys.exit(1)

    return config

CONFIG = load_config()
BOT_TOKEN = CONFIG["BOT_TOKEN"]
CHANNEL_ID = CONFIG["CHANNEL_ID"]
ADMIN_ID = CONFIG["ADMIN_ID"]
POST_INTERVAL_HOURS = CONFIG["POST_INTERVAL_HOURS"]
POST_AT_SPECIFIC_TIMES = CONFIG["POST_AT_SPECIFIC_TIMES"] == "true"
SCHEDULED_TIMES = CONFIG["SCHEDULED_TIMES"].split(",")

# ==================== LOGGING ====================
DB_FILE = "islamic_content.db"
LOG_FILE = "bot.log"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# ==================== LOAD CONTENT ====================
def load_content():
    try:
        with open("content.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error("content.json not found!")
        return {"ayat": [], "ahadith": [], "athkar": [], "images": []}

CONTENT = load_content()

# ==================== DATABASE ====================
class Database:
    def __init__(self):
        self.conn = sqlite3.connect(DB_FILE, check_same_thread=False)
        self.init_tables()
        self.seed_data()

    def init_tables(self):
        c = self.conn.cursor()

        tables = ["ayat", "ahadith", "athkar", "images"]
        for table in tables:
            c.execute(f"""
                CREATE TABLE IF NOT EXISTS {table} (
                    id INTEGER PRIMARY KEY,
                    content TEXT NOT NULL,
                    media_type TEXT DEFAULT 'text',
                    media_url TEXT,
                    posted INTEGER DEFAULT 0,
                    posted_date TEXT,
                    post_count INTEGER DEFAULT 0
                )
            """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS post_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content_type TEXT,
                content_id INTEGER,
                posted_date TEXT,
                status TEXT
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS bot_settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        self.conn.commit()
        logger.info("Database initialized")

    def seed_data(self):
        c = self.conn.cursor()

        c.execute("SELECT COUNT(*) FROM ayat")
        if c.fetchone()[0] > 0:
            logger.info("Database already has data")
            return

        logger.info("Adding content...")

        for i, item in enumerate(CONTENT.get("ayat", []), 1):
            content = json.dumps(item, ensure_ascii=False)
            image_url = f"https://cdn.islamic.network/quran/images/{item['surah']}_{item['ayah']}.png"
            c.execute("INSERT INTO ayat (id, content, media_type, media_url) VALUES (?, ?, ?, ?)",
                      (i, content, 'image', image_url))

        for i, item in enumerate(CONTENT.get("ahadith", []), 1):
            content = json.dumps(item, ensure_ascii=False)
            c.execute("INSERT INTO ahadith (id, content, media_type) VALUES (?, ?, ?)",
                      (i, content, 'text'))

        for i, item in enumerate(CONTENT.get("athkar", []), 1):
            content = json.dumps(item, ensure_ascii=False)
            c.execute("INSERT INTO athkar (id, content, media_type) VALUES (?, ?, ?)",
                      (i, content, 'text'))

        for i, item in enumerate(CONTENT.get("images", []), 1):
            content = json.dumps(item, ensure_ascii=False)
            c.execute("INSERT INTO images (id, content, media_type, media_url) VALUES (?, ?, ?, ?)",
                      (i, content, 'image', item.get('url', '')))

        self.conn.commit()
        logger.info("Content added successfully")

    def get_unposted(self, table_name):
        c = self.conn.cursor()
        c.execute(f"SELECT * FROM {table_name} WHERE posted = 0 ORDER BY RANDOM() LIMIT 1")
        return c.fetchone()

    def mark_posted(self, table_name, content_id):
        c = self.conn.cursor()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute(f"UPDATE {table_name} SET posted = 1, posted_date = ?, post_count = post_count + 1 WHERE id = ?", 
                  (now, content_id))
        c.execute("INSERT INTO post_log (content_type, content_id, posted_date, status) VALUES (?, ?, ?, ?)",
                  (table_name, content_id, now, "success"))
        self.conn.commit()

    def reset_table(self, table_name):
        c = self.conn.cursor()
        c.execute(f"UPDATE {table_name} SET posted = 0, posted_date = NULL")
        self.conn.commit()
        logger.info(f"Reset {table_name}")

    def get_stats(self):
        c = self.conn.cursor()
        stats = {}
        for table in ["ayat", "ahadith", "athkar", "images"]:
            c.execute(f"SELECT COUNT(*) FROM {table}")
            total = c.fetchone()[0]
            c.execute(f"SELECT COUNT(*) FROM {table} WHERE posted = 1")
            posted = c.fetchone()[0]
            stats[table] = {"total": total, "posted": posted, "remaining": total - posted}
        return stats

    def get_recent_posts(self, limit=10):
        c = self.conn.cursor()
        c.execute("SELECT content_type, content_id, posted_date, status FROM post_log ORDER BY posted_date DESC LIMIT ?", (limit,))
        return c.fetchall()

    def get_setting(self, key, default=None):
        c = self.conn.cursor()
        c.execute("SELECT value FROM bot_settings WHERE key = ?", (key,))
        result = c.fetchone()
        return result[0] if result else default

    def set_setting(self, key, value):
        c = self.conn.cursor()
        c.execute("INSERT OR REPLACE INTO bot_settings (key, value) VALUES (?, ?)", (key, value))
        self.conn.commit()

# ==================== SMART PICKER ====================
class SmartPicker:
    def __init__(self, db):
        self.db = db
        self.recent_types = []
        self.max_history = 4

    def pick_content(self):
        content_types = ["images", "ayat", "ahadith", "athkar"]

        available = [t for t in content_types if t not in self.recent_types[-2:]]
        if not available:
            available = content_types

        chosen = random.choice(available)
        content = self.db.get_unposted(chosen)
        if not content:
            self.db.reset_table(chosen)
            content = self.db.get_unposted(chosen)

        if content:
            self.recent_types.append(chosen)
            if len(self.recent_types) > self.max_history:
                self.recent_types.pop(0)
            return chosen, content

        for t in content_types:
            self.db.reset_table(t)
            content = self.db.get_unposted(t)
            if content:
                self.recent_types.append(t)
                return t, content

        return None, None

# ==================== MESSAGE FORMATTING ====================
def format_caption(content_type, content_row):
    _, content_json, media_type, media_url, _, _, _ = content_row
    item = json.loads(content_json)

    if content_type == "ayat":
        return f"""📖 <b>آية قرآنية</b>

{item['text']}

📍 <i>{item['surah']} - الآية {item['ayah']}</i>
📝 <i>{item['tafsir']}</i>

#آيات #قرآن #تدبر"""

    elif content_type == "ahadith":
        return f"""🌟 <b>حديث شريف</b>

❝ {item['text']} ❞

📚 رواه: <i>{item['narrator']}</i>
📖 المصدر: <i>{item['source']}</i>

#أحاديث #سنة #نبوية"""

    elif content_type == "athkar":
        return f"""🤲 <b>ذكر طيب</b>

{item['text']}

📍 <i>التصنيف: {item['category']}</i>

#أذكار #أدعية #ذكر_الله"""

    elif content_type == "images":
        return f"""📸 <b>صورة دينية</b>

{item.get('description', '')}

#إسلامي #صورة #تذكير"""

    return ""

# ==================== POSTING ====================
async def send_post(bot, db, picker, specific_type=None):
    if specific_type:
        content = db.get_unposted(specific_type)
        if not content:
            db.reset_table(specific_type)
            content = db.get_unposted(specific_type)
        content_type = specific_type
    else:
        content_type, content = picker.pick_content()

    if not content:
        logger.error("No content available!")
        return False

    content_id, content_json, media_type, media_url, _, _, _ = content
    item = json.loads(content_json)
    caption = format_caption(content_type, content)

    try:
        if content_type in ["ayat", "images"] and media_url:
            try:
                response = requests.get(media_url, timeout=10)
                if response.status_code == 200:
                    photo = BytesIO(response.content)
                    await bot.send_photo(
                        chat_id=CHANNEL_ID,
                        photo=photo,
                        caption=caption,
                        parse_mode=ParseMode.HTML
                    )
                    logger.info(f"Sent image: {content_type} (ID: {content_id})")
                else:
                    await bot.send_message(chat_id=CHANNEL_ID, text=caption, parse_mode=ParseMode.HTML)
                    logger.info(f"Sent text (image failed): {content_type} (ID: {content_id})")
            except Exception as img_error:
                logger.warning(f"Image failed: {img_error}")
                await bot.send_message(chat_id=CHANNEL_ID, text=caption, parse_mode=ParseMode.HTML)
                logger.info(f"Sent text fallback: {content_type} (ID: {content_id})")
        else:
            await bot.send_message(chat_id=CHANNEL_ID, text=caption, parse_mode=ParseMode.HTML)
            logger.info(f"Sent text: {content_type} (ID: {content_id})")

        db.mark_posted(content_type, content_id)
        return True

    except Exception as e:
        logger.error(f"Error posting: {e}")
        return False

# ==================== ADMIN DASHBOARD ====================
def is_admin(user_id):
    return user_id == ADMIN_ID

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("⛔ هذا البوت خاص بالأدمن فقط.")
        return

    keyboard = [
        [InlineKeyboardButton("📊 الإحصائيات", callback_data="stats")],
        [InlineKeyboardButton("📝 نشر فوري", callback_data="post_now")],
        [InlineKeyboardButton("📋 سجل المنشورات", callback_data="logs")],
        [InlineKeyboardButton("🔄 إعادة تعيين", callback_data="reset")],
        [InlineKeyboardButton("⚙️ الإعدادات", callback_data="settings")],
        [InlineKeyboardButton("⏯️ تشغيل/إيقاف", callback_data="toggle")],
        [InlineKeyboardButton("❓ المساعدة", callback_data="help")],
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "👋 <b>لوحة تحكم البوت</b>\n\n"
        "اختر الإجراء المطلوب:",
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    if not is_admin(user_id):
        await query.edit_message_text("⛔ غير مصرح.")
        return

    db = Database()

    if query.data == "stats":
        stats = db.get_stats()
        msg = "📊 <b>إحصائيات المحتوى</b>\n\n"
        emojis = {"ayat": "📖", "ahadith": "🌟", "athkar": "🤲", "images": "📸"}

        for table, data in stats.items():
            emoji = emojis.get(table, "📄")
            msg += f"{emoji} <b>{table}:</b> {data['posted']}/{data['total']} (متبقي: {data['remaining']})\n"

        keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="back_to_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(msg, parse_mode=ParseMode.HTML, reply_markup=reply_markup)

    elif query.data == "post_now":
        keyboard = [
            [InlineKeyboardButton("📖 آية", callback_data="post_ayat")],
            [InlineKeyboardButton("🌟 حديث", callback_data="post_ahadith")],
            [InlineKeyboardButton("🤲 ذكر", callback_data="post_athkar")],
            [InlineKeyboardButton("📸 صورة", callback_data="post_images")],
            [InlineKeyboardButton("🎲 عشوائي", callback_data="post_random")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="back_to_menu")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("📝 <b>اختر نوع المنشور:</b>", parse_mode=ParseMode.HTML, reply_markup=reply_markup)

    elif query.data.startswith("post_"):
        post_type = query.data.replace("post_", "")
        bot = context.bot
        picker = SmartPicker(db)

        await query.edit_message_text("⏳ جاري النشر...")

        if post_type == "random":
            success = await send_post(bot, db, picker)
        else:
            success = await send_post(bot, db, picker, specific_type=post_type)

        msg = f"✅ تم النشر بنجاح! ({post_type})" if success else "❌ فشل النشر."
        keyboard = [[InlineKeyboardButton("🔙 رجوع للقائمة", callback_data="back_to_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(msg, reply_markup=reply_markup)

    elif query.data == "logs":
        posts = db.get_recent_posts(10)
        msg = "📋 <b>آخر 10 منشورات</b>\n\n"
        emojis = {"ayat": "📖", "ahadith": "🌟", "athkar": "🤲", "images": "📸"}

        for post in posts:
            content_type, content_id, date, status = post
            emoji = emojis.get(content_type, "📄")
            msg += f"{emoji} {content_type} (ID:{content_id}) - {date}\n"

        keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="back_to_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(msg, parse_mode=ParseMode.HTML, reply_markup=reply_markup)

    elif query.data == "reset":
        keyboard = [
            [InlineKeyboardButton("✅ تأكيد", callback_data="reset_confirm")],
            [InlineKeyboardButton("❌ إلغاء", callback_data="back_to_menu")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("⚠️ <b>هل تريد إعادة تعيين كل المحتوى؟</b>", parse_mode=ParseMode.HTML, reply_markup=reply_markup)

    elif query.data == "reset_confirm":
        for table in ["ayat", "ahadith", "athkar", "images"]:
            db.reset_table(table)

        keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="back_to_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("🔄 <b>تم إعادة تعيين كل المحتوى!</b>", parse_mode=ParseMode.HTML, reply_markup=reply_markup)

    elif query.data == "settings":
        keyboard = [
            [InlineKeyboardButton("⏱️ تغيير الفترة", callback_data="change_interval")],
            [InlineKeyboardButton("🕐 أوقات محددة", callback_data="specific_times")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="back_to_menu")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f"⚙️ <b>الإعدادات:</b>\n\n"
            f"⏱️ الفترة: كل {POST_INTERVAL_HOURS} ساعات\n"
            f"🕐 أوقات محددة: {'مفعل' if POST_AT_SPECIFIC_TIMES else 'معطل'}",
            parse_mode=ParseMode.HTML, reply_markup=reply_markup
        )

    elif query.data == "toggle":
        current = db.get_setting("bot_active", "true")
        new_value = "false" if current == "true" else "true"
        db.set_setting("bot_active", new_value)

        status = "🟢 <b>مفعل</b>" if new_value == "true" else "🔴 <b>معطل</b>"
        keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="back_to_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f"⏯️ <b>حالة البوت:</b> {status}\n\n"
            f"النشر التلقائي {'مفعل' if new_value == 'true' else 'معطل'} الآن.",
            parse_mode=ParseMode.HTML, reply_markup=reply_markup
        )

    elif query.data == "help":
        keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="back_to_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "📖 <b>دليل استخدام البوت</b>\n\n"
            "/admin - لوحة التحكم\n"
            "/post - نشر فوري\n"
            "/stats - إحصائيات\n"
            "/logs - سجل المنشورات\n"
            "/reset - إعادة تعيين\n\n"
            f"• البوت ينشر كل {POST_INTERVAL_HOURS} ساعات\n"
            "• المحتوى: صور + آيات + أحاديث + أذكار\n"
            "• لا يتكرر حتى ينتهي كل المحتوى",
            parse_mode=ParseMode.HTML, reply_markup=reply_markup
        )

    elif query.data == "back_to_menu":
        keyboard = [
            [InlineKeyboardButton("📊 الإحصائيات", callback_data="stats")],
            [InlineKeyboardButton("📝 نشر فوري", callback_data="post_now")],
            [InlineKeyboardButton("📋 سجل المنشورات", callback_data="logs")],
            [InlineKeyboardButton("🔄 إعادة تعيين", callback_data="reset")],
            [InlineKeyboardButton("⚙️ الإعدادات", callback_data="settings")],
            [InlineKeyboardButton("⏯️ تشغيل/إيقاف", callback_data="toggle")],
            [InlineKeyboardButton("❓ المساعدة", callback_data="help")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "👋 <b>لوحة تحكم البوت</b>\n\n"
            "اختر الإجراء المطلوب:",
            parse_mode=ParseMode.HTML, reply_markup=reply_markup
        )

# ==================== SIMPLE COMMANDS ====================
async def post_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("⛔ غير مصرح.")
        return

    await update.message.reply_text("⏳ جاري النشر العشوائي...")

    bot = context.bot
    db = Database()
    picker = SmartPicker(db)

    success = await send_post(bot, db, picker)

    if success:
        await update.message.reply_text("✅ تم النشر بنجاح!")
    else:
        await update.message.reply_text("❌ فشل النشر.")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("⛔ غير مصرح.")
        return

    db = Database()
    stats = db.get_stats()

    msg = "📊 <b>إحصائيات المحتوى</b>\n\n"
    emojis = {"ayat": "📖", "ahadith": "🌟", "athkar": "🤲", "images": "📸"}

    for table, data in stats.items():
        emoji = emojis.get(table, "📄")
        msg += f"{emoji} <b>{table}:</b> {data['posted']}/{data['total']} (متبقي: {data['remaining']})\n"

    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

async def logs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("⛔ غير مصرح.")
        return

    db = Database()
    posts = db.get_recent_posts(10)

    msg = "📋 <b>آخر 10 منشورات</b>\n\n"
    emojis = {"ayat": "📖", "ahadith": "🌟", "athkar": "🤲", "images": "📸"}

    for post in posts:
        content_type, content_id, date, status = post
        emoji = emojis.get(content_type, "📄")
        msg += f"{emoji} {content_type} (ID:{content_id}) - {date}\n"

    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("⛔ غير مصرح.")
        return

    db = Database()
    for table in ["ayat", "ahadith", "athkar", "images"]:
        db.reset_table(table)

    await update.message.reply_text("🔄 تم إعادة تعيين جميع المحتويات!")

# ==================== SCHEDULER ====================
def setup_scheduler(bot, db, picker):
    scheduler = BackgroundScheduler()

    if POST_AT_SPECIFIC_TIMES:
        for time_str in SCHEDULED_TIMES:
            hour, minute = map(int, time_str.strip().split(":"))
            scheduler.add_job(
                lambda: asyncio.run(send_scheduled_post(bot, db, picker)),
                CronTrigger(hour=hour, minute=minute),
                id=f"post_{hour}_{minute}",
                name=f"Post at {hour}:{minute:02d}"
            )
            logger.info(f"Scheduled post at {hour}:{minute:02d}")
    else:
        scheduler.add_job(
            lambda: asyncio.run(send_scheduled_post(bot, db, picker)),
            IntervalTrigger(hours=POST_INTERVAL_HOURS),
            id="auto_post",
            name=f"Post every {POST_INTERVAL_HOURS} hours"
        )
        logger.info(f"Scheduled post every {POST_INTERVAL_HOURS} hours")

    scheduler.start()
    return scheduler

async def send_scheduled_post(bot, db, picker):
    is_active = db.get_setting("bot_active", "true")
    if is_active != "true":
        logger.info("Bot is paused, skipping scheduled post")
        return

    await send_post(bot, db, picker)

# ==================== MAIN ====================
async def main():
    logger.info("Starting Islamic Channel Bot - Images Only + Admin Dashboard...")

    if not BOT_TOKEN or not CHANNEL_ID:
        logger.error("Please set BOT_TOKEN and CHANNEL_ID")
        return

    db = Database()
    picker = SmartPicker(db)

    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    bot = application.bot

    # Command handlers
    application.add_handler(CommandHandler("start", admin_command))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CommandHandler("post", post_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("logs", logs_command))
    application.add_handler(CommandHandler("reset", reset_command))

    # Callback handler
    application.add_handler(CallbackQueryHandler(button_handler))

    # Setup scheduler
    scheduler = setup_scheduler(bot, db, picker)

    # Post first content
    logger.info("Posting first content...")
    await send_post(bot, db, picker)

    logger.info(f"Bot running! Posts every {POST_INTERVAL_HOURS} hours.")
    logger.info("Admin dashboard: /admin")

    # Start application
    await application.initialize()
    await application.start()
    await application.updater.start_polling()

    # Keep running
    try:
        while True:
            await asyncio.sleep(3600)
    except KeyboardInterrupt:
        logger.info("Bot stopped")
    finally:
        await application.updater.stop()
        await application.stop()
        await application.shutdown()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped")
    except Exception as e:
        logger.error(f"Error: {e}")
