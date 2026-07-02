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
ADMIN_ID = 8175344606  # Admin Telegram ID

PAYMENT_CARD = "9860 0801 9212 8785"
PAYMENT_AMOUNT = 50000

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─── CONVERSATION STATES ───────────────────────────────────────────────────────
(
    MAIN_MENU,           # 0
    EMPLOYER_NAME,       # 1
    EMPLOYER_PHONE,      # 2
    WORKER_NAME,         # 3
    WORKER_PHONE,        # 4
    SEARCH_CARGO,        # 5
    AWAIT_PAYMENT,       # 6
    AWAIT_PAYMENT_CONFIRM, # 7
    EDIT_MENU,           # 8
    EDIT_NAME,           # 9
    EDIT_PHONE,          # 10
) = range(11)

# ─── DATABASE ──────────────────────────────────────────────────────────────────
DB_URL = os.environ.get("DATABASE_URL")

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
        run_query("""
            CREATE TABLE IF NOT EXISTS payments (
                id          SERIAL PRIMARY KEY,
                payer_id    BIGINT,
                target_id   BIGINT,
                amount      INTEGER,
                card_holder VARCHAR(255),
                status      VARCHAR(50) DEFAULT 'pending',
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
        run_query("""
            CREATE TABLE IF NOT EXISTS payments (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                payer_id    INTEGER,
                target_id   INTEGER,
                amount      INTEGER,
                card_holder TEXT,
                status      TEXT DEFAULT 'pending',
                created_at  TEXT
            )
        """)


def upsert_user(user_id, username, full_name, phone, role):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    row = run_query("SELECT user_id FROM users WHERE user_id = ?", (user_id,), fetch=True)
    
    if row:
        run_query("""
            UPDATE users SET username=?, full_name=?, phone=?, role=?, updated_at=?
            WHERE user_id=?
        """, (username, full_name, phone, role, now, user_id))
    else:
        run_query("""
            INSERT INTO users (user_id, username, full_name, phone, role, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?)
        """, (user_id, username, full_name, phone, role, now, now))


def get_user(user_id):
    row = run_query("SELECT * FROM users WHERE user_id = ?", (user_id,), fetch=True)
    if row:
        cols = ["user_id", "username", "full_name", "phone", "role", "created_at", "updated_at"]
        return dict(zip(cols, row))
    return None


def search_opposite(role):
    opposite = "worker" if role == "employer" else "employer"
    rows = run_query("""
        SELECT user_id, full_name, phone, username
        FROM users WHERE role=?
        ORDER BY updated_at DESC LIMIT 10
    """, (opposite,), fetchall=True)
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
        cols = ["id", "payer_id", "target_id", "amount", "card_holder", "status", "created_at"]
        return dict(zip(cols, row))
    return None


def update_user_field(user_id, field, value):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # field is safe because we only use it for 'full_name' or 'phone' internally
    run_query(f"UPDATE users SET {field}=?, updated_at=? WHERE user_id=?", (value, now, user_id))


# ─── KLAVIATURALAR ─────────────────────────────────────────────────────────────
def main_menu_keyboard():
    return ReplyKeyboardMarkup(
        [[KeyboardButton("💼 Ish berish"), KeyboardButton("🚛 Ish olish")]],
        resize_keyboard=True,
    )


def after_register_keyboard(role):
    search_btn = "🔍 Ish oluvchini qidirish" if role == "employer" else "🔍 Ish beruvchini qidirish"
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(search_btn)],
            [KeyboardButton("✏️ Ma'lumotlarni tahrirlash")],
            [KeyboardButton("🏠 Bosh menyu")],
        ],
        resize_keyboard=True,
    )


# ─── /START ────────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    existing = get_user(user.id)

    welcome = (
        f"🌟 *LogiConnect Botiga Xush Kelibsiz!* 🌟\n\n"
        f"Salom, *{user.first_name}*! 👋\n\n"
        f"Men logistika sohasidagi *ish beruvchilar* va *ish oluvchilar* o'rtasidagi "
        f"muloqotni osonlashtiruvchi raqamli broker botman.\n\n"
        f"✅ Ish beruvchi va oluvchilarni ulashaman\n"
        f"✅ Tez va qulay qidirish\n"
        f"✅ Ma'lumotlar xavfsiz saqlanadi\n\n"
        f"Quyidan o'zingizga kerakli bo'limni tanlang 👇"
    )

    if existing:
        role_label = "Ish beruvchi" if existing["role"] == "employer" else "Ish oluvchi"
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

    if text == "💼 Ish berish":
        await update.message.reply_text(
            "📝 *Ish berish bo'limi*\n\nBir nechta savol beramiz.\n\n"
            "1️⃣ Ismingiz va familiyangizni kiriting:",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode="Markdown",
        )
        return EMPLOYER_NAME

    elif text == "🚛 Ish olish":
        await update.message.reply_text(
            "📝 *Ish olish bo'limi*\n\nBir nechta savol beramiz.\n\n"
            "1️⃣ Ismingiz va familiyangizni kiriting:",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode="Markdown",
        )
        return WORKER_NAME

    elif text in ("🔍 Ish oluvchini qidirish", "🔍 Ish beruvchini qidirish"):
        u = get_user(update.effective_user.id)
        if not u:
            await update.message.reply_text("❌ Siz hali ro'yxatdan o'tmagansiz. /start bosing.")
            return MAIN_MENU
        context.user_data["searching_as"] = u["role"]
        results = search_opposite(u["role"])
        if not results:
            opposite_label = "ish oluvchi (haydovchi)" if u["role"] == "employer" else "ish beruvchi (shipper)"
            await update.message.reply_text(
                f"😔 Hozirda hech qanday *{opposite_label}* topilmadi.\n\nKeyinroq qayta urinib ko'ring.",
                parse_mode="Markdown",
                reply_markup=after_register_keyboard(u["role"]),
            )
            return MAIN_MENU

        # Topildi — to'lov talab qilamiz
        target = results[0]
        target_id = target[0]
        context.user_data["target_id"] = target_id

        opposite_label = "Ish oluvchi (haydovchi)" if u["role"] == "employer" else "Ish beruvchi (shipper)"
        await update.message.reply_text(
            f"✅ *{opposite_label} topildi!*\n\n"
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

    elif text == "✏️ Ma'lumotlarni tahrirlash":
        u = get_user(update.effective_user.id)
        if not u:
            await update.message.reply_text("❌ Siz hali ro'yxatdan o'tmagansiz.")
            return MAIN_MENU
        role_label = "💼 Ish beruvchi" if u["role"] == "employer" else "🚛 Ish oluvchi"
        await update.message.reply_text(
            f"✏️ *Ma'lumotlarni tahrirlash*\n\n"
            f"👤 Ism: {u['full_name']}\n"
            f"📞 Telefon: {u['phone']}\n"
            f"🏷️ Rol: {role_label}\n\n"
            "Nimani tahrirlashni istaysiz?",
            reply_markup=ReplyKeyboardMarkup(
                [
                    [KeyboardButton("✏️ Ism/Familiya"), KeyboardButton("📞 Telefon")],
                    [KeyboardButton("🔙 Orqaga")],
                ],
                resize_keyboard=True,
            ),
            parse_mode="Markdown",
        )
        return EDIT_MENU

    elif text == "🏠 Bosh menyu":
        await update.message.reply_text("🏠 Bosh menyuga qaytdingiz:", reply_markup=main_menu_keyboard())
        return MAIN_MENU

    else:
        await update.message.reply_text(
            "⬇️ Iltimos, quyidagi tugmalardan birini tanlang:",
            reply_markup=main_menu_keyboard(),
        )
        return MAIN_MENU


# ═══ ISH BERISH (EMPLOYER) ═════════════════════════════════════════════════════
async def employer_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["emp_name"] = update.message.text.strip()
    await update.message.reply_text("2️⃣ Telefon raqamingizni kiriting (masalan: +998901234567):")
    return EMPLOYER_PHONE


async def employer_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    user = update.effective_user
    upsert_user(user.id, user.username, context.user_data["emp_name"], phone, "employer")
    await update.message.reply_text(
        "✅ *Tabriklaymiz! Muvaffaqiyatli ro'yxatdan o'tdingiz!*\n\n"
        f"👤 Ism: {context.user_data['emp_name']}\n"
        f"📞 Telefon: {phone}\n"
        f"🏷️ Rol: 💼 Ish beruvchi\n\n"
        "Endi haydovchi (ish oluvchi) qidirish yoki boshqa amallarni bajarishingiz mumkin 👇",
        reply_markup=after_register_keyboard("employer"),
        parse_mode="Markdown",
    )
    return MAIN_MENU


# ═══ ISH OLISH (WORKER) ════════════════════════════════════════════════════════
async def worker_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["wrk_name"] = update.message.text.strip()
    await update.message.reply_text("2️⃣ Telefon raqamingizni kiriting (masalan: +998901234567):")
    return WORKER_PHONE


async def worker_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    user = update.effective_user
    upsert_user(user.id, user.username, context.user_data["wrk_name"], phone, "worker")
    await update.message.reply_text(
        "✅ *Tabriklaymiz! Muvaffaqiyatli ro'yxatdan o'tdingiz!*\n\n"
        f"👤 Ism: {context.user_data['wrk_name']}\n"
        f"📞 Telefon: {phone}\n"
        f"🏷️ Rol: 🚛 Ish oluvchi\n\n"
        "Endi ish beruvchi (shipper) qidirish yoki boshqa amallarni bajarishingiz mumkin 👇",
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

    # Adminga xabar yuborish
    if ADMIN_ID:
        try:
            confirm_btn = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"pay_ok|{pay_id}"),
                    InlineKeyboardButton("❌ Rad etish", callback_data=f"pay_no|{pay_id}"),
                ]
            ])
            opposite_label = "Ish oluvchi" if role == "employer" else "Ish beruvchi"
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    f"💰 *Yangi to'lov so'rovi!*\n\n"
                    f"📋 To'lov ID: #{pay_id}\n"
                    f"👤 To'lovchi: {payer_name}\n"
                    f"📞 Telefon: {payer_phone}\n"
                    f"💳 Karta egasi (to'lovchi ko'rsatgan): {card_holder}\n"
                    f"💵 Miqdor: {PAYMENT_AMOUNT:,} UZS\n"
                    f"🔍 Qidirilgan: {opposite_label}\n\n"
                    f"Kartangizda ushbu ismdan {PAYMENT_AMOUNT:,} UZS tushganini tekshiring va tasdiqlang."
                ),
                parse_mode="Markdown",
                reply_markup=confirm_btn,
            )
        except Exception as e:
            logger.error(f"Admin ga xabar yuborishda xatolik: {e}")

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
            opposite_label = "Ish oluvchi (Haydovchi)" if role == "employer" else "Ish beruvchi (Shipper)"
            uname = f"@{target['username']}" if target.get("username") else "Telegram username yo'q"
            msg = (
                f"✅ *To'lovingiz tasdiqlandi!*\n\n"
                f"🎉 *{opposite_label} ma'lumotlari:*\n\n"
                f"👤 Ism: *{target['full_name']}*\n"
                f"📞 Telefon: `{target['phone']}`\n"
                f"🔗 Telegram: {uname}\n\n"
                f"Muvaffaqiyatli hamkorlik tilaymiz! 🤝"
            )
            await context.bot.send_message(chat_id=payer_id, text=msg, parse_mode="Markdown")
            await query.edit_message_text(f"✅ To'lov #{pay_id} tasdiqlandi va foydalanuvchiga ma'lumot yuborildi.")
        else:
            await context.bot.send_message(
                chat_id=payer_id,
                text="❌ Kechirasiz, qidirilgan foydalanuvchi topilmadi. Adminla bog'laning."
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


# ═══ TAHRIRLASH ════════════════════════════════════════════════════════════════
async def edit_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "✏️ Ism/Familiya":
        await update.message.reply_text("✏️ Yangi ism va familiyangizni kiriting:", reply_markup=ReplyKeyboardRemove())
        return EDIT_NAME
    elif text == "📞 Telefon":
        await update.message.reply_text("📞 Yangi telefon raqamingizni kiriting:", reply_markup=ReplyKeyboardRemove())
        return EDIT_PHONE
    elif text == "🔙 Orqaga":
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


async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❓ Tushunmadim. /start bosing yoki tugmalardan birini tanlang.")


# ─── ASOSIY FUNKSIYA ───────────────────────────────────────────────────────────
def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        per_message=False,
        states={
            MAIN_MENU: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, main_menu_handler),
            ],
            EMPLOYER_NAME:  [MessageHandler(filters.TEXT & ~filters.COMMAND, employer_name)],
            EMPLOYER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, employer_phone)],
            WORKER_NAME:    [MessageHandler(filters.TEXT & ~filters.COMMAND, worker_name)],
            WORKER_PHONE:   [MessageHandler(filters.TEXT & ~filters.COMMAND, worker_phone)],
            AWAIT_PAYMENT:  [MessageHandler(filters.TEXT & ~filters.COMMAND, await_payment)],
            EDIT_MENU:      [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_menu_handler)],
            EDIT_NAME:      [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_name)],
            EDIT_PHONE:     [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_phone)],
        },
        fallbacks=[
            CommandHandler("start", start),
            MessageHandler(filters.TEXT & ~filters.COMMAND, unknown),
        ],
        allow_reentry=True,
    )

    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(admin_payment_callback, pattern=r"^pay_(ok|no)\|\d+$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown))

    logger.info("🚀 LogiConnect bot ishga tushdi...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
