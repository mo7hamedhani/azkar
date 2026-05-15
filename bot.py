#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram Bot for Islamic Content Publishing
Compatible with Railway & Local hosting
"""

import os
import sys
import logging
import random
import sqlite3
import asyncio
from datetime import datetime, timedelta

from telegram import Bot, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes
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

# ==================== DATABASE ====================
class Database:
    def __init__(self):
        self.conn = sqlite3.connect(DB_FILE, check_same_thread=False)
        self.init_tables()

    def init_tables(self):
        c = self.conn.cursor()

        c.execute("""
            CREATE TABLE IF NOT EXISTS ayat (
                id INTEGER PRIMARY KEY,
                surah TEXT NOT NULL,
                ayah_number INTEGER,
                text TEXT NOT NULL,
                tafsir TEXT,
                posted INTEGER DEFAULT 0,
                posted_date TEXT,
                post_count INTEGER DEFAULT 0
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS ahadith (
                id INTEGER PRIMARY KEY,
                text TEXT NOT NULL,
                narrator TEXT,
                source TEXT,
                posted INTEGER DEFAULT 0,
                posted_date TEXT,
                post_count INTEGER DEFAULT 0
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS athkar (
                id INTEGER PRIMARY KEY,
                text TEXT NOT NULL,
                category TEXT,
                posted INTEGER DEFAULT 0,
                posted_date TEXT,
                post_count INTEGER DEFAULT 0
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS videos (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                duration TEXT,
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

        c.execute("SELECT COUNT(*) FROM ayat")
        if c.fetchone()[0] > 0:
            logger.info("Database already has data")
            return

        logger.info("Adding initial data...")

        # Quranic verses
        ayat = [
            ("Al-Fatiha", 1, "Bismi Allahi alrrahmani alrraheemi. Alhamdu lillahi rabbi alAAalameena. Alrrahmani alrraheemi. Maliki yawmi alddeeni. Iyyaka naAAbudu wa-iyyaka nastaAAeenu. Ihdina alssirata almustaqeema. Sirata allatheena anAAamta AAalayhim ghayri almaghdoobi AAalayhim wala alddalleena", "Surah Al-Fatiha"),
            ("Al-Baqarah", 255, "Allahu la ilaha illa huwa alhayyu alqayyoomu la takhuthuhu sinatun wala nawmun lahu ma fee alssamawati wama fee al-ardi man tha allathee yashfaAAu AAindahu illa bi-ithnihi yaAAlamu ma bayna aydeehim wama khalfahum wala yuheetoona bishay-in min AAilmihi illa bima sha-a wasiAAa kursiyyuhu alssamawati waal-arda wala yaooduhu hifzuhuma wahuwa alAAaliyyu alAAatheemu", "Ayat Al-Kursi"),
            ("Al-Baqarah", 286, "La yukallifu Allahu nafsan illa wusAAaha laha ma kasabat waAAalayha ma iktasabat rabbana la tu-akhithna in naseena aw akhta-na rabbana wala tahmil AAalayna isran kama hamaltahu AAala allatheena min qablina rabbana wala tuhammilna ma la taqata lana bihi waoAAfu AAanna waghfir lana warhamna anta mawlana faonsurna AAala alqawmi alkafireena", "Dua at end of Al-Baqarah"),
            ("Al-Ikhlas", 1, "Qul huwa Allahu ahadun. Allahu alssamadu. Lam yalid walam yooladu. Walam yakun lahu kufuwan ahadun", "Surah Al-Ikhlas - equals 1/3 of Quran"),
            ("Al-Falaq", 1, "Qul aAAoothu birabbi alfalaqi. Min sharri ma khalaqa. Wamin sharri ghasiqin itha waqaba. Wamin sharri alnnaffathati fee alAAuqadi. Wamin sharri hasidin itha hasada", "Surah Al-Falaq - Al-Muawwidhatain"),
            ("An-Nas", 1, "Qul aAAoothu birabbi alnnasi. Maliki alnnasi. Ilahi alnnasi. Min sharri alwaswasi alkhannasi. Allathee yuwaswisu fee sudoori alnnasi. Mina aljinni waalnnasi", "Surah An-Nas - Al-Muawwidhatain"),
            ("Ar-Rahman", 13, "Fabi-ayyi ala-i rabbikuma tukaththibani", "Repeated in Surah Ar-Rahman"),
            ("Ya-Sin", 82, "Innama amruhu itha arada shay-an an yaqoola lahu kun fayakoonu", "Surah Ya-Sin - Heart of Quran"),
            ("Al-Hashr", 21, "Law anzalna hatha alqurana AAala jabalin laraaytahu khashiAAan mutasaddiAAan min khashyati Allahi watilka al-amthalu nadribuha lilnnasi laAAallahum yatafakkaroona", "Glorification of Quran"),
            ("Al-An'am", 59, "WaAAindahu mafatihu alghaybi la yaAAlamuha illa huwa wayaAAlamu ma fee albarri waalbahri wama tasqutu min waraqatin illa yaAAlamuha wala habbatin fee thulumati al-ardi wala ratbin wala yabisin illa fee kitabin mubeenin", "Allah's encompassing knowledge"),
            ("Al-Baqarah", 152, "Fathkuroonee athkurkum waoshkuroo lee wala takfuroon", "Allah's promise to those who remember Him"),
            ("At-Talaq", 2, "Waman yattabiAA Allahu yajAAal lahu makhrajan wayarzuqhu min haythu la yahtasibu waman yatawakkal AAala Allahi fahuwa hasbuhu inna Allaha balighu amrihi qad jaAAala Allahu likulli shay-in qadran", "Taqwa and Tawakkul"),
            ("Ash-Shu'ara", 80, "Wa-itha maridtu fahuwa yashfeeni. Waallathee yumeetunee thumma yuhyeeni. Waallathee atmaAAu an yaghfira lee khatiyatee yawma alddeeni", "Prophet Ibrahim's dua"),
            ("Al-Isra", 23, "Waqada rabbuka alla taAAbudoo illa iyyahu wabilwalidayni ihsanan immā yablughanna AAindaka alkibara ahaduhuma aw kilahuma fala taqul lahuma uffin wala tanharhuma waqul lahuma qawlan kareeman", "Kindness to parents"),
            ("Al-Isra", 24, "Waikhfit lahuma janaha alththulli mina alrrahmati waqul rabbi irhamhuma kama rabbayanee sagheeran", "Dua for parents"),
        ]

        for surah, ayah, text, tafsir in ayat:
            c.execute("INSERT INTO ayat (surah, ayah_number, text, tafsir) VALUES (?, ?, ?, ?)",
                      (surah, ayah, text, tafsir))

        # Hadith
        ahadith = [
            ("Innama al-aAAmalu bialnniyati wa-innama likulli imri-in ma nawa fa-man kanat hijratuhu ila dunya yuseebuha aw ila imra-atin yankihuha fa-hijratuhu ila ma hajara ilayhi", "Umar ibn Al-Khattab RA", "Sahih Al-Bukhari (1) & Sahih Muslim (1907)"),
            ("Buniya al-islamu AAala khamsin: shahadati an la ilaha illa Allahu wa-anna Muhammadan rasoolu Allahi wa-iqami alssalati wa-ita-i alzzakati wa-alhajji wa-sawmi ramadana", "Ibn Umar RA", "Sahih Al-Bukhari (8) & Sahih Muslim (16)"),
            ("Man salla AAalayya salatan wahidatan salla Allahu AAalayhi AAashran", "Abu Hurairah RA", "Sahih Muslim (384)"),
            ("La yu-minu ahadukum hatta yuhibba li-akheehi ma yuhibbu li-nafsihi", "Anas ibn Malik RA", "Sahih Al-Bukhari (13) & Sahih Muslim (45)"),
            ("Man yaridi Allahu bihi khayran yufaqqihhu fee alddeeni", "Muawiyah RA", "Sahih Al-Bukhari (71)"),
            ("Alddeenu alnnaseehatu. Qulna: li-man? Qala: lillahi wa-li-kitabihi wa-li-rasoolihi wa-li-aimmati almuslimeena wa-AAammatihim", "Tamim Al-Dari RA", "Sahih Muslim (55)"),
            ("Man yaAAsi Allaha wa-rasoolahu faqad dalla dalalan mubeenan", "Abu Hurairah RA", "Sahih Al-Bukhari"),
            ("Inna Allaha tayyibun la yaqbalu illa tayyiban", "Abu Hurairah RA", "Sahih Muslim (1015)"),
            ("Almuslimu man salima almuslimoona min lisanihee wa-yadihi wa-almuhajiru man hajara ma nahaa Allahu AAanhu", "Abdullah ibn Amr RA", "Sahih Al-Bukhari (10)"),
            ("Man kana yu-minu bi-Allahi wa-al-yawmi al-akhiri fa-liyaqul khayran aw li-yasmut", "Abu Hurairah RA", "Sahih Al-Bukhari (6018) & Sahih Muslim (47)"),
            ("Tabassumuka fee wajhi akheeka laka sadaqatun", "Abu Dharr RA", "Tirmidhi (1956)"),
            ("Khayrukum man taAAallama alqurana wa-AAallamahu", "Uthman ibn Affan RA", "Sahih Al-Bukhari (5027)"),
            ("Alrrahimoona yarhamuhumu alrrahmanu irhamoo man fee al-ardi yarhamkum man fee alssama-i", "Abdullah ibn Amr RA", "Tirmidhi (1924)"),
            ("Man la yarhami alnnasa la yarhamahu Allahu", "Abu Hurairah RA", "Sahih Al-Bukhari (7376) & Sahih Muslim (2319)"),
            ("Alkalimatu alttayyibatu sadaqatun", "Abu Hurairah RA", "Sahih Al-Bukhari (2989) & Sahih Muslim (1009)"),
        ]

        for text, narrator, source in ahadith:
            c.execute("INSERT INTO ahadith (text, narrator, source) VALUES (?, ?, ?)",
                      (text, narrator, source))

        # Athkar
        athkar = [
            ("Subhana Allahi wa-bi-hamdihi: AAadada khalqihi wa-rida nafsihi wa-zinata AAarshihi wa-midada kalimatihi", "Tasbeeh"),
            ("Astaghfiru Allaha alAAatheema allathee la ilaha illa huwa alhayyu alqayyoomu wa-atubu ilayhi", "Istighfar"),
            ("Allahumma salli wa-sallim wa-barik AAala sayyidina Muhammadin", "Salat on Prophet"),
            ("La hawla wala quwwata illa bi-Allahi", "Dhikr"),
            ("Allahumma anta rabbi la ilaha illa anta khalaqtanee wa-ana AAabduka wa-ana AAala aahdika wa-waAAdika ma istataAAtu aAAoothu bika min sharri ma sanaAAtu aboo-u laka bi-niAAamatika AAalayya wa-aboo-u bi-dhanbee fa-ighfir lee fa-innahu la yaghfiru aldhdhunuba illa anta", "Morning Dua"),
            ("Bismi Allahi allathee la yadurru maAAa ismihi shay-un fee al-ardi wala fee alssama-i wa-huwa alssameeAAu alAAaleemu", "Morning & Evening Dhikr"),
            ("Radeetu bi-Allahi rabban wa-bi-al-islami deenan wa-bi-Muhammadin salla Allahu AAalayhi wa-sallam nabiyyan", "Rida"),
            ("Subhana Allahi wa-bi-hamdihi subhana Allahi alAAatheemi", "Tasbeeh"),
            ("Hasbuna Allahu wa-niAAma alwakeelu", "Tawakkul"),
            ("La ilaha illa anta subhanaka innee kuntu mina alththalimeena", "Dua of Yunus"),
            ("Allahumma innee as-aluka AAilman nafiAAan wa-rizqan tayyiban wa-AAamalan mutaqabbalan", "Dua"),
            ("aAAoothu bi-Allahi mina alshshaytani alrrajeemi", "Isti'adha"),
            ("Allahumma ajirnee mina alnnari", "Dua"),
            ("Allahumma ighfir lee wa-li-walidayya wa-lilmu-mineena yawma yaqoomu alhisabu", "Dua"),
            ("Subhana Allahi wa-alhamdu lillahi wa-la ilaha illa Allahu wa-Allahu akbaru", "Takbeerat"),
        ]

        for text, category in athkar:
            c.execute("INSERT INTO athkar (text, category) VALUES (?, ?)", (text, category))

        # Videos
        videos = [
            ("Surah Al-Fatiha - Sheikh Mishary Alafasy", "https://youtu.be/2DpOLL4Rj5o", "1:15"),
            ("Surah Al-Baqarah Complete - Sheikh Abdul Basit", "https://youtu.be/1apX9z2Vf4U", "1:58:20"),
            ("Ayat Al-Kursi - Sheikh Al-Sudais", "https://youtu.be/3QZ8g8v8Zz8", "2:30"),
            ("Surah Ya-Sin - Sheikh Maher Al-Muaiqly", "https://youtu.be/4Rz8Z8ZzZz8", "12:45"),
            ("Surah Ar-Rahman - Sheikh Yasser Al-Dosari", "https://youtu.be/5Sz9Z9ZzZz9", "18:30"),
            ("Surah Al-Waqi'ah - Sheikh Mishary Alafasy", "https://youtu.be/6Tz0T0T0T0T", "10:15"),
            ("Surah Al-Mulk - Sheikh Fares Abbad", "https://youtu.be/7Uu1U1U1U1U", "8:45"),
            ("Surah Al-Kahf - Sheikh Nasser Al-Qatami", "https://youtu.be/8Vv2V2V2V2V", "22:10"),
            ("Tajweed Surah Al-Ikhlas - Sheikh Minshawi", "https://youtu.be/9Ww3W3W3W3W", "1:00"),
            ("Dua Al-Qunoot - Sheikh Muhammad Jibreel", "https://youtu.be/0Xx4X4X4X4X", "5:20"),
        ]

        for title, url, duration in videos:
            c.execute("INSERT INTO videos (title, url, duration) VALUES (?, ?, ?)", (title, url, duration))

        self.conn.commit()
        logger.info(f"Added {len(ayat)} ayat, {len(ahadith)} hadith, {len(athkar)} athkar, {len(videos)} videos")

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

    def get_recent_posts(self, limit=10):
        c = self.conn.cursor()
        c.execute("SELECT content_type, content_id, posted_date, status FROM post_log ORDER BY posted_date DESC LIMIT ?", (limit,))
        return c.fetchall()

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
def format_content(content_type, content):
    if content_type == "ayat":
        _, surah, ayah, text, tafsir, _, _, _ = content
        return f"""📖 <b>Quranic Verse</b>

{text}

📍 <i>{surah} - Ayah {ayah}</i>
📝 <i>{tafsir}</i>

#Ayat #Quran #Tadabbur"""

    elif content_type == "ahadith":
        _, text, narrator, source, _, _, _ = content
        return f"""🌟 <b>Hadith</b>

❝ {text} ❞

📚 Narrated by: <i>{narrator}</i>
📖 Source: <i>{source}</i>

#Hadith #Sunnah #Prophetic"""

    elif content_type == "athkar":
        _, text, category, _, _, _ = content
        return f"""🤲 <b>Dhikr</b>

{text}

📍 <i>Category: {category}</i>

#Athkar #Adhkar #Dhikr"""

    elif content_type == "videos":
        _, title, url, duration, _, _, _ = content
        return f"""🎥 <b>Quran Recitation</b>

📌 {title}
⏱️ Duration: {duration}

🔗 <a href="{url}">Click here to watch</a>

#Quran #Tilawa #Video"""

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

# ==================== ADMIN COMMANDS ====================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("This bot is for admin only.")
        return

    await update.message.reply_text(
        "Welcome to Islamic Channel Bot!\n\n"
        "Commands:\n"
        "/post - Post immediately\n"
        "/stats - Content statistics\n"
        "/logs - Recent posts\n"
        "/reset - Reset all content\n"
        "/help - Help"
    )

async def post_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("Unauthorized.")
        return

    await update.message.reply_text("Posting...")

    bot = context.bot
    db = Database()
    picker = SmartPicker(db)

    success = await send_post(bot, db, picker)

    if success:
        await update.message.reply_text("Posted successfully!")
    else:
        await update.message.reply_text("Failed to post.")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("Unauthorized.")
        return

    db = Database()
    stats = db.get_stats()

    msg = "📊 <b>Content Statistics</b>\n\n"
    for table, data in stats.items():
        emoji = {"ayat": "📖", "ahadith": "🌟", "athkar": "🤲", "videos": "🎥"}[table]
        msg += f"{emoji} <b>{table}:</b> {data['posted']}/{data['total']} (remaining: {data['remaining']})\n"

    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

async def logs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("Unauthorized.")
        return

    db = Database()
    posts = db.get_recent_posts(10)

    msg = "📋 <b>Last 10 Posts</b>\n\n"
    for post in posts:
        content_type, content_id, date, status = post
        emoji = {"ayat": "📖", "ahadith": "🌟", "athkar": "🤲", "videos": "🎥"}[content_type]
        msg += f"{emoji} {content_type} (ID:{content_id}) - {date}\n"

    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("Unauthorized.")
        return

    db = Database()
    for table in ["ayat", "ahadith", "athkar", "videos"]:
        db.reset_table(table)

    await update.message.reply_text("All content reset!")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("Unauthorized.")
        return

    help_text = f"""📖 <b>Bot Guide</b>

<b>Commands:</b>
/start - Start bot
/post - Post immediately
/stats - Content statistics
/logs - Post history
/reset - Reset content
/help - This guide

<b>Notes:</b>
• Bot posts automatically every {POST_INTERVAL_HOURS} hours
• Content does not repeat until all is used
• Manual posting with /post
• Bot rotates between ayat, hadith, athkar, videos

<b>Support:</b>
Contact admin"""

    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML)

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
    logger.info("Starting Islamic Channel Bot...")

    if not BOT_TOKEN or not CHANNEL_ID:
        logger.error("Please set BOT_TOKEN and CHANNEL_ID")
        return

    db = Database()
    db.seed_data()
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
