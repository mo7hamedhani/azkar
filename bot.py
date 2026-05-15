#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
بوت تليجرام لنشر محتوى ديني في القناة
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

# ==================== تحميل الإعدادات ====================
def load_config():
    """يحمل الإعدادات من متغيرات البيئة (Railway) أو ملف .env"""

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
        logger.error("❌ BOT_TOKEN غير موجود!")
        sys.exit(1)

    if not config["CHANNEL_ID"]:
        logger.error("❌ CHANNEL_ID غير موجود!")
        sys.exit(1)

    try:
        config["CHANNEL_ID"] = int(config["CHANNEL_ID"])
        config["ADMIN_ID"] = int(config["ADMIN_ID"]) if config["ADMIN_ID"] else 0
        config["POST_INTERVAL_HOURS"] = int(config["POST_INTERVAL_HOURS"])
    except ValueError as e:
        logger.error(f"❌ خطأ في تحويل الأرقام: {e}")
        sys.exit(1)

    return config

CONFIG = load_config()
BOT_TOKEN = CONFIG["BOT_TOKEN"]
CHANNEL_ID = CONFIG["CHANNEL_ID"]
ADMIN_ID = CONFIG["ADMIN_ID"]
POST_INTERVAL_HOURS = CONFIG["POST_INTERVAL_HOURS"]
POST_AT_SPECIFIC_TIMES = CONFIG["POST_AT_SPECIFIC_TIMES"] == "true"
SCHEDULED_TIMES = CONFIG["SCHEDULED_TIMES"].split(",")

# ==================== الإعدادات العامة ====================
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

