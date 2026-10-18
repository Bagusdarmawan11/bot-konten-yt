import json
import telebot
from telebot import types as tbtypes
from google import genai
from google.genai import types
import time
import os
import psycopg2
from flask import Flask
import threading
from gtts import gTTS
from datetime import datetime, timezone, timedelta
import requests

# Timezone WIB (UTC+7) — dipakai scheduler agar waktu selalu tepat di server Render (UTC)
WIB = timezone(timedelta(hours=7))

# ==========================================
# 1. KONFIGURASI
# ==========================================
# API keys dibaca dari environment variables
_GEMINI_MODELS = [
    "gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash",
    "gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3-flash",
    "gemini-2.5-flash", "gemini-2.5-flash-lite",
]
_GEMINI_KEYS = [k for k in [
    os.environ.get("GEMINI_API_KEY_1"),
    os.environ.get("GEMINI_API_KEY_2"),
    os.environ.get("GEMINI_API_KEY_3"),
] if k]
GEMINI_CONFIGS = [
    {"api_key": key, "model": model}
    for key in _GEMINI_KEYS
    for model in _GEMINI_MODELS
]

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
DATABASE_URL = os.environ.get("DATABASE_URL", "")
ACTIVE_CHAT_ID = None
OWNER_ID = int(os.environ.get("OWNER_ID", "8060468102"))

def is_owner(message):
    return message.from_user.id == OWNER_ID

def cek_owner(message):
    if not is_owner(message):
        bot.send_message(message.chat.id, "🔒 Bot ini bersifat private.")
        return False
    return True

AKSEN_OPTIONS = {
    "us":  {"label": "🇺🇸 American",   "tld": "com",   "lang": "en"},
    "uk":  {"label": "🇬🇧 British",    "tld": "co.uk", "lang": "en"},
    "au":  {"label": "🇦🇺 Australian", "tld": "com.au","lang": "en"},
    "in":  {"label": "🇮🇳 Indian",     "tld": "co.in", "lang": "en"},
    "id":  {"label": "🇮🇩 Indonesia",  "tld": None,    "lang": "id"},
}

TEMA_OPTIONS = {
    "diy":       {"label": "🏗️ DIY Miniature",      "emoji": "🏗️"},
    "toy":       {"label": "🚛 AI Toy Construction", "emoji": "🚛"},
    "animation": {"label": "🎭 AI Animation",        "emoji": "🎭"},
}

# Waktu pengingat dalam WIB (UTC+7) — 30 menit sebelum prime time pagi & malam lokal
# Prime time pagi  = 09:00 lokal → reminder 08:30 lokal → dikonversi ke WIB
# Prime time malam = 19:00 lokal → reminder 18:30 lokal → dikonversi ke WIB
PRIME_TIMES = {
    "us_east": {
        "label": "🇺🇸 USA East Coast (EST)",
        "waktu_pagi":   "20:30",  # 08:30 EST = 20:30 WIB
        "waktu_malam":  "06:30",  # 18:30 EST = 06:30 WIB
        "ket_pagi":     "08:30 EST — pagi US East",
        "ket_malam":    "18:30 EST — prime time US East",
    },
    "us_west": {
        "label": "🇺🇸 USA (3 Slot Upload)",
        "waktu_pagi":   "19:30",  # 30 mnt sebelum upload 20:00 WIB (= 8 am EST, pagi US)
        "waktu_tengah": "23:30",  # 30 mnt sebelum upload 00:00 WIB (= 12 pm EST, makan siang US)
        "waktu_malam":  "04:30",  # 30 mnt sebelum upload 05:00 WIB (= 5 pm EST, prime time US)
        "ket_pagi":     "20:00 WIB — upload slot 1 (08:00 EST pagi US)",
        "ket_tengah":   "00:00 WIB — upload slot 2 (12:00 EST makan siang US)",
        "ket_malam":    "05:00 WIB — upload slot 3 (17:00 EST prime time US)",
    },
    "uk": {
        "label": "🇬🇧 United Kingdom (GMT)",
        "waktu_pagi":  "15:30",  # 08:30 GMT = 15:30 WIB
        "waktu_malam": "01:30",  # 18:30 GMT = 01:30 WIB
        "ket_pagi":    "08:30 GMT — pagi UK",
        "ket_malam":   "18:30 GMT — prime time UK",
    },
    "au": {
        "label": "🇦🇺 Australia (AEST)",
        "waktu_pagi":  "05:30",  # 08:30 AEST = 05:30 WIB
        "waktu_malam": "15:30",  # 18:30 AEST = 15:30 WIB
        "ket_pagi":    "08:30 AEST — pagi Australia",
        "ket_malam":   "18:30 AEST — prime time Australia",
    },
    "sg": {
        "label": "🇸🇬 Singapore (SGT)",
        "waktu_pagi":  "07:30",  # 08:30 SGT = 07:30 WIB
        "waktu_malam": "17:30",  # 18:30 SGT = 17:30 WIB
        "ket_pagi":    "08:30 SGT — pagi Singapore",
        "ket_malam":   "18:30 SGT — prime time Singapore",
    },
    "jp": {
        "label": "🇯🇵 Japan (JST)",
        "waktu_pagi":  "06:30",  # 08:30 JST = 06:30 WIB
        "waktu_malam": "16:30",  # 18:30 JST = 16:30 WIB
        "ket_pagi":    "08:30 JST — pagi Jepang",
        "ket_malam":   "18:30 JST — prime time Jepang",
    },
    "in": {
        "label": "🇮🇳 India (IST)",
        "waktu_pagi":  "11:00",  # 08:30 IST = 11:00 WIB (IST = UTC+5:30)
        "waktu_malam": "20:00",  # 18:30 IST = 20:00 WIB
        "ket_pagi":    "08:30 IST — pagi India",
        "ket_malam":   "18:30 IST — prime time India",
    },
    "id": {
        "label": "🇮🇩 Indonesia (WIB)",
        "waktu_pagi":  "04:30",  # 30 menit sebelum prime time pagi 05:00 WIB
        "waktu_malam": "19:30",  # 30 menit sebelum prime time malam 20:00 WIB
        "ket_pagi":    "05:00 WIB — prime time pagi Indonesia",
        "ket_malam":   "20:00 WIB — prime time malam Indonesia",
    },
}

# ==========================================
# 2. DATABASE
# ==========================================
def connect_db():
    return psycopg2.connect(DATABASE_URL)

