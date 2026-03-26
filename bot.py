#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════╗
║   🤖  GROUP JOIN APPLICATION BOT  v2.0      ║
║       Modern · Secure · Multi-Admin          ║
╚══════════════════════════════════════════════╝

Автор: @YourBot  |  python-telegram-bot v20+
"""

import asyncio
import logging
import re
import os
import threading
from aiohttp import web
from datetime import datetime
from typing import Dict

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
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
from telegram.constants import ParseMode

# ═══════════════════════════════════════════════════════════════
#  ⚙️  НАЛАШТУВАННЯ — Змініть ці значення
BOT_TOKEN = os.getenv("BOT_TOKEN")
GROUP_CHAT_ID = int(os.getenv("GROUP_CHAT_ID"))
GROUP_NAME = os.getenv("GROUP_NAME")  # значение по умолчанию

# ADMIN_IDS — храним в переменной как строку через запятую, потом преобразуем
admin_ids_str = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = [int(x.strip()) for x in admin_ids_str.split(",") if x.strip()]

# ═══════════════════════════════════════════════════════════════
#  📊  СТАНИ РОЗМОВИ
# ═══════════════════════════════════════════════════════════════

NAME, SURNAME, CITY, REVIEW, CONTACT = range(5)

# ═══════════════════════════════════════════════════════════════
#  💾  СХОВИЩЕ ДАНИХ (in-memory)
# ═══════════════════════════════════════════════════════════════

applications: Dict[str, dict] = {}
_app_counter: int = 0
stats: Dict[str, int] = {
    "total": 0,
    "pending": 0,
    "approved": 0,
    "rejected": 0,
}

# ═══════════════════════════════════════════════════════════════
#  🪵  ЛОГУВАННЯ
# ═══════════════════════════════════════════════════════════════

logging.basicConfig(
    format="%(asctime)s │ %(levelname)-8s │ %(name)s │ %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
#  🛠️  УТИЛІТИ
# ═══════════════════════════════════════════════════════════════
def run_http_server_sync():
    """Запускає HTTP-сервер в окремому потоці."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    app = web.Application()
    app.router.add_get('/ping', lambda request: web.Response(text="OK"))

    runner = web.AppRunner(app)
    loop.run_until_complete(runner.setup())
    port = int(os.environ.get("PORT", 8000))
    site = web.TCPSite(runner, '0.0.0.0', port)
    loop.run_until_complete(site.start())

    print(f"🌐 HTTP-сервер запущено на порту {port} (у окремому потоці)")
    loop.run_forever()

def progress_bar(step: int, total: int = 5) -> str:
    """Прогрес-бар: ████░░ 4/5"""
    filled = "█" * step
    empty = "░" * (total - step)
    return f"{filled}{empty}  <b>{step}/{total}</b>"


def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS


def new_app_id() -> str:
    global _app_counter
    _app_counter += 1
    return f"APP{_app_counter:04d}"


def validate_name(text: str) -> bool:
    """Ім'я/прізвище: тільки літери (укр/рос/англ), дефіс, апостроф. 2–50 символів."""
    return bool(re.match(r"^[a-zA-Zа-яА-ЯіІїЇєЄґҐ''\-]{2,50}$", text.strip()))


def validate_city(text: str) -> bool:
    """Місто/село: літери, пробіли, дефіс, крапка. 2–100 символів."""
    return bool(re.match(r"^[a-zA-Zа-яА-ЯіІїЇєЄґҐ\s''\-\.]{2,100}$", text.strip()))


async def try_delete(msg) -> None:
    try:
        await msg.delete()
    except Exception:
        pass


async def delayed_delete(msg, seconds: float = 4.0) -> None:
    await asyncio.sleep(seconds)
    await try_delete(msg)


async def edit_main(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    msg_id: int,
    text: str,
    kb=None,
) -> None:
    """Редагує головне повідомлення анкети."""
    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=msg_id,
            text=text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.warning(f"edit_main: {e}")


async def warn(context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str) -> None:
    """Надсилає тимчасове попередження, яке автоматично видаляється."""
    msg = await context.bot.send_message(
        chat_id=chat_id,
        text=f"⚠️ {text}",
        parse_mode=ParseMode.HTML,
    )
    asyncio.create_task(delayed_delete(msg, 4))