# ==================== قاعدة البيانات ====================
class Database:
    def __init__(self):
        self.conn = sqlite3.connect(DB_FILE, check_same_thread=False)
        self.init_tables()

    def init_tables(self):
        c = self.conn.cursor()

        c.execute('''
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
        ''')

        c.execute('''
            CREATE TABLE IF NOT EXISTS ahadith (
                id INTEGER PRIMARY KEY,
                text TEXT NOT NULL,
                narrator TEXT,
                source TEXT,
                posted INTEGER DEFAULT 0,
                posted_date TEXT,
                post_count INTEGER DEFAULT 0
            )
        ''')

        c.execute('''
            CREATE TABLE IF NOT EXISTS athkar (
                id INTEGER PRIMARY KEY,
                text TEXT NOT NULL,
                category TEXT,
                posted INTEGER DEFAULT 0,
                posted_date TEXT,
                post_count INTEGER DEFAULT 0
            )
        ''')

        c.execute('''
            CREATE TABLE IF NOT EXISTS videos (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                duration TEXT,
                posted INTEGER DEFAULT 0,
                posted_date TEXT,
                post_count INTEGER DEFAULT 0
            )
        ''')

        c.execute('''
            CREATE TABLE IF NOT EXISTS post_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content_type TEXT,
                content_id INTEGER,
                posted_date TEXT,
                status TEXT
            )
        ''')

        self.conn.commit()
        logger.info("✅ تم تهيئة قاعدة البيانات")

    def seed_data(self):
        c = self.conn.cursor()

        c.execute("SELECT COUNT(*) FROM ayat")
        if c.fetchone()[0] > 0:
            logger.info("📊 قاعدة البيانات تحتوي على بيانات بالفعل")
            return

        logger.info("📝 جاري إضافة البيانات الأولية...")

        ayat = [
            ("الفاتحة", 1, "بِسْمِ اللَّهِ الرَّحْمَٰنِ الرَّحِيمِ ○ الْحَمْدُ لِلَّهِ رَبِّ الْعَالَمِينَ ○ الرَّحْمَٰنِ الرَّحِيمِ ○ مَالِكِ يَوْمِ الدِّينِ ○ إِيَّاكَ نَعْبُدُ وَإِيَّاكَ نَسْتَعِينُ ○ اهْدِنَا الصِّرَاطَ الْمُسْتَقِيمَ ○ صِرَاطَ الَّذِينَ أَنْعَمْتَ عَلَيْهِمْ غَيْرِ الْمَغْضُوبِ عَلَيْهِمْ وَلَا الضَّالِّينَ", "سورة الفاتحة"),
            ("البقرة", 255, "اللَّهُ لَا إِلَٰهَ إِلَّا هُوَ الْحَيُّ الْقَيُّومُ ۚ لَا تَأْخُذُهُ سِنَةٌ وَلَا نَوْمٌ ۚ لَّهُ مَا فِي السَّمَاوَاتِ وَمَا فِي الْأَرْضِ ۗ مَن ذَا الَّذِي يَشْفَعُ عِندَهُ إِلَّا بِإِذْنِهِ ۚ يَعْلَمُ مَا بَيْنَ أَيْدِيهِمْ وَمَا خَلْفَهُمْ ۖ وَلَا يُحِيطُونَ بِشَيْءٍ مِّنْ عِلْمِهِ إِلَّا بِمَا شَاءَ ۚ وَسِعَ كُرْسِيُّهُ السَّمَاوَاتِ وَالْأَرْضَ ۖ وَلَا يَئُودُهُ حِفْظُهُمَا ۚ وَهُوَ الْعَلِيُّ الْعَظِيمُ", "آية الكرسي"),
            ("البقرة", 286, "لَا يُكَلِّفُ اللَّهُ نَفْسًا إِلَّا وُسْعَهَا ۚ لَهَا مَا كَسَبَتْ وَعَلَيْهَا مَا اكْتَسَبَتْ ۗ رَبَّنَا لَا تُؤَاخِذْنَا إِن نَّسِينَا أَوْ أَخْطَأْنَا ۚ رَبَّنَا وَلَا تَحْمِلْ عَلَيْنَا إِصْرًا كَمَا حَمَلْتَهُ عَلَى الَّذِينَ مِن قَبْلِنَا ۚ رَبَّنَا وَلَا تُحَمِّلْنَا مَا لَا طَاقَةَ لَنَا بِهِ ۖ وَاعْفُ عَنَّا وَاغْفِرْ لَنَا وَارْحَمْنَا ۚ أَنتَ مَوْلَانَا فَانصُرْنَا عَلَى الْقَوْمِ الْكَافِرِينَ", "دعاء ختام سورة البقرة"),
            ("الإخلاص", 1, "قُلْ هُوَ اللَّهُ أَحَدٌ ○ اللَّهُ الصَّمَدُ ○ لَمْ يَلِدْ وَلَمْ يُولَدْ ○ وَلَمْ يَكُن لَّهُ كُفُوًا أَحَدٌ", "سورة الإخلاص - تعدل ثلث القرآن"),
            ("الفلق", 1, "قُلْ أَعُوذُ بِرَبِّ الْفَلَقِ ○ مِن شَرِّ مَا خَلَقَ ○ وَمِن شَرِّ غَاسِقٍ إِذَا وَقَبَ ○ وَمِن شَرِّ النَّفَّاثَاتِ فِي الْعُقَدِ ○ وَمِن شَرِّ حَاسِدٍ إِذَا حَسَدَ", "سورة الفلق - المعوذتين"),
            ("الناس", 1, "قُلْ أَعُوذُ بِرَبِّ النَّاسِ ○ مَلِكِ النَّاسِ ○ إِلَٰهِ النَّاسِ ○ مِن شَرِّ الْوَسْوَاسِ الْخَنَّاسِ ○ الَّذِي يُوَسْوِسُ فِي صُدُورِ النَّاسِ ○ مِنَ الْجِنَّةِ وَالنَّاسِ", "سورة الناس - المعوذتين"),
            ("الرحمن", 13, "فَبِأَيِّ آلَاءِ رَبِّكُمَا تُكَذِّبَانِ", "تكرار في سورة الرحمن"),
            ("يس", 82, "إِنَّمَا أَمْرُهُ إِذَا أَرَادَ شَيْئًا أَن يَقُولَ لَهُ كُن فَيَكُونُ", "سورة 36 - قلب القرآن"),
            ("الحشر", 21, "لَوْ أَنزَلْنَا هَٰذَا الْقُرْآنَ عَلَىٰ جَبَلٍ لَّرَأَيْتَهُ خَاشِعًا مُّتَصَدِّعًا مِّنْ خَشْيَةِ اللَّهِ ۚ وَتِلْكَ الْأَمْثَالُ نَضْرِبُهَا لِلنَّاسِ لَعَلَّهُمْ يَتَفَكَّرُونَ", "تعظيم القرآن"),
            ("الأنعام", 59, "وَعِندَهُ مَفَاتِحُ الْغَيْبِ لَا يَعْلَمُهَا إِلَّا هُوَ ۚ وَيَعْلَمُ مَا فِي الْبَرِّ وَالْبَحْرِ ۚ وَمَا تَسْقُطُ مِن وَرَقَةٍ إِلَّا يَعْلَمُهَا وَلَا حَبَّةٍ فِي ظُلُمَاتِ الْأَرْضِ وَلَا رَطْبٍ وَلَا يَابِسٍ إِلَّا فِي كِتَابٍ مُّبِينٍ", "علم الله المحيط"),
            ("البقرة", 152, "فَاذْكُرُونِي أَذْكُرْكُمْ وَاشْكُرُوا لِي وَلَا تَكْفُرُونِ", "وعد الله لأهل الذكر"),
            ("الطلاق", 2, "وَمَن يَتَّقِ اللَّهَ يَجْعَل لَّهُ مَخْرَجًا ○ وَيَرْزُقْهُ مِنْ حَيْثُ لَا يَحْتَسِبُ ○ وَمَن يَتَوَكَّلْ عَلَى اللَّهِ فَهُوَ حَسْبُهُ ○ إِنَّ اللَّهَ بَالِغُ أَمْرِهِ ○ قَدْ جَعَلَ اللَّهُ لِكُلِّ شَيْءٍ قَدْرًا", "التقوى والتوكل"),
            ("الشعراء", 80, "وَإِذَا مَرِضْتُ فَهُوَ يَشْفِينِ ○ وَالَّذِي يُمِيتُنِي ثُمَّ يُحْيِينِ ○ وَالَّذِي أَطْمَعُ أَن يَغْفِرَ لِي خَطِيئَتِي يَوْمَ الدِّينِ", "دعاء سيدنا إبراهيم"),
            ("الإسراء", 23, "وَقَضَىٰ رَبُّكَ أَلَّا تَعْبُدُوا إِلَّا إِيَّاهُ وَبِالْوَالِدَيْنِ إِحْسَانًا ۚ إِمَّا يَبْلُغَنَّ عِندَكَ الْكِبَرَ أَحَدُهُمَا أَوْ كِلَاهُمَا فَلَا تَقُل لَّهُمَا أُفٍّ وَلَا تَنْهَرْهُمَا وَقُل لَّهُمَا قَوْلًا كَرِيمًا", "بر الوالدين"),
            ("الإسراء", 24, "وَاخْفِضْ لَهُمَا جَنَاحَ الذُّلِّ مِنَ الرَّحْمَةِ وَقُل رَّبِّ ارْحَمْهُمَا كَمَا رَبَّيَانِي صَغِيرًا", "دعاء للوالدين"),
        ]

        for surah, ayah, text, tafsir in ayat:
            c.execute("INSERT INTO ayat (surah, ayah_number, text, tafsir) VALUES (?, ?, ?, ?)",
                      (surah, ayah, text, tafsir))

        ahadith = [
            ("إِنَّمَا الأَعْمَالُ بِالنِّيَّاتِ، وَإِنَّمَا لِكُلِّ امْرِئٍ مَا نَوَىٰ، فَمَنْ كَانَتْ هِجْرَتُهُ إِلَىٰ دُنْيَا يُصِيبُهَا أَوْ إِلَىٰ امْرَأَةٍ يَنْكِحُهَا فَهِجْرَتُهُ إِلَىٰ مَا هَاجَرَ إِلَيْهِ", "عمر بن الخطاب رضي الله عنه", "صحيح البخاري (1) وصحيح مسلم (1907)"),
            ("بُنِيَ الإِسْلَامُ عَلَىٰ خَمْسٍ: شَهَادَةِ أَنْ لَا إِلَٰهَ إِلَّا اللَّهُ وَأَنَّ مُحَمَّدًا رَسُولُ اللَّهِ، وَإِقَامِ الصَّلَاةِ، وَإِيتَاءِ الزَّكَاةِ، وَالْحَجِّ، وَصَوْمِ رَمَضَانَ", "ابن عمر رضي الله عنهما", "صحيح البخاري (8) وصحيح مسلم (16)"),
            ("مَنْ صَلَّىٰ عَلَيَّ صَلَاةً وَاحِدَةً صَلَّىٰ اللَّهُ عَلَيْهِ عَشْرًا", "أبو هريرة رضي الله عنه", "صحيح مسلم (384)"),
            ("لَا يُؤْمِنُ أَحَدُكُمْ حَتَّىٰ يُحِبَّ لِأَخِيهِ مَا يُحِبُّ لِنَفْسِهِ", "أنس بن مالك رضي الله عنه", "صحيح البخاري (13) وصحيح مسلم (45)"),
            ("مَنْ يُرِدِ اللَّهُ بِهِ خَيْرًا يُفَقِّهْهُ فِي الدِّينِ", "مُعَاوِيَةَ رضي الله عنه", "صحيح البخاري (71)"),
            ("الدِّينُ النَّصِيحَةُ. قُلْنَا: لِمَنْ؟ قَالَ: لِلَّهِ وَلِكِتَابِهِ وَلِرَسُولِهِ وَلِأَئِمَّةِ الْمُسْلِمِينَ وَعَامَّتِهِمْ", "تميم الداري رضي الله عنه", "صحيح مسلم (55)"),
            ("مَنْ يَعْصِ اللَّهَ وَرَسُولَهُ فَقَدْ ضَلَّ ضَلَالًا مُبِينًا", "أبو هريرة رضي الله عنه", "صحيح البخاري"),
            ("إِنَّ اللَّهَ طَيِّبٌ لَا يَقْبَلُ إِلَّا طَيِّبًا", "أبو هريرة رضي الله عنه", "صحيح مسلم (1015)"),
            ("الْمُسْلِمُ مَنْ سَلِمَ الْمُسْلِمُونَ مِنْ لِسَانِهِ وَيَدِهِ، وَالْمُهَاجِرُ مَنْ هَجَرَ مَا نَهَىٰ اللَّهُ عَنْهُ", "عبد الله بن عمرو رضي الله عنهما", "صحيح البخاري (10)"),
            ("مَنْ كَانَ يُؤْمِنُ بِاللَّهِ وَالْيَوْمِ الْآخِرِ فَلْيَقُلْ خَيْرًا أَوْ لِيَصْمُتْ", "أبو هريرة رضي الله عنه", "صحيح البخاري (6018) وصحيح مسلم (47)"),
            ("تَبَسُّمُكَ فِي وَجْهِ أَخِيكَ لَكَ صَدَقَةٌ", "أبو ذر رضي الله عنه", "الترمذي (1956)"),
            ("خَيْرُكُمْ مَنْ تَعَلَّمَ الْقُرْآنَ وَعَلَّمَهُ", "عثمان بن عفان رضي الله عنه", "صحيح البخاري (5027)"),
            ("الرَّاحِمُونَ يَرْحَمُهُمُ الرَّحْمَٰنُ، ارْحَمُوا مَنْ فِي الْأَرْضِ يَرْحَمْكُمْ مَنْ فِي السَّمَاءِ", "عبد الله بن عمرو رضي الله عنهما", "الترمذي (1924)"),
            ("مَنْ لَا يَرْحَمِ النَّاسَ لَا يَرْحَمْهُ اللَّهُ", "أبو هريرة رضي الله عنه", "صحيح البخاري (7376) وصحيح مسلم (2319)"),
            ("الْكَلِمَةُ الطَّيِّبَةُ صَدَقَةٌ", "أبو هريرة رضي الله عنه", "صحيح البخاري (2989) وصحيح مسلم (1009)"),
        ]

        for text, narrator, source in ahadith:
            c.execute("INSERT INTO ahadith (text, narrator, source) VALUES (?, ?, ?)",
                      (text, narrator, source))

        athkar = [
            ("سُبْحَانَ اللَّهِ وَبِحَمْدِهِ: عَدَدَ خَلْقِهِ، وَرِضَا نَفْسِهِ، وَزِنَةَ عَرْشِهِ، وَمِدَادَ كَلِمَاتِهِ", "تسبيح"),
            ("أَسْتَغْفِرُ اللَّهَ الْعَظِيمَ الَّذِي لَا إِلَٰهَ إِلَّا هُوَ الْحَيُّ الْقَيُّومُ وَأَتُوبُ إِلَيْهِ", "استغفار"),
            ("اللَّهُمَّ صَلِّ وَسَلِّمْ وَبَارِكْ عَلَىٰ سَيِّدِنَا مُحَمَّدٍ", "صلاة على النبي"),
            ("لَا حَوْلَ وَلَا قُوَّةَ إِلَّا بِاللَّهِ", "ذكر"),
            ("اللَّهُمَّ أَنْتَ رَبِّي لَا إِلَٰهَ إِلَّا أَنْتَ، خَلَقْتَنِي وَأَنَا عَبْدُكَ، وَأَنَا عَلَىٰ عَهْدِكَ وَوَعْدِكَ مَا اسْتَطَعْتُ، أَعُوذُ بِكَ مِنْ شَرِّ مَا صَنَعْتُ، أَبُوءُ لَكَ بِنِعْمَتِكَ عَلَيَّ، وَأَبُوءُ بِذَنْبِي فَاغْفِرْ لِي فَإِنَّهُ لَا يَغْفِرُ الذُّنُوبَ إِلَّا أَنْتَ", "دعاء الصباح"),
            ("بِسْمِ اللَّهِ الَّذِي لَا يَضُرُّ مَعَ اسْمِهِ شَيْءٌ فِي الْأَرْضِ وَلَا فِي السَّمَاءِ، وَهُوَ السَّمِيعُ الْعَلِيمُ", "أذكار الصباح والمساء"),
            ("رَضِيتُ بِاللَّهِ رَبًّا، وَبِالْإِسْلَامِ دِينًا، وَبِمُحَمَّدٍ صَلَّىٰ اللَّهُ عَلَيْهِ وَسَلَّمَ نَبِيًّا", "رضا"),
            ("سُبْحَانَ اللَّهِ وَبِحَمْدِهِ سُبْحَانَ اللَّهِ الْعَظِيمِ", "تسبيح"),
            ("حَسْبُنَا اللَّهُ وَنِعْمَ الْوَكِيلُ", "توكل"),
            ("لَا إِلَٰهَ إِلَّا أَنْتَ سُبْحَانَكَ إِنِّي كُنْتُ مِنَ الظَّالِمِينَ", "دعاء يونس"),
            ("اللَّهُمَّ إِنِّي أَسْأَلُكَ عِلْمًا نَافِعًا، وَرِزْقًا طَيِّبًا، وَعَمَلًا مُتَقَبَّلًا", "دعاء"),
            ("أَعُوذُ بِاللَّهِ مِنَ الشَّيْطَانِ الرَّجِيمِ", "استعاذة"),
            ("اللَّهُمَّ أَجِرْنِي مِنَ النَّارِ", "دعاء"),
            ("اللَّهُمَّ اغْفِرْ لِي وَلِوَالِدَيَّ وَلِلْمُؤْمِنِينَ يَوْمَ يَقُومُ الْحِسَابُ", "دعاء"),
            ("سُبْحَانَ اللَّهِ، وَالْحَمْدُ لِلَّهِ، وَلَا إِلَٰهَ إِلَّا اللَّهُ، وَاللَّهُ أَكْبَرُ", "تكبيرات"),
        ]

        for text, category in athkar:
            c.execute("INSERT INTO athkar (text, category) VALUES (?, ?)", (text, category))

        videos = [
            ("سورة الفاتحة - الشيخ مشاري العفاسي", "https://youtu.be/2DpOLL4Rj5o", "1:15"),
            ("سورة البقرة كاملة - الشيخ عبد الباسط عبد الصمد", "https://youtu.be/1apX9z2Vf4U", "1:58:20"),
            ("آية الكرسي - الشيخ السديس", "https://youtu.be/3QZ8g8v8Zz8", "2:30"),
            ("سورة يس - الشيخ ماهر المعيقلي", "https://youtu.be/4Rz8Z8ZzZz8", "12:45"),
            ("سورة الرحمن - الشيخ ياسر الدوسري", "https://youtu.be/5Sz9Z9ZzZz9", "18:30"),
            ("سورة الواقعة - الشيخ مشاري العفاسي", "https://youtu.be/6Tz0T0T0T0T", "10:15"),
            ("سورة الملك - الشيخ فارس عباد", "https://youtu.be/7Uu1U1U1U1U", "8:45"),
            ("سورة الكهف - الشيخ ناصر القطامي", "https://youtu.be/8Vv2V2V2V2V", "22:10"),
            ("تجويد سورة الإخلاص - الشيخ المنشاوي", "https://youtu.be/9Ww3W3W3W3W", "1:00"),
            ("دعاء القنوت - الشيخ محمد جبريل", "https://youtu.be/0Xx4X4X4X4X", "5:20"),
        ]

        for title, url, duration in videos:
            c.execute("INSERT INTO videos (title, url, duration) VALUES (?, ?, ?)", (title, url, duration))

        self.conn.commit()
        logger.info(f"✅ تم إضافة {len(ayat)} آية، {len(ahadith)} حديث، {len(athkar)} ذكر، {len(videos)} فيديو")

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
        logger.info(f"🔄 تم إعادة تعيين {table_name}")

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

