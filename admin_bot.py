"""
╔══════════════════════════════════════════════════════════╗
║        LOGISTIK TASDIQLASH BOT  (admin_bot.py)           ║
║  Bu bot faqat admin uchun — to'lovlarni tasdiqlash/rad   ║
║  etish va foydalanuvchilarga "ish tugatdingizmi?"        ║
║  savolini yuborish vazifasini bajaradi.                  ║
╚══════════════════════════════════════════════════════════╝
"""

import logging
import os
import urllib.parse
import pg8000.dbapi
from datetime import datetime
from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# ─── SOZLAMALAR ────────────────────────────────────────────────────────────────
# BU TOKENNI @BotFather dan oling: /newbot → nomi: Logistik_tasdiqlash_bot
ADMIN_BOT_TOKEN = os.environ.get("ADMIN_BOT_TOKEN", "8939855367:AAEWex_skRAjKhHQbD95R3E6COp6Q6AQkLQ")

# Asosiy botning tokeni (foydalanuvchilarga xabar yuborish uchun)
MAIN_BOT_TOKEN = os.environ.get("BOT_TOKEN", "8841015797:AAGyauWuYzItmfRfy7QwUSj0PCw1WKSyVPo")

ADMIN_ID = int(os.environ.get("ADMIN_ID", "8175344606"))
PAYMENT_AMOUNT = 50_000

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─── DATABASE (asosiy bot bilan bir xil DB) ───────────────────────────────────
DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:kMhzsVPUhELJnKadPEDacSVCMxcegXWz@postgres.railway.internal:5432/railway",
)


def get_db_connection():
    url = urllib.parse.urlparse(DB_URL)
    return pg8000.dbapi.connect(
        user=url.username,
        password=url.password,
        host=url.hostname,
        port=url.port or 5432,
        database=url.path[1:],
    )


def run_query(query, params=(), fetch=None, fetchall=False):
    conn = get_db_connection()
    c = conn.cursor()
    query = query.replace("?", "%s")
    try:
        c.execute(query, params)
        result = None
        if fetch:
            result = c.fetchone()
        elif fetchall:
            result = c.fetchall()
        conn.commit()
    finally:
        c.close()
        conn.close()
    return result


def get_payment(pay_id):
    row = run_query(
        "SELECT id, payer_id, target_id, amount, card_holder, status, created_at FROM payments WHERE id=%s",
        (pay_id,),
        fetch=True,
    )
    if row:
        cols = ["id", "payer_id", "target_id", "amount", "card_holder", "status", "created_at"]
        return dict(zip(cols, row))
    return None


def get_user(user_id):
    row = run_query(
        "SELECT user_id, username, full_name, phone, role, created_at, updated_at, cargo_type FROM users WHERE user_id=%s",
        (user_id,),
        fetch=True,
    )
    if row:
        cols = ["user_id", "username", "full_name", "phone", "role", "created_at", "updated_at", "cargo_type"]
        return dict(zip(cols, row))
    return None


def confirm_payment(pay_id):
    run_query("UPDATE payments SET status='confirmed' WHERE id=%s", (pay_id,))


def delete_user_order(user_id):
    """Foydalanuvchi buyurtmasini (users va wait_list) o'chiradi."""
    run_query("DELETE FROM users WHERE user_id=%s", (user_id,))
    run_query("DELETE FROM wait_list WHERE user_id=%s", (user_id,))


# ─── /START ────────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Bu bot faqat admin uchun.")
        return
    await update.message.reply_text(
        "👋 *Logistik Tasdiqlash Boti*\n\n"
        "Bu bot orqali siz:\n"
        "✅ To'lovlarni tasdiqlaysiz yoki rad etasiz\n"
        "📩 Foydalanuvchilarga 'Ish tugatdingizmi?' savoli avtomatik yuboriladi\n\n"
        "To'lov so'rovlari asosiy botdan avtomatik kelib turadi.",
        parse_mode="Markdown",
    )


