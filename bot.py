import logging
import sqlite3
import os
import urllib.parse
import pg8000.dbapi
from datetime import datetime
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardRemove,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
    ContextTypes,
)

# ─── SOZLAMALAR ────────────────────────────────────────────────────────────────
BOT_TOKEN = "8841015797:AAGyauWuYzItmfRfy7QwUSj0PCw1WKSyVPo"
ADMIN_IDS = [8175344606, 5611922080, 1277637813]
# Alohida tasdiqlash boti tokeni (Logistik_tasdiqlash_bot)
ADMIN_BOT_TOKEN = "8939855367:AAEWex_skRAjKhHQbD95R3E6COp6Q6AQkLQ"

PAYMENT_CARD = "9860 0801 9212 8785"
PAYMENT_AMOUNT = 50_000

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─── CONVERSATION STATES ───────────────────────────────────────────────────────
(
    MAIN_MENU,             # 1
    EMPLOYER_NAME,         # 2
    EMPLOYER_PHONE,        # 3
    WORKER_NAME,           # 4
    WORKER_PHONE,          # 5
    SEARCH_CARGO,          # 6
    AWAIT_PAYMENT,         # 7
    AWAIT_PAYMENT_CONFIRM, # 8
    EDIT_MENU,             # 9
    EDIT_NAME,             # 10
    EDIT_PHONE,            # 11
    EMPLOYER_CARGO,        # 12
    WORKER_CARGO,          # 13
    EDIT_CARGO,            # 14  — yuk turini tahrirlash
    ADD_ORDER_CARGO,       # 15  — qo'shimcha buyurtma qo'shish (yuk turi)
    EDIT_ROLE,             # 16  — rolni tahrirlash
    BUG_REPORT,            # 17  — bot xatoliklarini yozish
    BUG_REPORT_CONFIRM,    # 18  — bot xatoliklarini yuborishni tasdiqlash
) = range(1, 19)

# ─── DATABASE ──────────────────────────────────────────────────────────────────
DB_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:kMhzsVPUhELJnKadPEDacSVCMxcegXWz@postgres.railway.internal:5432/railway")

def get_db_connection():
    if DB_URL:
        # Parse URL for pg8000
        url = urllib.parse.urlparse(DB_URL)
        return pg8000.dbapi.connect(
            user=url.username,
            password=url.password,
            host=url.hostname,
            port=url.port or 5432,
            database=url.path[1:]
        )
    return sqlite3.connect("logistics.db")

def run_query(query, params=(), fetch=None, fetchall=False, return_id=False):
    conn = get_db_connection()
    c = conn.cursor()
    
    # SQLite uses ?, PostgreSQL uses %s
    if DB_URL:
        query = query.replace("?", "%s")
        # PostgreSQL AUTOINCREMENT logic for returning ID
        if return_id and "INSERT" in query:
            query += " RETURNING id"
            
    try:
        c.execute(query, params)
        result = None
        if fetch:
            result = c.fetchone()
        elif fetchall:
            result = c.fetchall()
        elif return_id:
            if DB_URL:
                result = c.fetchone()[0]
            else:
                result = c.lastrowid
        conn.commit()
    finally:
        c.close()
        conn.close()
    
    return result

def init_db():
    if DB_URL:
        # PostgreSQL schema
        run_query("""
            CREATE TABLE IF NOT EXISTS users (
                user_id     BIGINT PRIMARY KEY,
                username    VARCHAR(255),
                full_name   VARCHAR(255),
                phone       VARCHAR(50),
                role        VARCHAR(50),
                created_at  VARCHAR(50),
                updated_at  VARCHAR(50)
            )
        """)
        try:
            run_query("ALTER TABLE users ADD COLUMN cargo_type VARCHAR(255)")
        except Exception:
            pass
        try:
            run_query("ALTER TABLE users ADD COLUMN free_limits INTEGER DEFAULT 0")
        except Exception:
            pass
        run_query("""
            CREATE TABLE IF NOT EXISTS payments (
                id              SERIAL PRIMARY KEY,
                payer_id        BIGINT,
                target_id       BIGINT,
                amount          INTEGER,
                card_holder     VARCHAR(255),
                status          VARCHAR(50) DEFAULT 'pending',
                created_at      VARCHAR(50),
                payer_no_vote   INTEGER DEFAULT 0,
                target_no_vote  INTEGER DEFAULT 0
            )
        """)
        try:
            run_query("ALTER TABLE payments ADD COLUMN payer_no_vote INTEGER DEFAULT 0")
        except Exception:
            pass
        try:
            run_query("ALTER TABLE payments ADD COLUMN target_no_vote INTEGER DEFAULT 0")
        except Exception:
            pass
        run_query("""
            CREATE TABLE IF NOT EXISTS wait_list (
                id          SERIAL PRIMARY KEY,
                user_id     BIGINT,
                target_role VARCHAR(50),
                cargo_type  VARCHAR(255),
                created_at  VARCHAR(50)
            )
        """)
    else:
        # SQLite schema
        run_query("""
            CREATE TABLE IF NOT EXISTS users (
                user_id     INTEGER PRIMARY KEY,
                username    TEXT,
                full_name   TEXT,
                phone       TEXT,
                role        TEXT,
                created_at  TEXT,
                updated_at  TEXT
            )
        """)
        try:
            run_query("ALTER TABLE users ADD COLUMN cargo_type TEXT")
        except Exception:
            pass
        try:
            run_query("ALTER TABLE users ADD COLUMN free_limits INTEGER DEFAULT 0")
        except Exception:
            pass
        run_query("""
            CREATE TABLE IF NOT EXISTS payments (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                payer_id        INTEGER,
                target_id       INTEGER,
                amount          INTEGER,
                card_holder     TEXT,
                status          TEXT DEFAULT 'pending',
                created_at      TEXT,
                payer_no_vote   INTEGER DEFAULT 0,
                target_no_vote  INTEGER DEFAULT 0
            )
        """)
        try:
            run_query("ALTER TABLE payments ADD COLUMN payer_no_vote INTEGER DEFAULT 0")
        except Exception:
            pass
        try:
            run_query("ALTER TABLE payments ADD COLUMN target_no_vote INTEGER DEFAULT 0")
        except Exception:
            pass
        run_query("""
            CREATE TABLE IF NOT EXISTS wait_list (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER,
                target_role TEXT,
                cargo_type  TEXT,
                created_at  TEXT
            )
        """)


def upsert_user(user_id, username, full_name, phone, role, cargo_type):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    row = run_query("SELECT user_id FROM users WHERE user_id = ?", (user_id,), fetch=True)
    
    if row:
        run_query("""
            UPDATE users SET username=?, full_name=?, phone=?, role=?, cargo_type=?, updated_at=?
            WHERE user_id=?
        """, (username, full_name, phone, role, cargo_type, now, user_id))
    else:
        run_query("""
            INSERT INTO users (user_id, username, full_name, phone, role, cargo_type, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?)
        """, (user_id, username, full_name, phone, role, cargo_type, now, now))


def get_user(user_id):
    row = run_query("SELECT user_id, username, full_name, phone, role, created_at, updated_at, cargo_type FROM users WHERE user_id = ?", (user_id,), fetch=True)
    if row:
        cols = ["user_id", "username", "full_name", "phone", "role", "created_at", "updated_at", "cargo_type"]
        return dict(zip(cols, row))
    return None