def buat_tabel_jika_belum_ada():
    conn = connect_db()
    cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS riwayat_episode (
        id SERIAL PRIMARY KEY, judul_karya TEXT NOT NULL, tema TEXT DEFAULT 'diy')''')
    cur.execute('''CREATE TABLE IF NOT EXISTS chat_config (id INT PRIMARY KEY, chat_id BIGINT)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS youtube_videos (
        id SERIAL PRIMARY KEY,
        video_id TEXT UNIQUE NOT NULL,
        judul TEXT,
        tanggal_upload DATE DEFAULT CURRENT_DATE,
        views_last INT DEFAULT 0,
        likes_last INT DEFAULT 0,
        milestone_views TEXT DEFAULT '',
        milestone_likes TEXT DEFAULT '',
        auto_scan BOOLEAN DEFAULT TRUE
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS yt_milestones (
        id INT PRIMARY KEY DEFAULT 1,
        views_milestones TEXT DEFAULT '100,500,1000,5000,10000,50000,100000,500000,1000000',
        likes_milestones TEXT DEFAULT '10,50,100,500,1000,5000,10000'
    )''')
    cur.execute('''INSERT INTO yt_milestones (id) VALUES (1) ON CONFLICT (id) DO NOTHING''')
    cur.execute('''CREATE TABLE IF NOT EXISTS yt_weekly_config (
        id INT PRIMARY KEY DEFAULT 1,
        hari INT DEFAULT 0,
        jam TEXT DEFAULT '08:00',
        aktif BOOLEAN DEFAULT TRUE
    )''')
    cur.execute('''INSERT INTO yt_weekly_config (id) VALUES (1) ON CONFLICT (id) DO NOTHING''')
    cur.execute('''CREATE TABLE IF NOT EXISTS yt_views_history (
        id SERIAL PRIMARY KEY,
        video_id TEXT NOT NULL,
        dicatat_pada TIMESTAMPTZ DEFAULT NOW(),
        views INT DEFAULT 0,
        likes INT DEFAULT 0
    )''')
    cur.execute('''CREATE INDEX IF NOT EXISTS idx_yt_hist_vid ON yt_views_history(video_id, dicatat_pada DESC)''')
    # Tambah kolom viral_threshold ke yt_milestones jika belum ada
    try:
        cur.execute("ALTER TABLE yt_milestones ADD COLUMN IF NOT EXISTS viral_threshold_pct INT DEFAULT 50")
    except Exception as e:
        print(f"[DB MIGRATION] viral_threshold_pct: {e}")
    cur.execute('''CREATE TABLE IF NOT EXISTS user_preferensi (
        chat_id BIGINT PRIMARY KEY,
        aksen TEXT DEFAULT 'us',
        kecepatan TEXT DEFAULT 'normal',
        jumlah_scene INT DEFAULT 6,
        tema TEXT DEFAULT 'diy',
        bahasa_vo TEXT DEFAULT 'en',
        bahasa_prompt_video TEXT DEFAULT 'en',
        bahasa_overlay TEXT DEFAULT 'en',
        target_negara TEXT DEFAULT 'us_east'
    )''')
    # Migrasi kolom baru jika DB lama
    cols_to_add = [
        ("tema", "TEXT DEFAULT 'diy'"),
        ("bahasa_vo", "TEXT DEFAULT 'en'"),
        ("bahasa_prompt_video", "TEXT DEFAULT 'en'"),
        ("bahasa_overlay", "TEXT DEFAULT 'en'"),
        ("target_negara", "TEXT DEFAULT 'us_east'"),
    ]
    for col, definition in cols_to_add:
        try:
            cur.execute(f"ALTER TABLE user_preferensi ADD COLUMN IF NOT EXISTS {col} {definition}")
        except Exception as e:
            print(f"[DB MIGRATION] Kolom {col}: {e}")
    try:
        cur.execute("ALTER TABLE riwayat_episode ADD COLUMN IF NOT EXISTS tema TEXT DEFAULT 'diy'")
    except Exception as e:
        print(f"[DB MIGRATION] Kolom tema riwayat: {e}")
    # Migrasi tabel youtube_videos — tambah kolom baru jika belum ada
    yt_cols_to_add = [
        ("auto_scan",        "BOOLEAN DEFAULT TRUE"),
        ("milestone_views",  "TEXT DEFAULT ''"),
        ("milestone_likes",  "TEXT DEFAULT ''"),
    ]
    for col, definition in yt_cols_to_add:
        try:
            cur.execute(f"ALTER TABLE youtube_videos ADD COLUMN IF NOT EXISTS {col} {definition}")
        except Exception as e:
            print(f"[DB MIGRATION] youtube_videos.{col}: {e}")
    conn.commit(); cur.close(); conn.close()

def ambil_memori(tema='diy'):
    conn = connect_db(); cur = conn.cursor()
    cur.execute("SELECT judul_karya FROM riwayat_episode WHERE tema=%s ORDER BY id ASC", (tema,))
    baris = cur.fetchall(); cur.close(); conn.close()
    return [r[0] for r in baris]

def simpan_ke_memori(judul, tema='diy'):
    conn = connect_db(); cur = conn.cursor()
    cur.execute('INSERT INTO riwayat_episode (judul_karya, tema) VALUES (%s,%s)', (judul, tema))
    conn.commit(); cur.close(); conn.close()

def hapus_semua_riwayat(tema='diy'):
    conn = connect_db(); cur = conn.cursor()
    cur.execute("DELETE FROM riwayat_episode WHERE tema=%s", (tema,))
    conn.commit(); cur.close(); conn.close()

def simpan_chat_id(chat_id):
    conn = connect_db(); cur = conn.cursor()
    cur.execute('INSERT INTO chat_config (id,chat_id) VALUES (1,%s) ON CONFLICT (id) DO UPDATE SET chat_id=EXCLUDED.chat_id', (chat_id,))
    conn.commit(); cur.close(); conn.close()

def ambil_chat_id():
    conn = connect_db(); cur = conn.cursor()
    cur.execute('SELECT chat_id FROM chat_config WHERE id=1')
    h = cur.fetchone(); cur.close(); conn.close()
    return h[0] if h else None

DEFAULT_PREF = {"aksen":"us","kecepatan":"normal","jumlah_scene":6,"tema":"diy",
                "bahasa_vo":"en","bahasa_prompt_video":"en","bahasa_overlay":"en","target_negara":"us_east"}

def ambil_preferensi(chat_id):
    conn = connect_db(); cur = conn.cursor()
    try:
        cur.execute('SELECT aksen,kecepatan,jumlah_scene,tema,bahasa_vo,bahasa_prompt_video,bahasa_overlay,target_negara FROM user_preferensi WHERE chat_id=%s', (chat_id,))
        h = cur.fetchone()
    except: h = None
    cur.close(); conn.close()
    if h:
        return {"aksen":h[0],"kecepatan":h[1],"jumlah_scene":h[2],"tema":h[3] or "diy",
                "bahasa_vo":h[4] or "en","bahasa_prompt_video":h[5] or "en","bahasa_overlay":h[6] or "en",
                "target_negara":h[7] or "us_east"}  # default us_east jika kosong
    return dict(DEFAULT_PREF)

def simpan_preferensi(chat_id, **kwargs):
    pref = ambil_preferensi(chat_id)
    for k, v in kwargs.items():
        if v is not None: pref[k] = v
    conn = connect_db(); cur = conn.cursor()
    cur.execute('''
        INSERT INTO user_preferensi (chat_id,aksen,kecepatan,jumlah_scene,tema,bahasa_vo,bahasa_prompt_video,bahasa_overlay,target_negara)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (chat_id) DO UPDATE SET
            aksen=EXCLUDED.aksen, kecepatan=EXCLUDED.kecepatan, jumlah_scene=EXCLUDED.jumlah_scene,
            tema=EXCLUDED.tema, bahasa_vo=EXCLUDED.bahasa_vo,
            bahasa_prompt_video=EXCLUDED.bahasa_prompt_video, bahasa_overlay=EXCLUDED.bahasa_overlay,
            target_negara=EXCLUDED.target_negara
    ''', (chat_id,pref["aksen"],pref["kecepatan"],pref["jumlah_scene"],pref["tema"],
          pref["bahasa_vo"],pref["bahasa_prompt_video"],pref["bahasa_overlay"],pref["target_negara"]))
    conn.commit(); cur.close(); conn.close()

user_state = {}
# Lock untuk mencegah double-execution saat user spam tombol
processing_users = set()
buat_tabel_jika_belum_ada()
ACTIVE_CHAT_ID = ambil_chat_id()

# ==========================================
# 3. PROMPT TEMPLATES
# ==========================================

def _instruksi_bahasa(bahasa_vo, bahasa_overlay, bahasa_prompt_video, tema):
    """Instruksi bahasa yang disuntikkan ke semua prompt.
    CATATAN: prompt_dola_ai (video) selalu BAHASA INDONESIA, tidak peduli preferensi.
    """
    vo_lang   = "BAHASA INDONESIA" if bahasa_vo == "id" else "BAHASA INGGRIS"
    ov_lang   = "BAHASA INDONESIA" if bahasa_overlay == "id" else "BAHASA INGGRIS"
    # Video prompt SELALU Bahasa Indonesia — Dola AI bekerja lebih baik dengan Indonesia
    return f"""
ATURAN BAHASA — WAJIB DIIKUTI TANPA PENGECUALIAN:
A. naskah_vo: WAJIB dalam {vo_lang}. Tidak boleh campur bahasa.
B. teks_overlay: WAJIB dalam {ov_lang}. Tidak boleh campur bahasa.
C. prompt_dola_ai (prompt video untuk Dola AI): WAJIB BAHASA INDONESIA TANPA PENGECUALIAN.
   Video prompt hanya berisi: deskripsi visual + aksi + kamera + Audio. TANPA teks overlay.
   ⚠️ DILARANG keras menulis prompt_dola_ai dalam Bahasa Inggris.
D. prompt_referensi_scene (prompt gambar untuk DALL-E/ChatGPT): WAJIB BAHASA INGGRIS tanpa pengecualian.
   ⚠️ DILARANG keras menulis prompt_referensi_scene dalam Bahasa Indonesia.
E. prompt_gambar_referensi_global (prompt gambar global): WAJIB BAHASA INGGRIS tanpa pengecualian.
F. prompt_thumbnail_ai dan prompt_thumbnail_midjourney: WAJIB BAHASA INGGRIS.
"""

def buat_prompt_diy(riwayat, topik, jumlah_scene, bahasa_vo, bahasa_overlay, bahasa_prompt_video):
    if topik:
        topik_instruksi = (
            f"Topik WAJIB: buat miniatur {topik}. "
            f"PENTING: Sebelum melanjutkan, verifikasi dulu bahwa topik ini REALISTIS untuk dibuat dari stik es krim dan kardus "
            f"(struktur berdiri di darat, tidak butuh air/kanal/apung). "
            f"Jika topik tidak realistis (misalnya bangunan di atas air, flying structure, arsitektur impossible), "
            f"GANTI dengan variasi yang realistis dari topik serupa (contoh: 'perpustakaan apung' → 'perpustakaan klasik dua lantai')."
        )
    else:
        topik_instruksi = (
            "Pilih 1 topik miniatur yang UNIK, SEGAR, dan SAMA SEKALI BERBEDA dari semua episode di riwayat.\n\n"
            "🚫 LARANGAN MUTLAK:\n"
            "  ❌ DILARANG memilih topik yang SAMA, MIRIP, atau SATU KELUARGA dengan episode manapun di riwayat\n"
            "     (contoh: jika riwayat ada 'kincir angin' → DILARANG kincir air, windmill, water wheel, dll)\n"
            "  ❌ DILARANG bangunan toko / kedai / warung / shop / store dalam bentuk apapun\n"
            "  ❌ DILARANG bangunan di atas air, kanal, gondola, struktur apung\n\n"
            "✅ PILIH dari salah satu kategori berikut — ROTASI WAJIB, jangan pilih kategori yang sama 2x berturut-turut:\n\n"
            "🏠 HUNIAN UNIK:\n"
            "  Rumah hobbit bawah bukit, pondok nelayan pantai, cabin kayu pegunungan, rumah pohon bertingkat,\n"
            "  cottage Inggris berbunga, chalet Alpine bersalju, rumah adat Jawa/Bali/Minang, rumah jamur fairytale,\n"
            "  rumah batu viking, igloo kayu, yurt Mongolia mini, rumah panjang Kalimantan\n\n"
            "🏯 LANDMARK & KASTIL DUNIA:\n"
            "  Kastil Edinburgh Skotlandia, Benteng Neuschwanstein Jerman, Istana Versailles (sayap kecil),\n"
            "  Colosseum Roma (penampang), Taj Mahal gerbang, Angkor Wat menara tengah,\n"
            "  Alhambra Spanyol, Benteng Bourtange Belanda, Kapel Sistina eksterior,\n"
            "  Gerbang Brandenburg Jerman, Arc de Triomphe Paris, Menara Pisa\n\n"
            "✈️ KENDARAAN MILITER & ALAT TEMPUR IKONIK:\n"
            "  Pesawat B-2 Spirit bomber (tampak atas), F-22 Raptor, Spitfire WWII, P-51 Mustang,\n"
            "  Tank Sherman WWII, Panzer Tiger Jerman, tank T-34 Soviet, Jeep Willys WWII,\n"
            "  Kapal perang HMS Victory (sailing warship), Kapal selam U-boat mini,\n"
            "  Meriam kastil abad pertengahan, katapel kayu perang (trebuchet),\n"
            "  Panah balistik Romawi (ballista), Meriam Napoleon, Howitzer WWII\n\n"
            "🚀 KENDARAAN & EKSPLORASI:\n"
            "  Roket Saturn V NASA, Space Shuttle mini, Apollo Lunar Module,\n"
            "  Kapal uap paddle wheel abad 19, kapal bajak laut Black Pearl,\n"
            "  Lokomotif uap Orient Express, Concorde mini, Wright Flyer replika\n\n"
            "🌿 ALAM, TAMAN & DIORAMA:\n"
            "  Taman zen Jepang dengan jembatan kayu, gua batu berpohon, kandang domba dengan pagar kayu,\n"
            "  gubuk petani sawah, hutan mini dengan jalur setapak, tebing batu dengan air terjun dekoratif,\n"
            "  pulau terpencil mini, perkemahan hutan dengan api unggun, gerbang hutan misterius\n\n"
            "🪑 FURNITURE & INTERIOR UNIK:\n"
            "  Rak buku vintage berlaci, meja kerja steampunk, ranjang tingkat dengan kanopi,\n"
            "  piano mini, dapur klasik mini, lemari perpustakaan besar, meja biliar mini,\n"
            "  singgasana raja abad pertengahan, meja makan kerajaan dengan lilin\n\n"
            "🎡 WAHANA & MEKANIK:\n"
            "  Bianglala berputar (ferris wheel), carousel kayu, jam dinding besar mekanik,\n"
            "  panggung teater vikingkat, menara kastil dengan portcullis (pintu jebakan),\n"
            "  tenda sirkus Victorian, arena gladiator mini\n\n"
            "🏛️ BANGUNAN PUBLIK & BUDAYA:\n"
            "  Stasiun kereta kuno Paris style, perpustakaan klasik Eropa, kapel batu kecil,\n"
            "  balai desa tradisional, menara mercusuar di tebing, pos penjaga abad pertengahan,\n"
            "  masjid Umayyad mini, pagoda 5 lantai Jepang, candi Prambanan satu menara\n\n"
            "ATURAN PEMILIHAN — WAJIB DIPATUHI:\n"
            "1. Baca SEMUA riwayat — buat mental checklist topik yang sudah ada\n"
            "2. WAJIB pilih dari kategori BERBEDA dari 2 episode terakhir\n"
            "3. Tambahkan twist unik: misal 'B-2 Bomber dari stik es krim DENGAN detail panel sayap' atau 'Kastil Edinburgh DENGAN jembatan drawbridge'\n"
            "4. UTAMAKAN topik dari kategori yang BELUM PERNAH muncul sama sekali di riwayat\n"
            "5. Kategori 'Kendaraan Militer' dan 'Eksplorasi' adalah prioritas tinggi jika belum ada di riwayat\n\n"
            "⭐ TIPS VIRAL — ELEMEN 'WOW FACTOR':\n"
            "   Tambahkan elemen yang membuat penonton takjub: detail yang sangat presisi, skala yang mengejutkan,\n"
            "   atau objek yang tidak terduga dibuat dari stik es krim (misal: 'siapa sangka B-2 bomber bisa dari stik es krim?!')\n"
            "   Hindari topik yang sudah terlalu umum di YouTube Shorts DIY.\n\n"
            "LARANGAN TOPIK: JANGAN pilih bangunan di atas air, kanal, gondola, atau arsitektur yang butuh material non-stik-es-krim."
        )
    scene_instruksi = f"JUMLAH SCENE: WAJIB tepat {jumlah_scene} scene." if jumlah_scene else \
        ("JUMLAH SCENE: Tentukan sendiri berdasarkan kompleksitas karya:\n"
         "  - Proyek SANGAT SEDERHANA (1 komponen utama, misal: kursi kecil, sumur mini) → 4 scene\n"
         "  - Proyek SEDANG (2-3 komponen, misal: gazebo, rumah hobbit kecil) → 5-6 scene\n"
         "  - Proyek KOMPLEKS (4+ komponen, banyak detail, misal: kastil, rumah 2 lantai) → 7-8 scene\n"
         "  WAJIB memilih angka spesifik (4/5/6/7/8), sesuaikan dengan kompleksitas nyata karya yang dipilih.")
    return f"""
Kamu adalah Kreator Konten DIY kelas dunia untuk YouTube Shorts dan ahli copywriting viral.
Buat 1 naskah tutorial pembuatan miniatur konstruksi/diorama dari stik es krim atau kardus.

{topik_instruksi}

⚠️ REALISME WAJIB — BACA DAN PATUHI SEBELUM MEMBUAT IDE:
Material yang digunakan adalah STIK ES KRIM KAYU dan KARDUS. Ide HARUS 100% bisa diwujudkan dengan bahan ini.

MATERIAL YANG BOLEH DIGUNAKAN:
✅ Stik es krim kayu (semua ukuran)
✅ Kardus bekas / karton
✅ Lem tembak / lem putih
✅ Cat air atau cat akrilik (dioleskan dengan kuas manual — TANPA aerosol)
✅ Benang, kain perca, kertas pasir (sebagai aksen dekoratif kecil)

MATERIAL YANG DILARANG KERAS:
❌ Batu / batu bata / batu kerikil / gravel / pebble / rock / stone — DILARANG KERAS dalam bentuk apapun
❌ Pasir / tanah / lumpur / material alam mentah sebagai elemen struktural
❌ Mika plastik / PVC / akrilik / plexiglass (untuk jendela atau panel apapun)
❌ Kawat / logam / besi struktural
❌ Kaca sungguhan
❌ Kayu papan / triplek (bukan stik es krim)
❌ Plastik cor / cetakan plastik apapun
❌ Material apapun selain yang tercantum di atas

⚠️ JUDUL KARYA & SINOPSIS WAJIB menyebutkan "dari stik es krim" atau "from popsicle sticks" — bukan dari batu, tanah, beton, atau material lain.

KATEGORI AMAN (boleh dibuat):
- Bangunan darat: rumah sederhana, villa, cottage, cabin, kastil mini, pura/masjid kecil, gereja kecil, rumah hobbit, treehouse
- Infrastruktur darat: jembatan darat (bukan jembatan di atas kanal terbuka), menara, gapura, pagar
- Taman & outdoor: gazebo, kincir angin, sumur dekoratif, kandang, gubuk
- Furniture: rak, kursi, meja, ranjang, lemari mini
- Kendaraan statis: kereta kayu, becak, gerobak, kapal pajangan (tidak mengapung sungguhan)
- Landmark darat: replika menara, pintu masuk kastil, benteng, lighthouse (di atas batu/tanah)

KATEGORI TERLARANG (TIDAK BOLEH dipilih):
- ❌ Bangunan di atas air / mengapung: perpustakaan apung, rumah perahu, floating village, water temple
- ❌ Membutuhkan kanal / gondola / kolam besar sebagai elemen utama struktur
- ❌ Struktur yang mustahil dari stik es krim: jembatan suspensi skala besar, bandara, mall
- ❌ Arsitektur sangat kompleks yang butuh material logam/kaca/besi struktural

Sebelum menentukan judul_karya, tanya diri sendiri: "Apakah ini bisa dibuat HANYA dari stik es krim, lem tembak, dan kardus — TANPA mika, plastik, kawat, atau kayu papan?" Jika TIDAK — ganti topik.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 VISUAL ANCHOR — WAJIB DIPATUHI DI SEMUA SCENE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Definisikan SATU visual anchor global di awal, lalu TERAPKAN IDENTIK di SETIAP scene tanpa variasi:

TANGAN (WAJIB SAMA DI SEMUA SCENE):
- Warna kulit: sawo matang / medium brown skin tone
- Pakaian lengan: hoodie abu-abu medium / grey hoodie sleeve
- Panjang lengan terlihat: dari pergelangan hingga sekitar 10 cm di atas pergelangan
- DILARANG: warna kulit berubah, warna hoodie berubah, baju berbeda antar scene

MEJA KERJA (WAJIB SAMA DI SEMUA SCENE):
- Material meja: kayu natural / natural wood surface
- Warna permukaan: coklat muda hangat / warm light wood
- Pencahayaan: warm soft overhead light, bayangan lembut ke kanan
- KEBERSIHAN MEJA: MEJA WAJIB BERSIH DAN MINIMALIS — hanya objek miniatur yang dikerjakan + alat yang dipegang tangan
- DILARANG di atas meja: cutting mat hijau, penggaris, cutter, gunting berserakan, stik es krim berserakan, botol lem tergeletak, tisu, kotak peralatan, alat-alat yang tidak sedang dipakai
- DILARANG: meja berubah warna/material, arah cahaya berubah, meja berantakan/cluttered

BACKGROUND (WAJIB SAMA DI SEMUA SCENE):
- Background blur (bokeh)
- Warna dominan background: putih krem / cream white, out of focus
- DILARANG: background berbeda warna atau style antar scene, background berubah jadi gelap atau terang berbeda

REFERENSI GAMBAR GLOBAL (prompt_gambar_referensi_global) WAJIB mendefinisikan:
Semua elemen di atas secara eksplisit, sehingga menjadi "DNA visual" yang direplikasi oleh setiap prompt_referensi_scene.

SETIAP prompt_referensi_scene WAJIB menyalin ULANG elemen visual anchor di atas kata per kata, plus tambah detail spesifik scene tersebut (kondisi objek saat itu, alat yang dipegang, tahap pengerjaan).

RIWAYAT EPISODE SEBELUMNYA (JANGAN diulangi):
{riwayat}

{_instruksi_bahasa(bahasa_vo, bahasa_overlay, bahasa_prompt_video, 'diy')}

ATURAN PRODUKSI:
1. {scene_instruksi}
2. DYNAMIC HOOK (SCENE 1): Karya SUDAH HAMPIR JADI (90%), sudah diwarnai/dicat penuh. Tampilkan tangan melakukan satu aksi penyelesaian akhir presisi (menempelkan detail terakhir, merapikan bagian kecil, dll). JANGAN mulai dari bahan mentah. JANGAN tangan hanya memegang atau memutar objek tanpa aksi nyata.
3. ALUR SCENE WAJIB KRONOLOGIS (scene 2 dst mundur ke tahap awal):
   - Scene 2: Merakit RANGKA/FONDASI DASAR — objek baru berupa susunan stik es krim kasar, BELUM DIBENTUK sempurna, BELUM dicat sama sekali (warna natural stik coklat muda)
   - Scene 3: Merakit STRUKTUR UTAMA — objek sudah berbentuk lebih jelas, tapi masih 40-50% selesai, MASIH BELUM dicat (warna natural stik)
   - Scene 4 (jika ada): Merakit DETAIL TAMBAHAN — objek sudah 70% selesai, MASIH BELUM dicat, tangan menempelkan elemen dekoratif kecil
   - Scene PENGECATAN: Objek sudah SEPENUHNYA dirakit tapi 100% BELUM dicat (warna natural stik mentah). Tangan memegang kuas kecil, mengoleskan cat pertama ke permukaan yang BELUM BERWARNA. ⚠️ DILARANG KERAS: objek sudah berwarna/dicat saat scene pengecatan dimulai.
   - Scene TERAKHIR (sebelum scene 1): Objek SUDAH SELESAI dan sudah dicat penuh — beauty shot / reveal angle terbaik.
   ⚠️ SETIAP scene WAJIB menyebutkan dengan eksplisit kondisi pengecatan objek: "belum dicat / natural popsicle stick color" ATAU "sudah dicat warna [X]"
4. KONSISTENSI ANTAR SCENE — WAJIB: Setiap elemen yang ada di scene N HARUS ada di scene N+1. Jika scene 2 ada 4 dinding, scene 3 HARUS ada 4 dinding + penambahan baru. DILARANG elemen menghilang atau berubah bentuk drastis tantar scene.
5. KAMERA STATIS: Kamera WAJIB diam atau bergerak SANGAT lambat. DILARANG dolly zoom atau putaran cepat.
6. STANDALONE SCENE: Di SETIAP scene WAJIB deskripsikan ulang wujud meja, ciri pakaian tangan, dan kondisi benda SAAT ITU secara detail. JANGAN tulis "melanjutkan scene sebelumnya".
7. NO AEROSOL. Pewarnaan selalu pakai kuas kecil manual.
8. Audio di prompt video: WAJIB tulis "Audio: [Jenis Musik]". Tidak boleh ada suara manusia di deskripsi video.
9. VOICE OVER per scene: 1-2 kalimat energetik. Panjang VO: MAKSIMAL 25 kata per scene.
10. TEXT OVERLAY per scene: Maksimal 5 kata, catchy. JANGAN masukkan overlay ke dalam prompt video.
9. REFERENSI PER SCENE: prompt_referensi_scene WAJIB dalam BAHASA INGGRIS minimal 120 kata.
   ⚠️ VISUAL ANCHOR — COPY IDENTIK KE SETIAP prompt_referensi_scene (tidak boleh bervariasi):
   - Tangan: "medium brown / sawo matang skin tone, grey hoodie sleeve visible at wrist area"
   - Meja: "natural warm wood surface, soft warm overhead lighting, gentle shadow to the right, CLEAN MINIMAL TABLE — no cutting mat, no ruler, no scattered tools, no clutter, only the craft object and the tool held in hand"
   - Background: "blurred cream white background, out of focus (bokeh), consistent warm cream tone"
   SETELAH menyalin anchor di atas, tambahkan detail SPESIFIK scene ini:
   - Jenis foto: "Photorealistic DSLR photo," atau "Hyper-detailed macro photography,"
   - Kondisi objek miniatur: ukuran, material (stik es krim/kardus), tahap pengerjaan SAAT ITU, detail tekstur
   - STATUS PENGECATAN WAJIB DISEBUTKAN EKSPLISIT: "object is UNPAINTED, natural popsicle stick color" ATAU "object is fully painted in [warna]" — jangan biarkan ambigu
   - Alat yang dipegang tangan: nama alat, posisi jari secara spesifik
   - Mood visual: warm/cool tone, atmosfer
   - Kualitas: "ultra sharp, 8K resolution, professional photography lighting"
10. METADATA VIRAL (semua dalam Bahasa Inggris):
    - judul_youtube: maks 70 karakter, WAJIB ada angka atau "ONLY" atau "?!"
    - judul_youtube_alternatif: 3 variasi berbeda angle, maks 70 karakter masing-masing
    - deskripsi_youtube: minimal 5 kalimat. Kalimat ke-2 WAJIB ada pertanyaan mendorong komentar. Sebelum baris penutup, tambahkan 1 baris kosong lalu baris: "🛒 Materials I used: [AFFILIATE LINK]" (ini placeholder opsional untuk link affiliate). Akhiri dengan 2 baris berisi hashtag: baris 1 "#Shorts #miniature #diycraft" dan baris 2 "#popsiclestickscraft #satisfying #handmade". Subscribe CTA: "Subscribe for more satisfying DIY builds every week! 🔔". TOTAL hashtag di deskripsi: 5-6 hashtag saja (jangan terlalu banyak).
    - tags_youtube: MINIMAL 30 tag, campuran: niche spesifik + trending craft + lokasi internasional + keyword populer. WAJIB selalu sertakan: #Shorts, #miniature, #popsiclestickscraft, #diycraft, #satisfying, #handmade, #miniaturecraft, #diorama, #craftideas, #diyminiature. Format: #tag1, #tag2, #tag3, ... (pisahkan dengan koma)
    - komentar_pinned: 1 pertanyaan Bahasa Inggris untuk di-pin, JANGAN pakai sapaan langsung
    - playlist_youtube: WAJIB pilih TEPAT 1 dari daftar playlist berikut berdasarkan topik video ini:
      * "Miniature Houses & Cottages" → rumah hobbit, cottage, cabin, treehouse, chalet, rumah adat
      * "Miniature Landmarks & Towers" → menara kastil, lighthouse, pagoda, torii gate, benteng, Big Ben, Eiffel mini
      * "Miniature Gardens & Nature" → taman zen, sumur batu, kolam koi, gazebo, kandang, gubuk petani, gua
      * "Miniature Furniture & Interiors" → rak buku, meja steampunk, ranjang, kursi taman, piano, dapur mini
      * "Miniature Vehicles & Transport" → lokomotif uap, kapal layar, becak, gerobak, pesawat biplane
      * "Miniature Rides & Attractions" → bianglala, carousel, panggung teater, tenda sirkus, arena kastil
      * "Miniature Windmills & Wells" → kincir angin, sumur batu, water wheel, kincir air — topik high-viral
      ⚠️ Pilih playlist yang PALING SPESIFIK sesuai objek. Satu video masuk SATU playlist saja.
11. THUMBNAIL (prompt dalam Bahasa Inggris):
    - teks_thumbnail: maks 4 kata, KAPITAL semua
    - prompt_thumbnail_ai: minimal 80 kata, mulai: "YouTube thumbnail image, 16:9 aspect ratio,"
    - prompt_thumbnail_midjourney: akhiri dengan --ar 16:9 --style raw --v 6
12. prompt_gambar_referensi_global: BAHASA INGGRIS minimal 120 kata.
    ⚠️ WAJIB menyebutkan OBJEK SPESIFIK yang dibuat — nama, bentuk, ukuran kira-kira, warna/material:
    Contoh BENAR: "...the miniature being crafted is a small arched wooden bridge (approx 15cm long, natural popsicle stick color, with curved arc structure and side railings), placed on a flat cardboard base..."
    Contoh SALAH: "...a miniature construction project..." (terlalu generik — DALL-E tidak tahu bentuk objeknya)
    Objek harus digambarkan dalam kondisi HAMPIR SELESAI (85-90%), sudah terlihat bentuknya dengan jelas.

Output HARUS berupa JSON murni:
{{
  "judul_karya": "Nama miniatur Bahasa Indonesia",
  "bahan_utama": "Daftar bahan dan alat",
  "jumlah_scene_dipilih": [angka scene yang digunakan],
  "judul_youtube": "...",
  "judul_youtube_alternatif": ["...", "...", "..."],
  "deskripsi_youtube": "...",
  "tags_youtube": "#tag1, #tag2, #tag3, ...",
  "playlist_youtube": "Nama playlist dari daftar yang ditentukan",
  "komentar_pinned": "...",
  "thumbnail_konsep": {{
    "teks_thumbnail": "MAX 4 KATA KAPITAL",
    "prompt_thumbnail_ai": "Full DALL-E prompt...",
    "prompt_thumbnail_midjourney": "Midjourney prompt... --ar 16:9 --style raw --v 6"
  }},
  "deskripsi_konsep_video": "Sinopsis Bahasa Indonesia minimal 5 kalimat",
  "prompt_gambar_referensi_global": "Full English prompt 120+ kata...",
  "alur_cerita": [
    {{
      "scene": 1,
      "langkah": "Dynamic Hook (Karya 90% Jadi)",
      "prompt_dola_ai": "[WAJIB BAHASA INDONESIA. Deskripsi visual scene TANPA overlay. Sertakan: setting meja, kondisi benda, aksi tangan (kulit sawo matang, hoodie abu-abu), sudut kamera, Audio: [jenis musik]. Min 60 kata]",
      "naskah_vo": "[VO dalam bahasa yang ditentukan. Maks 25 kata]",
      "teks_overlay": "[Overlay dalam bahasa yang ditentukan. Maks 5 kata]",
      "prompt_referensi_scene": "[WAJIB BAHASA INGGRIS. Photorealistic DSLR photo description 120+ kata — sebutkan: jenis shot, setting meja, kondisi objek miniatur SAAT ITU (termasuk STATUS PENGECATAN eksplisit: unpainted/natural OR painted in [color]), detail tangan, background, mood visual, quality tags untuk DALL-E]"
    }}
  ]
}}
"""

def buat_prompt_toy(riwayat, topik, jumlah_scene, bahasa_overlay, bahasa_prompt_video):
    """Toy Construction: tidak ada VO karena pakai backsound sendiri."""
    if topik:
        topik_instruksi = f"Topik WAJIB: proyek konstruksi bertema {topik}."
    else:
        topik_instruksi = (
            "Pilih 1 proyek konstruksi mainan yang UNIK dan BERBEDA dari riwayat episode di atas.\n\n"
            "🚫 LARANGAN: JANGAN pilih proyek yang sama atau mirip dengan episode sebelumnya.\n\n"
            "✅ PILIH dari kategori berikut (variasikan — jangan pakai kategori yang sama 2x berturut-turut):\n\n"
            "🏗️ INFRASTRUKTUR:\n"
            "  Pembangunan jembatan gantung, konstruksi terowongan, pembangunan bendungan, pelebaran jalan raya,\n"
            "  pembangunan rel kereta, konstruksi landasan helikopter, pembangunan dermaga kecil\n\n"
            "🏢 BANGUNAN:\n"
            "  Konstruksi gedung bertingkat, pembangunan pabrik, pembangunan gudang besar,\n"
            "  pembangunan rumah susun, konstruksi menara air, pembangunan silo\n\n"
            "⛏️ PENGGALIAN & PERTAMBANGAN:\n"
            "  Penggalian tambang terbuka, pembukaan lahan hutan, pengerukan kolam/danau,\n"
            "  pembersihan reruntuhan, penggalian pondasi gedung pencakar langit\n\n"
            "🌊 PROYEK AIR:\n"
            "  Konstruksi kolam renang besar, pembangunan saluran irigasi, konstruksi pelabuhan,\n"
            "  pembangunan waduk, instalasi pipa bawah tanah\n\n"
            "🚀 PROYEK UNIK & AMBISIUS:\n"
            "  Konstruksi landasan pacu bandara mini, pembangunan sirkuit balap, pembuatan stadion mini,\n"
            "  konstruksi kota mini dari nol, pembangunan piramida pasir raksasa\n\n"
            "ATURAN PEMILIHAN:\n"
            "1. Baca riwayat di atas — pilih proyek dari KATEGORI BERBEDA dari 3 episode terakhir\n"
            "2. Tambahkan detail unik: 'Pembangunan JEMBATAN GANTUNG dengan 4 crane bekerja bersamaan'\n"
            "3. Prioritaskan proyek yang melibatkan BANYAK kendaraan berbeda bekerja bersama"
        )
    scene_instruksi = f"JUMLAH SCENE: WAJIB tepat {jumlah_scene} scene." if jumlah_scene else \
        ("JUMLAH SCENE: Tentukan sendiri berdasarkan skala proyek konstruksi:\n"
         "  - Proyek KECIL (1 kendaraan, 1 aktivitas, misal: ekskavator gali lubang) → 4 scene\n"
         "  - Proyek MENENGAH (2-3 kendaraan, 2-3 fase, misal: bangun jalan, bangun kolam) → 5-6 scene\n"
         "  - Proyek BESAR (4+ kendaraan, banyak fase, misal: bangun gedung, kompleks konstruksi) → 7-8 scene\n"
         "  WAJIB memilih angka spesifik sesuai skala proyek yang dipilih.")
    ov_lang = "BAHASA INDONESIA" if bahasa_overlay == "id" else "BAHASA INGGRIS"
    # prompt_dola_ai (video) SELALU Bahasa Indonesia
    return f"""
Kamu adalah Kreator Konten YouTube Shorts viral spesialis video mainan konstruksi (toy construction).
Buat 1 naskah video AI-generated tentang MAINAN KENDARAAN KONSTRUKSI (truk, buldozer, ekskavator, crane, dll) yang melakukan aktivitas konstruksi di pasir atau tanah.

{topik_instruksi}

RIWAYAT EPISODE SEBELUMNYA (JANGAN diulangi):
{riwayat}

ATURAN BAHASA — KRITIS:
A. teks_overlay: WAJIB dalam {ov_lang}. JANGAN masukkan overlay ke dalam prompt_dola_ai.
B. prompt_dola_ai: WAJIB BAHASA INDONESIA TANPA PENGECUALIAN. Ini adalah prompt untuk Dola AI (tool AI video Indonesia).
   Berisi: deskripsi visual + kendaraan + aksi + kamera + Audio. TANPA teks overlay.
   ⚠️ DILARANG menulis prompt_dola_ai dalam Bahasa Inggris.
C. prompt_referensi_scene: WAJIB BAHASA INGGRIS. Minimal 120 kata.
   WAJIB mencakup semua elemen ini secara spesifik:
   - Jenis foto: "Photorealistic miniature photography," atau "Hyper-detailed toy scene macro photography,"
   - Setting lokasi: jenis permukaan (tanah, pasir, batu), pencahayaan (warm/cool, sumber cahaya, bayangan)
   - Kondisi kendaraan/objek: ukuran, material (die-cast/plastik), warna, detail tekstur, tahap konstruksi
   - Aksi utama: kendaraan apa, melakukan apa, posisi/sudut spesifik
   - Background: apakah blur (bokeh), warna dominan, ada objek pendukung apa
   - Mood visual: warna tone keseluruhan (warm/cool/dusty), atmosfer keseluruhan
   - Kualitas: "ultra sharp, 8K resolution, professional miniature photography lighting"
D. Semua metadata YouTube (judul, deskripsi, tags, komentar_pinned): BAHASA INGGRIS.
E. prompt_thumbnail_ai, prompt_thumbnail_midjourney, prompt_gambar_referensi_global: WAJIB BAHASA INGGRIS.

CATATAN PENTING: Video ini TIDAK menggunakan Voice Over. Penonton hanya mendengar suara konstruksi + backsound musik.
Field "keterangan_aksi" digunakan sebagai penjelasan aksi per scene (tidak dibacakan, hanya referensi).

ATURAN PRODUKSI:
1. {scene_instruksi}
2. DYNAMIC HOOK (SCENE 1): Proyek hampir selesai 90%. Ada 1 kendaraan melakukan sentuhan akhir yang dramatis.
3. SCENE 2: Kembali ke awal — lahan kosong, armada kendaraan berbaris siap bekerja.
4. SCENE TENGAH: Aktivitas konstruksi berbeda di setiap scene. JANGAN ulangi aktivitas yang sama.
5. SCENE TERAKHIR: Hasil akhir sempurna, semua kendaraan parkir rapi di sekitar hasil karya.
6. Setiap scene WAJIB ada kendaraan yang BERGERAK dan aksi SPESIFIK berbeda.
7. KAMERA bervariasi per scene (bird's eye, close-up, side view, low angle).
8. AUDIO di setiap prompt: "Audio: [suara konstruksi realistis + jenis musik epic/upbeat]".
9. TEXT OVERLAY per scene: maks 5 kata, format ACTION label. Contoh: "FASE 1: PENGGALIAN 🚜" (sesuai bahasa overlay yang dipilih).
10. KETERANGAN AKSI per scene: BAHASA INDONESIA. 1-2 kalimat singkat menjelaskan APA yang terjadi di scene ini, KENDARAAN mana yang aktif, dan HASIL yang terlihat. Ini hanya referensi kreator, tidak dibacakan.
11. METADATA (semua Bahasa Inggris):
    - judul_youtube: maks 70 karakter, formula viral: jenis proyek + skala + hasil mengejutkan + ?! atau ONLY
    - judul_youtube_alternatif: 3 variasi, maks 70 karakter
    - deskripsi_youtube: min 5 kalimat, kalimat ke-2 WAJIB pertanyaan mendorong komentar. Sebelum baris penutup, tambahkan 1 baris kosong lalu baris: "🛒 Toy links: [AFFILIATE LINK]" (ini placeholder opsional untuk link affiliate). Akhiri dengan baris hashtag: "#Shorts #toyconstruction #satisfying #constructiontoys #miniature". Subscribe CTA: "Subscribe for more amazing toy construction builds! 🔔". TOTAL hashtag di deskripsi: 5-6 hashtag saja.
    - tags_youtube: MINIMAL 30 tag, mix niche + trending + lokasi internasional. WAJIB sertakan: #Shorts, #toyconstruction, #constructiontoys, #satisfying, #miniatureconstruction, #excavator, #heavyequipment, #diecast, #constructionvideo, #satisfyingvideo. Format: #tag1, #tag2, #tag3, ... (pisahkan dengan koma)
    - komentar_pinned: 1 pertanyaan Bahasa Inggris untuk di-pin
    - playlist_youtube: WAJIB pilih TEPAT 1 dari daftar playlist berikut:
      * "Road & Bridge Builds" → jembatan, jalan raya, rel kereta, terowongan, landasan
      * "Building Construction" → gedung bertingkat, pabrik, gudang, menara air, silo, rumah susun
      * "Mining & Excavation" → tambang terbuka, penggalian, pembukaan lahan, pengerukan, pondasi
      * "Water & Harbor Projects" → kolam renang, irigasi, pelabuhan, waduk, pipa bawah tanah
      * "Epic & Mega Builds" → proyek ambisius, futuristik, underground city, mega dam
      ⚠️ Pilih SATU playlist paling relevan dengan jenis konstruksi di video ini.
12. THUMBNAIL (Bahasa Inggris):
    - teks_thumbnail: maks 4 kata KAPITAL
    - prompt_thumbnail_ai: min 80 kata, mulai: "YouTube thumbnail image, 16:9 aspect ratio, toy construction scene,"
    - prompt_thumbnail_midjourney: akhiri --ar 16:9 --style raw --v 6
12. prompt_gambar_referensi_global: BAHASA INGGRIS, min 120 kata, overview seluruh proyek.
    ⚠️ WAJIB menyebutkan KENDARAAN SPESIFIK yang ada di proyek ini — jenis, warna, ukuran, posisi:
    Contoh BENAR: "...a yellow die-cast excavator (approx 8cm long) with its arm extended, digging into sandy ground next to a red dump truck with its cargo bed raised..."
    Contoh SALAH: "...toy construction vehicles working on a project..." (terlalu generik — DALL-E tidak tahu kendaraan apa)
    Gambarkan kondisi proyek di tahap TENGAH (50-60% selesai) agar terlihat progress konstruksinya.

Output HARUS berupa JSON murni:
{{
  "judul_karya": "Nama proyek Bahasa Indonesia",
  "alat_kendaraan": "Daftar kendaraan dan alat yang digunakan",
  "jumlah_scene_dipilih": [angka scene],
  "judul_youtube": "...",
  "judul_youtube_alternatif": ["...", "...", "..."],
  "deskripsi_youtube": "...",
  "tags_youtube": "#tag1, #tag2, #tag3, ...",
  "playlist_youtube": "Nama playlist dari daftar yang ditentukan",
  "komentar_pinned": "...",
  "thumbnail_konsep": {{
    "teks_thumbnail": "MAX 4 KATA KAPITAL",
    "prompt_thumbnail_ai": "...",
    "prompt_thumbnail_midjourney": "... --ar 16:9 --style raw --v 6"
  }},
  "deskripsi_konsep_video": "Sinopsis Bahasa Indonesia min 5 kalimat",
  "prompt_gambar_referensi_global": "Full English prompt 120+ kata...",
  "alur_cerita": [
    {{
      "scene": 1,
      "langkah": "Dynamic Hook — Proyek 90% Selesai",
      "prompt_dola_ai": "[WAJIB BAHASA INDONESIA. Deskripsi visual scene TANPA overlay. Sebutkan: setting, kendaraan, aksi, sudut kamera, Audio: [jenis musik]. Min 60 kata]",
      "keterangan_aksi": "[Penjelasan singkat apa yang terjadi di scene ini — untuk referensi kreator]",
      "teks_overlay": "[Overlay dalam bahasa yang ditentukan. Maks 5 kata]",
      "prompt_referensi_scene": "[WAJIB BAHASA INGGRIS. Photorealistic miniature photography description 120+ kata — sebutkan jenis shot, setting, kendaraan, aksi, background, mood visual, dan quality tags untuk DALL-E]"
    }}
  ]
}}
"""

def buat_prompt_animasi(riwayat, topik, jumlah_scene, bahasa_vo, bahasa_overlay, bahasa_prompt_video):
    if topik:
        topik_instruksi = f"Topik/tema cerita WAJIB: {topik}."
    else:
        topik_instruksi = (
            "Buat cerita animasi orisinal yang UNIK dan BERBEDA dari episode-episode sebelumnya.\n\n"
            "🚫 LARANGAN:\n"
            "  ❌ JANGAN buat cerita dengan tema yang sama atau mirip dengan episode di riwayat\n"
            "  ❌ JANGAN pakai formula yang sama berulang (contoh: jangan 3x berturut-turut pakai 'underdog jadi juara')\n\n"
            "✅ PILIH dari kategori cerita berikut (variasikan kategorinyA):\n\n"
            "😂 KOMEDI & SLICE OF LIFE:\n"
            "  Karakter salah paham yang lucu, rencana yang gagal total, persaingan konyol dua tetangga,\n"
            "  karakter yang terlalu percaya diri, makhluk kecil yang bermimpi besar\n\n"
            "💡 PETUALANGAN & MISTERI:\n"
            "  Harta karun tersembunyi, makhluk misterius baru di desa, perjalanan ke dunia kecil,\n"
            "  detektif cilik memecahkan kasus, portal ke dunia lain\n\n"
            "❤️ PERSAHABATAN & KELUARGA:\n"
            "  Dua karakter berlawanan jadi sahabat, perpisahan mengharukan, reuni tak terduga,\n"
            "  saudara bersaing tapi saling melindungi, hewan peliharaan dan tuannya\n\n"
            "🌍 MORAL & LINGKUNGAN:\n"
            "  Karakter serakah yang belajar berbagi, hutan yang terancam diselamatkan karakter kecil,\n"
            "  robot yang belajar empati, makhluk laut melawan polusi plastik\n\n"
            "🎭 TWIST & DARK COMEDY:\n"
            "  Antagonis yang ternyata protagonis, penyelamat yang butuh diselamatkan,\n"
            "  akhir tak terduga dari cerita biasa, karakter yang salah duga semua orang\n\n"
            "ATURAN PEMILIHAN:\n"
            "1. Baca riwayat di atas — pilih tema dari KATEGORI BERBEDA dari 3 episode terakhir\n"
            "2. Tambahkan elemen unik: setting tidak biasa, kombinasi karakter tak terduga, atau twist di akhir\n"
            "3. Karakter WAJIB punya nama yang mudah diucapkan dan ciri fisik yang sangat berbeda satu sama lain"
        )
    scene_instruksi = f"JUMLAH SCENE: WAJIB tepat {jumlah_scene} scene." if jumlah_scene else \
        ("JUMLAH SCENE: Tentukan sendiri berdasarkan kompleksitas cerita:\n"
         "  - Cerita SIMPEL (1 karakter, konflik langsung, misal: 1 karakter 1 masalah) → 5 scene\n"
         "  - Cerita MENENGAH (2 karakter, twist 1x, misal: persaingan/persahabatan) → 6 scene\n"
         "  - Cerita KOMPLEKS (3+ karakter, banyak twist, subplot, misal: petualangan kelompok) → 7-8 scene\n"
         "  WAJIB memilih angka spesifik sesuai kompleksitas cerita yang dibuat.")
    vo_lang  = "BAHASA INDONESIA" if bahasa_vo  == "id" else "BAHASA INGGRIS"
    ov_lang  = "BAHASA INDONESIA" if bahasa_overlay == "id" else "BAHASA INGGRIS"
    # prompt_dola_ai (video) SELALU Bahasa Indonesia
    return f"""
Kamu adalah penulis cerita animasi kelas dunia untuk YouTube Shorts — spesialis konten claymation yang viral.
Buat 1 episode animasi pendek YouTube Shorts yang UNIK, MENGHIBUR, dan membuat penonton PENASARAN menonton sampai akhir.

{topik_instruksi}

RIWAYAT EPISODE SEBELUMNYA (JANGAN diulangi):
{riwayat}

ATURAN BAHASA — KRITIS, WAJIB DIIKUTI TANPA PENGECUALIAN:
A. naskah_vo: WAJIB dalam {vo_lang}. DILARANG campur bahasa. Panjang VO: 15-25 kata per scene (tidak lebih, tidak kurang).
B. teks_overlay: WAJIB dalam {ov_lang}. JANGAN masukkan ke dalam prompt_dola_ai.
C. prompt_dola_ai: WAJIB BAHASA INDONESIA TANPA PENGECUALIAN. Ini adalah prompt untuk Dola AI (tool AI video).
   Berisi: setting + karakter + aksi + ekspresi + kamera + Audio. TANPA teks overlay sama sekali.
   ⚠️ DILARANG menulis prompt_dola_ai dalam Bahasa Inggris.
D. prompt_referensi_scene: WAJIB BAHASA INGGRIS. Minimal 120 kata.
   WAJIB mencakup semua elemen ini secara spesifik:
   - Jenis gambar: "Claymation still frame," atau "Stop-motion animation photography,"
   - Setting lokasi: latar belakang, material permukaan, pencahayaan (warm/cool, sumber cahaya)
   - Karakter: nama karakter, deskripsi fisik lengkap (warna clay, bentuk, pakaian), posisi, ekspresi wajah yang dilebihkan
   - Aksi utama: apa yang sedang dilakukan karakter di scene ini
   - Background: apakah blur, warna dominan, ada props/objek pendukung
   - Mood visual: color tone keseluruhan (bright/moody/playful), atmosfer emosional
   - Kualitas: "ultra sharp, 8K resolution, professional stop-motion studio lighting"
E. prompt_gambar_referensi_global, semua prompt thumbnail: WAJIB BAHASA INGGRIS.
F. Metadata YouTube (judul, deskripsi, tags, komentar_pinned): BAHASA INGGRIS.

ATURAN VOICE OVER — SUPER KETAT (untuk menghindari bug dan miss pada AI):
VO1. KONSISTENSI NAMA: Setiap kali menyebut karakter, SELALU gunakan NAMA LENGKAP yang SAMA PERSIS seperti yang didefinisikan di karakter_utama. DILARANG pakai pronoun (dia, he, she, they) TANPA menyebut nama dulu dalam kalimat yang sama.
VO2. SPESIFISITAS: Setiap VO WAJIB menyebutkan: SIAPA yang melakukan APA di MANA. Tidak boleh abstrak atau ambigu.
VO3. TIDAK ADA IMPROVISASI: VO harus sesuai PERSIS dengan yang terjadi di scene. Tidak ada VO yang "mungkin" atau "sepertinya".
VO4. FORMAT: Narrator third-person. Nada storytelling / dongeng. BUKAN instruksi atau pertanyaan langsung ke penonton.
VO5. PANJANG: 15-25 kata per scene. Lebih dari 25 kata = SALAH. Kurang dari 15 kata = SALAH.
VO6. PENGUCAPAN: Hindari kata-kata sulit diucapkan atau ambigu dalam bahasa yang dipilih.

ATURAN KARAKTER — KONSISTENSI WAJIB:
K1. Setiap karakter WAJIB punya nama unik yang mudah diucapkan.
K2. Ciri fisik karakter WAJIB IDENTIK di semua scene (warna clay, bentuk, pakaian, rambut).
K3. Di setiap prompt_dola_ai, WAJIB sebutkan ulang ciri fisik karakter yang muncul secara lengkap.
K4. Ekspresi wajah harus DILEBIHKAN (exaggerated) sesuai emosi scene — ini kunci claymation.

STRUKTUR CERITA WAJIB:
- Scene 1: HOOK DRAMATIS — momen paling menegangkan/mengejutkan dari cerita (spoiler visual, bukan resolusi)
- Scene 2: Perkenalan karakter + setting + masalah awal
- Scene 3+: Eskalasi konflik, karakter berusaha & gagal
- Scene sebelum terakhir: Titik terendah atau keputusan paling penting
- Scene terakhir: Resolusi + TWIST KEJUTAN yang tidak terduga

ATURAN PRODUKSI:
1. {scene_instruksi}
2. GAYA VISUAL: Claymation — karakter bulat lucu, warna cerah kontras, latar sederhana tapi detail, ekspresi dilebihkan.
3. AUDIO di setiap prompt: "Audio: [deskripsi musik: playful/tense/triumphant sesuai mood scene]".
4. Setiap prompt_dola_ai: WAJIB deskripsikan setting + semua karakter yang muncul (dengan ciri fisik lengkap) + aksi yang dilakukan + ekspresi wajah + sudut kamera.
5. DILARANG dialog panjang. Maks 1 kalimat pendek dialog per karakter per scene jika diperlukan.

METADATA:
- judul_youtube: Bahasa Inggris, maks 70 karakter. Formula viral: [situasi relatable] + [twist]. Contoh: "The Shy Kid Nobody Noticed — Until This Happened 😱"
- judul_youtube_alternatif: 3 variasi, maks 70 karakter
- deskripsi_youtube: min 5 kalimat. Kalimat ke-2 WAJIB pertanyaan mendorong komentar. Sebelum baris penutup, tambahkan 1 baris kosong lalu baris: "🛒 Watch more: [AFFILIATE LINK]" (ini placeholder opsional untuk link affiliate). Akhiri dengan baris hashtag: "#Shorts #claymation #animation #satisfying #animatedstory". Subscribe CTA: "Subscribe for more heartwarming animation stories every week! 🔔". TOTAL hashtag di deskripsi: 5-6 hashtag saja.
- tags_youtube: MINIMAL 30 tag, mix claymation + animation + educational + lokasi internasional. WAJIB sertakan: #Shorts, #claymation, #animation, #satisfying, #animationshorts, #claymationart, #stopmotion, #shortfilm, #animatedstory, #moralstory. Format: #tag1, #tag2, #tag3, ... (pisahkan dengan koma)
- komentar_pinned: 1 pertanyaan Bahasa Inggris untuk di-pin, mendorong penonton berbagi cerita pribadi
- playlist_youtube: WAJIB pilih TEPAT 1 dari daftar playlist berikut:
  * "Comedy & Daily Life" → komedi, slice of life, situasi lucu sehari-hari, misunderstanding
  * "Adventure & Mystery" → petualangan, eksplorasi, misteri, pencarian, thriller ringan
  * "Friendship & Family" → persahabatan, keluarga, tim, tolong-menolong, reunion
  * "Moral & Nature Tales" → pesan moral, lingkungan hidup, fabel modern, lesson learned
  * "Twist & Surprise Endings" → dark comedy ringan, plot twist, ending tak terduga, ironi
  ⚠️ Pilih SATU playlist berdasarkan genre/tone cerita yang paling dominan.
THUMBNAIL (Bahasa Inggris):
- teks_thumbnail: maks 4 kata KAPITAL, memicu rasa ingin tahu
- prompt_thumbnail_ai: min 80 kata, mulai: "YouTube thumbnail image, 16:9 aspect ratio, claymation animation style,"
- prompt_thumbnail_midjourney: akhiri --ar 16:9 --style raw --v 6
- prompt_gambar_referensi_global: BAHASA INGGRIS min 120 kata — gambarkan SEMUA karakter bersama di setting cerita, claymation style.
  ⚠️ WAJIB describe setiap karakter secara SPESIFIK: nama, warna clay tubuh, bentuk, pakaian, ekspresi, posisi berdiri/duduk.
  Contoh BENAR: "...Bimo, a round chubby blue clay character wearing a red clay hat, standing with arms raised in surprise, next to Kiki, a thin yellow clay girl with green clay braids, hiding behind a clay rock..."
  Contoh SALAH: "...claymation characters in a colorful setting..." (terlalu generik — DALL-E tidak tahu siapa karakternya)

Output HARUS berupa JSON murni:
{{
  "judul_karya": "Judul episode Bahasa Indonesia",
  "karakter_utama": [
    {{"nama": "NamaKarakter", "ciri_fisik": "Deskripsi lengkap: warna clay, bentuk tubuh, pakaian, rambut, ekspresi default", "peran": "protagonis/antagonis/pendukung"}}
  ],
  "jumlah_scene_dipilih": [angka scene],
  "judul_youtube": "...",
  "judul_youtube_alternatif": ["...", "...", "..."],
  "deskripsi_youtube": "...",
  "tags_youtube": "#tag1, #tag2, #tag3, ...",
  "playlist_youtube": "Nama playlist dari daftar yang ditentukan",
  "komentar_pinned": "...",
  "thumbnail_konsep": {{
    "teks_thumbnail": "MAX 4 KATA KAPITAL",
    "prompt_thumbnail_ai": "...",
    "prompt_thumbnail_midjourney": "... --ar 16:9 --style raw --v 6"
  }},
  "sinopsis_cerita": "Ringkasan lengkap Bahasa Indonesia min 5 kalimat (perkenalan, konflik, eskalasi, twist, resolusi)",
  "pesan_moral": "Satu kalimat pesan moral dalam Bahasa Inggris",
  "prompt_gambar_referensi_global": "Full English prompt 120+ kata — semua karakter bersama di setting cerita, claymation style...",
  "alur_cerita": [
    {{
      "scene": 1,
      "langkah": "Dynamic Hook — Momen Paling Dramatis",
      "prompt_dola_ai": "[WAJIB BAHASA INDONESIA. Deskripsi visual scene. Sebutkan: setting, SEMUA karakter yang muncul dengan ciri fisik lengkap, aksi, ekspresi wajah yang dilebihkan, sudut kamera, Audio: [jenis musik]. TANPA overlay. Min 60 kata]",
      "naskah_vo": "[VO narrator dalam bahasa yang ditentukan. 15-25 kata. Sebutkan nama karakter, bukan pronoun]",
      "teks_overlay": "[Overlay dalam bahasa yang ditentukan. Maks 5 kata]",
      "prompt_referensi_scene": "[WAJIB BAHASA INGGRIS. Claymation still frame description 120+ kata — sebutkan jenis shot, setting, semua karakter dengan ciri fisik lengkap, aksi, ekspresi wajah, background, mood visual, dan quality tags untuk DALL-E]"
    }}
  ]
}}

PERINGATAN AKHIR:
- naskah_vo HARUS 15-25 kata — cek ulang sebelum output.
- Karakter HARUS konsisten nama dan ciri fisiknya di semua scene.
- teks_overlay TIDAK BOLEH ada di dalam prompt_dola_ai.
- prompt_referensi_scene HARUS dalam BAHASA INGGRIS, minimal 120 kata, dengan 7 elemen wajib.
"""

# ==========================================
# 3b. PROMPT REGENERATE SCENE
# ==========================================
def buat_prompt_regen_scene(tema, judul_karya, sinopsis, alur, no_scene, bahasa_vo, bahasa_overlay, bahasa_prompt_video):
    """Generate ulang SATU scene spesifik dengan konteks video yang sudah ada."""
    vo_lang  = "BAHASA INDONESIA" if bahasa_vo == "id" else "BAHASA INGGRIS"
    ov_lang  = "BAHASA INDONESIA" if bahasa_overlay == "id" else "BAHASA INGGRIS"
    vid_lang = "BAHASA INDONESIA"  # SELALU Indonesia — prompt video untuk Dola AI

    target = next((s for s in alur if str(s.get('scene','')) == str(no_scene)), {})
    langkah = target.get('langkah', f'Scene {no_scene}')
    alur_ringkas = "\n".join([f"  Scene {s.get('scene')}: {s.get('langkah','')}" for s in alur])

    if tema == "toy":
        fields_json = (
            '  "prompt_dola_ai": "[Deskripsi visual TANPA overlay. Kendaraan + aksi + setting + kamera + Audio. Min 60 kata. Dalam ' + vid_lang + ']",\n'
            '  "keterangan_aksi": "[BAHASA INDONESIA. 1-2 kalimat: kendaraan apa, melakukan apa, hasil terlihat]",\n'
            '  "teks_overlay": "[' + ov_lang + '. Maks 5 kata action label]",\n'
            '  "prompt_referensi_scene": "[WAJIB BAHASA INGGRIS. Photorealistic miniature photography 120+ kata — jenis shot, setting, kendaraan, aksi, background, mood visual, quality tags]"'
        )
        aturan_tambahan = "Video TANPA Voice Over. Tidak ada field naskah_vo."
    elif tema == "animation":
        fields_json = (
            '  "prompt_dola_ai": "[WAJIB BAHASA INDONESIA. Deskripsi visual + karakter (nama + ciri fisik) + aksi + ekspresi + kamera + Audio: [musik]. TANPA overlay. Min 60 kata]",\n'
            '  "naskah_vo": "[' + vo_lang + '. Narrator third-person. 15-25 kata. Sebutkan nama karakter]",\n'
            '  "teks_overlay": "[' + ov_lang + '. Maks 5 kata]",\n'
            '  "prompt_referensi_scene": "[WAJIB BAHASA INGGRIS. Claymation still frame 120+ kata — jenis shot, setting, karakter+ekspresi, aksi, background, mood visual, quality tags]"'
        )
        aturan_tambahan = (f"naskah_vo WAJIB dalam {vo_lang}. WAJIB 15-25 kata. Third-person narrator. Sebutkan nama karakter, bukan pronoun. "
                           f"prompt_dola_ai WAJIB BAHASA INDONESIA. prompt_referensi_scene WAJIB BAHASA INGGRIS.")
    else:  # diy
        fields_json = (
            '  "prompt_dola_ai": "[WAJIB BAHASA INDONESIA. Deskripsi visual meja + kondisi benda + aksi tangan (kulit sawo matang, hoodie abu-abu) + kamera + Audio: [musik]. TANPA overlay. Min 60 kata]",\n'
            '  "naskah_vo": "[' + vo_lang + '. 1-2 kalimat energetik. Maks 25 kata]",\n'
            '  "teks_overlay": "[' + ov_lang + '. Maks 5 kata]",\n'
            '  "prompt_referensi_scene": "[WAJIB BAHASA INGGRIS. Photorealistic DSLR photo 120+ kata — jenis foto, setting meja (kayu natural, warm light), detail tangan (medium brown skin, grey hoodie sleeve), kondisi objek, background (cream bokeh), mood visual, quality tags]"'
        )
        aturan_tambahan = (f"naskah_vo WAJIB dalam {vo_lang}. Energetik. MAKSIMAL 25 kata. "
                           f"prompt_dola_ai WAJIB BAHASA INDONESIA. prompt_referensi_scene WAJIB BAHASA INGGRIS min 120 kata, sertakan detail tangan dan meja yang konsisten.")

    return f"""
Kamu membantu regenerate SATU scene dari video yang sudah ada.

KONTEKS VIDEO:
- Judul: {judul_karya}
- Tema: {tema}
- Sinopsis/Konsep: {sinopsis}

STRUKTUR SEMUA SCENE (untuk referensi alur — JANGAN ubah):
{alur_ringkas}

TUGAS: Generate ulang hanya SCENE {no_scene} — "{langkah}" dengan versi yang lebih baik, detail, dan menarik.
WAJIB tetap sesuai dengan posisi dan alur video secara keseluruhan. JANGAN ubah field "scene" dan "langkah".

ATURAN WAJIB:
- prompt_dola_ai: WAJIB dalam {vid_lang}. Min 60 kata. TANPA teks overlay.
- teks_overlay: WAJIB dalam {ov_lang}. Maks 5 kata.
- {aturan_tambahan}
- prompt_referensi_scene: WAJIB BAHASA INGGRIS. Min 120 kata.
  Wajib mencakup: jenis shot, setting, objek/karakter detail, aksi utama, background, mood visual, quality tags.

Output HARUS berupa JSON murni (hanya 1 scene, tanpa array pembungkus):
{{
  "scene": {no_scene},
  "langkah": "{langkah}",
{fields_json}
}}
"""

# ==========================================
# 4. AI & SCHEDULER
# ==========================================
def dapatkan_ide_dengan_rotasi(prompt_text):
    import concurrent.futures
    for config in GEMINI_CONFIGS:
        try:
            client = genai.Client(api_key=config['api_key'])
            def _call(c=client, m=config['model']):
                return c.models.generate_content(
                    model=m, contents=prompt_text,
                    config=types.GenerateContentConfig(response_mime_type="application/json"))
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                future = ex.submit(_call)
                response = future.result(timeout=60)  # max 60 detik per model
            return response
        except concurrent.futures.TimeoutError:
            print(f"Timeout {config['model']} — lanjut ke model berikutnya")
            continue
        except Exception as e:
            print(f"Error {config['model']}: {e}")
            continue
    raise Exception("Semua API Key & Model habis limit atau timeout.")

_scheduler_sent = set()

def run_scheduler():
    """
    Cek setiap 30 detik apakah sekarang waktunya kirim pengingat upload
    berdasarkan target negara yang dipilih user.
    Semua waktu dalam WIB (UTC+7) format HH:MM.
    """
    while True:
        try:
            _now_wib = datetime.now(WIB)
            now_wib  = _now_wib.strftime("%H:%M")
            today    = _now_wib.strftime("%Y-%m-%d")
            chat_id = ambil_chat_id()
            if chat_id:
                pref   = ambil_preferensi(chat_id)
                target = pref.get("target_negara", "us_east")
                pt     = PRIME_TIMES.get(target, PRIME_TIMES["us_east"])
                tema   = pref.get("tema", "diy")

                key_pagi   = f"{today}_{target}_pagi"
                key_tengah = f"{today}_{target}_tengah"
                key_malam  = f"{today}_{target}_malam"

                kemarin_str = (datetime.now(WIB) - timedelta(days=1)).strftime("%Y-%m-%d")

                if now_wib == pt["waktu_pagi"] and key_pagi not in _scheduler_sent:
                    _scheduler_sent.add(key_pagi)
                    _scheduler_sent.discard(f"{kemarin_str}_{target}_pagi")
                    _scheduler_sent.discard(f"{kemarin_str}_{target}_tengah")
                    _scheduler_sent.discard(f"{kemarin_str}_{target}_malam")
                    bot.send_message(
                        chat_id,
                        f"🌅 <b>PENGINGAT UPLOAD SLOT 1!</b>\n"
                        f"30 menit lagi waktu upload pertama!\n"
                        f"🕐 <b>{pt['ket_pagi']}</b> — Siapkan videomu!",
                        parse_mode="HTML", reply_markup=keyboard_menu_utama(tema)
                    )

                elif pt.get("waktu_tengah") and now_wib == pt["waktu_tengah"] and key_tengah not in _scheduler_sent:
                    _scheduler_sent.add(key_tengah)
                    _scheduler_sent.discard(f"{kemarin_str}_{target}_pagi")
                    _scheduler_sent.discard(f"{kemarin_str}_{target}_tengah")
                    _scheduler_sent.discard(f"{kemarin_str}_{target}_malam")
                    bot.send_message(
                        chat_id,
                        f"🌙 <b>PENGINGAT UPLOAD SLOT 2!</b>\n"
                        f"30 menit lagi waktu upload kedua!\n"
                        f"🕐 <b>{pt['ket_tengah']}</b> — Siapkan videomu!",
                        parse_mode="HTML", reply_markup=keyboard_menu_utama(tema)
                    )

                elif now_wib == pt["waktu_malam"] and key_malam not in _scheduler_sent:
                    _scheduler_sent.add(key_malam)
                    _scheduler_sent.discard(f"{kemarin_str}_{target}_pagi")
                    _scheduler_sent.discard(f"{kemarin_str}_{target}_tengah")
                    _scheduler_sent.discard(f"{kemarin_str}_{target}_malam")
                    bot.send_message(
                        chat_id,
                        f"🌃 <b>PENGINGAT UPLOAD SLOT 3!</b>\n"
                        f"30 menit lagi waktu upload ketiga!\n"
                        f"🕐 <b>{pt['ket_malam']}</b> — Siapkan videomu!",
                        parse_mode="HTML", reply_markup=keyboard_menu_utama(tema)
                    )
        except Exception as e:
            print(f"[SCHEDULER ERROR] {e}")
        time.sleep(30)

# ==========================================
# 5. HELPER
# ==========================================
def esc(t):
    if not t: return ""
    return str(t).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

def kirim_html(chat_id, teks, delay=1.5):
    BATAS = 3800
    def _kirim(bag):
        try: bot.send_message(chat_id, bag, parse_mode="HTML")
        except: bot.send_message(chat_id, bag, parse_mode=None)
        time.sleep(delay)
    if len(teks) <= BATAS:
        _kirim(teks); return
    paragraf = teks.split('\n\n')
    chunk = ""
    for para in paragraf:
        calon = (chunk + '\n\n' + para).strip() if chunk else para
        if len(calon) <= BATAS:
            chunk = calon
        else:
            if chunk: _kirim(chunk)
            chunk = para if len(para) <= BATAS else para
    if chunk: _kirim(chunk)

def kirim_kode(chat_id, judul_html, isi_teks, delay=1.5):
    BATAS = 3500
    if judul_html:
        try: bot.send_message(chat_id, judul_html, parse_mode="HTML")
        except: bot.send_message(chat_id, judul_html, parse_mode=None)
        time.sleep(0.8)
    def _send_chunk(c):
        try: bot.send_message(chat_id, f"<pre>{esc(c)}</pre>", parse_mode="HTML")
        except: bot.send_message(chat_id, c, parse_mode=None)
        time.sleep(delay)
    if len(isi_teks) <= BATAS:
        _send_chunk(isi_teks); return
    baris = isi_teks.split('\n')
    chunk = ""
    for b in baris:
        if len(chunk) + len(b) + 1 <= BATAS:
            chunk += ('\n' if chunk else '') + b
        else:
            if chunk: _send_chunk(chunk)
            chunk = b
    if chunk: _send_chunk(chunk)

def generate_vo_audio(chat_id, nomor_scene, langkah, teks_vo, aksen="us", lambat=False):
    try:
        aksen_info = AKSEN_OPTIONS.get(aksen, AKSEN_OPTIONS["us"])
        lang = aksen_info["lang"]
        tld  = aksen_info.get("tld")
        filename = f"/tmp/vo_scene{nomor_scene}.mp3"
        if tld and lang == "en":
            tts = gTTS(text=teks_vo, lang='en', tld=tld, slow=lambat)
        else:
            tts = gTTS(text=teks_vo, lang=lang, slow=lambat)
        tts.save(filename)
        with open(filename, "rb") as f:
            bot.send_audio(chat_id, f,
                caption=f"🎙️ <b>VO Scene {nomor_scene} — {langkah}</b>",
                parse_mode="HTML", title=f"Scene {nomor_scene}")
        os.remove(filename)
        time.sleep(1)
    except Exception as e:
        bot.send_message(chat_id, f"⚠️ Error VO Scene {nomor_scene}: {e}", parse_mode="HTML")

def bersihkan_json(raw):
    """Bersihkan teks AI menjadi JSON murni. Tangani berbagai format wrapper."""
    raw = raw.strip()
    # Hapus code block wrapper
    if raw.startswith("```json"): raw = raw[7:]
    elif raw.startswith("```"): raw = raw[3:]
    if raw.endswith("```"): raw = raw[:-3]
    raw = raw.strip()
    # Temukan kurung kurawal pertama dan terakhir (JSON murni)
    start = raw.find('{')
    end   = raw.rfind('}')
    if start != -1 and end != -1 and end > start:
        raw = raw[start:end+1]
    return raw

def parse_json_dengan_retry(raw_text, prompt_asal, chat_id_log=None):
    """
    Coba parse JSON. Jika gagal, kirim prompt koreksi ke AI untuk perbaiki JSON.
    Maksimum 1 kali retry.
    """
    teks = bersihkan_json(raw_text)
    try:
        return json.loads(teks)
    except json.JSONDecodeError as e_pertama:
        if chat_id_log:
            print(f"[JSON Retry] Parse pertama gagal: {e_pertama}. Mencoba koreksi AI...")
        # Prompt koreksi — minta AI perbaiki JSON yang rusak
        prompt_koreksi = (
            f"JSON di bawah ini TIDAK VALID dan gagal di-parse dengan error:\n"
            f"{e_pertama}\n\n"
            f"Perbaiki JSON berikut agar valid (double quotes, tidak ada trailing comma, tutup semua kurung).\n"
            f"KEMBALIKAN HANYA JSON MURNI TANPA PENJELASAN APAPUN:\n\n"
            f"{teks[:3000]}"  # batasi 3000 char untuk hemat token
        )
        try:
            resp_koreksi = dapatkan_ide_dengan_rotasi(prompt_koreksi)
            teks_koreksi = bersihkan_json(resp_koreksi.text)
            return json.loads(teks_koreksi)
        except json.JSONDecodeError as e_kedua:
            # Kedua gagal — raise error asli dengan info retry
            raise json.JSONDecodeError(
                f"Gagal parse (percobaan 1: {e_pertama} | percobaan 2 setelah AI koreksi: {e_kedua})",
                e_kedua.doc, e_kedua.pos
            )

# ==========================================
# 6. KEYBOARDS
# ==========================================
def keyboard_menu_utama(tema='diy'):
    tema_label = TEMA_OPTIONS.get(tema, TEMA_OPTIONS['diy'])['label']
    kb = tbtypes.InlineKeyboardMarkup()
    kb.row(tbtypes.InlineKeyboardButton(f"🎬 Buat Konten  [{tema_label}]", callback_data="menu_konten"))
    kb.row(
        tbtypes.InlineKeyboardButton("🔀 Ganti Tema",    callback_data="menu_ganti_tema"),
        tbtypes.InlineKeyboardButton("⚙️ Preferensi",    callback_data="menu_preferensi"),
    )
    kb.row(
        tbtypes.InlineKeyboardButton("📋 Riwayat",       callback_data="menu_riwayat"),
        tbtypes.InlineKeyboardButton("🗑️ Hapus Riwayat", callback_data="menu_hapus_riwayat"),
    )
    kb.row(tbtypes.InlineKeyboardButton("📺 YouTube Monitor", callback_data="menu_youtube"))
    kb.row(tbtypes.InlineKeyboardButton("❓ Bantuan",         callback_data="menu_bantuan"))
    return kb

def keyboard_pilih_tema():
    kb = tbtypes.InlineKeyboardMarkup()
    kb.row(tbtypes.InlineKeyboardButton("🏗️ DIY Miniature",       callback_data="tema_diy"))
    kb.row(tbtypes.InlineKeyboardButton("🚛 AI Toy Construction",  callback_data="tema_toy"))
    kb.row(tbtypes.InlineKeyboardButton("🎭 AI Animation",         callback_data="tema_animation"))
    kb.row(tbtypes.InlineKeyboardButton("🏠 Kembali",              callback_data="menu_utama"))
    return kb

def keyboard_konfirmasi_hapus():
    kb = tbtypes.InlineKeyboardMarkup()
    kb.row(
        tbtypes.InlineKeyboardButton("✅ Ya, Hapus", callback_data="konfirmasi_hapus_ya"),
        tbtypes.InlineKeyboardButton("❌ Batal",     callback_data="konfirmasi_hapus_tidak"),
    )
    return kb

def keyboard_youtube_monitor():
    kb = tbtypes.InlineKeyboardMarkup()
    kb.row(tbtypes.InlineKeyboardButton("🔍 Scan Channel Sekarang",    callback_data="yt_scan"))
    kb.row(tbtypes.InlineKeyboardButton("📊 Cek Views Semua Video",    callback_data="yt_cek_views"))
    kb.row(tbtypes.InlineKeyboardButton("📈 Analitik Pertumbuhan",     callback_data="yt_analitik"))
    kb.row(tbtypes.InlineKeyboardButton("💡 Ide Konten dari Tren",     callback_data="yt_ide_tren"))
    kb.row(tbtypes.InlineKeyboardButton("📋 Daftar Video Monitor",     callback_data="yt_daftar"))
    kb.row(tbtypes.InlineKeyboardButton("🎯 Lihat Milestone Aktif",    callback_data="yt_lihat_milestone"))
    kb.row(
        tbtypes.InlineKeyboardButton("⚙️ Set Milestone Views", callback_data="yt_set_milestone_views"),
        tbtypes.InlineKeyboardButton("⚙️ Set Milestone Likes", callback_data="yt_set_milestone_likes"),
    )
    kb.row(
        tbtypes.InlineKeyboardButton("⚡ Set Threshold Viral", callback_data="yt_set_viral"),
        tbtypes.InlineKeyboardButton("📤 Export CSV",          callback_data="yt_export"),
    )
    kb.row(tbtypes.InlineKeyboardButton("🗑️ Hapus Video dari Monitor",      callback_data="yt_hapus"))
    kb.row(tbtypes.InlineKeyboardButton("📅 Pengaturan Ringkasan Mingguan", callback_data="yt_setting_weekly"))
    kb.row(tbtypes.InlineKeyboardButton("❓ Panduan YouTube Monitor",        callback_data="yt_panduan"))
    kb.row(tbtypes.InlineKeyboardButton("🏠 Kembali",                        callback_data="menu_utama"))
    return kb

def keyboard_mulai():
    kb = tbtypes.InlineKeyboardMarkup()
    kb.row(
        tbtypes.InlineKeyboardButton("🎲 Random",      callback_data="topik_random"),
        tbtypes.InlineKeyboardButton("✏️ Pilih Topik", callback_data="topik_manual"),
    )
    kb.row(tbtypes.InlineKeyboardButton("🏠 Menu Utama", callback_data="menu_utama"))
    return kb

def keyboard_jumlah_scene():
    kb = tbtypes.InlineKeyboardMarkup()
    kb.row(
        tbtypes.InlineKeyboardButton("4️⃣ 4 Scene", callback_data="scene_4"),
        tbtypes.InlineKeyboardButton("5️⃣ 5 Scene", callback_data="scene_5"),
        tbtypes.InlineKeyboardButton("6️⃣ 6 Scene", callback_data="scene_6"),
    )
    kb.row(tbtypes.InlineKeyboardButton("🎲 AI Pilihkan (Optimal)", callback_data="scene_auto"))
    return kb

def keyboard_jumlah_scene_default():
    kb = tbtypes.InlineKeyboardMarkup()
    kb.row(
        tbtypes.InlineKeyboardButton("4️⃣ 4 Scene",   callback_data="scene_default_4"),
        tbtypes.InlineKeyboardButton("5️⃣ 5 Scene",   callback_data="scene_default_5"),
        tbtypes.InlineKeyboardButton("6️⃣ 6 Scene",   callback_data="scene_default_6"),
    )
    kb.row(tbtypes.InlineKeyboardButton("🎲 AI Pilihkan", callback_data="scene_default_auto"))
    kb.row(tbtypes.InlineKeyboardButton("🔙 Kembali ke Preferensi", callback_data="menu_preferensi"))
    return kb

def keyboard_aksen():
    kb = tbtypes.InlineKeyboardMarkup()
    kb.row(
        tbtypes.InlineKeyboardButton("🇺🇸 American", callback_data="aksen_us"),
        tbtypes.InlineKeyboardButton("🇬🇧 British",  callback_data="aksen_uk"),
    )
    kb.row(
        tbtypes.InlineKeyboardButton("🇦🇺 Australian", callback_data="aksen_au"),
        tbtypes.InlineKeyboardButton("🇮🇳 Indian",     callback_data="aksen_in"),
    )
    kb.row(tbtypes.InlineKeyboardButton("🇮🇩 Indonesia", callback_data="aksen_id"))
    kb.row(tbtypes.InlineKeyboardButton("🔙 Kembali ke Preferensi", callback_data="menu_preferensi"))
    return kb

def keyboard_kecepatan():
    kb = tbtypes.InlineKeyboardMarkup()
    kb.row(
        tbtypes.InlineKeyboardButton("⚡ Normal", callback_data="speed_normal"),
        tbtypes.InlineKeyboardButton("🐢 Lambat", callback_data="speed_slow"),
    )
    kb.row(tbtypes.InlineKeyboardButton("🔙 Kembali ke Preferensi", callback_data="menu_preferensi"))
    return kb

def keyboard_bahasa_prompt_video():
    kb = tbtypes.InlineKeyboardMarkup()
    kb.row(
        tbtypes.InlineKeyboardButton("🇺🇸 Prompt Video: Bahasa Inggris", callback_data="bpv_en"),
        tbtypes.InlineKeyboardButton("🇮🇩 Prompt Video: Bahasa Indonesia", callback_data="bpv_id"),
    )
    kb.row(tbtypes.InlineKeyboardButton("🔙 Kembali ke Preferensi", callback_data="menu_preferensi"))
    return kb

def keyboard_bahasa_overlay():
    kb = tbtypes.InlineKeyboardMarkup()
    kb.row(
        tbtypes.InlineKeyboardButton("🇺🇸 Overlay: English",   callback_data="bo_en"),
        tbtypes.InlineKeyboardButton("🇮🇩 Overlay: Indonesia", callback_data="bo_id"),
    )
    kb.row(tbtypes.InlineKeyboardButton("🔙 Kembali ke Preferensi", callback_data="menu_preferensi"))
    return kb

def keyboard_target_negara():
    kb = tbtypes.InlineKeyboardMarkup()
    kb.row(
        tbtypes.InlineKeyboardButton("🇺🇸 USA East (EST)", callback_data="negara_us_east"),
        tbtypes.InlineKeyboardButton("🇺🇸 USA West (PST)", callback_data="negara_us_west"),
    )
    kb.row(
        tbtypes.InlineKeyboardButton("🇬🇧 United Kingdom", callback_data="negara_uk"),
        tbtypes.InlineKeyboardButton("🇦🇺 Australia",      callback_data="negara_au"),
    )
    kb.row(
        tbtypes.InlineKeyboardButton("🇸🇬 Singapore",      callback_data="negara_sg"),
        tbtypes.InlineKeyboardButton("🇯🇵 Japan",          callback_data="negara_jp"),
    )
    kb.row(
        tbtypes.InlineKeyboardButton("🇮🇳 India",          callback_data="negara_in"),
        tbtypes.InlineKeyboardButton("🇮🇩 Indonesia (WIB)", callback_data="negara_id"),
    )
    kb.row(tbtypes.InlineKeyboardButton("🔙 Kembali ke Preferensi", callback_data="menu_preferensi"))
    return kb

def keyboard_bahasa_vo_animasi():
    """Pilihan VO bahasa khusus sebelum generate animasi."""
    kb = tbtypes.InlineKeyboardMarkup()
    kb.row(
        tbtypes.InlineKeyboardButton("🇺🇸 VO: Bahasa Inggris",   callback_data="bvo_en"),
        tbtypes.InlineKeyboardButton("🇮🇩 VO: Bahasa Indonesia", callback_data="bvo_id"),
    )
    kb.row(tbtypes.InlineKeyboardButton("🏠 Batal ke Menu", callback_data="menu_utama"))
    return kb

def keyboard_bahasa_vo_preferensi():
    """Pilihan bahasa VO dari menu Preferensi (berlaku untuk DIY & Animation)."""
    kb = tbtypes.InlineKeyboardMarkup()
    kb.row(
        tbtypes.InlineKeyboardButton("🇺🇸 VO: Bahasa Inggris",   callback_data="bvopref_en"),
        tbtypes.InlineKeyboardButton("🇮🇩 VO: Bahasa Indonesia", callback_data="bvopref_id"),
    )
    kb.row(tbtypes.InlineKeyboardButton("🔙 Kembali ke Preferensi", callback_data="menu_preferensi"))
    return kb

def keyboard_konfirmasi_vo():
    kb = tbtypes.InlineKeyboardMarkup()
    kb.row(
        tbtypes.InlineKeyboardButton("✅ Generate Audio VO", callback_data="vo_generate"),
        tbtypes.InlineKeyboardButton("❌ Lewati Audio",      callback_data="vo_skip"),
    )
    return kb

def keyboard_regenerate(alur):
    kb = tbtypes.InlineKeyboardMarkup()
    buttons = [tbtypes.InlineKeyboardButton(f"🔄 Scene {s.get('scene','')}", callback_data=f"regen_{s.get('scene','')}") for s in alur]
    for i in range(0, len(buttons), 3):
        kb.row(*buttons[i:i+3])
    kb.row(
        tbtypes.InlineKeyboardButton("✅ Selesai",     callback_data="regen_selesai"),
        tbtypes.InlineKeyboardButton("🎬 Konten Baru", callback_data="menu_konten"),
    )
    return kb

def keyboard_preferensi_menu(pref):
    tema  = pref.get("tema","diy")
    tema_label    = TEMA_OPTIONS.get(tema, TEMA_OPTIONS["diy"])["label"]
    aksen_label   = AKSEN_OPTIONS.get(pref["aksen"], AKSEN_OPTIONS["us"])["label"]
    speed_label   = "🐢 Lambat" if pref["kecepatan"] == "slow" else "⚡ Normal"
    scene_label   = "🎲 AI Pilihkan" if pref["jumlah_scene"] == 0 else f"{pref['jumlah_scene']} scene"
    bpv_label     = "🇮🇩 Indonesia" if pref.get("bahasa_prompt_video","en") == "id" else "🇺🇸 English"
    bo_label      = "🇮🇩 Indonesia" if pref.get("bahasa_overlay","en") == "id" else "🇺🇸 English"
    bvo_label     = "🇮🇩 Indonesia" if pref.get("bahasa_vo","en") == "id" else "🇺🇸 English"
    negara_key    = pref.get("target_negara","id")
    negara_label  = PRIME_TIMES.get(negara_key, PRIME_TIMES["id"])["label"]
    kb = tbtypes.InlineKeyboardMarkup()
    kb.row(tbtypes.InlineKeyboardButton(f"🔀 Tema: {tema_label}",              callback_data="menu_ganti_tema"))
    kb.row(tbtypes.InlineKeyboardButton(f"🎙️ Aksen VO: {aksen_label}",         callback_data="pref_aksen"))
    kb.row(tbtypes.InlineKeyboardButton(f"🗣️ Bahasa VO: {bvo_label}",          callback_data="pref_bvo"))
    kb.row(tbtypes.InlineKeyboardButton(f"⚡ Kecepatan: {speed_label}",         callback_data="pref_speed"))
    kb.row(tbtypes.InlineKeyboardButton(f"🎞️ Scene Default: {scene_label}",    callback_data="pref_scene"))
    kb.row(tbtypes.InlineKeyboardButton(f"🎬 Prompt Video: 🇮🇩 Indonesia (fixed)", callback_data="info_bpv_fixed"))
    kb.row(tbtypes.InlineKeyboardButton(f"📺 Overlay: {bo_label}",             callback_data="pref_bo"))
    kb.row(tbtypes.InlineKeyboardButton(f"🌍 Target Negara: {negara_label}",   callback_data="pref_negara"))
    kb.row(tbtypes.InlineKeyboardButton("🏠 Menu Utama",                       callback_data="menu_utama"))
    return kb

# ==========================================
# 7. CORE: GENERATE & KIRIM
# ==========================================
def proses_dan_kirim(chat_id, topik, jumlah_scene, tema, bahasa_vo):
    # Guard: tolak kalau user masih dalam proses
    if chat_id in processing_users:
        bot.send_message(chat_id, "⏳ Masih memproses konten sebelumnya. Harap tunggu hingga selesai.")
        return
    processing_users.add(chat_id)
    try:
        _proses_dan_kirim_internal(chat_id, topik, jumlah_scene, tema, bahasa_vo)
    finally:
        processing_users.discard(chat_id)

def _proses_dan_kirim_internal(chat_id, topik, jumlah_scene, tema, bahasa_vo):
    pref = ambil_preferensi(chat_id)
    aksen = pref["aksen"]
    lambat = pref["kecepatan"] == "slow"
    bahasa_prompt_video = "id"  # DIKUNCI: prompt video selalu Bahasa Indonesia untuk Dola AI
    bahasa_overlay = pref.get("bahasa_overlay", "en")
    aksen_info = AKSEN_OPTIONS.get(aksen, AKSEN_OPTIONS["us"])
    label_aksen = aksen_info["label"]
    tema_info = TEMA_OPTIONS.get(tema, TEMA_OPTIONS["diy"])
    tema_label = tema_info["label"]
    tema_emoji = tema_info["emoji"]

    scene_label = "AI Pilihkan (Optimal)" if not jumlah_scene else f"{jumlah_scene} scene"
    bvo_label = "🇮🇩 Indonesia" if bahasa_vo == "id" else "🇺🇸 English"
    bpv_label = "🇮🇩 Indonesia (dikunci)"  # selalu Indonesia
    bo_label  = "🇮🇩 Indonesia" if bahasa_overlay == "id" else "🇺🇸 English"

    info_lines = [
        f"⏳ <b>Memproses...</b>",
        f"{tema_emoji} Tema: <b>{tema_label}</b>",
        f"📌 Topik: <b>{'Random' if not topik else topik}</b>",
        f"🎞️ Scene: <b>{scene_label}</b>",
    ]
    if tema != "toy":
        info_lines.append(f"🎙️ VO: <b>{label_aksen}</b> | Bahasa VO: <b>{bvo_label}</b>")
    else:
        info_lines.append(f"🎵 Tanpa VO — Tambahkan backsound sendiri")
    info_lines += [f"🎬 Prompt Video: <b>{bpv_label}</b>", f"📺 Overlay: <b>{bo_label}</b>"]
    bot.send_message(chat_id, "\n".join(info_lines), parse_mode="HTML")

    riwayat = ambil_memori(tema)
    teks_riwayat = "\n".join(riwayat) if riwayat else "Belum ada."

    try:
        if tema == "toy":
            prompt_text = buat_prompt_toy(teks_riwayat, topik, jumlah_scene, bahasa_overlay, bahasa_prompt_video)
        elif tema == "animation":
            prompt_text = buat_prompt_animasi(teks_riwayat, topik, jumlah_scene, bahasa_vo, bahasa_overlay, bahasa_prompt_video)
        else:
            prompt_text = buat_prompt_diy(teks_riwayat, topik, jumlah_scene, bahasa_vo, bahasa_overlay, bahasa_prompt_video)

        response = dapatkan_ide_dengan_rotasi(prompt_text)
        hasil_ai = parse_json_dengan_retry(response.text, prompt_text, chat_id)
        nomor_ep = len(riwayat) + 1

        judul_karya_raw = hasil_ai.get('judul_karya', '')
        simpan_ke_memori(f"Episode {nomor_ep}: {judul_karya_raw}", tema)

        alur = hasil_ai.get('alur_cerita', [])
        total_scene = len(alur)
        titik_tengah = total_scene // 2

        # --- Field per tema ---
        judul_karya   = esc(judul_karya_raw)
        judul_yt      = esc(hasil_ai.get('judul_youtube', ''))
        judul_alt     = hasil_ai.get('judul_youtube_alternatif', [])
        desk_yt       = esc(hasil_ai.get('deskripsi_youtube', ''))
        tags_yt       = esc(hasil_ai.get('tags_youtube', ''))
        playlist_yt   = esc(hasil_ai.get('playlist_youtube', ''))
        komen_pinned  = esc(hasil_ai.get('komentar_pinned', ''))
        ref_global    = esc(hasil_ai.get('prompt_gambar_referensi_global', ''))

        if tema == "animation":
            info_produksi = ""
            chars = hasil_ai.get('karakter_utama', [])
            if isinstance(chars, list):
                for c in chars:
                    info_produksi += f"• <b>{esc(c.get('nama',''))}</b> [{esc(c.get('peran',''))}]: {esc(c.get('ciri_fisik',''))}\n"
            else:
                info_produksi = esc(str(chars))
            label_produksi = "🎭 Karakter"
            konsep = esc(hasil_ai.get('sinopsis_cerita', ''))
            pesan_moral = esc(hasil_ai.get('pesan_moral', ''))
            ai_tool = "Kling AI / Seedance"
        elif tema == "toy":
            info_produksi = esc(hasil_ai.get('alat_kendaraan', ''))
            label_produksi = "🚛 Kendaraan & Alat"
            konsep = esc(hasil_ai.get('deskripsi_konsep_video', ''))
            ai_tool = "Seedance / Dola AI"
        else:
            info_produksi = esc(hasil_ai.get('bahan_utama', ''))
            label_produksi = "📦 Bahan & Alat"
            konsep = esc(hasil_ai.get('deskripsi_konsep_video', ''))
            ai_tool = "Dola AI"

        # --- Panduan Eksekusi ---
        if tema == "toy":
            panduan = (
                "1️⃣ Copy <b>REFERENSI GLOBAL</b> ke ChatGPT/DALL-E\n"
                "2️⃣ Simpan <b>METADATA YOUTUBE</b> ke catatan\n"
                "3️⃣ Copy <b>REFERENSI PER SCENE</b> ke ChatGPT/DALL-E sesuai scene\n"
                "4️⃣ Copy <b>PROMPT MASTER GPT Bagian 1 &amp; 2</b> ke ChatGPT\n"
                "5️⃣ Masukkan hasil ke <b>Seedance / Dola AI</b>\n"
                "6️⃣ Tambahkan <b>backsound musik</b> sendiri saat editing\n"
                "7️⃣ Tambahkan <b>TEXT OVERLAY</b> sesuai daftar scene\n"
                "8️⃣ Upload video — isi <b>Judul, Deskripsi, Tags</b> dari metadata\n"
                "9️⃣ Assign ke <b>Playlist</b> yang tertera di metadata\n"
                "🔟 Buat <b>thumbnail</b> & <b>PIN komentar</b> setelah upload\n"
            )
        elif tema == "animation":
            panduan = (
                "1️⃣ Copy <b>REFERENSI GLOBAL</b> ke ChatGPT/DALL-E (generate karakter)\n"
                "2️⃣ Simpan <b>METADATA YOUTUBE</b> ke catatan\n"
                "3️⃣ Copy <b>REFERENSI PER SCENE</b> ke ChatGPT/DALL-E sesuai scene\n"
                "4️⃣ Copy <b>PROMPT MASTER GPT Bagian 1 &amp; 2</b> ke ChatGPT\n"
                "5️⃣ Masukkan hasil ke <b>Kling AI / Seedance</b>\n"
                "6️⃣ Download audio <b>VO</b> dan masukkan ke editor\n"
                "7️⃣ Tambahkan <b>TEXT OVERLAY</b> sesuai daftar scene\n"
                "8️⃣ Upload video — isi <b>Judul, Deskripsi, Tags</b> dari metadata\n"
                "9️⃣ Assign ke <b>Playlist</b> yang tertera di metadata\n"
                "🔟 Buat <b>thumbnail</b> & <b>PIN komentar</b> setelah upload\n"
            )
        else:
            panduan = (
                "1️⃣ Copy <b>REFERENSI GLOBAL</b> ke ChatGPT/DALL-E\n"
                "2️⃣ Simpan <b>METADATA YOUTUBE</b> ke catatan\n"
                "3️⃣ Copy <b>REFERENSI PER SCENE</b> ke ChatGPT/DALL-E sesuai scene\n"
                "4️⃣ Copy <b>PROMPT MASTER GPT Bagian 1 &amp; 2</b> ke ChatGPT\n"
                "5️⃣ Masukkan hasil ke <b>Dola AI</b>\n"
                "6️⃣ Download audio <b>VO</b> dan masukkan ke editor\n"
                "7️⃣ Tambahkan <b>TEXT OVERLAY</b> sesuai daftar scene\n"
                "8️⃣ Upload video — isi <b>Judul, Deskripsi, Tags</b> dari metadata\n"
                "9️⃣ Assign ke <b>Playlist</b> yang tertera di metadata\n"
                "🔟 Buat <b>thumbnail</b> & <b>PIN komentar</b> setelah upload\n"
            )

        # --- PESAN 1: METADATA & KONSEP ---
        pesan_info  = f"{tema_emoji} <b>EPISODE {nomor_ep} — {judul_karya}</b>\n"
        pesan_info += f"<i>Tema: {tema_label} | Scene: {total_scene}</i>\n\n"
        pesan_info += "<b>📋 PANDUAN EKSEKUSI:</b>\n" + panduan + "\n"
        pesan_info += f"{label_produksi}: {info_produksi}\n\n"
        if tema == "animation" and pesan_moral:
            pesan_info += f"💡 <b>Pesan Moral:</b> <i>{pesan_moral}</i>\n\n"
        pesan_info += f"<b>📖 KONSEP/SINOPSIS:</b>\n{konsep}\n\n"
        pesan_info += "<b>📌 METADATA YOUTUBE:</b>\n"
        pesan_info += f"🎯 <b>Judul Utama:</b>\n<code>{judul_yt}</code>\n\n"
        if judul_alt:
            pesan_info += "🔀 <b>Judul Alternatif:</b>\n"
            for i, alt in enumerate(judul_alt, 1):
                pesan_info += f"  {i}. <code>{esc(str(alt))}</code>\n"
            pesan_info += "\n"
        pesan_info += f"📝 <b>Deskripsi</b> <i>(masukkan ke kolom Description di YouTube Studio — ganti [AFFILIATE LINK] dengan link Shopee-mu, atau hapus baris itu jika belum ada):</i>\n<code>{desk_yt}</code>\n\n"
        pesan_info += f"🏷️ <b>Tags/Hashtag</b> <i>(masukkan ke kolom Tags di YouTube Studio — TERMASUK #Shorts):</i>\n<code>{tags_yt}</code>\n\n"
        if playlist_yt:
            pesan_info += f"📂 <b>Playlist:</b> <code>{playlist_yt}</code>\n<i>→ Assign ke playlist ini setelah upload!</i>\n\n"
        if komen_pinned:
            pesan_info += f"📌 <b>KOMENTAR YANG HARUS DI-PIN:</b>\n<code>{komen_pinned}</code>\n<i>→ Pin segera setelah upload!</i>\n\n"
        bvo_display = "🇮🇩 Indonesia" if bahasa_vo == "id" else "🇺🇸 English"
        pesan_info += f"🎙️ <b>Bahasa VO episode ini:</b> {bvo_display}\n\n"
        pesan_info += f"<b>🖼️ REFERENSI GLOBAL:</b>\n<code>{ref_global}</code>"
        kirim_html(chat_id, pesan_info)

        # --- THUMBNAIL PROMPT ---
        thumb = hasil_ai.get('thumbnail_konsep', {})
        if thumb:
            teks_thumb  = thumb.get('teks_thumbnail', '')
            dalle_p     = thumb.get('prompt_thumbnail_ai', '')
            mj_p        = thumb.get('prompt_thumbnail_midjourney', '')
            pesan_thumb = f"🎨 <b>PROMPT THUMBNAIL YOUTUBE</b>\n<i>Copy langsung ke DALL-E / Midjourney!</i>\n\n🔤 <b>Teks di Thumbnail:</b> <code>{esc(teks_thumb)}</code>\n\n"
            kirim_html(chat_id, pesan_thumb, delay=0.5)
            if dalle_p:
                kirim_kode(chat_id, "🖼️ <b>PROMPT DALL-E / ChatGPT Image:</b>", dalle_p, delay=1)
            if mj_p:
                kirim_kode(chat_id, "🎨 <b>PROMPT MIDJOURNEY:</b>", mj_p, delay=1)

        # --- PESAN 2: REFERENSI PER SCENE ---
        kirim_html(chat_id, "🖼️ <b>REFERENSI GAMBAR PER SCENE</b>\n<i>Copy prompt sesuai scene ke ChatGPT/DALL-E:</i>", delay=0.5)
        for scene in alur:
            no   = esc(str(scene.get('scene','')))
            lang = esc(scene.get('langkah',''))
            ref  = scene.get('prompt_referensi_scene', '')
            kirim_kode(chat_id, f"🎬 <b>SCENE {no} — {lang}</b>", ref, delay=1)

        # --- PESAN 3: VO & OVERLAY (DAFTAR LENGKAP) ---
        pesan_vo = f"🎙️ <b>{'VOICE OVER & ' if tema != 'toy' else ''}TEXT OVERLAY PER SCENE</b>\n"
        if tema == "toy":
            pesan_vo += "<i>Tambahkan backsound sendiri. Overlay di bawah ini untuk diedit manual.</i>\n\n"
        else:
            pesan_vo += "<i>Overlay tidak dimasukkan ke dalam video prompt — tambahkan sendiri saat editing.</i>\n\n"
        for scene in alur:
            no      = esc(str(scene.get('scene','')))
            lang    = esc(scene.get('langkah',''))
            overlay = esc(scene.get('teks_overlay',''))
            pesan_vo += f"🎬 <b>Scene {no} — {lang}</b>\n"
            if tema == "toy":
                aksi = esc(scene.get('keterangan_aksi',''))
                pesan_vo += f"🚛 Aksi: {aksi}\n"
            else:
                vo = esc(scene.get('naskah_vo',''))
                pesan_vo += f"🎙️ VO: <i>{vo}</i>\n"
            pesan_vo += f"📺 Overlay: <code>{overlay}</code>\n\n"
        kirim_html(chat_id, pesan_vo)

        # --- PESAN 4 & 5: PROMPT MASTER CHATGPT ---
        def buat_gpt_rules():
            if tema == "animation":
                return (
                    f"ATURAN MUTLAK:\n"
                    f"🌐 BAHASA: Semua prompt video WAJIB ditulis dalam BAHASA INDONESIA. DILARANG Bahasa Inggris.\n"
                    f"1. Gaya visual: CLAYMATION — karakter clay lucu, warna cerah, ekspresi dilebihkan.\n"
                    f"2. Setiap prompt WAJIB: setting + SEMUA karakter (nama + ciri fisik lengkap) + aksi + ekspresi + kamera.\n"
                    f"3. TEKS OVERLAY JANGAN dimasukkan ke dalam prompt video.\n"
                    f"4. Audio: WAJIB tulis 'Audio: [jenis musik sesuai mood]'. TIDAK ADA suara manusia/VO.\n"
                    f"5. Karakter WAJIB konsisten nama dan ciri fisiknya di semua scene.\n"
                    f"6. Voice Over sudah dipisah dan akan ditambahkan saat editing — JANGAN sertakan VO di prompt video.\n\n"
                )
            elif tema == "toy":
                return (
                    f"ATURAN MUTLAK:\n"
                    f"🌐 BAHASA: Semua prompt video WAJIB ditulis dalam BAHASA INDONESIA. DILARANG Bahasa Inggris.\n"
                    f"1. Video ini TANPA VO — audio hanya suara konstruksi + musik.\n"
                    f"2. Setiap prompt WAJIB: jenis kendaraan + aksi spesifik + setting + sudut kamera.\n"
                    f"3. TEKS OVERLAY JANGAN dimasukkan ke dalam prompt video.\n"
                    f"4. Audio: WAJIB tulis 'Audio: [suara konstruksi realistis + jenis musik]'.\n"
                    f"5. Kamera bervariasi per scene (aerial, close-up, side view, low angle).\n\n"
                )
            else:  # DIY
                return (
                    f"ATURAN MUTLAK:\n"
                    f"🌐 BAHASA: Semua prompt video WAJIB ditulis dalam BAHASA INDONESIA. DILARANG Bahasa Inggris.\n"
                    f"1. KAMERA STATIS: diam atau bergerak sangat lambat. DILARANG dolly zoom atau rotasi cepat.\n"
                    f"2. STANDALONE SCENE: deskripsikan ulang meja (kayu natural, warm light), tangan (kulit sawo matang, hoodie abu-abu), dan benda di SETIAP scene — JANGAN tulis 'melanjutkan scene sebelumnya'.\n"
                    f"3. TEKS OVERLAY JANGAN dimasukkan ke dalam prompt video.\n"
                    f"4. GERAKAN TANGAN: gambarkan sebagai 'gerakan sangat cepat, lincah, dan presisi'.\n"
                    f"5. Audio: WAJIB tulis 'Audio: [backsound musik + suara kerja]'. TIDAK ADA voice over di prompt video.\n\n"
                )

        intro_gpt = (
            f"Halo ChatGPT! Tolong rapikan skenario ini menjadi {total_scene} prompt AI Video ({ai_tool}) "
            f"dalam BAHASA INDONESIA yang sangat detail dan deskriptif.\n"
            f"PENTING: Semua prompt video WAJIB dalam BAHASA INDONESIA. Prompt gambar referensi terpisah (tidak ada di sini) menggunakan Bahasa Inggris.\n"
        )

        isi_gpt_1 = intro_gpt + buat_gpt_rules()
        for scene in alur[:titik_tengah]:
            p = scene.get('prompt_dola_ai','').replace('\n',' ')
            isi_gpt_1 += f"[SCENE {scene.get('scene','')} - {scene.get('langkah','')}]\nVIDEO PROMPT: {p}\n\n"
        kirim_kode(chat_id, "🤖 <b>PROMPT MASTER CHATGPT (BAGIAN 1/2)</b>\n<i>Copy ke ChatGPT:</i>", isi_gpt_1)

        isi_gpt_2 = ""
        for scene in alur[titik_tengah:]:
            p = scene.get('prompt_dola_ai','').replace('\n',' ')
            isi_gpt_2 += f"[SCENE {scene.get('scene','')} - {scene.get('langkah','')}]\nVIDEO PROMPT: {p}\n\n"
        isi_gpt_2 += f"\nBerikan hasilnya dalam {total_scene} blok Prompt Video terpisah siap di-copy ke {ai_tool}. JANGAN tambahkan Overlay Text atau Voice Over ke dalam prompt video — keduanya ditambahkan terpisah saat editing."
        kirim_kode(chat_id, "🤖 <b>PROMPT MASTER CHATGPT (BAGIAN 2/2)</b>\n<i>Copy ke ChatGPT di chat yang SAMA:</i>", isi_gpt_2)

        # --- STEP SETELAH KONTEN ---
        # Ambil sinopsis/konsep untuk konteks regenerate
        sinopsis_konteks = hasil_ai.get('sinopsis_cerita', '') if tema == "animation" else hasil_ai.get('deskripsi_konsep_video', '')

        if tema == "toy":
            # Toy: tidak ada VO, langsung ke regenerate
            bot.send_message(chat_id,
                "✅ <b>Konten selesai!</b> 🚛\n"
                "Ingat: video ini tanpa VO, tambahkan backsound musik sendiri saat editing.\n\n"
                "🔄 Ada scene yang ingin di-regenerate?",
                parse_mode="HTML", reply_markup=keyboard_regenerate(alur))
            user_state[chat_id] = {
                "step": "regenerate", "alur": alur, "aksen": aksen, "lambat": lambat, "tema": tema,
                "judul_karya": judul_karya_raw, "sinopsis": sinopsis_konteks, "bahasa_vo": bahasa_vo
            }
        else:
            # DIY & Animation: tawarin VO audio
            aksen_label_vo = AKSEN_OPTIONS.get(aksen, AKSEN_OPTIONS["us"])["label"]
            bot.send_message(chat_id,
                f"🎙️ <b>Mau generate audio Voice Over?</b>\n"
                f"Aksen: <b>{aksen_label_vo}</b> | Kecepatan: <b>{'Lambat' if lambat else 'Normal'}</b>\n"
                f"Bahasa VO: <b>{'🇮🇩 Indonesia' if bahasa_vo == 'id' else '🇺🇸 English'}</b>\n"
                f"Ganti aksen/bahasa di menu <b>⚙️ Preferensi</b>.",
                parse_mode="HTML", reply_markup=keyboard_konfirmasi_vo())
            user_state[chat_id] = {
                "step": "konfirmasi_vo", "alur": alur, "aksen": aksen, "lambat": lambat, "tema": tema,
                "bahasa_vo": bahasa_vo, "judul_karya": judul_karya_raw, "sinopsis": sinopsis_konteks
            }

        print(f"✅ Episode {nomor_ep} ({tema_label} | {total_scene} scene) selesai.")

    except json.JSONDecodeError as e:
        bot.send_message(chat_id, f"❌ Gagal parse JSON dari AI: {e}\nCoba lagi.", parse_mode="HTML", reply_markup=keyboard_menu_utama(tema))
    except Exception as e:
        bot.send_message(chat_id, f"❌ Error: {e}", reply_markup=keyboard_menu_utama(tema))

# ==========================================
# 8. SAMBUTAN
# ==========================================
PESAN_SAMBUTAN = """🎬 <b>Selamat datang di Bot Ide Konten Multi-Tema v10!</b>

Bot ini generate ide konten YouTube Shorts lengkap untuk 3 channel berbeda.

━━━━━━━━━━━━━━━━━
🎯 <b>3 TEMA CHANNEL:</b>
🏗️ <b>DIY Miniature</b> — tutorial miniatur stik es krim
🚛 <b>AI Toy Construction</b> — mainan konstruksi di pasir (tanpa VO)
🎭 <b>AI Animation</b> — cerita claymation lucu & unik

━━━━━━━━━━━━━━━━━
⚙️ <b>PENGATURAN (di Preferensi):</b>
🎙️ Aksen VO — pilih suara & bahasa VO (🇺🇸🇬🇧🇦🇺🇮🇳🇮🇩)
🎬 Prompt Video — Bahasa Inggris atau Indonesia
📺 Text Overlay — Bahasa Inggris atau Indonesia
🎞️ Jumlah Scene — pilih angka atau biarkan AI memilih yang optimal
🌍 Target Negara — sesuaikan waktu pengingat dengan negara penonton

⏰ <b>PENGINGAT UPLOAD OTOMATIS:</b>
Dikirim 30 menit sebelum prime time lokal negara target.
🇺🇸 USA (3 Slot): 19:30 · 23:30 · 04:30 WIB | Negara lain: 2x sehari.
Ganti target negara di ⚙️ Preferensi → 🌍 Target Negara.
Tersedia: 🇺🇸 USA East/West · 🇬🇧 UK · 🇦🇺 Australia · 🇸🇬 Singapore · 🇯🇵 Japan · 🇮🇳 India · 🇮🇩 Indonesia

📂 <b>PLAYLIST:</b> Setiap episode sudah otomatis diarahkan ke playlist yang sesuai.
🎙️ <b>BAHASA VO:</b> Pilih Indonesia atau English saat generate (DIY & Animation).

Pilih menu di bawah untuk mulai! 👇"""

# ==========================================
# 9. COMMAND HANDLERS
# ==========================================
@bot.message_handler(commands=['start'])
def cmd_start(message):
    if not cek_owner(message): return
    global ACTIVE_CHAT_ID
    ACTIVE_CHAT_ID = message.chat.id
    simpan_chat_id(ACTIVE_CHAT_ID)
    pref = ambil_preferensi(message.chat.id)
    bot.send_message(message.chat.id, PESAN_SAMBUTAN, parse_mode="HTML",
                     reply_markup=keyboard_menu_utama(pref.get("tema","diy")))

@bot.message_handler(commands=['menu'])
def cmd_menu(message):
    if not cek_owner(message): return
    pref = ambil_preferensi(message.chat.id)
    bot.send_message(message.chat.id, "📌 <b>Menu Utama</b>", parse_mode="HTML",
                     reply_markup=keyboard_menu_utama(pref.get("tema","diy")))

@bot.message_handler(commands=['bantuan'])
def cmd_bantuan(message):
    if not cek_owner(message): return
    pref = ambil_preferensi(message.chat.id)
    bot.send_message(message.chat.id, PESAN_SAMBUTAN, parse_mode="HTML",
                     reply_markup=keyboard_menu_utama(pref.get("tema","diy")))

@bot.message_handler(commands=['riwayat'])
def cmd_riwayat(message):
    if not cek_owner(message): return
    _tampilkan_riwayat(message.chat.id)

@bot.message_handler(commands=['hapus_riwayat'])
def cmd_hapus_riwayat(message):
    if not cek_owner(message): return
    _konfirmasi_hapus_riwayat(message.chat.id)

@bot.message_handler(commands=['preferensi'])
def cmd_preferensi(message):
    if not cek_owner(message): return
    _tampilkan_preferensi(message.chat.id)

@bot.message_handler(commands=['batal'])
def cmd_batal(message):
    if not cek_owner(message): return
    chat_id = message.chat.id
    state = user_state.pop(chat_id, None)
    if state:
        bot.send_message(chat_id,
            "❌ <b>Dibatalkan.</b>\nKamu kembali ke menu YouTube Monitor.",
            parse_mode="HTML", reply_markup=keyboard_youtube_monitor())
    else:
        bot.send_message(chat_id,
            "ℹ️ Tidak ada aksi yang sedang berjalan.",
            parse_mode="HTML")

# ==========================================
# 10. FUNGSI AKSI TERPUSAT
# ==========================================
def _tampilkan_riwayat(chat_id):
    pref = ambil_preferensi(chat_id)
    tema = pref.get("tema","diy")
    tema_label = TEMA_OPTIONS.get(tema, TEMA_OPTIONS["diy"])["label"]
    riwayat = ambil_memori(tema)
    if not riwayat:
        bot.send_message(chat_id,
            f"📭 Belum ada riwayat untuk tema <b>{tema_label}</b>.",
            parse_mode="HTML", reply_markup=keyboard_menu_utama(tema))
        return
    pesan = f"📚 <b>RIWAYAT — {tema_label} ({len(riwayat)} episode):</b>\n\n"
    for item in riwayat:
        pesan += f"✅ {esc(item)}\n"
    pesan += "\n<i>Bot tidak akan mengulang episode di atas.</i>"
    kirim_html(chat_id, pesan)
    bot.send_message(chat_id, "📌 <b>Menu Utama</b>", parse_mode="HTML",
                     reply_markup=keyboard_menu_utama(tema))

def _konfirmasi_hapus_riwayat(chat_id):
    pref = ambil_preferensi(chat_id)
    tema = pref.get("tema","diy")
    tema_label = TEMA_OPTIONS.get(tema, TEMA_OPTIONS["diy"])["label"]
    jumlah = len(ambil_memori(tema))
    if jumlah == 0:
        bot.send_message(chat_id, f"📭 Riwayat tema <b>{tema_label}</b> sudah kosong.",
                         parse_mode="HTML", reply_markup=keyboard_menu_utama(tema)); return
    bot.send_message(chat_id,
        f"⚠️ <b>Hapus {jumlah} riwayat tema {tema_label}?</b>\nTidak bisa dibatalkan.",
        parse_mode="HTML", reply_markup=keyboard_konfirmasi_hapus())

def _tampilkan_preferensi(chat_id):
    pref = ambil_preferensi(chat_id)
    aksen_label  = AKSEN_OPTIONS.get(pref["aksen"], AKSEN_OPTIONS["us"])["label"]
    speed_label  = "🐢 Lambat" if pref["kecepatan"] == "slow" else "⚡ Normal"
    tema_label   = TEMA_OPTIONS.get(pref.get("tema","diy"), TEMA_OPTIONS["diy"])["label"]
    scene_label  = "🎲 AI Pilihkan" if pref["jumlah_scene"] == 0 else f"{pref['jumlah_scene']} scene"
    bpv_label    = "🇮🇩 Indonesia (dikunci)"  # prompt video selalu Indonesia
    bo_label     = "🇮🇩 Indonesia" if pref.get("bahasa_overlay","en") == "id" else "🇺🇸 English"
    bvo_label    = "🇮🇩 Indonesia" if pref.get("bahasa_vo","en") == "id" else "🇺🇸 English"
    negara_key   = pref.get("target_negara","id")
    pt           = PRIME_TIMES.get(negara_key, PRIME_TIMES["id"])
    negara_label = pt["label"]
    # Bangun teks pengingat — support 2 slot (standar) atau 3 slot (us_west)
    if pt.get("waktu_tengah"):
        ket_pengingat = (
            f"⏰ Slot 1: <b>{pt['waktu_pagi']} WIB</b> → upload {pt['ket_pagi']}\n"
            f"⏰ Slot 2: <b>{pt['waktu_tengah']} WIB</b> → upload {pt['ket_tengah']}\n"
            f"⏰ Slot 3: <b>{pt['waktu_malam']} WIB</b> → upload {pt['ket_malam']}"
        )
    else:
        ket_pengingat = (
            f"⏰ Pengingat pukul <b>{pt['waktu_pagi']} WIB</b> (30 mnt sebelum {pt['ket_pagi']})\n"
            f"    dan pukul <b>{pt['waktu_malam']} WIB</b> (30 mnt sebelum {pt['ket_malam']})"
        )
    bot.send_message(chat_id,
        f"⚙️ <b>PREFERENSI SAAT INI:</b>\n\n"
        f"🔀 Tema: <b>{tema_label}</b>\n"
        f"🎙️ Aksen VO: <b>{aksen_label}</b>\n"
        f"🗣️ Bahasa VO: <b>{bvo_label}</b>\n"
        f"⚡ Kecepatan: <b>{speed_label}</b>\n"
        f"🎞️ Scene Default: <b>{scene_label}</b>\n"
        f"🎬 Prompt Video: <b>{bpv_label}</b>\n"
        f"📺 Text Overlay: <b>{bo_label}</b>\n"
        f"🌍 Target Negara: <b>{negara_label}</b>\n"
        f"{ket_pengingat}\n\n"
        f"<i>Bahasa VO animasi dipilih saat generate.</i>\n"
        f"Tap tombol untuk ubah:",
        parse_mode="HTML", reply_markup=keyboard_preferensi_menu(pref))

def _mulai_generate(chat_id, topik, jumlah_scene, tema):
    """Titik masuk generate — untuk animasi tanya bahasa VO dulu."""
    # Guard: tolak kalau masih memproses
    if chat_id in processing_users:
        bot.send_message(chat_id, "⏳ Bot masih memproses permintaan sebelumnya. Tunggu hingga selesai ya!")
        return
    if tema == "animation":
        pref = ambil_preferensi(chat_id)
        bvo_saved = pref.get("bahasa_vo", "en")
        bvo_label = "🇮🇩 Indonesia" if bvo_saved == "id" else "🇺🇸 English"
        user_state[chat_id] = {"step": "pilih_bvo", "data": {"topik": topik, "jumlah_scene": jumlah_scene}, "tema": tema}
        bot.send_message(chat_id,
            f"🎭 <b>AI Animation — Pilih Bahasa Voice Over</b>\n"
            f"Terakhir digunakan: <b>{bvo_label}</b>\n\n"
            f"VO audio akan di-generate sesuai pilihan ini.",
            parse_mode="HTML", reply_markup=keyboard_bahasa_vo_animasi())
    else:
        # DIY & Toy: langsung generate di thread terpisah
        pref = ambil_preferensi(chat_id)
        bahasa_vo = pref.get("bahasa_vo", "en")
        bot.send_message(chat_id, f"✅ Jumlah scene: <b>{'AI Pilihkan' if not jumlah_scene else str(jumlah_scene)+' scene'}</b>\n⏳ Memulai generate...", parse_mode="HTML")
        threading.Thread(target=proses_dan_kirim, args=(chat_id, topik, jumlah_scene, tema, bahasa_vo), daemon=True).start()

# ==========================================
# 11. HANDLER "konten" (teks)
# ==========================================
@bot.message_handler(func=lambda m: m.text and m.text.lower() == "konten")
def setor_ide(message):
    if not cek_owner(message): return
    global ACTIVE_CHAT_ID
    ACTIVE_CHAT_ID = message.chat.id
    simpan_chat_id(ACTIVE_CHAT_ID)
    pref = ambil_preferensi(message.chat.id)
    tema = pref.get("tema","diy")
    tema_label = TEMA_OPTIONS.get(tema, TEMA_OPTIONS["diy"])["label"]
    user_state[message.chat.id] = {"step":"pilih_topik","data":{},"tema":tema}
    bot.send_message(message.chat.id,
        f"🎬 <b>Buat Konten Baru!</b>\nTema: <b>{tema_label}</b>\nMau topiknya random atau pilih sendiri?",
        parse_mode="HTML", reply_markup=keyboard_mulai())

# ==========================================
# 12. CALLBACK HANDLER
# ==========================================
@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    if call.from_user.id != OWNER_ID:
        bot.answer_callback_query(call.id, "🔒 Bot ini bersifat private.")
        return
    # ⚠️ WAJIB answer dulu sebelum apapun — kalau terlambat, Telegram timeout & tombol freeze
    try: bot.answer_callback_query(call.id)
    except: pass

    chat_id = call.message.chat.id
    data    = call.data

    def tutup():
        try: bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=None)
        except: pass
    tutup()

    try:
        state   = user_state.get(chat_id, {})
        pref    = ambil_preferensi(chat_id)
        tema_aktif = pref.get("tema","diy")
    except Exception as e:
        bot.send_message(chat_id, f"⚠️ Error memuat preferensi: {e}\nCoba lagi atau ketik /start")
        return

    # ── MENU UTAMA ──
    if data == "menu_utama":
        bot.send_message(chat_id, "📌 <b>Menu Utama</b>", parse_mode="HTML",
                         reply_markup=keyboard_menu_utama(tema_aktif))

    elif data == "menu_konten":
        global ACTIVE_CHAT_ID
        ACTIVE_CHAT_ID = chat_id; simpan_chat_id(chat_id)
        tema_label = TEMA_OPTIONS.get(tema_aktif, TEMA_OPTIONS["diy"])["label"]
        user_state[chat_id] = {"step":"pilih_topik","data":{},"tema":tema_aktif}
        bot.send_message(chat_id,
            f"🎬 <b>Buat Konten Baru!</b>\nTema: <b>{tema_label}</b>\nMau topiknya random atau pilih sendiri?",
            parse_mode="HTML", reply_markup=keyboard_mulai())

    elif data == "menu_ganti_tema":
        tema_label = TEMA_OPTIONS.get(tema_aktif, TEMA_OPTIONS["diy"])["label"]
        bot.send_message(chat_id,
            f"🔀 <b>Ganti Tema Channel</b>\nAktif: <b>{tema_label}</b>\nPilih tema baru:",
            parse_mode="HTML", reply_markup=keyboard_pilih_tema())

    elif data.startswith("tema_"):
        tema_baru = data.split("_", 1)[1]
        if tema_baru in TEMA_OPTIONS:
            simpan_preferensi(chat_id, tema=tema_baru)
            bot.send_message(chat_id,
                f"✅ Tema: <b>{TEMA_OPTIONS[tema_baru]['label']}</b>",
                parse_mode="HTML", reply_markup=keyboard_menu_utama(tema_baru))

    elif data == "menu_preferensi":
        _tampilkan_preferensi(chat_id)

    elif data == "menu_riwayat":
        _tampilkan_riwayat(chat_id)

    elif data == "menu_hapus_riwayat":
        _konfirmasi_hapus_riwayat(chat_id)

    elif data == "menu_bantuan":
        bot.send_message(chat_id, PESAN_SAMBUTAN, parse_mode="HTML",
                         reply_markup=keyboard_menu_utama(tema_aktif))

    # ── KONFIRMASI HAPUS ──
    elif data == "konfirmasi_hapus_ya":
        tema = pref.get("tema","diy"); jumlah = len(ambil_memori(tema))
        hapus_semua_riwayat(tema)
        bot.send_message(chat_id,
            f"🗑️ <b>{jumlah} riwayat {TEMA_OPTIONS.get(tema,TEMA_OPTIONS['diy'])['label']} dihapus!</b>",
            parse_mode="HTML", reply_markup=keyboard_menu_utama(tema))

    elif data == "konfirmasi_hapus_tidak":
        bot.send_message(chat_id, "✅ Riwayat tetap aman.", reply_markup=keyboard_menu_utama(tema_aktif))

    # ── PILIH TOPIK ──
    elif data == "topik_random":
        tema = state.get("tema", tema_aktif)
        user_state[chat_id] = {"step":"pilih_scene","data":{"topik":None},"tema":tema}
        bot.send_message(chat_id,
            f"✅ Topik: <b>Random</b>\n\n🎞️ Berapa jumlah scene?\n<i>(Default: {pref['jumlah_scene'] if pref['jumlah_scene'] else 'AI Pilihkan'} scene)</i>",
            parse_mode="HTML", reply_markup=keyboard_jumlah_scene())

    elif data == "topik_manual":
        tema = state.get("tema", tema_aktif)
        user_state[chat_id] = {"step":"tunggu_topik","data":{},"tema":tema}
        if tema == "toy": contoh = "Membangun jembatan pasir, tambang batu bara, proyek tol"
        elif tema == "animation": contoh = "Anak yang selalu diremehkan, robot yang ingin berteman, kucing penakut jadi pahlawan"
        else: contoh = "Menara Eiffel, rumah hobbit, kapal bajak laut"
        bot.send_message(chat_id,
            f"✏️ <b>Ketik topik untuk {TEMA_OPTIONS.get(tema,TEMA_OPTIONS['diy'])['label']}:</b>\n<i>Contoh: {contoh}</i>",
            parse_mode="HTML")

    # ── PILIH JUMLAH SCENE ──
    elif data.startswith("scene_") and not data.startswith("scene_default_"):
        jumlah = None if data == "scene_auto" else int(data.split("_")[1])
        if jumlah is not None: simpan_preferensi(chat_id, jumlah_scene=jumlah)
        topik = state.get("data",{}).get("topik", None)
        tema  = state.get("tema", tema_aktif)
        _mulai_generate(chat_id, topik, jumlah, tema)

    # ── PILIH BAHASA VO ANIMASI ──
    elif data.startswith("bvo_"):
        bahasa_vo = data.split("_")[1]
        simpan_preferensi(chat_id, bahasa_vo=bahasa_vo)
        st = state.get("data", {})
        topik = st.get("topik", None)
        jumlah = st.get("jumlah_scene", None)
        tema = state.get("tema", "animation")
        bvo_label = "🇮🇩 Indonesia" if bahasa_vo == "id" else "🇺🇸 English"
        bot.send_message(chat_id, f"✅ Bahasa VO: <b>{bvo_label}</b>\n⏳ Memulai generate...", parse_mode="HTML")
        threading.Thread(target=proses_dan_kirim, args=(chat_id, topik, jumlah, tema, bahasa_vo), daemon=True).start()

    # ── KONFIRMASI VO AUDIO ──
    elif data == "vo_generate":
        alur   = state.get("alur", [])
        aksen  = state.get("aksen", "us")
        lambat = state.get("lambat", False)
        bahasa_vo = state.get("bahasa_vo", "en")
        label_a = AKSEN_OPTIONS.get(aksen, AKSEN_OPTIONS["us"])["label"]
        bot.send_message(chat_id,
            f"🎙️ <b>Generating VO...</b> Aksen: <b>{label_a}</b>", parse_mode="HTML")
        for scene in alur:
            generate_vo_audio(chat_id, scene.get('scene',''), scene.get('langkah',''),
                              scene.get('naskah_vo',''), aksen, lambat)
        bot.send_message(chat_id, "✅ <b>Semua VO selesai!</b> 🎬\n\n🔄 Ada scene yang ingin di-regenerate?",
            parse_mode="HTML", reply_markup=keyboard_regenerate(alur))
        user_state[chat_id]["step"] = "regenerate"

    elif data == "vo_skip":
        alur = state.get("alur", [])
        bot.send_message(chat_id, "⏭️ Audio dilewati.\n\n🔄 Ada scene yang ingin di-regenerate?",
            parse_mode="HTML", reply_markup=keyboard_regenerate(alur))
        user_state[chat_id]["step"] = "regenerate"

    # ── REGENERATE ──
    elif data.startswith("regen_") and data != "regen_selesai":
        no_scene = data.split("_")[1]
        alur = state.get("alur", [])
        aksen = state.get("aksen", "us")
        lambat = state.get("lambat", False)
        tema_regen = state.get("tema", "diy")
        judul_karya_regen = state.get("judul_karya", "")
        sinopsis_regen = state.get("sinopsis", "")
        bahasa_vo_regen = state.get("bahasa_vo", pref.get("bahasa_vo", "en"))
        bahasa_overlay_regen = pref.get("bahasa_overlay", "en")
        bahasa_prompt_video_regen = pref.get("bahasa_prompt_video", "en")

        bot.send_message(chat_id, f"🔄 <b>Regenerate Scene {no_scene}...</b>\n<i>Menghubungi AI...</i>", parse_mode="HTML")

        def _regen(cid=chat_id, ns=no_scene, a=alur, ak=aksen, lb=lambat, tr=tema_regen,
                   jk=judul_karya_regen, si=sinopsis_regen, bv=bahasa_vo_regen,
                   bo=bahasa_overlay_regen, bpv=bahasa_prompt_video_regen):
            try:
                prompt_regen = buat_prompt_regen_scene(tr, jk, si, a, ns, bv, bo, bpv)
                response = dapatkan_ide_dengan_rotasi(prompt_regen)
                scene_baru = parse_json_dengan_retry(response.text, prompt_regen, chat_id)

                # Update alur di state
                for i, s in enumerate(a):
                    if str(s.get('scene','')) == str(ns):
                        a[i] = scene_baru
                        break
                user_state[cid]["alur"] = a

                langkah_baru = scene_baru.get('langkah', f'Scene {ns}')
                ref_baru = scene_baru.get('prompt_referensi_scene', '')

                # Kirim referensi scene baru
                kirim_kode(cid, f"✅ <b>SCENE {ns} — {esc(langkah_baru)}</b>\n<i>Referensi gambar baru:</i>", ref_baru)

                # Kirim VO & overlay baru
                overlay_baru = esc(scene_baru.get('teks_overlay', ''))
                if tr == "toy":
                    aksi_baru = esc(scene_baru.get('keterangan_aksi', ''))
                    pesan_update = f"🚛 Aksi: {aksi_baru}\n📺 Overlay: <code>{overlay_baru}</code>"
                    bot.send_message(cid, pesan_update, parse_mode="HTML")
                else:
                    vo_baru = scene_baru.get('naskah_vo', '')
                    pesan_update = f"🎙️ VO: <i>{esc(vo_baru)}</i>\n📺 Overlay: <code>{overlay_baru}</code>"
                    bot.send_message(cid, pesan_update, parse_mode="HTML")
                    generate_vo_audio(cid, scene_baru.get('scene', ns), langkah_baru, vo_baru, ak, lb)

                bot.send_message(cid, "🔄 Scene lain yang ingin di-regenerate?",
                                 parse_mode="HTML", reply_markup=keyboard_regenerate(a))
            except Exception as e:
                bot.send_message(cid, f"❌ Gagal regenerate scene {ns}: {e}",
                                 reply_markup=keyboard_regenerate(a))

        threading.Thread(target=_regen, daemon=True).start()

    elif data == "regen_selesai":
        bot.send_message(chat_id, "🎉 <b>Episode selesai!</b>",
            parse_mode="HTML", reply_markup=keyboard_menu_utama(tema_aktif))
        user_state.pop(chat_id, None)

    # ── PREFERENSI ──
    elif data == "pref_aksen":
        bot.send_message(chat_id, "🎙️ <b>Pilih aksen Voice Over:</b>\n<i>🇮🇩 Indonesia = VO dalam Bahasa Indonesia</i>",
            parse_mode="HTML", reply_markup=keyboard_aksen())

    elif data == "pref_speed":
        bot.send_message(chat_id, "⚡ <b>Pilih kecepatan Voice Over:</b>",
            parse_mode="HTML", reply_markup=keyboard_kecepatan())

    elif data == "pref_scene":
        bot.send_message(chat_id, "🎞️ <b>Pilih jumlah scene default:</b>",
            parse_mode="HTML", reply_markup=keyboard_jumlah_scene_default())

    elif data == "pref_bpv":
        bot.send_message(chat_id,
            "🎬 <b>Pilih bahasa Prompt Video:</b>\n<i>Ini bahasa yang digunakan untuk instruksi ke ChatGPT & prompt_dola_ai.</i>",
            parse_mode="HTML", reply_markup=keyboard_bahasa_prompt_video())

    elif data == "pref_bo":
        bot.send_message(chat_id,
            "📺 <b>Pilih bahasa Text Overlay:</b>\n<i>Overlay ditampilkan di layar video saat editing.</i>",
            parse_mode="HTML", reply_markup=keyboard_bahasa_overlay())

    elif data.startswith("aksen_"):
        key = data.split("_")[1]
        simpan_preferensi(chat_id, aksen=key)
        label = AKSEN_OPTIONS.get(key, AKSEN_OPTIONS["us"])["label"]
        bot.send_message(chat_id, f"✅ Aksen VO: <b>{label}</b>", parse_mode="HTML")
        _tampilkan_preferensi(chat_id)

    elif data.startswith("speed_"):
        speed = data.split("_")[1]
        simpan_preferensi(chat_id, kecepatan=speed)
        bot.send_message(chat_id, f"✅ Kecepatan: <b>{'Lambat 🐢' if speed=='slow' else 'Normal ⚡'}</b>", parse_mode="HTML")
        _tampilkan_preferensi(chat_id)

    elif data.startswith("scene_default_"):
        val = data.split("_")[2]
        jumlah = 0 if val == "auto" else int(val)
        simpan_preferensi(chat_id, jumlah_scene=jumlah)
        label = "🎲 AI Pilihkan" if jumlah == 0 else f"{jumlah} scene"
        bot.send_message(chat_id, f"✅ Scene default: <b>{label}</b>", parse_mode="HTML")
        _tampilkan_preferensi(chat_id)

    elif data.startswith("bpv_"):
        val = data.split("_")[1]
        simpan_preferensi(chat_id, bahasa_prompt_video=val)
        label = "🇮🇩 Indonesia" if val == "id" else "🇺🇸 English"
        bot.send_message(chat_id, f"✅ Prompt Video: <b>{label}</b>", parse_mode="HTML")
        _tampilkan_preferensi(chat_id)

    elif data.startswith("bo_"):
        val = data.split("_")[1]
        simpan_preferensi(chat_id, bahasa_overlay=val)
        label = "🇮🇩 Indonesia" if val == "id" else "🇺🇸 English"
        bot.send_message(chat_id, f"✅ Text Overlay: <b>{label}</b>", parse_mode="HTML")
        _tampilkan_preferensi(chat_id)

    elif data == "info_bpv_fixed":
        # Prompt video sudah dikunci ke Indonesia — tombol ini hanya info
        bot.send_message(chat_id,
            "🎬 <b>Prompt Video: Bahasa Indonesia (Dikunci)</b>\n\n"
            "Prompt video untuk Dola AI selalu digenerate dalam <b>Bahasa Indonesia</b>.\n"
            "Ini tidak bisa diubah karena Dola AI bekerja optimal dengan Bahasa Indonesia.\n\n"
            "📸 Prompt gambar referensi (DALL-E/ChatGPT) tetap dalam <b>Bahasa Inggris</b>.",
            parse_mode="HTML", reply_markup=keyboard_preferensi_menu(pref))

    elif data == "pref_bvo":
        pref_now = ambil_preferensi(chat_id)
        bvo_now = "🇮🇩 Indonesia" if pref_now.get("bahasa_vo","en") == "id" else "🇺🇸 English"
        bot.send_message(chat_id,
            f"🗣️ <b>Pilih Bahasa Voice Over:</b>\n"
            f"Aktif: <b>{bvo_now}</b>\n\n"
            f"<i>Berlaku untuk tema DIY dan Animation. Pastikan aksen VO sesuai bahasa yang dipilih.</i>",
            parse_mode="HTML", reply_markup=keyboard_bahasa_vo_preferensi())

    elif data.startswith("bvopref_"):
        val = data.split("_")[1]
        simpan_preferensi(chat_id, bahasa_vo=val)
        label = "🇮🇩 Indonesia" if val == "id" else "🇺🇸 English"
        bot.send_message(chat_id, f"✅ Bahasa VO: <b>{label}</b>", parse_mode="HTML")
        _tampilkan_preferensi(chat_id)

    elif data == "pref_negara":
        pref_now = ambil_preferensi(chat_id)
        negara_now = pref_now.get("target_negara", "us_east")
        pt_now = PRIME_TIMES.get(negara_now, PRIME_TIMES["us_east"])
        bot.send_message(chat_id,
            f"🌍 <b>Pilih Target Negara Penonton:</b>\n"
            f"Aktif: <b>{pt_now['label']}</b>\n"
            f"⏰ Pengingat: <b>{pt_now['waktu_pagi']} WIB</b> (pagi)"
            + (f" · <b>{pt_now['waktu_tengah']} WIB</b> (tengah)" if pt_now.get('waktu_tengah') else "")
            + f" · <b>{pt_now['waktu_malam']} WIB</b> (malam)\n\n"
            f"<i>Waktu pengingat dikirim 30 menit sebelum prime time lokal negara yang dipilih.</i>",
            parse_mode="HTML", reply_markup=keyboard_target_negara())

    elif data.startswith("negara_"):
        # Ambil key negara: "negara_us_east" → "us_east", "negara_uk" → "uk"
        negara_key = data[len("negara_"):]
        if negara_key in PRIME_TIMES:
            simpan_preferensi(chat_id, target_negara=negara_key)
            pt_new = PRIME_TIMES[negara_key]
            slot_tengah_msg = (
                f"\n⏰ Pengingat tengah: <b>{pt_new['waktu_tengah']} WIB</b> ({pt_new.get('ket_tengah','')})"
                if pt_new.get('waktu_tengah') else ""
            )
            bot.send_message(chat_id,
                f"✅ Target negara: <b>{pt_new['label']}</b>\n"
                f"⏰ Pengingat pagi: <b>{pt_new['waktu_pagi']} WIB</b> ({pt_new['ket_pagi']})"
                + slot_tengah_msg +
                f"\n⏰ Pengingat malam: <b>{pt_new['waktu_malam']} WIB</b> ({pt_new['ket_malam']})",
                parse_mode="HTML")
            _tampilkan_preferensi(chat_id)

    # --- YOUTUBE MONITOR ---
    elif data == "menu_youtube":
        bot.send_message(chat_id,
            "📺 <b>YOUTUBE MONITOR</b>\n\n"
            "Bot otomatis scan channel & kirim notif saat video melewati milestone views/likes.\n\n"
            "Pilih aksi:",
            parse_mode="HTML", reply_markup=keyboard_youtube_monitor())

    elif data == "yt_scan":
        bot.send_message(chat_id, "🔍 Scanning channel untuk video baru...")
        def _do_scan():
            try:
                token = _yt_access_token()
                if not token:
                    bot.send_message(chat_id,
                        "❌ Gagal dapat access token YouTube.\n"
                        "<i>Pastikan env var YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, "
                        "dan YOUTUBE_REFRESH_TOKEN sudah di-set di Render.</i>",
                        parse_mode="HTML")
                    return
                baru = auto_scan_channel(token, notify_chat_id=chat_id)
                if baru == 0:
                    bot.send_message(chat_id,
                        "✅ Scan selesai — tidak ada video baru.\n<i>Semua video sudah terdaftar di monitor.</i>",
                        parse_mode="HTML", reply_markup=keyboard_youtube_monitor())
                else:
                    bot.send_message(chat_id,
                        f"✅ Scan selesai — <b>{baru} video baru</b> ditambahkan ke monitor.",
                        parse_mode="HTML", reply_markup=keyboard_youtube_monitor())
            except Exception as e:
                print(f"[YT SCAN THREAD ERROR] {e}")
                bot.send_message(chat_id,
                    f"❌ Error saat scanning: <code>{esc(str(e))}</code>\n\n"
                    f"<i>Cek log Render untuk detail.</i>",
                    parse_mode="HTML", reply_markup=keyboard_youtube_monitor())
        threading.Thread(target=_do_scan, daemon=True).start()

    elif data == "yt_cek_views":
        bot.send_message(chat_id, "⏳ Mengambil data views dari YouTube...")
        threading.Thread(target=cek_views_manual, args=(chat_id,), daemon=True).start()

    elif data == "yt_daftar":
        daftar_video_yt(chat_id)

    elif data == "yt_analitik":
        bot.send_message(chat_id, "⏳ Mengambil data pertumbuhan...")
        threading.Thread(target=tampilkan_analitik_pertumbuhan, args=(chat_id,), daemon=True).start()

    elif data == "yt_ide_tren":
        threading.Thread(target=generate_ide_dari_tren, args=(chat_id,), daemon=True).start()

    elif data == "yt_export":
        bot.send_message(chat_id, "⏳ Menyiapkan laporan CSV...")
        threading.Thread(target=export_laporan_csv, args=(chat_id,), daemon=True).start()

    elif data == "yt_set_viral":
        threshold = _ambil_viral_threshold()
        user_state[chat_id] = {"step": "tunggu_viral_threshold"}
        bot.send_message(chat_id,
            f"⚡ <b>Set Threshold Deteksi Viral</b>\n\n"
            f"Threshold saat ini: <b>{threshold}%</b>\n\n"
            f"Bot akan kirim notif <b>⚡ VIDEO SEDANG VIRAL</b> kalau views naik lebih dari X% dalam 1 jam.\n\n"
            f"Ketik angka persentase baru (misal: <code>30</code> artinya naik 30% per jam):\n\n"
            f"<i>Saran: 30–50% untuk video yang mulai naik, 100%+ untuk yang benar-benar viral.\n"
            f"Ketik /batal untuk membatalkan.</i>",
            parse_mode="HTML")

    elif data == "yt_hapus":
        tampilkan_daftar_hapus_video(chat_id)

    elif data.startswith("yt_konfirmasi_hapus_"):
        vid_id = data[len("yt_konfirmasi_hapus_"):]
        # Tampilkan konfirmasi hapus per video
        try:
            conn = connect_db(); cur = conn.cursor()
            cur.execute("SELECT judul, views_last FROM youtube_videos WHERE video_id=%s", (vid_id,))
            row = cur.fetchone(); cur.close(); conn.close()
            judul = row[0] if row else vid_id
            views = row[1] if row else 0
        except Exception:
            judul = vid_id; views = 0
        kb = tbtypes.InlineKeyboardMarkup()
        kb.row(
            tbtypes.InlineKeyboardButton("🗑️ Ya, Hapus",  callback_data=f"yt_lakukan_hapus_{vid_id}"),
            tbtypes.InlineKeyboardButton("❌ Batal",       callback_data="yt_hapus"),
        )
        bot.send_message(chat_id,
            f"⚠️ <b>Hapus video ini dari monitor?</b>\n\n"
            f"🎬 <b>{esc(judul)}</b>\n"
            f"👁️ {views:,} views\n"
            f"<code>{vid_id}</code>\n\n"
            f"<i>Video tidak akan lagi dipantau, tapi tidak terhapus dari YouTube.</i>",
            parse_mode="HTML", reply_markup=kb)

    elif data.startswith("yt_lakukan_hapus_"):
        vid_id = data[len("yt_lakukan_hapus_"):]
        hapus_video_yt(chat_id, vid_id)

    elif data == "yt_lihat_milestone":
        mv, ml = _ambil_milestones()
        mv_str = " · ".join(f"{m:,}" for m in mv)
        ml_str = " · ".join(f"{m:,}" for m in ml)
        bot.send_message(chat_id,
            f"🎯 <b>MILESTONE AKTIF:</b>\n\n"
            f"👁️ <b>Views:</b>\n{mv_str}\n\n"
            f"👍 <b>Likes:</b>\n{ml_str}",
            parse_mode="HTML", reply_markup=keyboard_youtube_monitor())

    elif data == "yt_set_milestone_views":
        user_state[chat_id] = {"step": "tunggu_milestone_views"}
        mv, _ = _ambil_milestones()
        mv_str = " ".join(str(m) for m in mv)
        bot.send_message(chat_id,
            f"⚙️ <b>Set Milestone Views</b>\n\n"
            f"Milestone views saat ini:\n<code>{mv_str}</code>\n\n"
            f"Ketik angka-angka milestone baru yang kamu inginkan, pisahkan dengan spasi.\n"
            f"Contoh: <code>100 500 1000 5000 10000 50000 100000</code>\n\n"
            f"<i>Ketik /batal untuk membatalkan.</i>",
            parse_mode="HTML")

    elif data == "yt_set_milestone_likes":
        user_state[chat_id] = {"step": "tunggu_milestone_likes"}
        _, ml = _ambil_milestones()
        ml_str = " ".join(str(m) for m in ml)
        bot.send_message(chat_id,
            f"⚙️ <b>Set Milestone Likes</b>\n\n"
            f"Milestone likes saat ini:\n<code>{ml_str}</code>\n\n"
            f"Ketik angka-angka milestone baru yang kamu inginkan, pisahkan dengan spasi.\n"
            f"Contoh: <code>10 50 100 500 1000 5000 10000</code>\n\n"
            f"<i>Ketik /batal untuk membatalkan.</i>",
            parse_mode="HTML")

    elif data == "yt_panduan":
        bot.send_message(chat_id,
            "📺 <b>PANDUAN YOUTUBE MONITOR</b>\n\n"
            "🔍 <b>Scan Channel Sekarang</b>\n"
            "Bot otomatis mengambil semua video terbaru dari channel YouTube kamu (tanpa input manual). "
            "Video yang ditemukan langsung masuk ke daftar monitor.\n\n"
            "📊 <b>Cek Views Semua Video</b>\n"
            "Tampilkan views & likes terkini untuk semua video yang sedang dimonitor.\n\n"
            "📋 <b>Daftar Video Monitor</b>\n"
            "Lihat semua video yang sedang dipantau beserta total views & likes-nya.\n\n"
            "🎯 <b>Milestone Notifikasi</b>\n"
            "Bot mengirim notifikasi Telegram setiap kali views atau likes sebuah video melewati angka milestone. "
            "Bot mengecek secara otomatis setiap <b>1 jam</b> sekali.\n\n"
            "⚙️ <b>Set Milestone Views / Likes</b>\n"
            "Atur sendiri angka-angka milestone sesuai target kamu. "
            "Klik tombol ⚙️ lalu ketik angkanya — bot yang simpan otomatis.\n\n"
            "➕ <b>Tambah Video Manual</b>\n"
            "Kirim link YouTube ke bot, lalu ketik /tambah_video [link] untuk menambah video ke monitor.\n\n"
            "🗑️ <b>Hapus Video dari Monitor</b>\n"
            "Klik tombol 🗑️ Hapus Video — bot tampilkan daftar video, klik video yang ingin dihapus, bot minta konfirmasi sebelum menghapus.\n\n"
            "📈 <b>Analitik Pertumbuhan</b>\n"
            "Lihat berapa views yang naik dalam 1 jam, 24 jam, dan 7 hari untuk setiap video.\n\n"
            "💡 <b>Ide Konten dari Tren</b>\n"
            "Bot cari video mana yang tumbuh paling cepat minggu ini, lalu generate 5 ide konten serupa via AI.\n\n"
            "⚡ <b>Deteksi Viral</b>\n"
            "Bot otomatis notif kalau views naik melebihi threshold % dalam 1 jam. Set threshold via tombol ⚡.\n\n"
            "📤 <b>Export CSV</b>\n"
            "Download laporan lengkap views, likes, dan histori pertumbuhan semua video dalam format CSV/Excel.\n\n"
            "📅 <b>Ringkasan Mingguan</b>\n"
            "Klik 📅 Pengaturan Ringkasan Mingguan untuk atur hari, jam, dan aktif/nonaktif. "
            "Bot kirim rangkuman views & likes semua video secara otomatis sesuai jadwal.\n\n"
            "💡 <b>Tips:</b> Dengan 1 refresh token kamu bisa monitor semua video dari channel yang sama. "
            "Bot scan otomatis tiap 1 jam, jadi video baru langsung terdeteksi.",
            parse_mode="HTML", reply_markup=keyboard_youtube_monitor())

    elif data == "yt_setting_weekly":
        hari_cfg, jam_cfg, aktif = _ambil_weekly_config()
        status_label = "✅ Aktif" if aktif else "⛔ Nonaktif"
        kb = tbtypes.InlineKeyboardMarkup()
        # Baris pilih hari
        row1 = [tbtypes.InlineKeyboardButton(
            ("▶️ " if i == hari_cfg else "") + NAMA_HARI[i],
            callback_data=f"yt_weekly_hari_{i}"
        ) for i in range(4)]
        row2 = [tbtypes.InlineKeyboardButton(
            ("▶️ " if i == hari_cfg else "") + NAMA_HARI[i]
            , callback_data=f"yt_weekly_hari_{i}"
        ) for i in range(4, 7)]
        kb.row(*row1)
        kb.row(*row2)
        kb.row(tbtypes.InlineKeyboardButton(f"🕐 Ubah Jam (sekarang: {jam_cfg} WIB)", callback_data="yt_weekly_ubah_jam"))
        kb.row(tbtypes.InlineKeyboardButton(
            f"{'⛔ Nonaktifkan' if aktif else '✅ Aktifkan'} Ringkasan Mingguan",
            callback_data="yt_weekly_toggle"
        ))
        kb.row(tbtypes.InlineKeyboardButton("📤 Kirim Ringkasan Sekarang", callback_data="yt_weekly_kirim_sekarang"))
        kb.row(tbtypes.InlineKeyboardButton("🔙 Kembali", callback_data="menu_youtube"))
        bot.send_message(chat_id,
            f"📅 <b>PENGATURAN RINGKASAN MINGGUAN</b>\n\n"
            f"Status: <b>{status_label}</b>\n"
            f"Jadwal: <b>{NAMA_HARI[hari_cfg]}, {jam_cfg} WIB</b>\n\n"
            f"Pilih hari pengiriman (yang dipilih ditandai ▶️), "
            f"lalu ubah jam atau toggle aktif/nonaktif:",
            parse_mode="HTML", reply_markup=kb)

    elif data.startswith("yt_weekly_hari_"):
        hari_baru = int(data.split("_")[-1])
        _simpan_weekly_config(hari=hari_baru)
        _, jam_cfg, aktif = _ambil_weekly_config()
        status_label = "✅ Aktif" if aktif else "⛔ Nonaktif"
        kb = tbtypes.InlineKeyboardMarkup()
        row1 = [tbtypes.InlineKeyboardButton(
            ("▶️ " if i == hari_baru else "") + NAMA_HARI[i],
            callback_data=f"yt_weekly_hari_{i}"
        ) for i in range(4)]
        row2 = [tbtypes.InlineKeyboardButton(
            ("▶️ " if i == hari_baru else "") + NAMA_HARI[i],
            callback_data=f"yt_weekly_hari_{i}"
        ) for i in range(4, 7)]
        kb.row(*row1)
        kb.row(*row2)
        kb.row(tbtypes.InlineKeyboardButton(f"🕐 Ubah Jam (sekarang: {jam_cfg} WIB)", callback_data="yt_weekly_ubah_jam"))
        kb.row(tbtypes.InlineKeyboardButton(
            f"{'⛔ Nonaktifkan' if aktif else '✅ Aktifkan'} Ringkasan Mingguan",
            callback_data="yt_weekly_toggle"
        ))
        kb.row(tbtypes.InlineKeyboardButton("📤 Kirim Ringkasan Sekarang", callback_data="yt_weekly_kirim_sekarang"))
        kb.row(tbtypes.InlineKeyboardButton("🔙 Kembali", callback_data="menu_youtube"))
        bot.edit_message_text(
            f"📅 <b>PENGATURAN RINGKASAN MINGGUAN</b>\n\n"
            f"Status: <b>{status_label}</b>\n"
            f"Jadwal: <b>{NAMA_HARI[hari_baru]}, {jam_cfg} WIB</b>\n\n"
            f"Pilih hari pengiriman (yang dipilih ditandai ▶️), "
            f"lalu ubah jam atau toggle aktif/nonaktif:",
            chat_id=chat_id, message_id=call.message.message_id,
            parse_mode="HTML", reply_markup=kb)

    elif data == "yt_weekly_kirim_sekarang":
        bot.send_message(chat_id, "⏳ Menyusun ringkasan, sebentar...")
        threading.Thread(target=_kirim_ringkasan_weekly, args=(chat_id,), daemon=True).start()

    elif data == "yt_weekly_ubah_jam":
        user_state[chat_id] = {"step": "tunggu_jam_weekly"}
        _, jam_cfg, _ = _ambil_weekly_config()
        bot.send_message(chat_id,
            f"🕐 <b>Ubah Jam Ringkasan Mingguan</b>\n\n"
            f"Jam saat ini: <b>{jam_cfg} WIB</b>\n\n"
            f"Ketik jam baru dalam format <code>HH:MM</code>\n"
            f"Contoh: <code>08:00</code> atau <code>20:30</code>\n\n"
            f"<i>Ketik /batal untuk membatalkan.</i>",
            parse_mode="HTML")

    elif data == "yt_weekly_toggle":
        hari_cfg, jam_cfg, aktif = _ambil_weekly_config()
        aktif_baru = not aktif
        _simpan_weekly_config(aktif=aktif_baru)
        status_label = "✅ Aktif" if aktif_baru else "⛔ Nonaktif"
        kb = tbtypes.InlineKeyboardMarkup()
        row1 = [tbtypes.InlineKeyboardButton(
            ("▶️ " if i == hari_cfg else "") + NAMA_HARI[i],
            callback_data=f"yt_weekly_hari_{i}"
        ) for i in range(4)]
        row2 = [tbtypes.InlineKeyboardButton(
            ("▶️ " if i == hari_cfg else "") + NAMA_HARI[i],
            callback_data=f"yt_weekly_hari_{i}"
        ) for i in range(4, 7)]
        kb.row(*row1)
        kb.row(*row2)
        kb.row(tbtypes.InlineKeyboardButton(f"🕐 Ubah Jam (sekarang: {jam_cfg} WIB)", callback_data="yt_weekly_ubah_jam"))
        kb.row(tbtypes.InlineKeyboardButton(
            f"{'⛔ Nonaktifkan' if aktif_baru else '✅ Aktifkan'} Ringkasan Mingguan",
            callback_data="yt_weekly_toggle"
        ))
        kb.row(tbtypes.InlineKeyboardButton("📤 Kirim Ringkasan Sekarang", callback_data="yt_weekly_kirim_sekarang"))
        kb.row(tbtypes.InlineKeyboardButton("🔙 Kembali", callback_data="menu_youtube"))
        bot.edit_message_text(
            f"📅 <b>PENGATURAN RINGKASAN MINGGUAN</b>\n\n"
            f"Status: <b>{status_label}</b>\n"
            f"Jadwal: <b>{NAMA_HARI[hari_cfg]}, {jam_cfg} WIB</b>\n\n"
            f"Pilih hari pengiriman (yang dipilih ditandai ▶️), "
            f"lalu ubah jam atau toggle aktif/nonaktif:",
            chat_id=chat_id, message_id=call.message.message_id,
            parse_mode="HTML", reply_markup=kb)

    elif data == "konfirmasi_milestone_views_ya":
        state = user_state.pop(chat_id, {})
        angka = state.get("pending", [])
        if angka:
            _simpan_milestones("views", angka)
            mv_str = " · ".join(f"{m:,}" for m in angka)
            bot.send_message(chat_id,
                f"✅ <b>Milestone Views berhasil disimpan!</b>\n\n"
                f"👁️ {mv_str}\n\n"
                f"Bot akan notif saat views video melewati angka-angka ini.",
                parse_mode="HTML", reply_markup=keyboard_youtube_monitor())
        else:
            bot.send_message(chat_id, "⚠️ Data milestone tidak ditemukan, coba lagi.",
                parse_mode="HTML", reply_markup=keyboard_youtube_monitor())

    elif data == "konfirmasi_milestone_views_batal":
        user_state.pop(chat_id, None)
        bot.send_message(chat_id,
            "❌ Perubahan milestone views <b>dibatalkan</b>.\nMilestone lama tetap berlaku.",
            parse_mode="HTML", reply_markup=keyboard_youtube_monitor())

    elif data == "konfirmasi_milestone_likes_ya":
        state = user_state.pop(chat_id, {})
        angka = state.get("pending", [])
        if angka:
            _simpan_milestones("likes", angka)
            ml_str = " · ".join(f"{m:,}" for m in angka)
            bot.send_message(chat_id,
                f"✅ <b>Milestone Likes berhasil disimpan!</b>\n\n"
                f"👍 {ml_str}\n\n"
                f"Bot akan notif saat likes video melewati angka-angka ini.",
                parse_mode="HTML", reply_markup=keyboard_youtube_monitor())
        else:
            bot.send_message(chat_id, "⚠️ Data milestone tidak ditemukan, coba lagi.",
                parse_mode="HTML", reply_markup=keyboard_youtube_monitor())

    elif data == "konfirmasi_milestone_likes_batal":
        user_state.pop(chat_id, None)
        bot.send_message(chat_id,
            "❌ Perubahan milestone likes <b>dibatalkan</b>.\nMilestone lama tetap berlaku.",
            parse_mode="HTML", reply_markup=keyboard_youtube_monitor())

# ==========================================
# 13. TEKS BEBAS
# ==========================================
@bot.message_handler(func=lambda m: m.text and not m.text.startswith("/"))
def handle_teks(message):
    if not cek_owner(message): return
    chat_id = message.chat.id
    state   = user_state.get(chat_id, {})
    step    = state.get("step", "")
    pref    = ambil_preferensi(chat_id)
    tema_aktif = pref.get("tema","diy")

    if step == "tunggu_topik":
        topik = message.text.strip()
        tema  = state.get("tema", tema_aktif)
        user_state[chat_id] = {"step":"pilih_scene","data":{"topik":topik},"tema":tema}
        bot.send_message(chat_id,
            f"✅ Topik: <b>{esc(topik)}</b>\n\n🎞️ Berapa jumlah scene?",
            parse_mode="HTML", reply_markup=keyboard_jumlah_scene())

    elif step == "tunggu_viral_threshold":
        user_state.pop(chat_id, None)
        teks = message.text.strip()
        try:
            pct = int(teks)
            if not (1 <= pct <= 10000):
                raise ValueError("di luar range")
            _simpan_viral_threshold(pct)
            bot.send_message(chat_id,
                f"✅ <b>Threshold viral berhasil diset: {pct}%</b>\n\n"
                f"Bot akan kirim notif ⚡ kalau ada video yang views-nya naik lebih dari <b>{pct}%</b> dalam 1 jam.",
                parse_mode="HTML", reply_markup=keyboard_youtube_monitor())
        except Exception:
            bot.send_message(chat_id,
                "❌ Format salah. Masukkan angka bulat, contoh: <code>50</code>",
                parse_mode="HTML")

    elif step == "tunggu_jam_weekly":
        user_state.pop(chat_id, None)
        teks = message.text.strip()
        import re
        if re.match(r'^\d{1,2}:\d{2}$', teks):
            jam_h, jam_m = teks.split(":")
            if 0 <= int(jam_h) <= 23 and 0 <= int(jam_m) <= 59:
                jam_format = f"{int(jam_h):02d}:{jam_m}"
                _simpan_weekly_config(jam=jam_format)
                hari_cfg, _, aktif = _ambil_weekly_config()
                status_label = "✅ Aktif" if aktif else "⛔ Nonaktif"
                bot.send_message(chat_id,
                    f"✅ <b>Jam ringkasan mingguan berhasil diubah!</b>\n\n"
                    f"📅 Jadwal baru: <b>{NAMA_HARI[hari_cfg]}, {jam_format} WIB</b>\n"
                    f"Status: {status_label}",
                    parse_mode="HTML", reply_markup=keyboard_youtube_monitor())
            else:
                bot.send_message(chat_id,
                    "❌ Jam tidak valid. Contoh yang benar: <code>08:00</code> atau <code>20:30</code>",
                    parse_mode="HTML")
        else:
            bot.send_message(chat_id,
                "❌ Format salah. Gunakan format <code>HH:MM</code>\nContoh: <code>08:00</code>",
                parse_mode="HTML")

    elif step == "tunggu_milestone_views":
        teks = message.text.strip()
        try:
            angka = sorted(set(int(x) for x in teks.split() if x.isdigit() and int(x) > 0))
            if not angka:
                raise ValueError("kosong")
            # Simpan pending, minta konfirmasi dulu
            user_state[chat_id] = {"step": "konfirmasi_milestone_views", "pending": angka}
            mv_str = " · ".join(f"{m:,}" for m in angka)
            kb = tbtypes.InlineKeyboardMarkup()
            kb.row(
                tbtypes.InlineKeyboardButton("✅ Ya, Simpan", callback_data="konfirmasi_milestone_views_ya"),
                tbtypes.InlineKeyboardButton("❌ Batal",      callback_data="konfirmasi_milestone_views_batal"),
            )
            bot.send_message(chat_id,
                f"🎯 <b>Konfirmasi Milestone Views Baru:</b>\n\n"
                f"👁️ {mv_str}\n\n"
                f"Apakah kamu yakin ingin mengganti milestone views dengan angka-angka di atas?",
                parse_mode="HTML", reply_markup=kb)
        except Exception as e:
            bot.send_message(chat_id,
                f"❌ Format salah. Masukkan hanya angka dipisah spasi.\nContoh: <code>100 500 1000 5000</code>\n\n<i>Error: {e}</i>",
                parse_mode="HTML")

    elif step == "tunggu_milestone_likes":
        teks = message.text.strip()
        try:
            angka = sorted(set(int(x) for x in teks.split() if x.isdigit() and int(x) > 0))
            if not angka:
                raise ValueError("kosong")
            # Simpan pending, minta konfirmasi dulu
            user_state[chat_id] = {"step": "konfirmasi_milestone_likes", "pending": angka}
            ml_str = " · ".join(f"{m:,}" for m in angka)
            kb = tbtypes.InlineKeyboardMarkup()
            kb.row(
                tbtypes.InlineKeyboardButton("✅ Ya, Simpan", callback_data="konfirmasi_milestone_likes_ya"),
                tbtypes.InlineKeyboardButton("❌ Batal",      callback_data="konfirmasi_milestone_likes_batal"),
            )
            bot.send_message(chat_id,
                f"🎯 <b>Konfirmasi Milestone Likes Baru:</b>\n\n"
                f"👍 {ml_str}\n\n"
                f"Apakah kamu yakin ingin mengganti milestone likes dengan angka-angka di atas?",
                parse_mode="HTML", reply_markup=kb)
        except Exception as e:
            bot.send_message(chat_id,
                f"❌ Format salah. Masukkan hanya angka dipisah spasi.\nContoh: <code>10 50 100 500</code>\n\n<i>Error: {e}</i>",
                parse_mode="HTML", reply_markup=keyboard_youtube_monitor())

    else:
        bot.send_message(chat_id,
            "📌 Pilih menu di bawah atau ketik <b>Konten</b> untuk generate:",
            parse_mode="HTML", reply_markup=keyboard_menu_utama(tema_aktif))

# ==========================================
# 14. FLASK & THREADING
# ==========================================
app = Flask(__name__)

# Auto-start semua thread saat dijalankan oleh Gunicorn
import atexit
_threads_started = False

def _start_threads():
    global _threads_started
    if _threads_started:
        return
    _threads_started = True
    threading.Thread(target=jalankan_bot, daemon=True).start()
    threading.Thread(target=run_scheduler, daemon=True).start()
    threading.Thread(target=run_keep_alive, daemon=True).start()
    threading.Thread(target=run_youtube_monitor, daemon=True).start()
    threading.Thread(target=run_weekly_summary, daemon=True).start()
    print("[STARTUP] Semua thread berhasil distart.")

    # Kirim notifikasi ke owner saat bot pertama kali nyala
    def _notif_startup():
        time.sleep(3)  # tunggu polling siap dulu
        try:
            chat_id = ambil_chat_id() or OWNER_ID
            bot.send_message(chat_id,
                "✅ <b>Bot aktif dan siap digunakan!</b>\n"
                "<i>Semua thread berjalan normal.</i>",
                parse_mode="HTML")
        except Exception as e:
            print(f"[STARTUP NOTIF] Gagal kirim notif: {e}")
    threading.Thread(target=_notif_startup, daemon=True).start()


@app.route('/')
def home():
    return "Bot Konten Multi-Tema v10 — DIY | AI Toy Construction | AI Animation | Multi-Bahasa — Running 24/7"

# ==========================================
# 15. YOUTUBE MONITOR (OAuth2)
# ==========================================
YT_CLIENT_ID     = os.environ.get("YOUTUBE_CLIENT_ID", "")
YT_CLIENT_SECRET = os.environ.get("YOUTUBE_CLIENT_SECRET", "")
YT_REFRESH_TOKEN = os.environ.get("YOUTUBE_REFRESH_TOKEN", "")

DEFAULT_MILESTONES_VIEWS = [100, 500, 1_000, 5_000, 10_000, 50_000, 100_000, 500_000, 1_000_000]
DEFAULT_MILESTONES_LIKES = [10, 50, 100, 500, 1_000, 5_000, 10_000]

def _ambil_milestones():
    """Ambil milestone custom dari DB, fallback ke default."""
    try:
        conn = connect_db(); cur = conn.cursor()
        cur.execute("SELECT views_milestones, likes_milestones FROM yt_milestones WHERE id=1")
        row = cur.fetchone(); cur.close(); conn.close()
        if row:
            mv = [int(x) for x in row[0].split(",") if x.strip().isdigit()]
            ml = [int(x) for x in row[1].split(",") if x.strip().isdigit()]
            return sorted(mv), sorted(ml)
    except Exception as e:
        print(f"[YT MILESTONE] Gagal ambil: {e}")
    return DEFAULT_MILESTONES_VIEWS, DEFAULT_MILESTONES_LIKES

def _simpan_milestones(tipe, angka_list):
    """Simpan milestone custom ke DB."""
    val = ",".join(str(x) for x in sorted(angka_list))
    conn = connect_db(); cur = conn.cursor()
    if tipe == "views":
        cur.execute("UPDATE yt_milestones SET views_milestones=%s WHERE id=1", (val,))
    else:
        cur.execute("UPDATE yt_milestones SET likes_milestones=%s WHERE id=1", (val,))
    conn.commit(); cur.close(); conn.close()

def _yt_access_token():
    """Tukar refresh_token dengan access_token baru."""
    try:
        resp = requests.post("https://oauth2.googleapis.com/token", data={
            "client_id":     YT_CLIENT_ID,
            "client_secret": YT_CLIENT_SECRET,
            "refresh_token": YT_REFRESH_TOKEN,
            "grant_type":    "refresh_token",
        }, timeout=15)
        return resp.json().get("access_token")
    except Exception as e:
        print(f"[YT TOKEN] Gagal refresh token: {e}")
        return None

def _yt_video_stats(video_id, access_token):
    """Ambil statistik 1 video dari YouTube Data API v3."""
    try:
        resp = requests.get(
            "https://www.googleapis.com/youtube/v3/videos",
            params={"part": "snippet,statistics", "id": video_id},
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15
        )
        items = resp.json().get("items", [])
        if not items:
            return None
        item  = items[0]
        stats = item.get("statistics", {})
        title = item.get("snippet", {}).get("title", "")
        return {
            "title":  title,
            "views":  int(stats.get("viewCount", 0)),
            "likes":  int(stats.get("likeCount", 0)),
        }
    except Exception as e:
        print(f"[YT STATS] Error {video_id}: {e}")
        return None

def _parse_video_id(url_or_id: str):
    """Ekstrak video ID dari URL YouTube atau langsung ID."""
    url_or_id = url_or_id.strip()
    for sep in ["/shorts/", "v=", "youtu.be/"]:
        if sep in url_or_id:
            vid = url_or_id.split(sep)[-1]
            return vid.split("?")[0].split("&")[0].split("/")[0]
    return url_or_id  # anggap sudah berupa ID

def _yt_channel_upload_playlist(access_token):
    """Ambil ID playlist 'Uploads' dari channel milik akun yang login."""
    try:
        resp = requests.get(
            "https://www.googleapis.com/youtube/v3/channels",
            params={"part": "contentDetails", "mine": "true"},
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15
        )
        items = resp.json().get("items", [])
        if not items:
            return None
        return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    except Exception as e:
        print(f"[YT CHANNEL] Gagal ambil playlist uploads: {e}")
        return None

def _yt_latest_video_ids(access_token, playlist_id, max_results=20):
    """Ambil video_id terbaru dari playlist uploads channel."""
    try:
        resp = requests.get(
            "https://www.googleapis.com/youtube/v3/playlistItems",
            params={
                "part":       "contentDetails",
                "playlistId": playlist_id,
                "maxResults": max_results,
            },
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15
        )
        items = resp.json().get("items", [])
        return [i["contentDetails"]["videoId"] for i in items]
    except Exception as e:
        print(f"[YT CHANNEL] Gagal ambil video list: {e}")
        return []

def auto_scan_channel(access_token, notify_chat_id=None):
    """
    Scan channel, tambahkan video baru ke DB secara otomatis.
    Kembalikan jumlah video baru yang ditemukan.
    """
    playlist_id = _yt_channel_upload_playlist(access_token)
    if not playlist_id:
        msg = ("[YT SCAN] Gagal ambil playlist ID channel. "
               "Kemungkinan: channel belum ada, atau scope OAuth belum mencakup youtube.readonly.")
        print(msg)
        if notify_chat_id:
            bot.send_message(notify_chat_id,
                "❌ <b>Gagal ambil data channel.</b>\n\n"
                "Kemungkinan penyebab:\n"
                "• Channel YouTube belum dibuat di akun ini\n"
                "• Scope OAuth belum include <code>youtube.readonly</code>\n\n"
                "<i>Coba jalankan ulang script get_youtube_token.py dan pastikan "
                "scope youtube.readonly dicentang saat authorize.</i>",
                parse_mode="HTML")
        return 0
    video_ids = _yt_latest_video_ids(access_token, playlist_id, max_results=50)
    if not video_ids:
        return 0
    baru = 0
    conn = connect_db(); cur = conn.cursor()
    for vid_id in video_ids:
        cur.execute("SELECT id FROM youtube_videos WHERE video_id=%s", (vid_id,))
        if cur.fetchone():
            continue  # sudah ada, skip
        # Video baru — ambil info dan simpan
        stats = _yt_video_stats(vid_id, access_token)
        if not stats:
            continue
        cur.execute("""
            INSERT INTO youtube_videos (video_id, judul, views_last, likes_last, auto_scan)
            VALUES (%s, %s, %s, %s, TRUE)
            ON CONFLICT (video_id) DO NOTHING
        """, (vid_id, stats["title"], stats["views"], stats["likes"]))
        baru += 1
        if notify_chat_id and baru <= 5:  # notif max 5 video sekaligus agar tidak spam
            bot.send_message(notify_chat_id,
                f"🆕 <b>Video baru ditemukan & ditambahkan ke monitor!</b>\n\n"
                f"🎬 <b>{esc(stats['title'])}</b>\n"
                f"👁️ {stats['views']:,} views · 👍 {stats['likes']:,} likes\n"
                f"🔗 https://youtube.com/shorts/{vid_id}",
                parse_mode="HTML")
    if baru > 5 and notify_chat_id:
        bot.send_message(notify_chat_id,
            f"🆕 <b>{baru} video baru</b> ditemukan dan ditambahkan ke monitor sekaligus.",
            parse_mode="HTML")
    conn.commit(); cur.close(); conn.close()
    print(f"[YT SCAN] Auto-scan selesai — {baru} video baru ditambahkan.")
    return baru

def tambah_video_yt(chat_id, url_or_id):
    video_id = _parse_video_id(url_or_id)
    if not video_id or len(video_id) < 5:
        bot.send_message(chat_id, "❌ URL/ID video tidak valid. Contoh:\n<code>/tambah_video https://youtube.com/shorts/abc123</code>", parse_mode="HTML")
        return
    token = _yt_access_token()
    if not token:
        bot.send_message(chat_id, "❌ Gagal connect ke YouTube API. Cek env var YOUTUBE_*.")
        return
    stats = _yt_video_stats(video_id, token)
    if not stats:
        bot.send_message(chat_id, f"❌ Video <code>{video_id}</code> tidak ditemukan atau tidak publik.", parse_mode="HTML")
        return
    try:
        conn = connect_db(); cur = conn.cursor()
        cur.execute("""
            INSERT INTO youtube_videos (video_id, judul, views_last, likes_last)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (video_id) DO UPDATE SET judul=EXCLUDED.judul
        """, (video_id, stats["title"], stats["views"], stats["likes"]))
        conn.commit(); cur.close(); conn.close()
        bot.send_message(chat_id,
            f"✅ <b>Video ditambahkan ke monitor!</b>\n\n"
            f"🎬 <b>{esc(stats['title'])}</b>\n"
            f"🔗 ID: <code>{video_id}</code>\n"
            f"👁️ Views sekarang: <b>{stats['views']:,}</b>\n"
            f"👍 Likes sekarang: <b>{stats['likes']:,}</b>\n\n"
            f"<i>Bot akan kirim notif tiap kali video melewati milestone baru.</i>",
            parse_mode="HTML")
    except Exception as e:
        print(f"[YT DB] Gagal simpan: {e}")
        bot.send_message(chat_id, f"❌ Error database: {e}")

def daftar_video_yt(chat_id):
    try:
        conn = connect_db(); cur = conn.cursor()
        cur.execute("SELECT video_id, judul, views_last, likes_last, tanggal_upload FROM youtube_videos ORDER BY views_last DESC")
        rows = cur.fetchall(); cur.close(); conn.close()
        if not rows:
            bot.send_message(chat_id,
                "📭 Belum ada video yang dimonitor.\n\nGunakan:\n<code>/tambah_video [URL YouTube]</code>",
                parse_mode="HTML")
            return
        pesan = "📊 <b>VIDEO YANG DIMONITOR:</b>\n\n"
        for i, (vid_id, judul, views, likes, tgl) in enumerate(rows, 1):
            pesan += (f"{i}. <b>{esc(judul or vid_id)}</b>\n"
                      f"   👁️ {views:,} views · 👍 {likes:,} likes\n"
                      f"   📅 {tgl} · <code>{vid_id}</code>\n\n")
        pesan += "<i>Cek views: /cek_views | Hapus: /hapus_video [ID]</i>"
        bot.send_message(chat_id, pesan, parse_mode="HTML")
    except Exception as e:
        bot.send_message(chat_id, f"❌ Error: {e}")

def hapus_video_yt(chat_id, video_id):
    video_id = _parse_video_id(video_id)
    try:
        conn = connect_db(); cur = conn.cursor()
        cur.execute("DELETE FROM youtube_videos WHERE video_id=%s", (video_id,))
        affected = cur.rowcount
        conn.commit(); cur.close(); conn.close()
        if affected:
            bot.send_message(chat_id, f"🗑️ Video <code>{video_id}</code> dihapus dari monitor.",
                parse_mode="HTML", reply_markup=keyboard_youtube_monitor())
        else:
            bot.send_message(chat_id, f"❌ Video <code>{video_id}</code> tidak ditemukan.", parse_mode="HTML")
    except Exception as e:
        bot.send_message(chat_id, f"❌ Error: {e}")

def tampilkan_daftar_hapus_video(chat_id):
    """Tampilkan daftar video dengan tombol hapus per baris."""
    try:
        conn = connect_db(); cur = conn.cursor()
        cur.execute("SELECT video_id, judul, views_last FROM youtube_videos ORDER BY views_last DESC")
        rows = cur.fetchall(); cur.close(); conn.close()
        if not rows:
            bot.send_message(chat_id,
                "📭 Belum ada video yang dimonitor.",
                parse_mode="HTML", reply_markup=keyboard_youtube_monitor())
            return
        kb = tbtypes.InlineKeyboardMarkup()
        for (vid_id, judul, views) in rows:
            label = (judul or vid_id)[:35] + ("…" if len(judul or vid_id) > 35 else "")
            kb.row(tbtypes.InlineKeyboardButton(
                f"🗑️ {label}  ({views:,} views)",
                callback_data=f"yt_konfirmasi_hapus_{vid_id}"
            ))
        kb.row(tbtypes.InlineKeyboardButton("🔙 Kembali", callback_data="menu_youtube"))
        bot.send_message(chat_id,
            f"🗑️ <b>HAPUS VIDEO DARI MONITOR</b>\n\n"
            f"Pilih video yang ingin kamu hapus:",
            parse_mode="HTML", reply_markup=kb)
    except Exception as e:
        bot.send_message(chat_id, f"❌ Error: {e}")

def cek_views_manual(chat_id):
    token = _yt_access_token()
    if not token:
        bot.send_message(chat_id, "❌ Gagal connect ke YouTube API."); return
    try:
        conn = connect_db(); cur = conn.cursor()
        cur.execute("SELECT video_id, judul, views_last, likes_last FROM youtube_videos ORDER BY views_last DESC")
        rows = cur.fetchall()
        if not rows:
            bot.send_message(chat_id, "📭 Belum ada video yang dimonitor. Gunakan /tambah_video")
            cur.close(); conn.close(); return
        pesan = "📊 <b>CEK VIEWS TERKINI:</b>\n\n"
        for (vid_id, judul, views_old, likes_old) in rows:
            stats = _yt_video_stats(vid_id, token)
            if not stats:
                pesan += f"❓ <code>{vid_id}</code> — tidak dapat diambil\n\n"
                continue
            delta_v = stats['views'] - views_old
            delta_l = stats['likes'] - likes_old
            delta_v_str = f" (+{delta_v:,})" if delta_v > 0 else ""
            delta_l_str = f" (+{delta_l:,})" if delta_l > 0 else ""
            cur.execute("UPDATE youtube_videos SET views_last=%s, likes_last=%s WHERE video_id=%s",
                        (stats['views'], stats['likes'], vid_id))
            pesan += (f"🎬 <b>{esc(stats['title'] or judul or vid_id)}</b>\n"
                      f"👁️ {stats['views']:,}{delta_v_str} views\n"
                      f"👍 {stats['likes']:,}{delta_l_str} likes\n\n")
        conn.commit(); cur.close(); conn.close()
        bot.send_message(chat_id, pesan, parse_mode="HTML")
    except Exception as e:
        bot.send_message(chat_id, f"❌ Error: {e}")

def run_youtube_monitor():
    """
    Tiap 1 jam:
    1. Auto-scan channel → tambah video baru otomatis
    2. Cek views & likes semua video
    3. Kirim notif Telegram jika melewati milestone (custom atau default)
    """
    if not all([YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN]):
        print("[YT MONITOR] Env var YOUTUBE_* belum di-set, monitor dinonaktifkan.")
        return
    print("[YT MONITOR] Monitor YouTube aktif — auto-scan + cek milestone tiap 1 jam.")
    while True:
        time.sleep(3600)  # cek tiap 1 jam
        try:
            token = _yt_access_token()
            if not token:
                continue
            chat_id = ambil_chat_id()

            # -- 1. Auto-scan channel untuk video baru --
            auto_scan_channel(token, notify_chat_id=chat_id)

            # -- 2. Ambil threshold viral --
            try:
                conn_v = connect_db(); cur_v = conn_v.cursor()
                cur_v.execute("SELECT viral_threshold_pct FROM yt_milestones WHERE id=1")
                row_v = cur_v.fetchone(); cur_v.close(); conn_v.close()
                viral_threshold = row_v[0] if row_v and row_v[0] else 50
            except Exception:
                viral_threshold = 50

            # -- 3. Cek milestone semua video --
            milestones_views, milestones_likes = _ambil_milestones()
            conn = connect_db(); cur = conn.cursor()
            cur.execute("SELECT id, video_id, judul, views_last, likes_last, milestone_views, milestone_likes FROM youtube_videos")
            rows = cur.fetchall()
            for (row_id, vid_id, judul, views_old, likes_old, ms_views_str, ms_likes_str) in rows:
                stats = _yt_video_stats(vid_id, token)
                if not stats: continue
                views_now = stats['views']
                likes_now = stats['likes']
                passed_mv = set(ms_views_str.split(",")) if ms_views_str else set()
                passed_ml = set(ms_likes_str.split(",")) if ms_likes_str else set()
                notif_parts = []
                for m in milestones_views:
                    if views_now >= m and str(m) not in passed_mv:
                        passed_mv.add(str(m))
                        notif_parts.append(f"👁️ <b>{m:,} VIEWS</b> tercapai!")
                for m in milestones_likes:
                    if likes_now >= m and str(m) not in passed_ml:
                        passed_ml.add(str(m))
                        notif_parts.append(f"👍 <b>{m:,} LIKES</b> tercapai!")
                if notif_parts and chat_id:
                    teks = (f"🎉 <b>MILESTONE YOUTUBE!</b>\n\n"
                            f"🎬 {esc(stats['title'] or judul or vid_id)}\n"
                            + "\n".join(notif_parts) +
                            f"\n\n👁️ Total views: <b>{views_now:,}</b>\n"
                            f"👍 Total likes: <b>{likes_now:,}</b>\n"
                            f"🔗 https://youtube.com/shorts/{vid_id}")
                    try:
                        bot.send_message(chat_id, teks, parse_mode="HTML")
                    except Exception as e:
                        print(f"[YT MONITOR] Gagal kirim notif: {e}")
                # -- Deteksi viral (laju naik per jam) --
                if views_old > 0 and chat_id:
                    growth_pct = ((views_now - views_old) / views_old) * 100
                    if growth_pct >= viral_threshold:
                        delta = views_now - views_old
                        try:
                            bot.send_message(chat_id,
                                f"⚡ <b>VIDEO SEDANG VIRAL!</b>\n\n"
                                f"🎬 {esc(stats['title'] or judul or vid_id)}\n\n"
                                f"📈 Naik <b>+{delta:,} views</b> dalam 1 jam terakhir\n"
                                f"🔥 Pertumbuhan: <b>+{growth_pct:.1f}%</b>\n"
                                f"👁️ Total sekarang: <b>{views_now:,} views</b>\n"
                                f"🔗 https://youtube.com/shorts/{vid_id}",
                                parse_mode="HTML")
                        except Exception as e:
                            print(f"[YT VIRAL] Gagal kirim notif: {e}")
                cur.execute("""UPDATE youtube_videos
                    SET views_last=%s, likes_last=%s,
                        milestone_views=%s, milestone_likes=%s
                    WHERE id=%s""",
                    (views_now, likes_now,
                     ",".join(sorted(passed_mv, key=lambda x: int(x) if x.strip().isdigit() else 0)),
                     ",".join(sorted(passed_ml, key=lambda x: int(x) if x.strip().isdigit() else 0)),
                     row_id))
                # -- Catat histori per jam --
                cur.execute(
                    "INSERT INTO yt_views_history (video_id, views, likes) VALUES (%s, %s, %s)",
                    (vid_id, views_now, likes_now))
            conn.commit()
            # -- Auto-prune histori > 90 hari (1x per hari, jam 03:xx WIB) --
            now_wib = datetime.now(WIB)
            if now_wib.hour == 3:
                try:
                    cur2 = conn.cursor()
                    cur2.execute("DELETE FROM yt_views_history WHERE dicatat_pada < NOW() - INTERVAL '90 days'")
                    deleted = cur2.rowcount
                    conn.commit(); cur2.close()
                    if deleted > 0:
                        print(f"[YT PRUNE] Dihapus {deleted} baris histori lama (>90 hari)")
                except Exception as pe:
                    print(f"[YT PRUNE ERROR] {pe}")
            cur.close(); conn.close()
        except Exception as e:
            print(f"[YT MONITOR ERROR] {e}")

# ==========================================
# 16. COMMAND HANDLER YOUTUBE
# ==========================================
@bot.message_handler(commands=["tambah_video"])
def cmd_tambah_video(message):
    if not cek_owner(message): return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        bot.send_message(message.chat.id,
            "📎 Format: <code>/tambah_video [URL atau ID video]</code>\n\n"
            "Contoh:\n<code>/tambah_video https://youtube.com/shorts/abc123xyz</code>",
            parse_mode="HTML")
        return
    tambah_video_yt(message.chat.id, parts[1])

@bot.message_handler(commands=["daftar_video"])
def cmd_daftar_video(message):
    if not cek_owner(message): return
    daftar_video_yt(message.chat.id)

@bot.message_handler(commands=["hapus_video"])
def cmd_hapus_video(message):
    if not cek_owner(message): return
    # Tampilkan daftar dengan tombol hapus langsung
    tampilkan_daftar_hapus_video(message.chat.id)

@bot.message_handler(commands=["cek_views"])
def cmd_cek_views(message):
    if not cek_owner(message): return
    bot.send_message(message.chat.id, "⏳ Mengambil data views dari YouTube...")
    cek_views_manual(message.chat.id)

@bot.message_handler(commands=["youtube_help"])
def cmd_youtube_help(message):
    if not cek_owner(message): return
    bot.send_message(message.chat.id,
        "📺 <b>YOUTUBE MONITOR — PANDUAN:</b>\n\n"
        "➕ <code>/tambah_video [URL]</code>\n"
        "   Tambah video ke daftar monitor\n\n"
        "📋 <code>/daftar_video</code>\n"
        "   Lihat semua video yang dimonitor\n\n"
        "📊 <code>/cek_views</code>\n"
        "   Cek views & likes terkini semua video\n\n"
        "🗑️ <code>/hapus_video [ID]</code>\n"
        "   Hapus video dari monitor\n\n"
        "🔔 <b>Notif otomatis</b> dikirim saat video melewati milestone.\n"
        "   Lihat milestone aktif: /lihat_milestone\n\n"
        "⚙️ <code>/set_milestone views 100 500 1000 5000</code>\n"
        "   Set milestone views custom\n\n"
        "⚙️ <code>/set_milestone likes 10 50 100 500</code>\n"
        "   Set milestone likes custom\n\n"
        "🔍 <code>/scan_channel</code>\n"
        "   Scan manual channel untuk temukan video baru\n\n"
        "<i>Monitor auto-scan + cek milestone setiap 1 jam.</i>",
        parse_mode="HTML")

@bot.message_handler(commands=["export_yt"])
def cmd_export_yt(message):
    if not cek_owner(message): return
    bot.send_message(message.chat.id, "⏳ Menyiapkan laporan CSV...")
    threading.Thread(target=export_laporan_csv, args=(message.chat.id,), daemon=True).start()

@bot.message_handler(commands=["scan_channel"])
def cmd_scan_channel(message):
    if not cek_owner(message): return
    chat_id = message.chat.id
    token = _yt_access_token()
    if not token:
        bot.send_message(chat_id, "❌ Gagal connect ke YouTube API. Cek env var YOUTUBE_*."); return
    bot.send_message(chat_id, "🔍 Scanning channel untuk video baru...")
    baru = auto_scan_channel(token, notify_chat_id=chat_id)
    if baru == 0:
        bot.send_message(chat_id, "✅ Scan selesai — tidak ada video baru ditemukan.\n<i>Semua video sudah terdaftar di monitor.</i>", parse_mode="HTML")

@bot.message_handler(commands=["lihat_milestone"])
def cmd_lihat_milestone(message):
    if not cek_owner(message): return
    mv, ml = _ambil_milestones()
    mv_str = " · ".join(f"{m:,}" for m in mv)
    ml_str = " · ".join(f"{m:,}" for m in ml)
    bot.send_message(message.chat.id,
        f"🎯 <b>MILESTONE AKTIF:</b>\n\n"
        f"👁️ <b>Views:</b>\n{mv_str}\n\n"
        f"👍 <b>Likes:</b>\n{ml_str}\n\n"
        f"<i>Ubah dengan /set_milestone views [angka...] atau /set_milestone likes [angka...]</i>",
        parse_mode="HTML")

@bot.message_handler(commands=["set_milestone"])
def cmd_set_milestone(message):
    if not cek_owner(message): return
    chat_id = message.chat.id
    parts = message.text.split()
    # Format: /set_milestone views 100 500 1000
    if len(parts) < 3 or parts[1] not in ("views", "likes"):
        bot.send_message(chat_id,
            "📎 <b>Format:</b>\n"
            "<code>/set_milestone views 100 500 1000 5000 10000</code>\n"
            "<code>/set_milestone likes 10 50 100 500 1000</code>\n\n"
            "Pisahkan angka dengan spasi. Minimal 1 angka.",
            parse_mode="HTML")
        return
    tipe = parts[1]
    try:
        angka_list = sorted(set(int(x) for x in parts[2:] if x.isdigit() and int(x) > 0))
        if not angka_list:
            raise ValueError("Tidak ada angka valid")
    except Exception:
        bot.send_message(chat_id, "❌ Angka tidak valid. Gunakan bilangan bulat positif saja.")
        return
    _simpan_milestones(tipe, angka_list)
    angka_str = " · ".join(f"{m:,}" for m in angka_list)
    bot.send_message(chat_id,
        f"✅ <b>Milestone {tipe} diperbarui!</b>\n\n"
        f"{'👁️' if tipe == 'views' else '👍'} <b>{tipe.capitalize()}:</b>\n{angka_str}\n\n"
        f"<i>Akan berlaku mulai cek berikutnya.</i>",
        parse_mode="HTML")

def jalankan_bot():
    while True:
        try:
            bot.polling(none_stop=True, interval=0, timeout=30, long_polling_timeout=30)
        except Exception as e:
            print(f"[BOT ERROR] polling crash: {e} — restart dalam 5 detik")
            time.sleep(5)

def run_keep_alive():
    """
    Self-ping setiap 10 menit agar Render tidak spin down service.
    Tanpa ini, scheduler jam 23:30 dan 04:30 tidak akan pernah terkirim
    karena Render mematikan proses setelah ~15 menit tidak ada traffic.
    """
    render_url = os.environ.get("RENDER_EXTERNAL_URL", "")
    if not render_url:
        print("[KEEP-ALIVE] RENDER_EXTERNAL_URL tidak di-set, self-ping dinonaktifkan.")
        return
    while True:
        try:
            resp = requests.get(render_url, timeout=10)
            print(f"[KEEP-ALIVE] Ping {render_url} → {resp.status_code}")
        except Exception as e:
            print(f"[KEEP-ALIVE] Ping gagal: {e}")
        time.sleep(600)  # ping setiap 10 menit

NAMA_HARI = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]

def _ambil_weekly_config():
    """Ambil config ringkasan mingguan dari DB. Return (hari, jam_str, aktif)."""
    try:
        conn = connect_db(); cur = conn.cursor()
        cur.execute("SELECT hari, jam, aktif FROM yt_weekly_config WHERE id=1")
        row = cur.fetchone(); cur.close(); conn.close()
        if row:
            return row[0], row[1], row[2]
    except Exception as e:
        print(f"[YT WEEKLY CONFIG] {e}")
    return 0, "08:00", True  # default: Senin 08:00, aktif

def _simpan_weekly_config(hari=None, jam=None, aktif=None):
    """Simpan sebagian atau semua field config ringkasan mingguan."""
    try:
        conn = connect_db(); cur = conn.cursor()
        if hari is not None:
            cur.execute("UPDATE yt_weekly_config SET hari=%s WHERE id=1", (hari,))
        if jam is not None:
            cur.execute("UPDATE yt_weekly_config SET jam=%s WHERE id=1", (jam,))
        if aktif is not None:
            cur.execute("UPDATE yt_weekly_config SET aktif=%s WHERE id=1", (aktif,))
        conn.commit(); cur.close(); conn.close()
    except Exception as e:
        print(f"[YT WEEKLY CONFIG SAVE] {e}")

def _ambil_viral_threshold():
    """Ambil threshold % viral dari DB."""
    try:
        conn = connect_db(); cur = conn.cursor()
        cur.execute("SELECT viral_threshold_pct FROM yt_milestones WHERE id=1")
        row = cur.fetchone(); cur.close(); conn.close()
        return row[0] if row and row[0] else 50
    except Exception:
        return 50

def _simpan_viral_threshold(pct: int):
    """Simpan threshold % viral ke DB."""
    try:
        conn = connect_db(); cur = conn.cursor()
        cur.execute("UPDATE yt_milestones SET viral_threshold_pct=%s WHERE id=1", (pct,))
        conn.commit(); cur.close(); conn.close()
    except Exception as e:
        print(f"[YT VIRAL THRESHOLD] {e}")

def tampilkan_analitik_pertumbuhan(chat_id):
    """Tampilkan delta views/likes 1h, 24h, 7d untuk semua video."""
    try:
        conn = connect_db(); cur = conn.cursor()
        cur.execute("SELECT video_id, judul, views_last FROM youtube_videos ORDER BY views_last DESC")
        videos = cur.fetchall()
        if not videos:
            bot.send_message(chat_id, "📭 Belum ada video yang dimonitor.", parse_mode="HTML")
            cur.close(); conn.close(); return
        pesan = "📈 <b>ANALITIK PERTUMBUHAN VIDEO</b>\n\n"
        for (vid_id, judul, views_now) in videos:
            pesan += f"🎬 <b>{esc(judul or vid_id)}</b>\n"
            for label, jam in [("1j", 1), ("24j", 24), ("7h", 168)]:
                cur.execute("""
                    SELECT views FROM yt_views_history
                    WHERE video_id=%s AND dicatat_pada <= NOW() - (%s * INTERVAL '1 hour')
                    ORDER BY dicatat_pada DESC LIMIT 1
                """, (vid_id, jam))
                row = cur.fetchone()
                if row:
                    delta = views_now - row[0]
                    arrow = "📈" if delta > 0 else ("📉" if delta < 0 else "➡️")
                    pesan += f"   {arrow} +{delta:,} views ({label})\n"
                else:
                    pesan += f"   ⏳ Data {label} belum tersedia\n"
            pesan += "\n"
        cur.close(); conn.close()
        bot.send_message(chat_id, pesan, parse_mode="HTML", reply_markup=keyboard_youtube_monitor())
    except Exception as e:
        bot.send_message(chat_id, f"❌ Error analitik: {e}")

def generate_ide_dari_tren(chat_id):
    """Ambil video pertumbuhan tercepat 7 hari, generate ide konten serupa via Gemini."""
    try:
        conn = connect_db(); cur = conn.cursor()
        # Cari video dengan delta views terbesar dalam 7 hari
        cur.execute("""
            SELECT v.video_id, v.judul, v.views_last,
                   (v.views_last - COALESCE(h.views, v.views_last)) AS delta
            FROM youtube_videos v
            LEFT JOIN LATERAL (
                SELECT views FROM yt_views_history
                WHERE video_id = v.video_id AND dicatat_pada <= NOW() - INTERVAL '168 hours'
                ORDER BY dicatat_pada DESC LIMIT 1
            ) h ON TRUE
            ORDER BY delta DESC LIMIT 1
        """)
        row = cur.fetchone(); cur.close(); conn.close()
        if not row:
            bot.send_message(chat_id, "⏳ Data histori belum cukup (butuh minimal 7 hari). Coba lagi minggu depan!", parse_mode="HTML")
            return
        vid_id, judul, views_now, delta = row
        bot.send_message(chat_id,
            f"💡 <b>Generating ide dari video tren...</b>\n\n"
            f"🎬 Video terlaris: <b>{esc(judul or vid_id)}</b>\n"
            f"📈 +{delta:,} views dalam 7 hari\n\n"
            f"⏳ Sedang generate ide konten serupa...",
            parse_mode="HTML")
        tema = "konten video kreatif"
        prompt = (
            f"Kamu adalah asisten kreatif untuk konten YouTube.\n\n"
            f"Video tren saat ini berjudul: \"{judul or vid_id}\"\n"
            f"Video ini naik {delta:,} views dalam 7 hari terakhir.\n\n"
            f"Berikan 5 ide konten video baru yang serupa, unik, dan menarik. "
            f"Setiap ide harus berupa:\n"
            f"- Judul video yang catchy\n"
            f"- 1 kalimat konsep singkat\n"
            f"- 1 hook pembuka yang menarik perhatian di 3 detik pertama\n\n"
            f"Format dengan nomor. Gunakan bahasa yang natural dan energik."
        )
        result = generate_with_fallback(prompt)
        bot.send_message(chat_id,
            f"💡 <b>IDE KONTEN DARI VIDEO TREN</b>\n"
            f"<i>Berdasarkan: {esc(judul or vid_id)}</i>\n\n"
            f"{result}",
            parse_mode="HTML", reply_markup=keyboard_youtube_monitor())
    except Exception as e:
        bot.send_message(chat_id, f"❌ Error generate ide: {e}")

def export_laporan_csv(chat_id):
    """Generate CSV laporan semua video + histori views, kirim sebagai file."""
    import csv, io
    try:
        conn = connect_db(); cur = conn.cursor()
        cur.execute("SELECT video_id, judul, views_last, likes_last, tanggal_upload FROM youtube_videos ORDER BY views_last DESC")
        videos = cur.fetchall()
        if not videos:
            bot.send_message(chat_id, "📭 Belum ada video yang dimonitor.", parse_mode="HTML")
            cur.close(); conn.close(); return
        # Buat CSV di memory
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["video_id", "judul", "views_sekarang", "likes_sekarang", "tanggal_upload",
                         "delta_views_1j", "delta_views_24j", "delta_views_7h"])
        for (vid_id, judul, views_now, likes_now, tgl) in videos:
            deltas = []
            for jam in [1, 24, 168]:
                cur.execute("""
                    SELECT views FROM yt_views_history
                    WHERE video_id=%s AND dicatat_pada <= NOW() - (%s * INTERVAL '1 hour')
                    ORDER BY dicatat_pada DESC LIMIT 1
                """, (vid_id, jam))
                r = cur.fetchone()
                deltas.append(views_now - r[0] if r else "")
            writer.writerow([vid_id, judul or vid_id, views_now, likes_now, tgl] + deltas)
        # Tambah sheet histori lengkap
        writer.writerow([])
        writer.writerow(["=== HISTORI VIEWS (tiap jam) ==="])
        writer.writerow(["video_id", "judul", "waktu", "views", "likes"])
        cur.execute("""
            SELECT h.video_id, v.judul, h.dicatat_pada, h.views, h.likes
            FROM yt_views_history h
            JOIN youtube_videos v ON v.video_id = h.video_id
            ORDER BY h.video_id, h.dicatat_pada DESC
            LIMIT 1000
        """)
        for row in cur.fetchall():
            writer.writerow([row[0], row[1] or row[0], row[2].strftime("%Y-%m-%d %H:%M") if row[2] else "", row[3], row[4]])
        cur.close(); conn.close()
        # Kirim sebagai file
        csv_bytes = output.getvalue().encode("utf-8-sig")  # utf-8-sig agar Excel baca BOM
        tgl_str = datetime.now(WIB).strftime("%Y%m%d_%H%M")
        bio = io.BytesIO(csv_bytes)
        bio.name = "laporan_youtube_{}.csv".format(tgl_str)
        bot.send_document(chat_id, bio,
            caption=f"📊 Laporan YouTube Monitor — {datetime.now(WIB).strftime('%d %b %Y %H:%M WIB')}")
    except Exception as e:
        bot.send_message(chat_id, f"❌ Error export: {e}")

def _kirim_ringkasan_weekly(chat_id):
    """Kirim pesan ringkasan views/likes semua video."""
    try:
        token = _yt_access_token()
        conn = connect_db(); cur = conn.cursor()
        cur.execute("SELECT video_id, judul, views_last, likes_last FROM youtube_videos ORDER BY views_last DESC")
        rows = cur.fetchall(); cur.close(); conn.close()
        if not rows:
            return
        hari_cfg, jam_cfg, _ = _ambil_weekly_config()
        tgl = datetime.now(WIB).strftime("%d %b %Y")
        pesan = f"📊 <b>RINGKASAN MINGGUAN YOUTUBE</b>\n<i>{tgl} — {NAMA_HARI[hari_cfg]} {jam_cfg} WIB</i>\n\n"
        total_views = 0
        total_likes = 0
        for (vid_id, judul, views, likes) in rows:
            if token:
                stats = _yt_video_stats(vid_id, token)
                views = stats['views'] if stats else views
                likes = stats['likes'] if stats else likes
            total_views += views
            total_likes += likes
            pesan += (f"🎬 <b>{esc(judul or vid_id)}</b>\n"
                      f"   👁️ {views:,} views · 👍 {likes:,} likes\n\n")
        pesan += f"─────────────────\n"
        pesan += f"📈 Total: <b>{total_views:,} views</b> · <b>{total_likes:,} likes</b>"
        bot.send_message(chat_id, pesan, parse_mode="HTML", reply_markup=keyboard_youtube_monitor())
        print(f"[YT WEEKLY] Ringkasan terkirim ke {chat_id}")
    except Exception as e:
        print(f"[YT WEEKLY ERROR] {e}")

def run_weekly_summary():
    """
    Kirim ringkasan views/likes semua video sesuai jadwal yang disimpan di DB.
    Scheduler tidur 60 detik, cek waktu setiap menit.
    """
    if not all([YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN]):
        return
    print("[YT WEEKLY] Scheduler ringkasan mingguan aktif (cek tiap menit).")
    last_fired_date = None
    while True:
        time.sleep(60)
        try:
            hari_cfg, jam_cfg, aktif = _ambil_weekly_config()
            if not aktif:
                continue
            now = datetime.now(WIB)
            jam_parts = jam_cfg.split(":")
            jam_h = int(jam_parts[0]); jam_m = int(jam_parts[1]) if len(jam_parts) > 1 else 0
            # Cocokkan hari (weekday: 0=Senin) dan jam:menit
            if now.weekday() == hari_cfg and now.hour == jam_h and now.minute == jam_m:
                today = now.date()
                if last_fired_date == today:
                    continue  # sudah kirim hari ini
                last_fired_date = today
                chat_id = ambil_chat_id()
                if chat_id:
                    _kirim_ringkasan_weekly(chat_id)
        except Exception as e:
            print(f"[YT WEEKLY LOOP ERROR] {e}")

# Jalankan thread saat diimport Gunicorn maupun dijalankan langsung
_start_threads()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)