# ═══════════════════════════════════════════════════════════════
#  🏠  /START
# ═══════════════════════════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    context.user_data.clear()

    text = (
        f"👋 <b>Привіт, {user.first_name}!</b>\n"
        f"{'─' * 30}\n\n"
        f"🏆 Хочеш потрапити до закритої\n"
        f"спільноти <b>« {GROUP_NAME} »</b>?\n\n"
        f"📋 <b>Що потрібно зробити:</b>\n"
        f"  ➊  Заповнити анкету — 3 поля\n"
        f"  ➋  Поділитися номером телефону\n"
        f"  ➌  Дочекатися рішення адміна\n\n"
        f"⚡ Займе <b>лише 1–2 хвилини</b>!"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝  Надіслати заявку", callback_data="apply")],
        [InlineKeyboardButton("ℹ️  Про спільноту", callback_data="about")],
    ])
    if update.message:
        await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


async def cb_about(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    text = (
        f"🌟 <b>Про « {GROUP_NAME} »</b>\n"
        f"{'─' * 30}\n\n"
        f"Закрита спільнота перевірених людей.\n"
        f"Кожен учасник проходить ручну верифікацію.\n\n"
        f"🔒  Тільки перевірені учасники\n"
        f"💬  Активне спілкування\n"
        f"🚀  Корисний та ексклюзивний контент\n"
        f"🤝  Підтримка та нетворкінг\n\n"
        f"<i>Готовий? Тисни кнопку нижче!</i> 👇"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝  Надіслати заявку", callback_data="apply")],
        [InlineKeyboardButton("◀️  Назад", callback_data="home")],
    ])
    await q.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


async def cb_home(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    user = q.from_user
    text = (
        f"👋 <b>Привіт, {user.first_name}!</b>\n"
        f"{'─' * 30}\n\n"
        f"🏆 Хочеш потрапити до закритої\n"
        f"спільноти <b>« {GROUP_NAME} »</b>?\n\n"
        f"📋 <b>Що потрібно зробити:</b>\n"
        f"  ➊  Заповнити анкету — 3 поля\n"
        f"  ➋  Поділитися номером телефону\n"
        f"  ➌  Дочекатися рішення адміна\n\n"
        f"⚡ Займе <b>лише 1–2 хвилини</b>!"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝  Надіслати заявку", callback_data="apply")],
        [InlineKeyboardButton("ℹ️  Про спільноту", callback_data="about")],
    ])
    await q.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


# ═══════════════════════════════════════════════════════════════
#  📝  КРОК 1 — ІМ'Я
# ═══════════════════════════════════════════════════════════════

async def cb_apply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()

    context.user_data.clear()
    context.user_data["main_msg_id"] = q.message.message_id
    context.user_data["chat_id"] = q.message.chat_id
    context.user_data["editing"] = False

    text = (
        f"📝 <b>Заявка на вступ</b>\n"
        f"{'─' * 30}\n\n"
        f"🔸 {progress_bar(1)}\n\n"
        f"👤 Введіть ваше <b>Ім'я</b>:\n\n"
        f"<i>💡 Тільки літери, 2–50 символів</i>"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌  Скасувати", callback_data="cancel")],
    ])
    await q.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    return NAME


async def handle_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw = update.message.text.strip()
    chat_id = context.user_data.get("chat_id", update.effective_chat.id)
    msg_id = context.user_data.get("main_msg_id")

    await try_delete(update.message)

    if not validate_name(raw):
        await warn(
            context, chat_id,
            "<b>Некоректне ім'я!</b>\n\n"
            "Дозволено тільки літери (укр/англ), 2–50 символів.\n"
            "<i>Спробуйте ще раз:</i>"
        )
        return NAME

    context.user_data["name"] = raw.capitalize()

    if context.user_data.get("editing"):
        context.user_data["editing"] = False
        await _show_review(context, chat_id, msg_id)
        return REVIEW

    text = (
        f"📝 <b>Заявка на вступ</b>\n"
        f"{'─' * 30}\n\n"
        f"🔸 {progress_bar(2)}\n\n"
        f"✅ Ім'я: <b>{context.user_data['name']}</b>\n\n"
        f"👤 Введіть ваше <b>Прізвище</b>:\n\n"
        f"<i>💡 Тільки літери, 2–50 символів</i>"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️  Змінити ім'я", callback_data="back_name")],
        [InlineKeyboardButton("❌  Скасувати", callback_data="cancel")],
    ])
    await edit_main(context, chat_id, msg_id, text, kb)
    return SURNAME