def get_total_users(role):
    opposite = "worker" if role == "employer" else "employer"
    row = run_query("SELECT COUNT(*) FROM users WHERE role=?", (opposite,), fetch=True)
    return row[0] if row else 0


def search_opposite(role, cargo_type):
    opposite = "worker" if role == "employer" else "employer"
    rows = run_query("""
        SELECT user_id, full_name, phone, username, cargo_type
        FROM users WHERE role=? AND cargo_type=?
        ORDER BY updated_at DESC LIMIT 10
    """, (opposite, cargo_type), fetchall=True)
    return rows


def save_payment(payer_id, target_id, amount, card_holder):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    pay_id = run_query("""
        INSERT INTO payments (payer_id, target_id, amount, card_holder, status, created_at)
        VALUES (?,?,?,?,'pending',?)
    """, (payer_id, target_id, amount, card_holder, now), return_id=True)
    return pay_id


def confirm_payment(pay_id):
    run_query("UPDATE payments SET status='confirmed' WHERE id=?", (pay_id,))


def get_payment(pay_id):
    row = run_query("SELECT * FROM payments WHERE id=?", (pay_id,), fetch=True)
    if row:
        cols = ["id", "payer_id", "target_id", "amount", "card_holder", "status", "created_at", "payer_no_vote", "target_no_vote"]
        return dict(zip(cols, row))
    return None


def set_no_vote(pay_id, who):
    """who: 'payer' yoki 'target'"""
    if who == "payer":
        run_query("UPDATE payments SET payer_no_vote=1 WHERE id=?", (pay_id,))
    else:
        run_query("UPDATE payments SET target_no_vote=1 WHERE id=?", (pay_id,))


def update_user_field(user_id, field, value):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # field is safe because we only use it for 'full_name' or 'phone' internally
    run_query(f"UPDATE users SET {field}=?, updated_at=? WHERE user_id=?", (value, now, user_id))


def delete_user_order(user_id):
    """Foydalanuvchi buyurtmasini (users va wait_list) o'chiradi."""
    run_query("DELETE FROM users WHERE user_id=?", (user_id,))
    run_query("DELETE FROM wait_list WHERE user_id=?", (user_id,))


def get_free_limits(user_id):
    row = run_query("SELECT free_limits FROM users WHERE user_id=?", (user_id,), fetch=True)
    return row[0] if row else 0


def use_free_limit(user_id):
    """Limitni 1 taga kamaytiradi."""
    run_query("UPDATE users SET free_limits = free_limits - 1 WHERE user_id=?", (user_id,))


def add_free_limit(user_id):
    """Limitni 1 taga oshiradi."""
    run_query("UPDATE users SET free_limits = free_limits + 1 WHERE user_id=?", (user_id,))


async def notify_waitlist(context: ContextTypes.DEFAULT_TYPE, new_user_role: str, cargo_type: str):
    rows = run_query("SELECT id, user_id FROM wait_list WHERE target_role=? AND cargo_type=?", (new_user_role, cargo_type), fetchall=True)
    if not rows:
        return
    
    new_label = "📦 Buyurtma beruvchi (Shipper)" if new_user_role == "employer" else "🚚 Buyurtma oluvchi (Haydovchi)"
    search_label = "Buyurtma oluvchini qidirish" if new_user_role == "worker" else "Buyurtma beruvchini qidirish"
    
    for row in rows:
        wait_id, user_id = row
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    f"🔔 *Xushxabar!*\n\n"
                    f"Siz qidirgan *{cargo_type}* yuk turi bo'yicha yangi *{new_label}* botda ro'yxatdan o'tdi!\n\n"
                    f"Uni hoziroq topish uchun quyidagi tugmani bosing 👇\n"
                    f"➡️ *\"🔍 {search_label}\"*"
                ),
                parse_mode="Markdown"
            )
            run_query("DELETE FROM wait_list WHERE id=?", (wait_id,))
        except Exception as e:
            logger.error(f"Waitlist xabarini yuborishda xatolik: {e}")


# ─── KLAVIATURALAR ─────────────────────────────────────────────────────────────
def main_menu_keyboard():
    return ReplyKeyboardMarkup(
        [[KeyboardButton("📦 Buyurtma berish"), KeyboardButton("🚚 Buyurtma olish")]],
        resize_keyboard=True,
    )


def after_register_keyboard(role):
    search_btn = "🔍 Buyurtma oluvchini qidirish" if role == "employer" else "🔍 Buyurtma beruvchini qidirish"
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(search_btn)],
            [KeyboardButton("➕ Buyurtma qo'shish"), KeyboardButton("✏️ Ma'lumotlarni tahrirlash")],
            [KeyboardButton("🐛 Bot xatoliklari")],
        ],
        resize_keyboard=True,
    )


def cargo_types_keyboard():
    cargos = [
        "1: Meva-sabzavot va oziq-ovqatlar (Muzlatgichli trucklar)",
        "2: Tekstil va to'qimachilik mahsulotlari (Yopiq tentli trucklar)",
        "3: Qurilish materiallari (Ochiq va yopiq trucklar)",
        "4: Xo'jalik va kundalik iste'mol mollari (FMCG)",
        "5: Maishiy texnika va elektronika (Yopiq va quruq trucklar)",
        "6: Avtomobillar va ehtiyot qismlar (Avtovozlar va furalar)",
        "7: Sanoat xomashyosi (Maxsus trucklar)",
        "8: Stanoklar va og'ir texnikalar (Trallar)"
    ]
    keyboard = [[KeyboardButton(cargo)] for cargo in cargos]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