# ==================== نظام الاختيار الذكي ====================
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

# ==================== تنسيق الرسائل ====================
def format_content(content_type, content):
    if content_type == "ayat":
        _, surah, ayah, text, tafsir, _, _, _ = content
        return f"""📖 <b>آية قرآنية</b>

{text}

📍 <i>{surah} - الآية {ayah}</i>
📝 <i>{tafsir}</i>

#آيات #قرآن #تدبر #آية_اليوم"""

    elif content_type == "ahadith":
        _, text, narrator, source, _, _, _ = content
        return f"""🌟 <b>حديث شريف</b>

❝ {text} ❞

📚 رواه: <i>{narrator}</i>
📖 المصدر: <i>{source}</i>

#أحاديث #سنة #نبوية #حديث_اليوم"""

    elif content_type == "athkar":
        _, text, category, _, _, _ = content
        return f"""🤲 <b>ذكر طيب</b>

{text}

📍 <i>التصنيف: {category}</i>

#أذكار #أدعية #ذكر_الله #ذكر_اليوم"""

    elif content_type == "videos":
        _, title, url, duration, _, _, _ = content
        return f"""🎥 <b>تلاوة قرآنية</b>

📌 {title}
⏱️ المدة: {duration}

🔗 <a href="{url}">اضغط هنا للمشاهدة</a>

#قرآن #تلاوة #فيديو #تلاوة_اليوم"""

    return ""