# ═══════════════════════════════════════════════════════════════
#  📝  КРОК 2 — ПРІЗВИЩЕ
# ═══════════════════════════════════════════════════════════════

async def handle_surname(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw = update.message.text.strip()
    chat_id = context.user_data.get("chat_id", update.effective_chat.id)
    msg_id = context.user_data.get("main_msg_id")

    await try_delete(update.message)

    if not validate_name(raw):
        await warn(
            context, chat_id,
            "<b>Некоректне прізвище!</b>\n\n"
            "Дозволено тільки літери (укр/англ), 2–50 символів.\n"
            "<i>Спробуйте ще раз:</i>"
        )
        return SURNAME

    context.user_data["surname"] = raw.capitalize()

    if context.user_data.get("editing"):
        context.user_data["editing"] = False
        await _show_review(context, chat_id, msg_id)
        return REVIEW

    text = (
        f"📝 <b>Заявка на вступ</b>\n"
        f"{'─' * 30}\n\n"
        f"🔸 {progress_bar(3)}\n\n"
        f"✅ Ім'я:       <b>{context.user_data['name']}</b>\n"
        f"✅ Прізвище: <b>{context.user_data['surname']}</b>\n\n"
        f"🏘️ Введіть ваше <b>Місто або Село</b>:\n\n"
        f"<i>💡 Наприклад: Київ, Рівне, Дубно, Радивилів</i>"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️  Змінити прізвище", callback_data="back_surname")],
        [InlineKeyboardButton("❌  Скасувати", callback_data="cancel")],
    ])
    await edit_main(context, chat_id, msg_id, text, kb)
    return CITY


# ═══════════════════════════════════════════════════════════════
#  📝  КРОК 3 — МІСТО/СЕЛО
# ═══════════════════════════════════════════════════════════════

async def handle_city(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw = update.message.text.strip()
    chat_id = context.user_data.get("chat_id", update.effective_chat.id)
    msg_id = context.user_data.get("main_msg_id")

    await try_delete(update.message)

    if not validate_city(raw):
        await warn(
            context, chat_id,
            "<b>Некоректна назва!</b>\n\n"
            "Введіть назву міста або села (2–100 символів).\n"
            "<i>Спробуйте ще раз:</i>"
        )
        return CITY

    context.user_data["city"] = raw.strip().title()
    context.user_data["editing"] = False
    await _show_review(context, chat_id, msg_id)
    return REVIEW


# ═══════════════════════════════════════════════════════════════
#  🔍  ОГЛЯД ДАНИХ (Review)
# ═══════════════════════════════════════════════════════════════

async def _show_review(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    msg_id: int,
) -> None:
    d = context.user_data
    text = (
        f"🔍 <b>Перевірте ваші дані</b>\n"
        f"{'─' * 30}\n\n"
        f"🔸 {progress_bar(3)}\n\n"
        f"👤 Ім'я:           <b>{d.get('name', '—')}</b>\n"
        f"👤 Прізвище:    <b>{d.get('surname', '—')}</b>\n"
        f"🏘️ Місто/Село:  <b>{d.get('city', '—')}</b>\n\n"
        f"<i>Усе вірно? Натисніть «Підтвердити» ✅\n"
        f"Або відредагуйте потрібне поле нижче.</i>"
    )
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✏️ Ім'я", callback_data="edit_name"),
            InlineKeyboardButton("✏️ Прізвище", callback_data="edit_surname"),
            InlineKeyboardButton("✏️ Місто", callback_data="edit_city"),
        ],
        [InlineKeyboardButton("✅  Підтвердити та продовжити →", callback_data="confirm_data")],
        [InlineKeyboardButton("❌  Скасувати", callback_data="cancel")],
    ])
    await edit_main(context, chat_id, msg_id, text, kb)


# ── Редагування з огляду ─────────────────────────────────────

async def cb_edit_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    context.user_data["editing"] = True
    chat_id = context.user_data["chat_id"]
    msg_id = context.user_data["main_msg_id"]
    text = (
        f"✏️ <b>Редагування — Ім'я</b>\n"
        f"{'─' * 30}\n\n"
        f"Поточне: <b>{context.user_data.get('name', '—')}</b>\n\n"
        f"Введіть нове ім'я:"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️  Повернутися", callback_data="back_to_review")],
    ])
    await edit_main(context, chat_id, msg_id, text, kb)
    return NAME