# ─── /START ────────────────────────────────────────────────────────────────────
async def force_approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    
    # ... logic here ...
    # (Simplified for example, ensure ADMIN_IDS loops are implemented in relevant pay functions)
    pass


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    existing = get_user(user.id)

    welcome = (
        f"🌟 *LogiConnect Botiga Xush Kelibsiz!* 🌟\n\n"
        f"Salom, *{user.first_name}*! 👋\n\n"
        f"Men logistika sohasidagi *buyurtma beruvchilar* va *buyurtma oluvchilar* o'rtasidagi "
        f"muloqotni osonlashtiruvchi raqamli broker botman.\n\n"
        f"✅ Buyurtma beruvchi va oluvchilarni ulashaman\n"
        f"✅ Tez va qulay qidirish\n"
        f"✅ Ma'lumotlar xavfsiz saqlanadi\n\n"
        f"Quyidan o'zingizga kerakli bo'limni tanlang 👇"
    )

    if existing:
        role_label = "Buyurtma beruvchi" if existing["role"] == "employer" else "Buyurtma oluvchi"
        welcome += f"\n\n_(Siz avval *{role_label}* sifatida ro'yxatdan o'tgansiz)_"
        await update.message.reply_text(
            welcome,
            reply_markup=after_register_keyboard(existing["role"]),
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(
            welcome,
            reply_markup=main_menu_keyboard(),
            parse_mode="Markdown",
        )
    return MAIN_MENU


# ─── BOSH MENYU ────────────────────────────────────────────────────────────────
async def main_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if "Buyurtma berish" in text:
        await update.message.reply_text(
            "📝 *Buyurtma berish bo'limi*\n\nBir nechta savol beramiz.\n\n"
            "1️⃣ Ismingiz va familiyangizni kiriting:",
            reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🔙 Orqaga")]], resize_keyboard=True),
            parse_mode="Markdown",
        )
        return EMPLOYER_NAME

    elif "Buyurtma olish" in text:
        await update.message.reply_text(
            "📝 *Buyurtma olish bo'limi*\n\nBir nechta savol beramiz.\n\n"
            "1️⃣ Ismingiz va familiyangizni kiriting:",
            reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🔙 Orqaga")]], resize_keyboard=True),
            parse_mode="Markdown",
        )
        return WORKER_NAME

    elif "qidirish" in text:
        u = get_user(update.effective_user.id)
        if not u:
            await update.message.reply_text("❌ Siz hali ro'yxatdan o'tmagansiz. /start bosing.")
            return MAIN_MENU
            
        context.user_data["searching_as"] = u["role"]
        total_count = get_total_users(u["role"])
        opposite_label = "buyurtma oluvchi (haydovchi)" if u["role"] == "employer" else "buyurtma beruvchi (shipper)"
        
        await update.message.reply_text(
            f"📊 *Ma'lumot:* Hozirda botda jami *{total_count}* ta {opposite_label} bor.\n\n"
            "Qaysi turdagi yuk bo'yicha qidiryapsiz? Quydagi menyudan tanlang 👇",
            parse_mode="Markdown",
            reply_markup=cargo_types_keyboard(),
        )
        return SEARCH_CARGO

    elif "Buyurtma qo'shish" in text:
        u = get_user(update.effective_user.id)
        if not u:
            await update.message.reply_text("❌ Siz hali ro'yxatdan o'tmagansiz. /start bosing.")
            return MAIN_MENU
        opposite_label = "buyurtma oluvchi (haydovchi)" if u["role"] == "employer" else "buyurtma beruvchi (shipper)"
        await update.message.reply_text(
            f"➕ *Qo'shimcha buyurtma qo'shish*\n\n"
            f"Yangi qaysi turdagi yuk bo'yicha *{opposite_label}* qidirmoqchisiz?\n"
            "Quyidagi menyudan tanlang 👇",
            parse_mode="Markdown",
            reply_markup=cargo_types_keyboard(),
        )
        return ADD_ORDER_CARGO

    elif "Bot xatoliklari" in text:
        u = get_user(update.effective_user.id)
        if not u:
            await update.message.reply_text("❌ Siz hali ro'yxatdan o'tmagansiz. Avval ro'yxatdan o'tish uchun /start buyrug'ini bosing.")
            return MAIN_MENU
        await update.message.reply_text(
            "🐛 *Bot xatoliklari bo'limi*\n\n"
            "Botdan foydalanishda qanday muammo, bag yoki xatoliklarga duch keldingiz? "
            "Iltimos, ularni batafsil yozib yuboring.\n\n"
            "Ortga qaytish uchun 🔙 Orqaga tugmasini bosing.",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🔙 Orqaga")]], resize_keyboard=True)
        )
        return BUG_REPORT

    elif "tahrirlash" in text:
        u = get_user(update.effective_user.id)
        if not u:
            await update.message.reply_text("❌ Siz hali ro'yxatdan o'tmagansiz.")
            return MAIN_MENU
        role_label = "📦 Buyurtma beruvchi" if u["role"] == "employer" else "🚚 Buyurtma oluvchi"
        await update.message.reply_text(
            f"✏️ *Ma'lumotlarni tahrirlash*\n\n"
            f"👤 Ism: {u['full_name']}\n"
            f"📞 Telefon: {u['phone']}\n"
            f"🏷️ Rol: {role_label}\n"
            f"📦 Yuk turi: {u.get('cargo_type', 'Kiritilmagan')}\n\n"
            "Nimani tahrirlashni istaysiz?",
            reply_markup=ReplyKeyboardMarkup(
                [
                    [KeyboardButton("✏️ Ism/Familiya"), KeyboardButton("📞 Telefon")],
                    [KeyboardButton("🏷️ Rolni o'zgartirish"), KeyboardButton("📦 Yuk turi")],
                    [KeyboardButton("🔙 Orqaga")],
                ],
                resize_keyboard=True,
            ),
            parse_mode="Markdown",
        )
        return EDIT_MENU

    elif "Bosh menyu" in text:
        await update.message.reply_text("🏠 Bosh menyuga qaytdingiz:", reply_markup=main_menu_keyboard())
        return MAIN_MENU

    else:
        await update.message.reply_text(
            "⬇️ Iltimos, quyidagi tugmalardan birini tanlang:",
            reply_markup=main_menu_keyboard(),
        )
        return MAIN_MENU


async def search_cargo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cargo_type = update.message.text.strip()

    # Orqaga tugmasi
    if "Orqaga" in cargo_type:
        u = get_user(update.effective_user.id)
        kb = after_register_keyboard(u["role"]) if u else main_menu_keyboard()
        await update.message.reply_text("🔙 Orqaga qaytdingiz.", reply_markup=kb)
        return MAIN_MENU

    u = get_user(update.effective_user.id)
    if not u:
        await update.message.reply_text("❌ Siz hali ro'yxatdan o'tmagansiz. /start bosing.")
        return MAIN_MENU

    results = search_opposite(u["role"], cargo_type)
    opposite_label = "Buyurtma oluvchi (haydovchi)" if u["role"] == "employer" else "Buyurtma beruvchi (shipper)"
    opposite_label_short = "buyurtma oluvchi" if u["role"] == "employer" else "buyurtma beruvchi"

    if not results:
        target_role = "worker" if u["role"] == "employer" else "employer"
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        existing_wait = run_query(
            "SELECT id FROM wait_list WHERE user_id=? AND target_role=? AND cargo_type=?",
            (u["user_id"], target_role, cargo_type), fetch=True
        )
        if not existing_wait:
            run_query(
                "INSERT INTO wait_list (user_id, target_role, cargo_type, created_at) VALUES (?,?,?,?)",
                (u["user_id"], target_role, cargo_type, now)
            )
        await update.message.reply_text(
            f"😔 Hozirda *{cargo_type}* turdagi yuk bo'yicha hech qanday *{opposite_label}* topilmadi.\n\n"
            f"✅ *Xavotir olmang!* Biz sizni ro'yxatga qo'shib qo'ydik.\n"
            f"Siz qidirgandek *{opposite_label_short}* botda ro'yxatdan o'tishi bilanoq sizga darhol xabar beramiz! 🔔",
            parse_mode="Markdown",
            reply_markup=after_register_keyboard(u["role"]),
        )
        return MAIN_MENU

    # Topildi
    target = results[0]
    target_id = target[0]
    context.user_data["target_id"] = target_id
    context.user_data["target_cargo"] = cargo_type
    context.user_data["searching_as"] = u["role"]

    # ── Bepul limit bormi? ──
    free = get_free_limits(u["user_id"])
    if free > 0:
        use_free_limit(u["user_id"])
        target_user = get_user(target_id)
        if target_user:
            uname = f"@{target_user['username']}" if target_user.get("username") else "Telegram username yo'q"
            await update.message.reply_text(
                f"🎁 *Sizda bepul limit bor edi — foydalandingiz!*\n\n"
                f"🎉 *{opposite_label} ma'lumotlari:*\n\n"
                f"👤 Ism: *{target_user['full_name']}*\n"
                f"📞 Telefon: `{target_user['phone']}`\n"
                f"📦 Yuk turi: {target_user.get('cargo_type', 'Kiritilmagan')}\n"
                f"🔗 Telegram: {uname}\n\n"
                f"Muvaffaqiyatli hamkorlik tilaymiz! 🤝",
                parse_mode="Markdown",
                reply_markup=after_register_keyboard(u["role"]),
            )
        else:
            await update.message.reply_text("❌ Foydalanuvchi topilmadi.", reply_markup=after_register_keyboard(u["role"]))
        return MAIN_MENU

    # To'lov talab qilamiz
    await update.message.reply_text(
        f"✅ *{cargo_type} bo'yicha {opposite_label} topildi!*\n\n"
        f"Uning to'liq ma'lumotlarini olish uchun botga to'lov qiling.\n\n"
        f"💳 *To'lov miqdori:* {PAYMENT_AMOUNT:,} UZS\n"
        f"💳 *Karta raqami:* `{PAYMENT_CARD}`\n\n"
        f"❗ *Iltimos:*\n"
        f"1. Yuqoridagi kartaga *naqd {PAYMENT_AMOUNT:,} UZS* o'tkazing\n"
        f"2. To'lovni amalga oshirgach, quyida *karta raqamingizda yozilgan ism va familiyangizni* yozing\n\n"
        f"_(Masalan: Alisher Karimov)_",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )
    return AWAIT_PAYMENT

# ═══ BUYURTMA BERISH (EMPLOYER) ═════════════════════════════════════════════════════
async def employer_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if "Orqaga" in text:
        u = get_user(update.effective_user.id)
        kb = after_register_keyboard(u["role"]) if u else main_menu_keyboard()
        await update.message.reply_text("🔙 Orqaga qaytdingiz.", reply_markup=kb)
        return MAIN_MENU
    context.user_data["emp_name"] = text
    await update.message.reply_text(
        "2️⃣ Telefon raqamingizni kiriting (masalan: +998901234567):",
        reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🔙 Orqaga")]], resize_keyboard=True),
    )
    return EMPLOYER_PHONE


async def employer_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if "Orqaga" in text:
        u = get_user(update.effective_user.id)
        kb = after_register_keyboard(u["role"]) if u else main_menu_keyboard()
        await update.message.reply_text("🔙 Orqaga qaytdingiz.", reply_markup=kb)
        return MAIN_MENU
    context.user_data["emp_phone"] = text
    await update.message.reply_text(
        "3️⃣ Asosan qaysi turdagi yuklarni berasiz? (Quyidagilardan birini tanlang):",
        reply_markup=cargo_types_keyboard(),
    )
    return EMPLOYER_CARGO


async def employer_cargo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cargo_type = update.message.text.strip()
    user = update.effective_user
    name = context.user_data.get("emp_name", "Noma'lum")
    phone = context.user_data.get("emp_phone", "Noma'lum")
    
    upsert_user(user.id, user.username, name, phone, "employer", cargo_type)
    await notify_waitlist(context, "employer", cargo_type)
    await update.message.reply_text(
        "✅ *Tabriklaymiz! Muvaffaqiyatli ro'yxatdan o'tdingiz!*\n\n"
        f"👤 Ism: {name}\n"
        f"📞 Telefon: {phone}\n"
        f"🏷️ Rol: 📦 Buyurtma beruvchi\n"
        f"📦 Yuk turi: {cargo_type}\n\n"
        "Endi buyurtma oluvchini (haydovchini) qidirish yoki boshqa amallarni bajarishingiz mumkin 👇",
        reply_markup=after_register_keyboard("employer"),
        parse_mode="Markdown",
    )
    return MAIN_MENU


# ═══ BUYURTMA OLISH (WORKER) ════════════════════════════════════════════════════════
async def worker_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if "Orqaga" in text:
        u = get_user(update.effective_user.id)
        kb = after_register_keyboard(u["role"]) if u else main_menu_keyboard()
        await update.message.reply_text("🔙 Orqaga qaytdingiz.", reply_markup=kb)
        return MAIN_MENU
    context.user_data["wrk_name"] = text
    await update.message.reply_text(
        "2️⃣ Telefon raqamingizni kiriting (masalan: +998901234567):",
        reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🔙 Orqaga")]], resize_keyboard=True),
    )
    return WORKER_PHONE


async def worker_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if "Orqaga" in text:
        u = get_user(update.effective_user.id)
        kb = after_register_keyboard(u["role"]) if u else main_menu_keyboard()
        await update.message.reply_text("🔙 Orqaga qaytdingiz.", reply_markup=kb)
        return MAIN_MENU
    context.user_data["wrk_phone"] = text
    await update.message.reply_text(
        "3️⃣ Asosan qaysi turdagi yuklarni yetkazib berasiz? (Quyidagilardan birini tanlang):",
        reply_markup=cargo_types_keyboard(),
    )
    return WORKER_CARGO


async def worker_cargo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cargo_type = update.message.text.strip()
    user = update.effective_user
    name = context.user_data.get("wrk_name", "Noma'lum")
    phone = context.user_data.get("wrk_phone", "Noma'lum")
    
    upsert_user(user.id, user.username, name, phone, "worker", cargo_type)
    await notify_waitlist(context, "worker", cargo_type)
    await update.message.reply_text(
        "✅ *Tabriklaymiz! Muvaffaqiyatli ro'yxatdan o'tdingiz!*\n\n"
        f"👤 Ism: {name}\n"
        f"📞 Telefon: {phone}\n"
        f"🏷️ Rol: 🚚 Buyurtma oluvchi\n"
        f"📦 Yuk turi: {cargo_type}\n\n"
        "Endi buyurtma beruvchini (shipper) qidirish yoki boshqa amallarni bajarishingiz mumkin 👇",
        reply_markup=after_register_keyboard("worker"),
        parse_mode="Markdown",
    )
    return MAIN_MENU


# ═══ TO'LOV KUTISH ══════════════════════════════════════════════════════════════
async def await_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    card_holder = update.message.text.strip()
    payer_id = update.effective_user.id
    target_id = context.user_data.get("target_id")
    role = context.user_data.get("searching_as", "employer")

    if not target_id:
        await update.message.reply_text("❌ Xatolik yuz berdi. /start bosing.")
        return MAIN_MENU

    pay_id = save_payment(payer_id, target_id, PAYMENT_AMOUNT, card_holder)
    context.user_data["pay_id"] = pay_id

    payer = get_user(payer_id)
    payer_name = payer["full_name"] if payer else "Noma'lum"
    payer_phone = payer["phone"] if payer else "Noma'lum"

    # Tasdiqlash botiga (Logistik_tasdiqlash_bot) yoki oddiy admin ga xabar yuborish
    confirm_btn = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"pay_ok|{pay_id}"),
            InlineKeyboardButton("❌ Rad etish", callback_data=f"pay_no|{pay_id}"),
        ]
    ])
    opposite_label = "Buyurtma oluvchi" if role == "employer" else "Buyurtma beruvchi"
    target_cargo = context.user_data.get("target_cargo", "Noma'lum")
    payment_text = (
        f"💰 *Yangi to'lov so'rovi!*\n\n"
        f"📋 To'lov ID: #{pay_id}\n"
        f"👤 To'lovchi: {payer_name}\n"
        f"📞 Telefon: {payer_phone}\n"
        f"💳 Karta egasi (to'lovchi ko'rsatgan): {card_holder}\n"
        f"💵 Miqdor: {PAYMENT_AMOUNT:,} UZS\n"
        f"🔍 Qidirilgan: {opposite_label} ({target_cargo})\n\n"
        f"Kartangizda ushbu ismdan {PAYMENT_AMOUNT:,} UZS tushganini tekshiring va tasdiqlang."
    )

    if ADMIN_BOT_TOKEN:
        # Alohida Logistik_tasdiqlash_bot ga yuboramiz
        try:
            from telegram import Bot as TgBot
            admin_bot = TgBot(token=ADMIN_BOT_TOKEN)
            for admin_id in ADMIN_IDS:
                try:
                    await admin_bot.send_message(
                        chat_id=admin_id,
                        text=payment_text,
                        parse_mode="Markdown",
                        reply_markup=confirm_btn,
                    )
                except Exception as e:
                    logger.error(f"Tasdiqlash botiga xabar yuborishda xatolik ({admin_id}): {e}")
        except Exception as e:
            logger.error(f"Admin bot ulanishida xatolik: {e}")
    else:
        # Agar admin bot tokeni yo'q bo'lsa, asosiy bot orqali adminlarga yuboramiz
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=payment_text,
                    parse_mode="Markdown",
                    reply_markup=confirm_btn,
                )
            except Exception as e:
                logger.error(f"Admin ga xabar yuborishda xatolik ({admin_id}): {e}")

    await update.message.reply_text(
        "⏳ *To'lovingiz tekshirilmoqda...*\n\n"
        f"👤 Ism familiya (siz ko'rsatgan): *{card_holder}*\n"
        f"💳 Karta: `{PAYMENT_CARD}`\n"
        f"💵 Miqdor: {PAYMENT_AMOUNT:,} UZS\n\n"
        "Admin to'lovni tasdiqlash bilanoq sizga ma'lumot yuboriladi. "
        "Odatda bu 5-15 daqiqa ichida bo'ladi. ⏰",
        parse_mode="Markdown",
        reply_markup=after_register_keyboard(role),
    )
    return MAIN_MENU