# ==================== إرسال المنشورات ====================
async def send_post(bot, db, picker):
    content_type, content = picker.pick_content()
    if not content:
        logger.error("❌ لا يوجد محتوى متاح!")
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
        logger.info(f"✅ تم النشر: {content_type} (ID: {content[0]})")
        return True

    except Exception as e:
        logger.error(f"❌ خطأ في النشر: {e}")
        return False

# ==================== أوامر البوت للأدمن ====================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ هذا البوت خاص بالأدمن فقط.")
        return

    await update.message.reply_text(
        "👋 أهلاً بك في بوت القناة الدينية!

"
        "الأوامر المتاحة:
"
        "/post - نشر منشور فوري
"
        "/stats - إحصائيات المحتوى
"
        "/logs - آخر المنشورات
"
        "/reset - إعادة تعيين المحتوى
"
        "/help - المساعدة"
    )

async def post_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ غير مصرح.")
        return

    await update.message.reply_text("⏳ جاري النشر...")

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
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ غير مصرح.")
        return

    db = Database()
    stats = db.get_stats()

    msg = "📊 <b>إحصائيات المحتوى</b>

"
    for table, data in stats.items():
        emoji = {"ayat": "📖", "ahadith": "🌟", "athkar": "🤲", "videos": "🎥"}[table]
        msg += f"{emoji} <b>{table}:</b> {data['posted']}/{data['total']} (متبقي: {data['remaining']})