# ─── ADMIN: TO'LOV TASDIQLASH / RAD ETISH ─────────────────────────────────────
async def payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if update.effective_user.id != ADMIN_ID:
        await query.answer("❌ Sizda ruxsat yo'q!", show_alert=True)
        return

    parts = query.data.split("|")
    action = parts[0]   # pay_ok yoki pay_no
    pay_id = int(parts[1])

    payment = get_payment(pay_id)
    if not payment:
        await query.edit_message_text("❌ To'lov topilmadi. Ehtimol allaqachon ko'rib chiqilgan.")
        return

    if payment["status"] == "confirmed":
        await query.edit_message_text(f"ℹ️ To'lov #{pay_id} allaqachon tasdiqlangan.")
        return

    payer_id = payment["payer_id"]
    target_id = payment["target_id"]

    # Asosiy bot orqali foydalanuvchilarga xabar yuboramiz
    main_bot = context.application.bot  # Bu admin bot, main botga ulanamiz quyida

    if action == "pay_ok":
        confirm_payment(pay_id)
        target = get_user(target_id)
        payer = get_user(payer_id)

        if not target:
            await query.edit_message_text(
                f"⚠️ To'lov #{pay_id} tasdiqlandi, lekin target foydalanuvchi bazada topilmadi."
            )
            # Payer ga xabar
            try:
                from telegram import Bot
                main = Bot(token=MAIN_BOT_TOKEN)
                await main.send_message(
                    chat_id=payer_id,
                    text="❌ Kechirasiz, siz qidirgan foydalanuvchi topilmadi. Admin bilan bog'laning.",
                )
            except Exception as e:
                logger.error(f"Payer ga xabar yuborishda xatolik: {e}")
            return

        role = payer["role"] if payer else "employer"
        opposite_label = "Buyurtma oluvchi (Haydovchi)" if role == "employer" else "Buyurtma beruvchi (Shipper)"
        payer_role_label = "buyurtmachi" if role == "employer" else "buyurtma oluvchi"
        target_role_label = "buyurtma oluvchi" if role == "employer" else "buyurtmachi"
        uname = f"@{target['username']}" if target.get("username") else "Telegram username yo'q"

        # ── Asosiy bot orqali payer ga ma'lumot va savol yuboramiz ──
        from telegram import Bot
        main = Bot(token=MAIN_BOT_TOKEN)

        contact_msg = (
            f"✅ *To'lovingiz tasdiqlandi!*\n\n"
            f"🎉 *{opposite_label} ma'lumotlari:*\n\n"
            f"👤 Ism: *{target['full_name']}*\n"
            f"📞 Telefon: `{target['phone']}`\n"
            f"📦 Yuk turi: {target.get('cargo_type', 'Kiritilmagan')}\n"
            f"🔗 Telegram: {uname}\n\n"
            f"Muvaffaqiyatli hamkorlik tilaymiz! 🤝"
        )
        try:
            await main.send_message(chat_id=payer_id, text=contact_msg, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Payer ga kontakt yuborishda xatolik: {e}")

        # ── Payer ga "Ish tugatdingizmi?" savoli ──
        finish_kb_payer = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Ha, tugatdim", callback_data=f"finish_yes|{pay_id}|payer"),
            InlineKeyboardButton("❌ Yo'q, hali yo'q", callback_data=f"finish_no|{pay_id}|payer"),
        ]])
        try:
            await main.send_message(
                chat_id=payer_id,
                text=(
                    f"❓ *Savol:*\n\n"
                    f"Siz ushbu *{target_role_label}* bilan bog'landingizmi?\n"
                    f"Kelishib oldingizmi? Ish hal bo'ldimi?\n\n"
                    f"_(Agar 'Ha' deb javob bersangiz, sizning buyurtmangiz bazadan o'chiriladi "
                    f"— chunki siz hamkorni topib bo'ldingiz va keyingi safar boshqa odamlar "
                    f"sizni telefon qilib bezovta qilmasligi uchun.)_"
                ),
                parse_mode="Markdown",
                reply_markup=finish_kb_payer,
            )
        except Exception as e:
            logger.error(f"Payer ga savol yuborishda xatolik: {e}")

        # ── Target ga "Ish tugatdingizmi?" savoli ──
        finish_kb_target = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Ha, tugatdim", callback_data=f"finish_yes|{pay_id}|target"),
            InlineKeyboardButton("❌ Yo'q, hali yo'q", callback_data=f"finish_no|{pay_id}|target"),
        ]])
        try:
            await main.send_message(
                chat_id=target_id,
                text=(
                    f"🎉 *Tabriklaymiz!*\n\n"
                    f"Sizning kontakt ma'lumotlaringiz yangi hamkorga yuborildi.\n\n"
                    f"❓ *Savol:*\n"
                    f"Siz ushbu *{payer_role_label}* bilan bog'landingizmi?\n"
                    f"Kelishib oldingizmi? Ish hal bo'ldimi?\n\n"
                    f"_(Agar 'Ha' deb javob bersangiz, sizning buyurtmangiz bazadan o'chiriladi "
                    f"— chunki siz hamkorni topib bo'ldingiz va boshqalar sizga bezovta "
                    f"qo'ng'iroq qilmasligi uchun, tizimda ham chalkashliklar bo'lmasligi uchun.)_"
                ),
                parse_mode="Markdown",
                reply_markup=finish_kb_target,
            )
        except Exception as e:
            logger.error(f"Target ga savol yuborishda xatolik: {e}")

        await query.edit_message_text(
            f"✅ *To'lov #{pay_id} tasdiqlandi!*\n\n"
            f"👤 To'lovchi: {payer['full_name'] if payer else 'Noma\\'lum'}\n"
            f"📞 Telefon: {payer['phone'] if payer else '-'}\n\n"
            f"📩 Ikkala foydalanuvchiga kontakt va 'Ish tugatdingizmi?' savoli yuborildi.",
            parse_mode="Markdown",
        )

    elif action == "pay_no":
        from telegram import Bot
        main = Bot(token=MAIN_BOT_TOKEN)
        try:
            await main.send_message(
                chat_id=payer_id,
                text=(
                    "❌ *To'lovingiz tasdiqlanmadi.*\n\n"
                    "Sabab: Karta raqamida ko'rsatilgan ism-familiya yoki to'lov miqdori noto'g'ri bo'lishi mumkin.\n\n"
                    "Iltimos, to'g'ri ma'lumotlar bilan qayta urinib ko'ring yoki admin bilan bog'laning."
                ),
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error(f"Payer ga rad xabar yuborishda xatolik: {e}")

        await query.edit_message_text(
            f"❌ *To'lov #{pay_id} rad etildi.*\n\n"
            f"Foydalanuvchiga xabar yuborildi.",
            parse_mode="Markdown",
        )


# ─── FOYDALANUVCHI: "ISH TUGATDINGIZMI?" JAVOBLARI ───────────────────────────
async def finish_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bu callback asosiy botdan kelgan tugmalarni ushlab oladi."""
    # Bu handleri asosiy botda ishlaydi, admin_bot emas.
    # Shuning uchun bu callback main bot tomonida handle qilinadi.
    # Qarang: bot.py dagi finish_callback
    pass


# ─── ISH TUGATISH: HA dedi → tasdiqlash so'rovi ──────────────────────────────
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


# ─── ISH TUGATISH: YO'Q dedi ─────────────────────────────────────────────────
async def finish_no_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    parts = query.data.split("|")
    pay_id = int(parts[1])
    who = parts[2]

    payment = get_payment(pay_id)
    payer_id = payment["payer_id"] if payment else None

    await query.edit_message_text(
        "✅ *Tushunarli!*\n\n"
        "Sizning buyurtmangiz bazada saqlanib qoldi.\n\n"
        "Xuddi shunga o'xshash buyurtma kimdan kelib qolsa, "
        "biz sizni tavsiya etamiz va yana xabardor qilamiz. 🔔\n\n"
        "Botdan davom etish uchun /start bosing.",
        parse_mode="Markdown",
    )

    # Agar to'lov qilgan odam (payer) "Yo'q" desa — limit haqida eslatamiz
    if who == "payer" and payer_id:
        try:
            from telegram import Bot
            main = Bot(token=MAIN_BOT_TOKEN)
            await main.send_message(
                chat_id=payer_id,
                text=(
                    "ℹ️ *Ma'lumot:*\n\n"
                    "Siz botga to'lov qilib qo'ygansiz, shuning uchun endi sizda *1 ta limit* bor. "
                    "Faqat bitta buyurtmachi yoki buyurtma oluvchi haqidagi ma'lumotni olishingiz mumkin. "
                    "Agar keyinchalik yana boshqa hamkor qidirmoqchi bo'lsangiz, qayta to'lov qilishingiz kerak bo'ladi."
                ),
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error(f"Limit xabari yuborishda xatolik: {e}")


# ─── BUYURTMANI O'CHIRISH: YAKUNIY TASDIQLASH ────────────────────────────────
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


# ─── ASOSIY ──────────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(ADMIN_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))

    # Admin: to'lovni tasdiqlash/rad etish
    app.add_handler(CallbackQueryHandler(payment_callback,       pattern=r"^pay_(ok|no)\|\d+$"))

    # Foydalanuvchi: "Ha, tugatdim" yoki "Yo'q, hali yo'q"
    app.add_handler(CallbackQueryHandler(finish_yes_callback,    pattern=r"^finish_yes\|\d+\|(payer|target)$"))
    app.add_handler(CallbackQueryHandler(finish_no_callback,     pattern=r"^finish_no\|\d+\|(payer|target)$"))

    # Foydalanuvchi: "Ha, o'chiring" yoki "Yo'q, qoldirib turing"
    app.add_handler(CallbackQueryHandler(delete_confirm_callback, pattern=r"^del_(confirm|cancel)\|\d+\|(payer|target)$"))

    logger.info("🚀 Logistik Tasdiqlash Boti ishga tushdi...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