# ═══ ADMIN TO'LOV TASDIQLASH ════════════════════════════════════════════════════
async def admin_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if update.effective_user.id != ADMIN_ID:
        await query.answer("❌ Sizda ruxsat yo'q!", show_alert=True)
        return

    parts = query.data.split("|")
    action = parts[0]
    pay_id = int(parts[1])

    payment = get_payment(pay_id)
    if not payment:
        await query.edit_message_text("❌ To'lov topilmadi.")
        return

    payer_id = payment["payer_id"]
    target_id = payment["target_id"]

    if action == "pay_ok":
        confirm_payment(pay_id)
        target = get_user(target_id)
        payer = get_user(payer_id)

        if target:
            role = payer["role"] if payer else "employer"
            opposite_label = "Buyurtma oluvchi (Haydovchi)" if role == "employer" else "Buyurtma beruvchi (Shipper)"
            uname = f"@{target['username']}" if target.get("username") else "Telegram username yo'q"

            # To'lovchi (payer) ga ma'lumot yuboramiz
            msg = (
                f"✅ *To'lovingiz tasdiqlandi!*\n\n"
                f"🎉 *{opposite_label} ma'lumotlari:*\n\n"
                f"👤 Ism: *{target['full_name']}*\n"
                f"📞 Telefon: `{target['phone']}`\n"
                f"📦 Yuk turi: {target.get('cargo_type', 'Kiritilmagan')}\n"
                f"🔗 Telegram: {uname}\n\n"
                f"Muvaffaqiyatli hamkorlik tilaymiz! 🤝"
            )
            await context.bot.send_message(chat_id=payer_id, text=msg, parse_mode="Markdown")

            # === IKKala foydalanuvchidan ishni tugatganini so'raymiz ===
            # Payer ga savol
            payer_role_label = "buyurtmachi" if role == "employer" else "buyurtma oluvchi"
            target_role_label = "buyurtma oluvchi" if role == "employer" else "buyurtmachi"

            finish_keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Ha, tugatdim", callback_data=f"finish_yes|{pay_id}|payer"),
                    InlineKeyboardButton("❌ Yo'q, hali yo'q", callback_data=f"finish_no|{pay_id}|payer"),
                ]
            ])
            await context.bot.send_message(
                chat_id=payer_id,
                text=(
                    f"❓ *Savol:*\n\n"
                    f"Siz ushbu *{target_role_label}* bilan bog'lanib, ishingizni tugatdingizmi?\n\n"
                    f"_(Agar 'Ha' deb javob bersangiz, sizning buyurtmangiz bazadan o'chiriladi, "
                    f"chunki siz hamkorni topib bo'ldingiz va boshqalar sizga keraksiz qo'ng'iroq qilmasligi uchun.)_"
                ),
                parse_mode="Markdown",
                reply_markup=finish_keyboard,
            )

            # Target ga savol
            finish_keyboard_target = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Ha, tugatdim", callback_data=f"finish_yes|{pay_id}|target"),
                    InlineKeyboardButton("❌ Yo'q, hali yo'q", callback_data=f"finish_no|{pay_id}|target"),
                ]
            ])
            try:
                await context.bot.send_message(
                    chat_id=target_id,
                    text=(
                        f"🎉 *Tabriklaymiz!*\n\n"
                        f"Sizning ma'lumotlaringiz yangi hamkorga yuborildi.\n\n"
                        f"❓ *Savol:*\n"
                        f"Siz ushbu *{payer_role_label}* bilan bog'lanib, ishingizni tugatdingizmi?\n\n"
                        f"_(Agar 'Ha' deb javob bersangiz, sizning buyurtmangiz bazadan o'chiriladi, "
                        f"chunki siz hamkorni topib bo'ldingiz va boshqalar sizga bezovta qo'ng'iroq qilmasligi uchun.)_"
                    ),
                    parse_mode="Markdown",
                    reply_markup=finish_keyboard_target,
                )
            except Exception as e:
                logger.error(f"Target ga savol yuborishda xatolik: {e}")

            await query.edit_message_text(
                f"✅ To'lov #{pay_id} tasdiqlandi va ikkala foydalanuvchiga ma'lumot yuborildi.\n"
                f"Endi ulardan ishni tugatganliklarini tasdiqlaslari so'ralmoqda."
            )
        else:
            await context.bot.send_message(
                chat_id=payer_id,
                text="❌ Kechirasiz, qidirilgan foydalanuvchi topilmadi. Admin bilan bog'laning."
            )
            await query.edit_message_text(f"⚠️ To'lov #{pay_id} tasdiqlandi, lekin target foydalanuvchi topilmadi.")

    elif action == "pay_no":
        await context.bot.send_message(
            chat_id=payer_id,
            text=(
                "❌ *To'lovingiz tasdiqlanmadi.*\n\n"
                "Sabab: Karta raqamida ko'rsatilgan ism familiya yoki to'lov miqdori noto'g'ri bo'lishi mumkin.\n\n"
                "Iltimos, to'g'ri ma'lumotlar bilan qayta urinib ko'ring yoki admin bilan bog'laning."
            ),
            parse_mode="Markdown",
        )
        await query.edit_message_text(f"❌ To'lov #{pay_id} rad etildi.")