"

    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

async def logs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ غير مصرح.")
        return

    db = Database()
    posts = db.get_recent_posts(10)

    msg = "📋 <b>آخر 10 منشورات</b>

"
    for post in posts:
        content_type, content_id, date, status = post
        emoji = {"ayat": "📖", "ahadith": "🌟", "athkar": "🤲", "videos": "🎥"}[content_type]
        msg += f"{emoji} {content_type} (ID:{content_id}) - {date}
"

    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ غير مصرح.")
        return

    db = Database()
    for table in ["ayat", "ahadith", "athkar", "videos"]:
        db.reset_table(table)

    await update.message.reply_text("🔄 تم إعادة تعيين جميع المحتويات!")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ غير مصرح.")
        return

    help_text = f"""📖 <b>دليل استخدام البوت</b>

<b>الأوامر:</b>
/start - بدء البوت
/post - نشر منشور فوري
/stats - عرض إحصائيات المحتوى
/logs - عرض سجل المنشورات
/reset - إعادة تعيين المحتوى
/help - هذا الدليل

<b>ملاحظات:</b>
• البوت ينشر تلقائياً كل {POST_INTERVAL_HOURS} ساعات
• المحتوى لا يتكرر حتى ينتهي كل المحتوى
• يمكنك النشر اليدوي بأمر /post
• البوت يتناوب بين الآيات والأحاديث والأذكار والفيديوهات

<b>للدعم:</b>
تواصل مع الأدمن"""

    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML)

