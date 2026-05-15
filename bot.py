#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
بوت تليجرام لنشر محتوى ديني - بالعربي فقط
Telegram Islamic Content Bot - Arabic Only
"""

import os
import sys
import logging
import random
import sqlite3
import asyncio
import json
from datetime import datetime, timedelta

from telegram import Bot
from telegram.constants import ParseMode
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

# ==================== LOAD ARABIC CONTENT ====================
def load_arabic_content():
    """Load Arabic content from JSON file"""
    try:
        with open("content.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error("content.json not found!")
        return {"ayat": [], "ahadith": [], "athkar": [], "videos": []}

ARABIC_CONTENT = load_arabic_content()

# ==================== DATABASE ====================
class Database:
    def __init__(self):
        self.conn = sqlite3.connect(DB_FILE, check_same_thread=False)
        self.init_tables()
        self.seed_data()

    def init_tables(self):
        c = self.conn.cursor()

        tables = ["ayat", "ahadith", "athkar", "videos"]
        for table in tables:
            c.execute(f"""
                CREATE TABLE IF NOT EXISTS {table} (
                    id INTEGER PRIMARY KEY,
                    content TEXT NOT NULL,
                    extra1 TEXT,
                    extra2 TEXT,
                    extra3 TEXT,
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

        self.conn.commit()
        logger.info("Database initialized")

    def seed_data(self):
        c = self.conn.cursor()

        # Check if already has data
        c.execute("SELECT COUNT(*) FROM ayat")
        if c.fetchone()[0] > 0:
            logger.info("Database already has data")
            return

        logger.info("Adding Arabic content...")

        # Add Ayat
        for i, item in enumerate(ARABIC_CONTENT["ayat"], 1):
            content = json.dumps(item, ensure_ascii=False)
            c.execute("INSERT INTO ayat (id, content, extra1, extra2, extra3) VALUES (?, ?, ?, ?, ?)",
                      (i, content, item["surah"], str(item["ayah"]), item["tafsir"]))

        # Add Ahadith
        for i, item in enumerate(ARABIC_CONTENT["ahadith"], 1):
            content = json.dumps(item, ensure_ascii=False)
            c.execute("INSERT INTO ahadith (id, content, extra1, extra2, extra3) VALUES (?, ?, ?, ?, ?)",
                      (i, content, item["narrator"], item["source"], ""))

        # Add Athkar
        for i, item in enumerate(ARABIC_CONTENT["athkar"], 1):
            content = json.dumps(item, ensure_ascii=False)
            c.execute("INSERT INTO athkar (id, content, extra1, extra2, extra3) VALUES (?, ?, ?, ?, ?)",
                      (i, content, item["category"], "", ""))

        # Add Videos
        for i, item in enumerate(ARABIC_CONTENT["videos"], 1):
            content = json.dumps(item, ensure_ascii=False)
            c.execute("INSERT INTO videos (id, content, extra1, extra2, extra3) VALUES (?, ?, ?, ?, ?)",
                      (i, content, item["title"], item["url"], item["duration"]))

        self.conn.commit()
        logger.info(f"Added {len(ARABIC_CONTENT['ayat'])} ayat, {len(ARABIC_CONTENT['ahadith'])} hadith, {len(ARABIC_CONTENT['athkar'])} athkar, {len(ARABIC_CONTENT['videos'])} videos")

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
        for table in ["ayat", "ahadith", "athkar", "videos"]:
            c.execute(f"SELECT COUNT(*) FROM {table}")
            total = c.fetchone()[0]
            c.execute(f"SELECT COUNT(*) FROM {table} WHERE posted = 1")
            posted = c.fetchone()[0]
            stats[table] = {"total": total, "posted": posted, "remaining": total - posted}
        return stats

# ==================== SMART PICKER ====================
class SmartPicker:
    def __init__(self, db):
        self.db = db
        self.recent_types = []
        self.max_history = 4

    def pick_content(self):
        content_types = ["ayat", "ahadith", "athkar", "videos"]
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
def format_content(content_type, content_row):
    """Format content for Telegram - Arabic only"""
    _, content_json, extra1, extra2, extra3, _, _, _ = content_row
    item = json.loads(content_json)

    if content_type == "ayat":
        return f"""📖 <b>آية قرآنية</b>

{item['text']}

📍 <i>{item['surah']} - الآية {item['ayah']}</i>
📝 <i>{item['tafsir']}</i>

#آيات #قرآن #تدبر #آية_اليوم"""

    elif content_type == "ahadith":
        return f"""🌟 <b>حديث شريف</b>

❝ {item['text']} ❞

📚 رواه: <i>{item['narrator']}</i>
📖 المصدر: <i>{item['source']}</i>

#أحاديث #سنة #نبوية #حديث_اليوم"""

    elif content_type == "athkar":
        return f"""🤲 <b>ذكر طيب</b>

{item['text']}

📍 <i>التصنيف: {item['category']}</i>

#أذكار #أدعية #ذكر_الله #ذكر_اليوم"""

    elif content_type == "videos":
        return f"""🎥 <b>تلاوة قرآنية</b>

📌 {item['title']}
⏱️ المدة: {item['duration']}

🔗 <a href="{item['url']}">اضغط هنا للمشاهدة</a>

#قرآن #تلاوة #فيديو #تلاوة_اليوم"""

    return ""

# ==================== POSTING ====================
async def send_post(bot, db, picker):
    content_type, content = picker.pick_content()
    if not content:
        logger.error("No content available!")
        return False

    message = format_content(content_type, content)

    try:
        if content_type == "videos":
            await bot.send_message(
                chat_id=CHANNEL_ID,
                text=message,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=False
            )
        else:
            await bot.send_message(
                chat_id=CHANNEL_ID,
                text=message,
                parse_mode=ParseMode.HTML
            )

        db.mark_posted(content_type, content[0])
        logger.info(f"Posted: {content_type} (ID: {content[0]})")
        return True

    except Exception as e:
        logger.error(f"Error posting: {e}")
        return False

# ==================== SCHEDULER ====================
def setup_scheduler(bot, db, picker):
    scheduler = BackgroundScheduler()

    if POST_AT_SPECIFIC_TIMES:
        for time_str in SCHEDULED_TIMES:
            hour, minute = map(int, time_str.strip().split(":"))
            scheduler.add_job(
                lambda: asyncio.run(send_post(bot, db, picker)),
                CronTrigger(hour=hour, minute=minute),
                id=f"post_{hour}_{minute}",
                name=f"Post at {hour}:{minute:02d}"
            )
            logger.info(f"Scheduled post at {hour}:{minute:02d}")
    else:
        scheduler.add_job(
            lambda: asyncio.run(send_post(bot, db, picker)),
            IntervalTrigger(hours=POST_INTERVAL_HOURS),
            id="auto_post",
            name=f"Post every {POST_INTERVAL_HOURS} hours"
        )
        logger.info(f"Scheduled post every {POST_INTERVAL_HOURS} hours")

    scheduler.start()
    return scheduler

# ==================== MAIN ====================
async def main():
    logger.info("Starting Islamic Channel Bot - Arabic Only...")

    if not BOT_TOKEN or not CHANNEL_ID:
        logger.error("Please set BOT_TOKEN and CHANNEL_ID")
        return

    db = Database()
    picker = SmartPicker(db)

    bot = Bot(token=BOT_TOKEN)

    logger.info("Posting first content...")
    await send_post(bot, db, picker)

    scheduler = setup_scheduler(bot, db, picker)

    logger.info(f"Bot running! Posts every {POST_INTERVAL_HOURS} hours.")

    try:
        while True:
            await asyncio.sleep(3600)
    except KeyboardInterrupt:
        logger.info("Bot stopped")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped")
    except Exception as e:
        logger.error(f"Error: {e}")