# ═══ ISH TUGATISH: HA / YO'Q ═════════════════════════════════════════════════════
async def finish_yes_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    parts = query.data.split("|")
    pay_id = int(parts[1])
    who = parts[2]  # payer yoki target

    payment = get_payment(pay_id)
    if not payment:
        await query.edit_message_text("❌ To'lov ma'lumoti topilmadi.")
        return

    payer_id = payment["payer_id"]
    target_id = payment["target_id"]

    delete_uid = payer_id if who == "payer" else target_id
    user_data_row = get_user(delete_uid)

    if not user_data_row:
        await query.edit_message_text("ℹ️ Sizning buyurtmangiz allaqachon o'chirilgan yoki topilmadi.")
        return

    name  = user_data_row.get("full_name", "Noma'lum")
    phone = user_data_row.get("phone", "Noma'lum")
    cargo = user_data_row.get("cargo_type", "Kiritilmagan")

    confirm_kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Ha, o'chiring", callback_data=f"del_confirm|{pay_id}|{who}"),
        InlineKeyboardButton("❌ Yo'q, qoldirib turing", callback_data=f"del_cancel|{pay_id}|{who}"),
    ]])

    await query.edit_message_text(
        f"📋 *Tasdiqlash so'rovi:*\n\n"
        f"Siz foydalanuvchi bilan ishingizni tugatdingiz — bu juda yaxshi! 🎉\n\n"
        f"Endi sizning buyurtmangiz botda turmasligi kerak, negaki:\n"
        f"• Siz xaridor/yo'lovchi topib bo'ldingiz\n"
        f"• Boshqalar sizga keraksiz qo'ng'iroq qilmasligi uchun\n"
        f"• Tizimda xatoliklar va chalkashliklar bo'lmasligi uchun\n\n"
        f"🗑️ *O'chiriladigan buyurtma:*\n"
        f"👤 Ism: {name}\n"
        f"📞 Telefon: {phone}\n"
        f"📦 Yuk turi: {cargo}\n\n"
        f"*Siz bunga rozimisiz?*",
        parse_mode="Markdown",
        reply_markup=confirm_kb,
    )