# ==================== الجدولة ====================
def setup_scheduler(bot, db, picker):
    scheduler = BackgroundScheduler()

    if POST_AT_SPECIFIC_TIMES:
        for time_str in SCHEDULED_TIMES:
            hour, minute = map(int, time_str.strip().split(":"))
            scheduler.add_job(
                lambda: asyncio.run(send_post(bot, db, picker)),
                CronTrigger(hour=hour, minute=minute),
                id=f"post_{hour}_{minute}",
                name=f"نشر الساعة {hour}:{minute:02d}"
            )
            logger.info(f"⏰ تم جدولة النشر الساعة {hour}:{minute:02d}")
    else:
        scheduler.add_job(
            lambda: asyncio.run(send_post(bot, db, picker)),
            IntervalTrigger(hours=POST_INTERVAL_HOURS),
            id="auto_post",
            name=f"نشر كل {POST_INTERVAL_HOURS} ساعات"
        )
        logger.info(f"⏰ تم جدولة النشر كل {POST_INTERVAL_HOURS} ساعات")

    scheduler.start()
    return scheduler

# ==================== التشغيل الرئيسي (بدون Polling) ====================
async def main():
    logger.info("🚀 تشغيل بوت القناة الدينية...")

    if not BOT_TOKEN or not CHANNEL_ID:
        logger.error("❌ يرجى ضبط BOT_TOKEN و CHANNEL_ID")
        return

    db = Database()
    db.seed_data()
    picker = SmartPicker(db)

    # إنشاء البوت بدون Application (للـ Railway)
    bot = Bot(token=BOT_TOKEN)

    # نشر أول منشور فوراً
    logger.info("🧪 جاري نشر أول منشور...")
    await send_post(bot, db, picker)

    # إعداد الجدولة
    scheduler = setup_scheduler(bot, db, picker)

    logger.info("✅ البوت يعمل الآن! ينشر كل {} ساعات.".format(POST_INTERVAL_HOURS))

    # إبقاء البرنامج شغال (بدون polling)
    try:
        while True:
            await asyncio.sleep(3600)  # ينام ساعة ويصحى يتأكد
    except KeyboardInterrupt:
        logger.info("🛑 تم إيقاف البوت")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 تم إيقاف البوت")
    except Exception as e:
        logger.error(f"❌ خطأ: {e}")