async def cb_edit_surname(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    context.user_data["editing"] = True
    chat_id = context.user_data["chat_id"]
    msg_id = context.user_data["main_msg_id"]
    text = (
        f"✏️ <b>Редагування — Прізвище</b>\n"
        f"{'─' * 30}\n\n"
        f"Поточне: <b>{context.user_data.get('surname', '—')}</b>\n\n"
        f"Введіть нове прізвище:"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️  Повернутися", callback_data="back_to_review")],
    ])
    await edit_main(context, chat_id, msg_id, text, kb)
    return SURNAME


async def cb_edit_city(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    context.user_data["editing"] = True
    chat_id = context.user_data["chat_id"]
    msg_id = context.user_data["main_msg_id"]
    text = (
        f"✏️ <b>Редагування — Місто/Село</b>\n"
        f"{'─' * 30}\n\n"
        f"Поточне: <b>{context.user_data.get('city', '—')}</b>\n\n"
        f"Введіть нову назву:"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️  Повернутися", callback_data="back_to_review")],
    ])
    await edit_main(context, chat_id, msg_id, text, kb)
    return CITY


async def cb_back_to_review(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    context.user_data["editing"] = False
    chat_id = context.user_data["chat_id"]
    msg_id = context.user_data["main_msg_id"]
    await _show_review(context, chat_id, msg_id)
    return REVIEW


# ── Повернення назад (зі кроків 2 та 3) ─────────────────────

async def cb_back_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Крок 2 → повернутися до кроку 1 (ім'я)."""
    q = update.callback_query
    await q.answer()
    context.user_data["editing"] = False
    chat_id = context.user_data["chat_id"]
    msg_id = context.user_data["main_msg_id"]
    text = (
        f"📝 <b>Заявка на вступ</b>\n"
        f"{'─' * 30}\n\n"
        f"🔸 {progress_bar(1)}\n\n"
        f"👤 Введіть ваше <b>Ім'я</b>:\n\n"
        f"<i>💡 Тільки літери, 2–50 символів</i>"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌  Скасувати", callback_data="cancel")],
    ])
    await edit_main(context, chat_id, msg_id, text, kb)
    return NAME


async def cb_back_surname(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Крок 3 → повернутися до кроку 2 (прізвище)."""
    q = update.callback_query
    await q.answer()
    context.user_data["editing"] = False
    chat_id = context.user_data["chat_id"]
    msg_id = context.user_data["main_msg_id"]
    text = (
        f"📝 <b>Заявка на вступ</b>\n"
        f"{'─' * 30}\n\n"
        f"🔸 {progress_bar(2)}\n\n"
        f"✅ Ім'я: <b>{context.user_data.get('name', '—')}</b>\n\n"
        f"👤 Введіть ваше <b>Прізвище</b>:\n\n"
        f"<i>💡 Тільки літери, 2–50 символів</i>"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️  Змінити ім'я", callback_data="back_name")],
        [InlineKeyboardButton("❌  Скасувати", callback_data="cancel")],
    ])
    await edit_main(context, chat_id, msg_id, text, kb)
    return SURNAME


# ─────────────────────────────────────────────────────────────
# Відхилення стороннього тексту під час REVIEW
# ─────────────────────────────────────────────────────────────

async def handle_text_in_review(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Видаляє будь-який текст і нагадує користуватись кнопками."""
    await try_delete(update.message)
    chat_id = context.user_data.get("chat_id", update.effective_chat.id)
    await warn(context, chat_id, "Використовуйте кнопки нижче 👆")
    return REVIEW


# ═══════════════════════════════════════════════════════════════
#  📱  КРОК 4 — КОНТАКТ
# ═══════════════════════════════════════════════════════════════

async def cb_confirm_data(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()

    chat_id = context.user_data["chat_id"]
    msg_id = context.user_data["main_msg_id"]

    text = (
        f"📱 <b>Заявка на вступ</b>\n"
        f"{'─' * 30}\n\n"
        f"🔸 {progress_bar(4)}\n\n"
        f"Натисніть кнопку нижче щоб\n"
        f"<b>поділитися номером телефону</b>.\n\n"
        f"🔒 <i>Номер бачать лише адміністратори.\n"
        f"Введення вручну — заборонено.</i>"
    )
    kb_inline = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌  Скасувати", callback_data="cancel")],
    ])
    await edit_main(context, chat_id, msg_id, text, kb_inline)

    kb_reply = ReplyKeyboardMarkup(
        [[KeyboardButton("📱  Поділитися контактом", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    prompt = await context.bot.send_message(
        chat_id=chat_id,
        text="👇 <b>Натисніть кнопку:</b>",
        reply_markup=kb_reply,
        parse_mode=ParseMode.HTML,
    )
    context.user_data["contact_prompt_id"] = prompt.message_id
    return CONTACT


async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    contact = update.message.contact
    user_id = update.effective_user.id
    chat_id = context.user_data.get("chat_id", update.effective_chat.id)
    msg_id = context.user_data.get("main_msg_id")

    # 🔐 БЕЗПЕКА: перевіряємо, що контакт належить самому користувачу
    if contact.user_id != user_id:
        await try_delete(update.message)
        await warn(context, chat_id, "<b>Поділіться СВОЇМ контактом!</b>")
        return CONTACT

    phone = contact.phone_number
    if not phone.startswith("+"):
        phone = "+" + phone
    context.user_data["phone"] = phone

    # Прибираємо повідомлення та клавіатуру
    await try_delete(update.message)
    if cid := context.user_data.get("contact_prompt_id"):
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=cid)
        except Exception:
            pass

    tmp = await context.bot.send_message(
        chat_id=chat_id, text="✔", reply_markup=ReplyKeyboardRemove()
    )
    await try_delete(tmp)

    # Фінальний екран перед відправкою
    d = context.user_data
    text = (
        f"🚀 <b>Заявка на вступ</b>\n"
        f"{'─' * 30}\n\n"
        f"🔸 {progress_bar(5)}\n\n"
        f"📋 <b>Ваша анкета:</b>\n\n"
        f"  👤 Ім'я:           <b>{d.get('name')}</b>\n"
        f"  👤 Прізвище:    <b>{d.get('surname')}</b>\n"
        f"  🏘️ Місто/Село:  <b>{d.get('city')}</b>\n"
        f"  📱 Телефон:     <b>{phone}</b>\n\n"
        f"<i>Перевірте дані та натисніть «Надіслати» 🚀</i>"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀  Надіслати заявку!", callback_data="submit")],
        [InlineKeyboardButton("❌  Скасувати", callback_data="cancel")],
    ])
    await edit_main(context, chat_id, msg_id, text, kb)
    return CONTACT


async def handle_text_in_contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """🔒 Блокуємо ручне введення телефону."""
    await try_delete(update.message)
    chat_id = context.user_data.get("chat_id", update.effective_chat.id)
    await warn(
        context, chat_id,
        "🔒 <b>Введення вручну заборонено!</b>\n\n"
        "Натисніть кнопку «📱 Поділитися контактом» нижче."
    )
    return CONTACT


# ═══════════════════════════════════════════════════════════════
#  🚀  ВІДПРАВКА ЗАЯВКИ
# ═══════════════════════════════════════════════════════════════

async def cb_submit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer("⏳ Надсилаємо заявку...")

    user = q.from_user
    d = context.user_data
    chat_id = d["chat_id"]
    msg_id = d["main_msg_id"]

    app_id = new_app_id()
    phone: str = d.get("phone", "")
    phone_digits = re.sub(r"[^\d]", "", phone)

    app_data = {
        "id": app_id,
        "user_id": user.id,
        "username": user.username,
        "first_name": user.first_name,
        "name": d.get("name"),
        "surname": d.get("surname"),
        "city": d.get("city"),
        "phone": phone,
        "submitted_at": datetime.now().strftime("%d.%m.%Y %H:%M"),
        "status": "pending",
        "admin_msg_ids": {},  # admin_id → message_id для оновлення статусу
    }
    applications[app_id] = app_data
    stats["total"] += 1
    stats["pending"] += 1

    # ── Повідомлення для користувача ──────────────────────────
    ok_text = (
        f"✅ <b>Заявку надіслано!</b>\n"
        f"{'─' * 30}\n\n"
        f"🎉 Заявка <code>{app_id}</code> отримана!\n\n"
        f"⏳ <b>Очікуйте рішення адміністратора.</b>\n"
        f"Ми надішлемо сповіщення одразу після розгляду.\n\n"
        f"<i>Дякуємо за інтерес до нашої спільноти! 🙏</i>"
    )
    kb_user = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄  Подати нову заявку", callback_data="apply")],
    ])
    await edit_main(context, chat_id, msg_id, ok_text, kb_user)

    # ── Повідомлення для адмінів ──────────────────────────────
    uname_display = (
        f"@{user.username}" if user.username
        else f'<a href="tg://user?id={user.id}">{user.first_name}</a>'
    )
    phone_link = (
        f'<a href="https://t.me/+{phone_digits}">{phone}</a>'
        if phone_digits else phone
    )

    admin_text = (
        f"🔔 <b>НОВА ЗАЯВКА  ·  {app_id}</b>\n"
        f"{'━' * 30}\n\n"
        f"  👤 <b>Ім'я:</b>            {d.get('name')} {d.get('surname')}\n"
        f"  🏘️ <b>Місто/Село:</b>   {d.get('city')}\n"
        f"  📱 <b>Телефон:</b>      {phone_link}\n"
        f"  🔗 <b>Акаунт:</b>       {uname_display}\n"
        f"  🆔 <b>User ID:</b>      <code>{user.id}</code>\n"
        f"  📅 <b>Час:</b>            {app_data['submitted_at']}\n"
        f"{'━' * 30}\n"
        f"<i>Оберіть рішення:</i>"
    )
    admin_kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅  Схвалити", callback_data=f"approve|{app_id}"),
            InlineKeyboardButton("❌  Відхилити", callback_data=f"reject|{app_id}"),
        ],
    ])

    for admin_id in ADMIN_IDS:
        try:
            sent = await context.bot.send_message(
                chat_id=admin_id,
                text=admin_text,
                reply_markup=admin_kb,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
            app_data["admin_msg_ids"][admin_id] = sent.message_id
        except Exception as e:
            logger.warning(f"Cannot notify admin {admin_id}: {e}")

    context.user_data.clear()
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════════════
#  ✅  АДМІН: СХВАЛЕННЯ ЗАЯВКИ
# ═══════════════════════════════════════════════════════════════

async def cb_approve(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query

    if not is_admin(q.from_user.id):
        await q.answer("⛔ Недостатньо прав!", show_alert=True)
        return

    _, app_id = q.data.split("|", 1)
    app = applications.get(app_id)

    if not app:
        await q.answer("⚠️ Заявку не знайдено!", show_alert=True)
        return
    if app["status"] != "pending":
        label = "схвалена ✅" if app["status"] == "approved" else "відхилена ❌"
        await q.answer(f"Заявка вже {label}", show_alert=True)
        return

    app["status"] = "approved"
    stats["pending"] -= 1
    stats["approved"] += 1

    # Генеруємо одноразове запрошення
    invite_link: str | None = None
    try:
        lnk = await context.bot.create_chat_invite_link(
            chat_id=GROUP_CHAT_ID,
            member_limit=1,
            name=f"Заявка {app_id}",
        )
        invite_link = lnk.invite_link
    except Exception as e:
        logger.warning(f"Cannot create invite link: {e}")

    admin_name = q.from_user.username or q.from_user.first_name
    new_text = (
        q.message.text
        + f"\n\n{'━' * 30}\n"
        + f"✅ <b>СХВАЛЕНО</b>  ·  @{admin_name}"
    )

    # Оновлюємо повідомлення у ВСІХ адмінів
    for admin_id, msg_id in app.get("admin_msg_ids", {}).items():
        try:
            await context.bot.edit_message_text(
                chat_id=admin_id,
                message_id=msg_id,
                text=new_text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except Exception:
            pass

    await q.answer("✅ Заявку схвалено!")

    # Повідомляємо користувача
    if invite_link:
        user_msg = (
            f"🎉 <b>Заявку схвалено!</b>\n"
            f"{'─' * 30}\n\n"
            f"✅ Заявка <code>{app_id}</code> — схвалена!\n\n"
            f"🔗 <b>Ваше посилання для входу в групу:</b>\n"
            f"{invite_link}\n\n"
            f"⚠️ <i>Посилання одноразове!\n"
            f"Нікому не передавайте його.</i>"
        )
    else:
        user_msg = (
            f"🎉 <b>Заявку схвалено!</b>\n"
            f"{'─' * 30}\n\n"
            f"✅ Заявка <code>{app_id}</code> — схвалена!\n\n"
            f"Незабаром адміністратор надішле вам посилання."
        )
    try:
        await context.bot.send_message(
            chat_id=app["user_id"],
            text=user_msg,
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        logger.warning(f"Cannot notify user {app['user_id']}: {e}")


# ═══════════════════════════════════════════════════════════════
#  ❌  АДМІН: ВІДХИЛЕННЯ ЗАЯВКИ
# ═══════════════════════════════════════════════════════════════

async def cb_reject(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query

    if not is_admin(q.from_user.id):
        await q.answer("⛔ Недостатньо прав!", show_alert=True)
        return

    _, app_id = q.data.split("|", 1)
    app = applications.get(app_id)

    if not app:
        await q.answer("⚠️ Заявку не знайдено!", show_alert=True)
        return
    if app["status"] != "pending":
        label = "схвалена ✅" if app["status"] == "approved" else "відхилена ❌"
        await q.answer(f"Заявка вже {label}", show_alert=True)
        return

    app["status"] = "rejected"
    stats["pending"] -= 1
    stats["rejected"] += 1

    admin_name = q.from_user.username or q.from_user.first_name
    new_text = (
        q.message.text
        + f"\n\n{'━' * 30}\n"
        + f"❌ <b>ВІДХИЛЕНО</b>  ·  @{admin_name}"
    )

    for admin_id, msg_id in app.get("admin_msg_ids", {}).items():
        try:
            await context.bot.edit_message_text(
                chat_id=admin_id,
                message_id=msg_id,
                text=new_text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except Exception:
            pass

    await q.answer("❌ Заявку відхилено!")

    try:
        await context.bot.send_message(
            chat_id=app["user_id"],
            text=(
                f"😔 <b>Заявку відхилено</b>\n"
                f"{'─' * 30}\n\n"
                f"На жаль, заявка <code>{app_id}</code> — відхилена.\n\n"
                f"Якщо маєте питання — зверніться до адміністратора."
            ),
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        logger.warning(f"Cannot notify user {app['user_id']}: {e}")


# ═══════════════════════════════════════════════════════════════
#  🛡️  АДМІН-ПАНЕЛЬ  /admin
# ═══════════════════════════════════════════════════════════════

async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Доступ заборонено.")
        return
    await _send_admin_panel(update.effective_chat.id, context, via_message=True)


async def _send_admin_panel(
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    via_message: bool = False,
    msg_id: int | None = None,
) -> None:
    pending_list = [a for a in applications.values() if a["status"] == "pending"]
    approved_list = [a for a in applications.values() if a["status"] == "approved"]
    rejected_list = [a for a in applications.values() if a["status"] == "rejected"]

    text = (
        f"🛡️ <b>Адмін-панель</b>\n"
        f"{'━' * 30}\n\n"
        f"📊 <b>Загальна статистика:</b>\n"
        f"  📥 Всього заявок:    <b>{stats['total']}</b>\n"
        f"  ⏳ Очікують:              <b>{stats['pending']}</b>\n"
        f"  ✅ Схвалено:             <b>{stats['approved']}</b>\n"
        f"  ❌ Відхилено:            <b>{stats['rejected']}</b>\n"
        f"{'━' * 30}\n\n"
    )

    if pending_list:
        text += f"⏳ <b>Очікують розгляду ({len(pending_list)}):</b>\n\n"
        for a in pending_list[-10:]:
            uname = f"@{a['username']}" if a.get("username") else f"ID:{a['user_id']}"
            text += (
                f"  🔸 <code>{a['id']}</code> — "
                f"{a['name']} {a['surname']}\n"
                f"       📱 {a['phone']}  ·  {uname}\n"
                f"       📅 {a['submitted_at']}\n\n"
            )
    else:
        text += "✅ <i>Нових заявок немає.</i>"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄  Оновити статистику", callback_data="admin_refresh")],
    ])

    if via_message:
        await context.bot.send_message(
            chat_id=chat_id, text=text, reply_markup=kb, parse_mode=ParseMode.HTML
        )
    elif msg_id:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id, message_id=msg_id,
                text=text, reply_markup=kb, parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass


async def cb_admin_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if not is_admin(q.from_user.id):
        await q.answer("⛔ Немає прав!", show_alert=True)
        return
    await q.answer("🔄 Оновлено!")
    await _send_admin_panel(q.message.chat_id, context, msg_id=q.message.message_id)


# ═══════════════════════════════════════════════════════════════
#  ❌  СКАСУВАННЯ
# ═══════════════════════════════════════════════════════════════

async def cb_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()

    chat_id = context.user_data.get("chat_id", q.message.chat_id)

    # Прибираємо Reply-клавіатуру якщо була
    tmp = await context.bot.send_message(
        chat_id=chat_id, text=".", reply_markup=ReplyKeyboardRemove()
    )
    await try_delete(tmp)

    text = (
        f"❌ <b>Заявку скасовано</b>\n\n"
        f"<i>Натисніть кнопку нижче щоб розпочати знову.</i>"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄  Розпочати знову", callback_data="apply")],
        [InlineKeyboardButton("🏠  На головну", callback_data="home")],
    ])
    try:
        await context.bot.edit_message_text(
            chat_id=q.message.chat_id,
            message_id=q.message.message_id,
            text=text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass

    context.user_data.clear()
    return ConversationHandler.END


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text(
        "❌ <b>Скасовано.</b>\n\nНатисніть /start щоб розпочати.",
        parse_mode=ParseMode.HTML,
        reply_markup=ReplyKeyboardRemove(),
    )
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════════════
#  🚦  MAIN — ЗБІРКА БОТА
# ═══════════════════════════════════════════════════════════════

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    http_thread = threading.Thread(target=run_http_server_sync, daemon=True)
    http_thread.start()

    # ── ConversationHandler ────────────────────────────────────
    conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(cb_apply, pattern="^apply$"),
        ],
        states={
            NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_name),
                CallbackQueryHandler(cb_cancel, pattern="^cancel$"),
                CallbackQueryHandler(cb_back_to_review, pattern="^back_to_review$"),
            ],
            SURNAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_surname),
                CallbackQueryHandler(cb_back_name, pattern="^back_name$"),
                CallbackQueryHandler(cb_back_to_review, pattern="^back_to_review$"),
                CallbackQueryHandler(cb_cancel, pattern="^cancel$"),
            ],
            CITY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_city),
                CallbackQueryHandler(cb_back_surname, pattern="^back_surname$"),
                CallbackQueryHandler(cb_back_to_review, pattern="^back_to_review$"),
                CallbackQueryHandler(cb_cancel, pattern="^cancel$"),
            ],
            REVIEW: [
                # Кнопки редагування
                CallbackQueryHandler(cb_edit_name, pattern="^edit_name$"),
                CallbackQueryHandler(cb_edit_surname, pattern="^edit_surname$"),
                CallbackQueryHandler(cb_edit_city, pattern="^edit_city$"),
                # Підтвердження
                CallbackQueryHandler(cb_confirm_data, pattern="^confirm_data$"),
                CallbackQueryHandler(cb_cancel, pattern="^cancel$"),
                # Ігноруємо будь-який текст під час Review
                MessageHandler(filters.ALL & ~filters.COMMAND, handle_text_in_review),
            ],
            CONTACT: [
                MessageHandler(filters.CONTACT, handle_contact),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_in_contact),
                # Блокуємо будь-які медіа (фото, стікери, etc.)
                MessageHandler(
                    ~filters.CONTACT & ~filters.COMMAND & ~filters.TEXT,
                    handle_text_in_contact
                ),
                CallbackQueryHandler(cb_submit, pattern="^submit$"),
                CallbackQueryHandler(cb_cancel, pattern="^cancel$"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cmd_cancel),
            CommandHandler("start", cmd_start),
        ],
        per_message=False,
        per_chat=True,
        per_user=True,
        allow_reentry=True,     # дозволяє подати нову заявку після завершення
    )

    # ── Реєструємо хендлери ────────────────────────────────────
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(conv)

    # Хендлери поза розмовою
    app.add_handler(CallbackQueryHandler(cb_about,         pattern="^about$"))
    app.add_handler(CallbackQueryHandler(cb_home,          pattern="^home$"))
    app.add_handler(CallbackQueryHandler(cb_approve,       pattern=r"^approve\|"))
    app.add_handler(CallbackQueryHandler(cb_reject,        pattern=r"^reject\|"))
    app.add_handler(CallbackQueryHandler(cb_admin_refresh, pattern="^admin_refresh$"))

    logger.info("🤖  Бот запущено. Натисніть Ctrl+C для зупинки.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