async def finish_no_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    parts = query.data.split("|")
    pay_id = int(parts[1])
    who = parts[2]  # "payer" yoki "target"

    payment = get_payment(pay_id)
    if not payment:
        await query.edit_message_text("❌ To'lov ma'lumoti topilmadi.")
        return

    payer_id  = payment["payer_id"]
    target_id = payment["target_id"]

    # Bu odamning ovozini saqlаymiz
    set_no_vote(pay_id, who)
    # Yangilangan holat
    payment = get_payment(pay_id)

    payer_voted  = payment.get("payer_no_vote", 0)
    target_voted = payment.get("target_no_vote", 0)

    if payer_voted and target_voted:
        # ─── Ikkalasi ham "Yo'q" dedi ───────────────────────────────
        # Faqat PAYER ga bepul limit beramiz
        add_free_limit(payer_id)

        bonus_msg = (
            "✅ *Tushunarli!*\n\n"
            "Sizning buyurtmangiz bazada saqlanib qoldi.\n\n"
            "🎁 *Bonus:* Siz to'lov qilgan edingiz, shuning uchun sizga *1 ta bepul limit* berildi! "
            "Keyingi safar qidirib topganingizda qayta to'lov qilmasdan kontakt olishingiz mumkin.\n\n"
            "Xuddi shunga o'xshash buyurtma kimdan kelib qolsa, biz sizni tavsiya etamiz va xabardor qilamiz. 🔔"
        )
        no_bonus_msg = (
            "✅ *Tushunarli!*\n\n"
            "Sizning buyurtmangiz bazada saqlanib qoldi.\n\n"
            "ℹ️ *Ma'lumot:* Siz to'lov qilmagansiz — boshqa odam to'lov qilib sizni topgan edi. "
            "Shuning uchun bepul limit to'lov qilgan tomonga beriladi, sizga emas.\n\n"
            "Xuddi shunga o'xshash buyurtma kimdan kelib qolsa, biz sizni xabardor qilamiz. 🔔"
        )

        # Tugmani bosgan odamga uning roliga mos xabar
        if who == "payer":
            await query.edit_message_text(bonus_msg, parse_mode="Markdown")
            # Target ga "no bonus" xabari
            try:
                await context.bot.send_message(chat_id=target_id, text=no_bonus_msg, parse_mode="Markdown")
            except Exception as e:
                logger.error(f"Target ga xabar yuborishda xatolik: {e}")
        else:
            # Target tugmani bosdi — unga "no bonus" xabari
            await query.edit_message_text(no_bonus_msg, parse_mode="Markdown")
            # Payer ga bonus xabari
            try:
                await context.bot.send_message(chat_id=payer_id, text=bonus_msg, parse_mode="Markdown")
            except Exception as e:
                logger.error(f"Payer ga bonus xabar yuborishda xatolik: {e}")

    else:
        # ─── Faqat bir taraf bosdi — kutish kerak ──────────────────
        partner_label = "Buyurtma beruvchi" if who == "target" else "Buyurtma oluvchi"
        await query.edit_message_text(
            f"⏳ *Ma'lumotingiz qabul qilindi.*\n\n"
            f"Lekin sizning sherigingiz (*{partner_label}*) hali «Yo'q, hali yo'q» tugmasini bosmadi.\n\n"
            f"Ikkala tomon ham «Yo'q» deb javob berganida, sizga tegishli xabar yuboramiz.",
            parse_mode="Markdown",
        )


async def delete_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    parts = query.data.split("|")
    action  = parts[0]   # del_confirm yoki del_cancel
    pay_id  = int(parts[1])
    who     = parts[2]   # payer yoki target

    payment = get_payment(pay_id)
    if not payment:
        await query.edit_message_text("❌ To'lov ma'lumoti topilmadi.")
        return

    delete_uid = payment["payer_id"] if who == "payer" else payment["target_id"]

    if action == "del_confirm":
        delete_user_order(delete_uid)
        await query.edit_message_text(
            "✅ *Buyurtmangiz muvaffaqiyatli o'chirildi!*\n\n"
            "Endi boshqalar sizga ko'rinmaydi va keraksiz qo'ng'iroqlar bo'lmaydi.\n\n"
            "Agar keyinchalik yana foydalanmoqchi bo'lsangiz, /start bosing va qaytadan "
            "ro'yxatdan o'tishingiz mumkin. 🚀",
            parse_mode="Markdown",
        )
    elif action == "del_cancel":
        await query.edit_message_text(
            "✅ *Yaxshi, buyurtmangiz bazada qoldirildi.*\n\n"
            "Xuddi shunga o'xshash ehtiyoj bo'lsa, yana foydalanishingiz mumkin.\n"
            "Biz sizning buyurtmangizni boshqa moslar uchun tavsiya etib boramiz. 🔔\n\n"
            "Botdan davom etish uchun /start bosing.",
            parse_mode="Markdown",
        )


