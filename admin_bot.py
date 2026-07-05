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
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

# ─── SOZLAMALAR ────────────────────────────────────────────────────────────────
# BU TOKENNI @BotFather dan oling: /newbot → nomi: Logistik_tasdiqlash_bot
ADMIN_BOT_TOKEN = "8939855367:AAEWex_skRAjKhHQbD95R3E6COp6Q6AQkLQ"

# Asosiy botning tokeni (foydalanuvchilarga xabar yuborish uchun)
MAIN_BOT_TOKEN = "8841015797:AAGyauWuYzItmfRfy7QwUSj0PCw1WKSyVPo"

ADMIN_IDS = [8175344606, 5611922080, 1277637813]
PAYMENT_AMOUNT = 50_000
WAITING_REJECT_REASON = {}

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
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ Bu bot faqat admin (shoxa_0001) uchun. Siz foydalana olmaysiz.")
        return
    await update.message.reply_text(
        "👋 *Logistik Tasdiqlash Boti*\n\n"
        "Bu bot orqali siz:\n"
        "✅ To'lovlarni tasdiqlaysiz yoki rad etasiz\n"
        "📩 Foydalanuvchilarga 'Ish tugatdingizmi?' savoli avtomatik yuboriladi\n\n"
        "To'lov so'rovlari asosiy botdan avtomatik kelib turadi.",
        parse_mode="Markdown",
    )

async def reject_others(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ Kechirasiz, bu yopiq bot. Undan faqat tizim administratori foydalana oladi.")


# ─── ADMIN: TO'LOV TASDIQLASH / RAD ETISH ─────────────────────────────────────
async def payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if update.effective_user.id not in ADMIN_IDS:
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

        # ── Asosiy bot orqali payer ga kontakt + savol BITTA xabarda ──
        from telegram import Bot
        main = Bot(token=MAIN_BOT_TOKEN)

        finish_kb_payer = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Ha, tugatdim",  callback_data=f"finish_yes|{pay_id}|payer"),
            InlineKeyboardButton("❌ Yo'q, hali yo'q", callback_data=f"finish_no|{pay_id}|payer"),
        ]])

        combined_payer_msg = (
            f"✅ *To'lovingiz tasdiqlandi!*\n\n"
            f"🎉 *{opposite_label} ma'lumotlari:*\n\n"
            f"👤 Ism: *{target['full_name']}*\n"
            f"📞 Telefon: `{target['phone']}`\n"
            f"📦 Yuk turi: {target.get('cargo_type', 'Kiritilmagan')}\n"
            f"🔗 Telegram: {uname}\n\n"
            f"Muvaffaqiyatli hamkorlik tilaymiz! 🤝\n\n"
            f"─────────────────────\n"
            f"❓ *Savol:*\n\n"
            f"Siz ushbu *{target_role_label}* bilan bog'landingizmi?\n"
            f"Kelishib oldingizmi? Ish hal bo'ldimi?\n\n"
            f"_(Agar 'Ha' deb javob bersangiz, sizning buyurtmangiz bazadan o'chiriladi.)_"
        )
        try:
            await main.send_message(
                chat_id=payer_id,
                text=combined_payer_msg,
                parse_mode="Markdown",
                reply_markup=finish_kb_payer,
            )
        except Exception as e:
            logger.error(f"Payer ga birlashtirilgan xabar yuborishda xatolik: {e}")

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

        payer_name = payer['full_name'] if payer else "Noma'lum"
        payer_phone = payer['phone'] if payer else "-"
        await query.edit_message_text(
            f"✅ *To'lov #{pay_id} tasdiqlandi!*\n\n"
            f"👤 To'lovchi: {payer_name}\n"
            f"📞 Telefon: {payer_phone}\n\n"
            f"📩 Ikkala foydalanuvchiga kontakt va 'Ish tugatdingizmi?' savoli yuborildi.",
            parse_mode="Markdown",
        )

    elif action == "pay_no":
        WAITING_REJECT_REASON[update.effective_user.id] = {"pay_id": pay_id, "payer_id": payer_id}
        skip_kb = InlineKeyboardMarkup([[InlineKeyboardButton("O'tkazib yuborish", callback_data=f"skip_reason|{pay_id}")]])
        await query.edit_message_text(
            f"❌ To'lov #{pay_id} ni rad etyapsiz.\n\n"
            f"Foydalanuvchiga nima sababdan rad etilganini yozib yuboring.\n"
            f"(Yoki sababsiz rad etish uchun 'O'tkazib yuborish' tugmasini bosing)",
            reply_markup=skip_kb
        )


