#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
بوت تليجرام لنشر محتوى ديني - فيديوهات + صور + نصوص
Telegram Islamic Content Bot - Videos + Photos + Text
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

from telegram import Bot, InputFile
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

# ==================== LOAD CONTENT ====================
def load_content():
    try:
        with open("content.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error("content.json not found!")
        return {"ayat": [], "ahadith": [], "athkar": [], "videos": [], "images": []}

CONTENT = load_content()

# ==================== DATABASE ====================
class Database:
    def __init__(self):
        self.conn = sqlite3.connect(DB_FILE, check_same_thread=False)
        self.init_tables()
        self.seed_data()

    def init_tables(self):
        c = self.conn.cursor()

        tables = ["ayat", "ahadith", "athkar", "videos", "images"]
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

        self.conn.commit()
        logger.info("Database initialized")

    def seed_data(self):
        c = self.conn.cursor()

        # Check if already has data
        c.execute("SELECT COUNT(*) FROM ayat")
        if c.fetchone()[0] > 0:
            logger.info("Database already has data")
            return

        logger.info("Adding content...")

        # Add Ayat (text + image URL from Quran.com)
        for i, item in enumerate(CONTENT.get("ayat", []), 1):
            content = json.dumps(item, ensure_ascii=False)
            # Generate image URL for ayah (Quran.com API)
            image_url = f"https://cdn.islamic.network/quran/images/{item['surah']}_{item['ayah']}.png"
            c.execute("INSERT INTO ayat (id, content, media_type, media_url) VALUES (?, ?, ?, ?)",
                      (i, content, 'image', image_url))

        # Add Ahadith (text only)
        for i, item in enumerate(CONTENT.get("ahadith", []), 1):
            content = json.dumps(item, ensure_ascii=False)
            c.execute("INSERT INTO ahadith (id, content, media_type) VALUES (?, ?, ?)",
                      (i, content, 'text'))

        # Add Athkar (text only)
        for i, item in enumerate(CONTENT.get("athkar", []), 1):
            content = json.dumps(item, ensure_ascii=False)
            c.execute("INSERT INTO athkar (id, content, media_type) VALUES (?, ?, ?)",
                      (i, content, 'text'))

        # Add Videos (short videos < 50MB)
        for i, item in enumerate(CONTENT.get("videos", []), 1):
            content = json.dumps(item, ensure_ascii=False)
            # Check if it's a file_id or URL
            media_type = 'video_file' if item.get('file_id') else 'video_url'
            media_url = item.get('file_id', item.get('url', ''))
            c.execute("INSERT INTO videos (id, content, media_type, media_url) VALUES (?, ?, ?, ?)",
                      (i, content, media_type, media_url))

        # Add Images
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
        for table in ["ayat", "ahadith", "athkar", "videos", "images"]:
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
        self.max_history = 5

    def pick_content(self):
        # Prioritize: videos > images > ayat > ahadith > athkar
        content_types = ["videos", "images", "ayat", "ahadith", "athkar"]

        # Don't repeat same type in last 2 posts
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

        # Try any available content
        for t in content_types:
            self.db.reset_table(t)
            content = self.db.get_unposted(t)
            if content:
                self.recent_types.append(t)
                return t, content

        return None, None

# ==================== MESSAGE FORMATTING ====================
def format_caption(content_type, content_row):
    """Format caption for media posts"""
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

    elif content_type == "videos":
        return f"""🎥 <b>تلاوة قرآنية</b>

📌 {item['title']}
⏱️ المدة: {item['duration']}

#قرآن #تلاوة #فيديو"""

    elif content_type == "images":
        return f"""📸 <b>صورة دينية</b>

{item.get('description', '')}

#إسلامي #صورة #تذكير"""

    return ""

# ==================== POSTING ====================
async def send_post(bot, db, picker):
    content_type, content = picker.pick_content()
    if not content:
        logger.error("No content available!")
        return False

    content_id, content_json, media_type, media_url, _, _, _ = content
    item = json.loads(content_json)
    caption = format_caption(content_type, content)

    try:
        if content_type == "videos" and media_type == "video_file" and media_url:
            # Send video using file_id (uploaded to Telegram before)
            await bot.send_video(
                chat_id=CHANNEL_ID,
                video=media_url,  # file_id
                caption=caption,
                parse_mode=ParseMode.HTML,
                supports_streaming=True
            )
            logger.info(f"Sent video file: {content_type} (ID: {content_id})")

        elif content_type == "videos" and media_type == "video_url":
            # For YouTube URLs, send as text with link preview
            await bot.send_message(
                chat_id=CHANNEL_ID,
                text=caption + f"\n\n🔗 {media_url}",
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=False
            )
            logger.info(f"Sent video URL: {content_type} (ID: {content_id})")

        elif content_type in ["ayat", "images"] and media_url:
            # Try to send image from URL
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
                    # Fallback to text
                    await bot.send_message(
                        chat_id=CHANNEL_ID,
                        text=caption,
                        parse_mode=ParseMode.HTML
                    )
                    logger.info(f"Sent text (image failed): {content_type} (ID: {content_id})")
            except Exception as img_error:
                logger.warning(f"Image failed: {img_error}, sending text instead")
                await bot.send_message(
                    chat_id=CHANNEL_ID,
                    text=caption,
                    parse_mode=ParseMode.HTML
                )
                logger.info(f"Sent text fallback: {content_type} (ID: {content_id})")
        else:
            # Text only
            await bot.send_message(
                chat_id=CHANNEL_ID,
                text=caption,
                parse_mode=ParseMode.HTML
            )
            logger.info(f"Sent text: {content_type} (ID: {content_id})")

        db.mark_posted(content_type, content_id)
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
    logger.info("Starting Islamic Channel Bot - Videos + Photos + Text...")

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