# ═══ QAYTA URINISH / ORQAGA QAYTISH (TO'LOV RAD ETILGANDA) ════════════════════
async def retry_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    u = get_user(update.effective_user.id)
    if not u:
        await query.edit_message_text("❌ Profil topilmadi. /start bosing.")
        return
    target_id = context.user_data.get("target_id")
    if not target_id:
        await query.edit_message_text(
            "⚠️ Qidiruvni qayta boshlash uchun menyudan *Qidirish* tugmasini bosing.",
            parse_mode="Markdown",
        )
        return
    await query.edit_message_text(
        f"💳 *To'lovni qayta amalga oshirish:*\n\n"
        f"💳 *Karta raqami:* `{PAYMENT_CARD}`\n"
        f"💵 *Miqdor:* {PAYMENT_AMOUNT:,} UZS\n\n"
        f"❗ Kartaga to'lovni o'tkazgach, *karta raqamingizda yozilgan ism va familiyangizni* yozing.\n"
        f"_(Masalan: Alisher Karimov)_",
        parse_mode="Markdown",
    )


async def back_to_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    u = get_user(update.effective_user.id)
    kb = after_register_keyboard(u["role"]) if u else main_menu_keyboard()
    await query.edit_message_text("🔙 Orqaga qaytdingiz. Menyudan kerakli bo'limni tanlang.")
    await context.bot.send_message(
        chat_id=update.effective_user.id,
        text="👇 Menyudan tanlang:",
        reply_markup=kb,
    )



async def edit_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if "Ism" in text or "Familiya" in text:
        await update.message.reply_text("✏️ Yangi ism va familiyangizni kiriting:", reply_markup=ReplyKeyboardRemove())
        return EDIT_NAME
    elif "Telefon" in text:
        await update.message.reply_text("📞 Yangi telefon raqamingizni kiriting:", reply_markup=ReplyKeyboardRemove())
        return EDIT_PHONE
    elif "Rol" in text:
        await update.message.reply_text(
            "🏷️ *Rolni o'zgartirish*\n\nSiz qaysi sifatida davom etmoqchisiz?",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardMarkup(
                [
                    [KeyboardButton("📦 Buyurtma beruvchi sifatida")],
                    [KeyboardButton("🚚 Buyurtma oluvchi sifatida")],
                    [KeyboardButton("🔙 Orqaga")],
                ],
                resize_keyboard=True,
            ),
        )
        return EDIT_ROLE
    elif "Yuk turi" in text:
        await update.message.reply_text(
            "📦 Yangi yuk turini quyidagi menyudan tanlang:",
            reply_markup=cargo_types_keyboard(),
        )
        return EDIT_CARGO
    elif "Orqaga" in text:
        u = get_user(update.effective_user.id)
        role = u["role"] if u else "employer"
        await update.message.reply_text("🔙 Orqaga qaytdingiz.", reply_markup=after_register_keyboard(role))
        return MAIN_MENU
    else:
        await update.message.reply_text("❗ Tugmalardan birini tanlang.")
        return EDIT_MENU


async def edit_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_name = update.message.text.strip()
    update_user_field(update.effective_user.id, "full_name", new_name)
    u = get_user(update.effective_user.id)
    await update.message.reply_text(
        f"✅ Ismingiz *{new_name}* ga o'zgartirildi!",
        reply_markup=after_register_keyboard(u["role"]),
        parse_mode="Markdown",
    )
    return MAIN_MENU


async def edit_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_phone = update.message.text.strip()
    update_user_field(update.effective_user.id, "phone", new_phone)
    u = get_user(update.effective_user.id)
    await update.message.reply_text(
        f"✅ Telefon raqamingiz *{new_phone}* ga o'zgartirildi!",
        reply_markup=after_register_keyboard(u["role"]),
        parse_mode="Markdown",
    )
    return MAIN_MENU


async def edit_cargo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Yuk turini tahrirlash — foydalanuvchi profili yangilanadi."""
    new_cargo = update.message.text.strip()
    uid = update.effective_user.id
    update_user_field(uid, "cargo_type", new_cargo)
    u = get_user(uid)
    # Yangi yuk turi bilan kutayotganlarni ham xabardor qilamiz
    await notify_waitlist(context, u["role"], new_cargo)
    await update.message.reply_text(
        f"✅ Yuk turingiz *{new_cargo}* ga o'zgartirildi!",
        reply_markup=after_register_keyboard(u["role"]),
        parse_mode="Markdown",
    )
    return MAIN_MENU


async def edit_role(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    u = get_user(update.effective_user.id)
    if not u:
        return MAIN_MENU

    if "Orqaga" in text:
        await update.message.reply_text("🔙 Orqaga qaytdingiz.", reply_markup=after_register_keyboard(u["role"]))
        return MAIN_MENU

    if "Buyurtma beruvchi" in text:
        chosen_role = "employer"
    elif "Buyurtma oluvchi" in text:
        chosen_role = "worker"
    else:
        await update.message.reply_text("❗ Iltimos, tugmalardan birini tanlang.")
        return EDIT_ROLE

    # Rolni o'zgartiramiz
    update_user_field(update.effective_user.id, "role", chosen_role)
    role_label = "📦 Buyurtma beruvchi" if chosen_role == "employer" else "🚚 Buyurtma oluvchi"
    await update.message.reply_text(
        f"✅ Rolingiz *{role_label}* qilib o'zgartirildi!\n\n"
        f"Agar yuk turingiz ham o'zgargan bo'lsa, uni ham *Tahrirlash* bo'limidan o'zgartirishingiz mumkin.",
        reply_markup=after_register_keyboard(chosen_role),
        parse_mode="Markdown",
    )
    return MAIN_MENU


async def add_order_cargo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Qo'shimcha buyurtma: faqat yuk turi so'ralib, kutish ro'yxatiga yoki qidiruvga yo'naltiriladi."""
    cargo_type = update.message.text.strip()
    
    if "Orqaga" in cargo_type:
        u = get_user(update.effective_user.id)
        kb = after_register_keyboard(u["role"]) if u else main_menu_keyboard()
        await update.message.reply_text("🔙 Orqaga qaytdingiz.", reply_markup=kb)
        return MAIN_MENU

    u = get_user(update.effective_user.id)
    if not u:
        await update.message.reply_text("❌ Siz hali ro'yxatdan o'tmagansiz. /start bosing.")
        return MAIN_MENU

    chosen_role = u["role"]

    # To'g'ridan to'g'ri kutish ro'yxatiga qo'shamiz
    target_role = "worker" if chosen_role == "employer" else "employer"
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    existing_wait = run_query(
        "SELECT id FROM wait_list WHERE user_id=? AND target_role=? AND cargo_type=?",
        (u["user_id"], target_role, cargo_type), fetch=True
    )
    if not existing_wait:
        run_query(
            "INSERT INTO wait_list (user_id, target_role, cargo_type, created_at) VALUES (?,?,?,?)",
            (u["user_id"], target_role, cargo_type, now)
        )
        
    opposite_label = "buyurtma oluvchi" if chosen_role == "employer" else "buyurtma beruvchi"
    await update.message.reply_text(
        f"✅ *Yangi buyurtmangiz qabul qilindi!*\n\n"
        f"Sizning *{cargo_type}* turdagi yulingiz bazaga qo'shildi.\n"
        f"Unga mos *{opposite_label}* topishimiz bilanoq sizga aytamiz! 🔔",
        parse_mode="Markdown",
        reply_markup=after_register_keyboard(u["role"]),
    )
    return MAIN_MENU


