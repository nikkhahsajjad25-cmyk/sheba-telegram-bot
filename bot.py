import os
import re
import html
import requests
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters


CARDINFO_BASE_URL = "https://cardinfo.ir/inquiry/apiv1"

DEPOSIT_STATUS_MAP = {
    "02": "حساب فعال است",
    "03": "حساب مسدود با قابلیت واریز",
    "04": "حساب مسدود بدون قابلیت واریز",
    "05": "حساب راکد است",
    "06": "خطا در پاسخ‌دهی",
    "07": "سایر موارد",
}


def normalize_digits(text: str) -> str:
    fa_digits = "۰۱۲۳۴۵۶۷۸۹"
    ar_digits = "٠١٢٣٤٥٦٧٨٩"
    en_digits = "0123456789"

    trans_table = str.maketrans(
        fa_digits + ar_digits,
        en_digits + en_digits
    )

    return text.translate(trans_table).strip()


def clean_input(text: str) -> str:
    text = normalize_digits(text)
    text = text.replace(" ", "")
    text = text.replace("-", "")
    text = text.replace("_", "")
    return text.upper()


def detect_input_type(value: str):
    if re.fullmatch(r"\d{16}", value):
        return "card"

    if re.fullmatch(r"IR\d{24}", value):
        return "sheba"

    return None


def call_cardinfo(api_name: str, params: dict) -> dict:
    cardinfo_token = os.getenv("CARDINFO_API_TOKEN")

    if not cardinfo_token:
        raise RuntimeError("توکن CardInfo تنظیم نشده است.")

    headers = {
        "Authorization": f"Bearer {cardinfo_token}"
    }

    query_params = {
        "api": api_name,
        **params
    }

    response = requests.post(
        CARDINFO_BASE_URL,
        headers=headers,
        params=query_params,
        timeout=30
    )

    response.raise_for_status()

    try:
        return response.json()
    except Exception:
        raise RuntimeError("پاسخ دریافتی از سرویس JSON معتبر نیست.")


def safe(value):
    if value is None or value == "":
        return "-"
    return html.escape(str(value))


def format_result(data: dict, input_type: str) -> str:
    status_code = str(data.get("depositStatus", "")).strip()
    status_text = DEPOSIT_STATUS_MAP.get(status_code, "نامشخص")

    iban = data.get("IBAN") or data.get("iban")
    bank_name = data.get("bankName")
    deposit = data.get("deposit")
    card = data.get("card")
    owners = data.get("depositOwners")
    description = data.get("description") or data.get("message") or data.get("desc")

    title = "نتیجه استعلام کارت" if input_type == "card" else "نتیجه استعلام شبا"

    lines = [
        f"✅ <b>{safe(title)}</b>",
        "",
        f"🏦 <b>نام بانک:</b> {safe(bank_name)}",
        f"💳 <b>شماره کارت:</b> {safe(card)}",
        f"🔢 <b>شماره حساب:</b> {safe(deposit)}",
        f"🌐 <b>شماره شبا:</b> <code>{safe(iban)}</code>",
        f"👤 <b>صاحب/صاحبان حساب:</b> {safe(owners)}",
        f"📌 <b>وضعیت حساب:</b> {safe(status_code)} - {safe(status_text)}",
    ]

    if description:
        lines.append(f"📝 <b>توضیحات:</b> {safe(description)}")

    return "\n".join(lines)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = """
سلام 👋

شماره کارت یا شماره شبا را بفرست تا استعلام بگیرم.

نمونه شماره کارت:
<code>6037991199500590</code>

نمونه شبا:
<code>IR880170000000106000600006</code>
"""
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


async def credits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        cardinfo_token = os.getenv("CARDINFO_API_TOKEN")

        if not cardinfo_token:
            await update.message.reply_text("❌ توکن CardInfo تنظیم نشده است.")
            return

        response = requests.get(
            CARDINFO_BASE_URL,
            headers={"Authorization": f"Bearer {cardinfo_token}"},
            params={"action": "listCredits"},
            timeout=30
        )

        response.raise_for_status()
        data = response.json()

        if not isinstance(data, list) or not data:
            await update.message.reply_text("اعتباری پیدا نشد.")
            return

        lines = ["💰 <b>بسته‌های اعتباری:</b>", ""]

        for item in data:
            lines.append(f"📦 <b>بسته:</b> {safe(item.get('package_name'))}")
            lines.append(f"🔢 <b>مانده:</b> {safe(item.get('credit'))}")
            lines.append(f"🕒 <b>خرید:</b> {safe(item.get('order_time'))}")
            lines.append(f"⏳ <b>انقضا:</b> {safe(item.get('expire_time'))}")
            lines.append("")

        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

    except Exception as e:
        await update.message.reply_text(f"❌ خطا در دریافت اعتبار:\n{safe(e)}")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_text = update.message.text or ""
    value = clean_input(raw_text)
    input_type = detect_input_type(value)

    if input_type is None:
        await update.message.reply_text(
            "❌ ورودی معتبر نیست.\n\n"
            "شماره کارت باید ۱۶ رقم باشد.\n"
            "شماره شبا باید با IR شروع شود و ۲۶ کاراکتر باشد."
        )
        return

    try:
        await update.message.reply_text("⏳ در حال استعلام...")

        if input_type == "card":
            data = call_cardinfo("card_sheba", {"card": value})
        else:
            data = call_cardinfo("sheba_info", {"sheba": value})

        result_text = format_result(data, input_type)

        await update.message.reply_text(
            result_text,
            parse_mode=ParseMode.HTML
        )

    except requests.exceptions.HTTPError as e:
        await update.message.reply_text(f"❌ خطای HTTP از سرویس:\n{safe(e)}")
    except requests.exceptions.Timeout:
        await update.message.reply_text("❌ زمان پاسخ‌دهی سرویس طولانی شد. دوباره امتحان کنید.")
    except Exception as e:
        await update.message.reply_text(f"❌ خطا:\n{safe(e)}")


def main():
    telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")

    if not telegram_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN تنظیم نشده است.")

    app = ApplicationBuilder().token(telegram_token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("credits", credits))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