# ─── FOYDALANUVCHI: "ISH TUGATDINGIZMI?" JAVOBLARI ───────────────────────────
async def send_rejection_to_user(payer_id, reason):
    from telegram import Bot, InlineKeyboardMarkup, InlineKeyboardButton
    main = Bot(token=MAIN_BOT_TOKEN)
    retry_kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔄 Qayta urinish", callback_data=f"retry_payment|{payer_id}"),
        InlineKeyboardButton("🔙 Orqaga qaytish", callback_data=f"back_to_menu|{payer_id}"),
    ]])
    if reason:
        text = (
            f"❌ *Uzur so'raymiz, admin to'lovni tasdiqlamadi!*\n\n"
            f"❗️ *Sabab:* {reason}\n\n"
            f"Siz aynan bizning karta raqamimizga naqd {PAYMENT_AMOUNT:,} UZS o'tkazganingizga ishonch hosil qiling.\n"
            f"💳 Karta: `9860 0801 9212 8785`"
        )
    else:
        text = (
            f"❌ *Uzur so'raymiz, admin to'lovni tasdiqlamadi.*\n\n"
            f"To'lov amalga oshirilmagan yoki to'lovda xatolik bor.\n"
            f"Siz aynan bizning karta raqamimizga naqd {PAYMENT_AMOUNT:,} UZS o'tkazganingizga ishonch hosil qiling.\n"
            f"💳 Karta: `9860 0801 9212 8785`"
        )
    try:
        await main.send_message(chat_id=payer_id, text=text, parse_mode="Markdown", reply_markup=retry_kb)
    except Exception as e:
        logger.error(f"Xatolik: {e}")

async def handle_admin_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = update.effective_user.id
    if admin_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Kechirasiz, bu yopiq bot. Undan faqat tizim administratori foydalana oladi.")
        return

    if admin_id in WAITING_REJECT_REASON:
        state = WAITING_REJECT_REASON.pop(admin_id)
        reason = update.message.text
        payer_id = state["payer_id"]
        pay_id = state["pay_id"]
        await send_rejection_to_user(payer_id, reason)
        await update.message.reply_text(f"✅ To'lov #{pay_id} rad etildi va foydalanuvchiga xabar yuborildi.")
        return

    await update.message.reply_text("👋 Xabar qabul qilindi. Tasdiqlash uchun to'lovlarni kuting.")

async def skip_reason_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    parts = query.data.split("|")
    pay_id = int(parts[1])
    admin_id = update.effective_user.id
    
    if admin_id in WAITING_REJECT_REASON:
        state = WAITING_REJECT_REASON.pop(admin_id)
        payer_id = state["payer_id"]
        
        await send_rejection_to_user(payer_id, None)
        await query.edit_message_text(f"✅ To'lov #{pay_id} sababsiz rad etildi va foydalanuvchiga xabar yuborildi.")

# ─── ASOSIY ──────────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(ADMIN_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))

    # Admin: to'lovni tasdiqlash/rad etish
    app.add_handler(CallbackQueryHandler(payment_callback,       pattern=r"^pay_(ok|no)\|\d+$"))

    app.add_handler(CallbackQueryHandler(skip_reason_callback,   pattern=r"^skip_reason\|\d+$"))

    # Matnli xabarlar uchun (rad etish sababini yozish)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_message))

    # Boshqa begona odamlarni rad etish
    app.add_handler(MessageHandler(filters.ALL, reject_others))

    logger.info("🚀 Logistik Tasdiqlash Boti ishga tushdi...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