async def bug_report_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    u = get_user(update.effective_user.id)
    if "Orqaga" in text:
        kb = after_register_keyboard(u["role"]) if u else main_menu_keyboard()
        await update.message.reply_text("🔙 Orqaga qaytdingiz.", reply_markup=kb)
        return MAIN_MENU

    # Matnni saqlab qo'yamiz va tasdiq so'raymiz
    context.user_data["bug_text"] = text

    await update.message.reply_text(
        "Aytgan gaplaringizni rostdan ham adminga yuborishni xohlaysizmi?",
        reply_markup=ReplyKeyboardMarkup(
            [
                [KeyboardButton("✅ Ha, yuborish")],
                [KeyboardButton("❌ Yo'q, qaytadan yozish")],
                [KeyboardButton("🔙 Orqaga")],
            ],
            resize_keyboard=True
        )
    )
    return BUG_REPORT_CONFIRM


async def bug_report_confirm_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    u = get_user(update.effective_user.id)
    
    if "Orqaga" in text:
        kb = after_register_keyboard(u["role"]) if u else main_menu_keyboard()
        await update.message.reply_text("🔙 Orqaga qaytdingiz.", reply_markup=kb)
        return MAIN_MENU
    
    if "Yo'q" in text:
        await update.message.reply_text(
            "Iltimos, muammoni qaytadan batafsil yozib yuboring:",
            reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🔙 Orqaga")]], resize_keyboard=True)
        )
        return BUG_REPORT
        
    if "Ha" in text:
        bug_text = context.user_data.get("bug_text", "Noma'lum xatolik")

        # Foydalanuvchi ma'lumotlari
        tg_user = update.effective_user
        full_name = u["full_name"] if u else (tg_user.full_name or "Noma'lum")
        phone    = u["phone"]     if u else "Kiritilmagan"
        role_lbl = ("📦 Buyurtma beruvchi" if u["role"] == "employer" else "🚚 Buyurtma oluvchi") if u else "Ro'yxatdan o'tmagan"

        msg_to_admin = (
            f"🚨 *Bot-muammolari:*\n\n"
            f"👤 *Ism:* {full_name}\n"
            f"📞 *Tel:* {phone}\n"
            f"🏷️ *Rol:* {role_lbl}\n"
            f"🆔 *Telegram ID:* `{tg_user.id}`\n\n"
            f"📝 *Muammo:*\n{bug_text}"
        )

        # Tasdiqlash botiga (ADMIN_BOT_TOKEN) yuboramiz
        try:
            from telegram import Bot as TgBot
            admin_bot = TgBot(token=ADMIN_BOT_TOKEN)
            for admin_id in ADMIN_IDS:
                try:
                    await admin_bot.send_message(chat_id=admin_id, text=msg_to_admin, parse_mode="Markdown")
                except Exception as e:
                    logger.error(f"Tasdiqlash botiga bug report yuborishda xatolik ({admin_id}): {e}")
        except Exception as e:
            logger.error(f"Admin bot ulanishida xatolik: {e}")

        kb = after_register_keyboard(u["role"]) if u else main_menu_keyboard()
        await update.message.reply_text(
            "✅ Rahmat! Sizning xabaringiz tizim administratorlariga yuborildi. Tez orada ko'rib chiqamiz.",
            reply_markup=kb
        )
        return MAIN_MENU
        
    await update.message.reply_text("❗ Iltimos, tugmalardan birini tanlang.")
    return BUG_REPORT_CONFIRM


async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❓ Tushunmadim. /start bosing yoki tugmalardan birini tanlang.")


# ─── ASOSIY FUNKSIYA ───────────────────────────────────────────────────────────
def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            # Yangi foydalanuvchilar uchun bosh menyu tugmalari
            MessageHandler(
                filters.Regex("(?i)(Buyurtma berish|Buyurtma olish)"),
                main_menu_handler
            ),
        ],
        per_message=False,
        states={
            MAIN_MENU: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, main_menu_handler),
            ],
            EMPLOYER_NAME:  [MessageHandler(filters.TEXT & ~filters.COMMAND, employer_name)],
            EMPLOYER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, employer_phone)],
            EMPLOYER_CARGO: [MessageHandler(filters.TEXT & ~filters.COMMAND, employer_cargo)],
            WORKER_NAME:    [MessageHandler(filters.TEXT & ~filters.COMMAND, worker_name)],
            WORKER_PHONE:   [MessageHandler(filters.TEXT & ~filters.COMMAND, worker_phone)],
            WORKER_CARGO:   [MessageHandler(filters.TEXT & ~filters.COMMAND, worker_cargo)],
            # SEARCH_CARGO: faqat search_cargo handleriga yo'naltiriladi
            SEARCH_CARGO: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, search_cargo),
            ],
            AWAIT_PAYMENT:  [MessageHandler(filters.TEXT & ~filters.COMMAND, await_payment)],
            EDIT_MENU:      [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_menu_handler)],
            EDIT_NAME:      [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_name)],
            EDIT_PHONE:     [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_phone)],
            EDIT_CARGO:     [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_cargo)],
            EDIT_ROLE:      [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_role)],
            ADD_ORDER_CARGO:[MessageHandler(filters.TEXT & ~filters.COMMAND, add_order_cargo)],
            BUG_REPORT:     [MessageHandler(filters.TEXT & ~filters.COMMAND, bug_report_handler)],
            BUG_REPORT_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, bug_report_confirm_handler)],
        },
        fallbacks=[
            CommandHandler("start", start),
            MessageHandler(filters.TEXT & ~filters.COMMAND, unknown),
        ],
        allow_reentry=True,
    )

    app.add_handler(conv)
    # To'lov tasdiqlash — faqat asosiy bot orqali adminga yuborilsa ishlaydi
    # (ADMIN_BOT_TOKEN bo'lsa, bu handler kerak emas — admin_bot.py boshqaradi)
    if not ADMIN_BOT_TOKEN:
        app.add_handler(CallbackQueryHandler(admin_payment_callback, pattern=r"^pay_(ok|no)\|\d+$"))

    app.add_handler(CallbackQueryHandler(finish_yes_callback,    pattern=r"^finish_yes\|\d+\|(payer|target)$"))
    app.add_handler(CallbackQueryHandler(finish_no_callback,     pattern=r"^finish_no\|\d+\|(payer|target)$"))
    app.add_handler(CallbackQueryHandler(delete_confirm_callback, pattern=r"^del_(confirm|cancel)\|\d+\|(payer|target)$"))
    app.add_handler(CallbackQueryHandler(retry_payment_callback,  pattern=r"^retry_payment\|\d+$"))
    app.add_handler(CallbackQueryHandler(back_to_menu_callback,   pattern=r"^back_to_menu\|\d+$"))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown))

    logger.info("🚀 LogiConnect bot ishga tushdi...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
