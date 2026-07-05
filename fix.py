import sys

def patch():
    with open('admin_bot.py', 'r', encoding='utf-8') as f:
        content = f.read()

    idx_pay_no = content.find('    elif action == "pay_no":')
    idx_main = content.find('# ─── ASOSIY ──────────────────────────────────────────────────────────────────')

    part1 = content[:idx_pay_no]

    new_pay_no_and_logic = """    elif action == "pay_no":
        WAITING_REJECT_REASON[ADMIN_ID] = {"pay_id": pay_id, "payer_id": payer_id}
        skip_kb = InlineKeyboardMarkup([[InlineKeyboardButton("O'tkazib yuborish", callback_data=f"skip_reason|{pay_id}")]])
        await query.edit_message_text(
            f"❌ To'lov #{pay_id} ni rad etyapsiz.\\n\\n"
            f"Foydalanuvchiga nima sababdan rad etilganini yozib yuboring.\\n"
            f"(Yoki sababsiz rad etish uchun 'O'tkazib yuborish' tugmasini bosing)",
            reply_markup=skip_kb
        )


async def send_rejection_to_user(payer_id, reason):
    from telegram import Bot
    main = Bot(token=MAIN_BOT_TOKEN)
    PAYMENT_CARD = "9860 1601 3067 3512"
    if reason:
        text = (
            f"❌ *Uzur so'raymiz, admin to'lovni tasdiqlamadi!*\\n\\n"
            f"❗️ *Sabab:* {reason}\\n\\n"
            f"Siz aynan bizning karta raqamimizga naqd {PAYMENT_AMOUNT:,} UZS o'tkazganingizga ishonch hosil qiling.\\n"
            f"💳 Karta: `{PAYMENT_CARD}`"
        )
    else:
        text = (
            f"❌ *Uzur so'raymiz, admin to'lovni tasdiqlamadi.*\\n\\n"
            f"To'lov amalga oshirilmagan yoki to'lovda xatolik bor.\\n"
            f"Siz aynan bizning karta raqamimizga naqd {PAYMENT_AMOUNT:,} UZS o'tkazganingizga ishonch hosil qiling.\\n"
            f"💳 Karta: `{PAYMENT_CARD}`"
        )
    try:
        await main.send_message(chat_id=payer_id, text=text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Xatolik: {e}")


async def handle_admin_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = update.effective_user.id
    if admin_id != ADMIN_ID:
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
    
    if ADMIN_ID in WAITING_REJECT_REASON:
        state = WAITING_REJECT_REASON.pop(ADMIN_ID)
        payer_id = state["payer_id"]
        
        await send_rejection_to_user(payer_id, None)
        await query.edit_message_text(f"✅ To'lov #{pay_id} sababsiz rad etildi va foydalanuvchiga xabar yuborildi.")


"""

    part3 = content[idx_main:]

    part3 = part3.replace(
        '''    # Foydalanuvchi: "Ha, tugatdim" yoki "Yo'q, hali yo'q"
    app.add_handler(CallbackQueryHandler(finish_yes_callback,    pattern=r"^finish_yes\|\d+\|(payer|target)$"))
    app.add_handler(CallbackQueryHandler(finish_no_callback,     pattern=r"^finish_no\|\d+\|(payer|target)$"))

    # Foydalanuvchi: "Ha, o'chiring" yoki "Yo'q, qoldirib turing"
    app.add_handler(CallbackQueryHandler(delete_confirm_callback, pattern=r"^del_(confirm|cancel)\|\d+\|(payer|target)$"))

    # Boshqa begona odamlar botga nimadir yozsa, rad etish
    app.add_handler(MessageHandler(filters.ALL, reject_others))''',
        '''    app.add_handler(CallbackQueryHandler(skip_reason_callback,   pattern=r"^skip_reason\|\d+$"))

    # Matnli xabarlar uchun (rad etish sababini yozish)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_message))

    # Boshqa begona odamlarni rad etish
    app.add_handler(MessageHandler(filters.ALL, reject_others))'''
    )

    with open('admin_bot.py', 'w', encoding='utf-8') as f:
        f.write(part1 + new_pay_no_and_logic + part3)

if __name__ == '__main__':
    patch()
