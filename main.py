import asyncio
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    BusinessConnection, Message, BusinessMessagesDeleted,
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
)
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command

# ==========================================
# ⚙️ ОСНОВНЫЕ НАСТРОЙКИ
# ==========================================
TOKEN = os.getenv('BOT_TOKEN')
ADMIN_ID = 1250562983

IMG_SETTINGS = "https://i.postimg.cc/nLtLjM5f/Gemini-Generated-Image-958e6h958e6h958e.jpg"
IMG_EDITED   = "https://i.postimg.cc/J4frvGR1/Gemini-Generated-Image-d4yhcwd4yhcwd4yh.jpg"
IMG_DELETED  = "https://i.postimg.cc/vmj3tFWK/e9c320fc-7cf5-43ec-b736-5354f04e46b2.jpg"

MAX_LOGS_PER_USER = 200  # храним последние N логов на юзера в БД

# ==========================================
# 💾 ПУТЬ К БАЗЕ
# ==========================================
# DATA_DIR можно задать через env (например, на Railway: /data)
DATA_DIR = Path(os.getenv("DATA_DIR", "."))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "bot.db"


# ==========================================
# 🗃 ИНИЦИАЛИЗАЦИЯ БД
# ==========================================
def db_init():
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    cur = con.cursor()
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id   INTEGER PRIMARY KEY,
            name      TEXT,
            username  TEXT,
            updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS settings (
            user_id  INTEGER PRIMARY KEY,
            deleted  INTEGER DEFAULT 1,
            edited   INTEGER DEFAULT 1,
            silent   INTEGER DEFAULT 0,
            compact  INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS logs (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id   INTEGER NOT NULL,
            type       TEXT NOT NULL,
            text       TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_logs_owner ON logs(owner_id, id DESC);

        CREATE TABLE IF NOT EXISTS connections (
            connection_id TEXT PRIMARY KEY,
            owner_id      INTEGER
        );
    """)
    con.commit()
    return con


db = db_init()


# ==========================================
# 🧠 ОПЕРАТИВНЫЙ КЭШ (только то, что нужно в моменте)
# ==========================================
msg_cache = {}          # для edit/delete — не критично, что обнулится
connections_map = {}    # подтянем из БД при старте


# ==========================================
# 🛠 ХЕЛПЕРЫ
# ==========================================
def get_user_info(user, compact=False):
    if not user:
        return "Собеседник"
    if compact:
        return user.full_name
    name = user.full_name
    username = f"(@{user.username})" if user.username else ""
    return f"{name} {username} <code>[ID: {user.id}]</code>".replace("  ", " ")


def db_upsert_user(user_id: int, name: str, username: str):
    db.execute(
        "INSERT INTO users(user_id, name, username, updated_at) VALUES(?,?,?,?) "
        "ON CONFLICT(user_id) DO UPDATE SET name=excluded.name, username=excluded.username, updated_at=excluded.updated_at",
        (user_id, name, username, datetime.now().isoformat())
    )
    db.commit()


def db_get_users():
    cur = db.execute("SELECT user_id, name, username FROM users")
    return {row[0]: {"name": row[1], "username": row[2]} for row in cur.fetchall()}


def db_get_settings(user_id: int) -> dict:
    cur = db.execute("SELECT deleted, edited, silent, compact FROM settings WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    if not row:
        db.execute("INSERT INTO settings(user_id) VALUES(?)", (user_id,))
        db.commit()
        return {"deleted": True, "edited": True, "silent": False, "compact": False}
    return {"deleted": bool(row[0]), "edited": bool(row[1]), "silent": bool(row[2]), "compact": bool(row[3])}


def db_set_setting(user_id: int, key: str, value: bool):
    # гарантируем наличие строки
    db_get_settings(user_id)
    db.execute(f"UPDATE settings SET {key}=? WHERE user_id=?", (1 if value else 0, user_id))
    db.commit()


def db_save_log(owner_id: int, log_type: str, text: str):
    db.execute(
        "INSERT INTO logs(owner_id, type, text, created_at) VALUES(?,?,?,?)",
        (owner_id, log_type, text, datetime.now().strftime("%d.%m %H:%M:%S"))
    )
    db.commit()
    # обрезаем историю
    db.execute(
        "DELETE FROM logs WHERE owner_id=? AND id NOT IN "
        "(SELECT id FROM logs WHERE owner_id=? ORDER BY id DESC LIMIT ?)",
        (owner_id, owner_id, MAX_LOGS_PER_USER)
    )
    db.commit()


def db_get_logs(owner_id: int, limit=5, offset=0):
    cur = db.execute(
        "SELECT type, text, created_at FROM logs WHERE owner_id=? ORDER BY id DESC LIMIT ? OFFSET ?",
        (owner_id, limit, offset)
    )
    return cur.fetchall()


def db_count_logs(owner_id: int) -> int:
    cur = db.execute("SELECT COUNT(*) FROM logs WHERE owner_id=?", (owner_id,))
    return cur.fetchone()[0]


def db_clear_logs(owner_id: int):
    db.execute("DELETE FROM logs WHERE owner_id=?", (owner_id,))
    db.commit()


def db_save_connection(connection_id: str, owner_id: int):
    db.execute(
        "INSERT INTO connections(connection_id, owner_id) VALUES(?,?) "
        "ON CONFLICT(connection_id) DO UPDATE SET owner_id=excluded.owner_id",
        (connection_id, owner_id)
    )
    db.commit()


def db_delete_connection(connection_id: str):
    db.execute("DELETE FROM connections WHERE connection_id=?", (connection_id,))
    db.commit()


def db_load_connections():
    cur = db.execute("SELECT connection_id, owner_id FROM connections")
    return {row[0]: row[1] for row in cur.fetchall()}


async def get_owner(connection_id, bot_instance: Bot):
    if connection_id in connections_map:
        return connections_map[connection_id]
    try:
        conn = await bot_instance.get_business_connection(connection_id)
        connections_map[connection_id] = conn.user_chat_id
        db_save_connection(connection_id, conn.user_chat_id)
        return conn.user_chat_id
    except Exception:
        return ADMIN_ID


def settings_keyboard(user_id):
    s = db_get_settings(user_id)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{'🟢' if s['deleted'] else '🔴'} Ловить удаления", callback_data="set_deleted")],
        [InlineKeyboardButton(text=f"{'🟢' if s['edited'] else '🔴'} Ловить изменения", callback_data="set_edited")],
        [
            InlineKeyboardButton(text=f"{'🔕' if s['silent'] else '🔔'} Без звука", callback_data="set_silent"),
            InlineKeyboardButton(text=f"{'📦' if s['compact'] else '📜'} Компакт", callback_data="set_compact")
        ]
    ])


# ==========================================
# 🎨 АДМИН-ПАНЕЛЬ
# ==========================================
def admin_main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Пользователи", callback_data="adm_users")],
        [
            InlineKeyboardButton(text="📊 Статистика", callback_data="adm_stats"),
            InlineKeyboardButton(text="🔄 Обновить", callback_data="adm_refresh")
        ],
    ])


def admin_users_keyboard():
    users = db_get_users()
    rows = []
    for uid, data in users.items():
        count = db_count_logs(uid)
        badge = f"🔴 {count}" if count else "⚪ 0"
        rows.append([
            InlineKeyboardButton(
                text=f"👤 {data['name']} • {badge}",
                callback_data=f"adm_user_{uid}"
            )
        ])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="adm_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_user_keyboard(owner_id: int, page: int = 0):
    total = db_count_logs(owner_id)
    total_pages = max(1, (total + 4) // 5)

    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="⬅️", callback_data=f"adm_upage_{owner_id}_{page-1}"))
    nav_row.append(InlineKeyboardButton(text=f"📄 {page+1}/{total_pages}", callback_data="adm_noop"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton(text="➡️", callback_data=f"adm_upage_{owner_id}_{page+1}"))

    rows = []
    if total > 0:
        rows.append(nav_row)
    rows.append([
        InlineKeyboardButton(text="🗑 Очистить логи", callback_data=f"adm_clear_{owner_id}"),
        InlineKeyboardButton(text="⬅️ К списку", callback_data="adm_users")
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_user_text(owner_id: int, page: int = 0) -> str:
    users = db_get_users()
    data = users.get(owner_id, {"name": "Неизвестный", "username": "—"})
    s = db_get_settings(owner_id)
    total = db_count_logs(owner_id)

    header = (
        f"👤 <b>{data['name']}</b> (@{data['username']})\n"
        f"└ 🆔 <code>{owner_id}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⚙️ Настройки узла:\n"
        f"  • Удаления: {'🟢' if s['deleted'] else '🔴'}\n"
        f"  • Изменения: {'🟢' if s['edited'] else '🔴'}\n"
        f"  • Без звука: {'🔕' if s['silent'] else '🔔'}\n"
        f"  • Компакт: {'📦' if s['compact'] else '📜'}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📜 <b>Логи</b> (всего: {total}):\n\n"
    )

    if total == 0:
        return header + "<i>Пока нет записей. Тишина в эфире…</i>"

    logs = db_get_logs(owner_id, limit=5, offset=page * 5)
    for log_type, text, created_at in logs:
        icon = "✍️" if log_type == "edited" else "🗑"
        label = "ИЗМЕНЕНО" if log_type == "edited" else "УДАЛЕНО"
        preview = text if len(text) <= 180 else text[:180] + "…"
        header += f"{icon} <b>{label}</b> • <i>{created_at}</i>\n{preview}\n\n"

    return header


# ==========================================
# 🚀 КОМАНДЫ
# ==========================================
@dp.message(Command("admin"))
async def admin_panel(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    users = db_get_users()
    total_logs = sum(db_count_logs(uid) for uid in users)
    text = (
        "💎 <b>ЦЕНТР УПРАВЛЕНИЯ СЕТЬЮ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 Активных узлов: <b>{len(users)}</b>\n"
        f"📜 Всего логов: <b>{total_logs}</b>\n"
        f"🔗 Живых соединений: <b>{len(connections_map)}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Выберите раздел для мониторинга:"
    )
    await message.answer(text, reply_markup=admin_main_keyboard())


@dp.message(Command("settings"))
async def open_settings(message: Message):
    text = (
        "<i>Настройте алгоритмы под себя:</i>\n\n"
        "🔕 <b>Без звука:</b> Уведомления приходят тихо.\n"
        "📦 <b>Компакт:</b> Скрывает ID и лишние детали из логов."
    )
    try:
        await message.answer_photo(photo=IMG_SETTINGS, caption=text,
                                   reply_markup=settings_keyboard(message.from_user.id))
    except Exception:
        await message.answer(text, reply_markup=settings_keyboard(message.from_user.id))


# ==========================================
# 🎛 CALLBACK — АДМИН
# ==========================================
@dp.callback_query(F.data == "adm_menu")
async def adm_menu(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return await callback.answer("⛔ Доступ запрещён", show_alert=True)
    users = db_get_users()
    total_logs = sum(db_count_logs(uid) for uid in users)
    text = (
        "💎 <b>ЦЕНТР УПРАВЛЕНИЯ СЕТЬЮ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 Активных узлов: <b>{len(users)}</b>\n"
        f"📜 Всего логов: <b>{total_logs}</b>\n"
        f"🔗 Живых соединений: <b>{len(connections_map)}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Выберите раздел для мониторинга:"
    )
    try:
        await callback.message.edit_text(text, reply_markup=admin_main_keyboard())
    except Exception:
        await callback.message.answer(text, reply_markup=admin_main_keyboard())
    await callback.answer()


@dp.callback_query(F.data == "adm_refresh")
async def adm_refresh(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return await callback.answer("⛔ Доступ запрещён", show_alert=True)
    await adm_menu(callback)


@dp.callback_query(F.data == "adm_stats")
async def adm_stats(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return await callback.answer("⛔ Доступ запрещён", show_alert=True)

    users = db_get_users()
    cur = db.execute("SELECT type, COUNT(*) FROM logs GROUP BY type")
    counts = dict(cur.fetchall())
    edited_count = counts.get("edited", 0)
    deleted_count = counts.get("deleted", 0)

    text = (
        "📊 <b>СТАТИСТИКА СЕТИ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 Узлов в базе: <b>{len(users)}</b>\n"
        f"🔗 Соединений: <b>{len(connections_map)}</b>\n"
        f"💬 Сообщений в кэше: <b>{len(msg_cache)}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"✍️ Перехвачено изменений: <b>{edited_count}</b>\n"
        f"🗑 Перехвачено удалений: <b>{deleted_count}</b>\n"
        f"📜 Всего в логах: <b>{edited_count + deleted_count}</b>\n"
        f"💾 БД: <code>{DB_PATH}</code>\n"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="adm_menu")]
    ])
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception:
        await callback.message.answer(text, reply_markup=kb)
    await callback.answer()


@dp.callback_query(F.data == "adm_users")
async def adm_users(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return await callback.answer("⛔ Доступ запрещён", show_alert=True)

    users = db_get_users()
    if not users:
        text = "👥 <b>Сеть пуста</b>\nПока ни один пользователь не подключился."
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="adm_menu")]
        ])
    else:
        text = f"👥 <b>УЗЛЫ СЕТИ</b> ({len(users)})\n━━━━━━━━━━━━━━━━━━━━\nВыберите пользователя для просмотра логов:"
        kb = admin_users_keyboard()

    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception:
        await callback.message.answer(text, reply_markup=kb)
    await callback.answer()


@dp.callback_query(F.data.startswith("adm_user_"))
async def adm_user_view(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return await callback.answer("⛔ Доступ запрещён", show_alert=True)
    owner_id = int(callback.data.replace("adm_user_", ""))
    text = admin_user_text(owner_id, page=0)
    kb = admin_user_keyboard(owner_id, page=0)
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception:
        await callback.message.answer(text, reply_markup=kb)
    await callback.answer()


@dp.callback_query(F.data.startswith("adm_upage_"))
async def adm_user_page(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return await callback.answer("⛔ Доступ запрещён", show_alert=True)
    _, _, owner_id, page = callback.data.split("_")
    owner_id, page = int(owner_id), int(page)
    text = admin_user_text(owner_id, page=page)
    kb = admin_user_keyboard(owner_id, page=page)
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception:
        pass
    await callback.answer()


@dp.callback_query(F.data.startswith("adm_clear_"))
async def adm_clear(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return await callback.answer("⛔ Доступ запрещён", show_alert=True)
    owner_id = int(callback.data.replace("adm_clear_", ""))
    db_clear_logs(owner_id)
    text = admin_user_text(owner_id, page=0)
    kb = admin_user_keyboard(owner_id, page=0)
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception:
        pass
    await callback.answer("🗑 Логи очищены", show_alert=False)


@dp.callback_query(F.data == "adm_noop")
async def adm_noop(callback: CallbackQuery):
    await callback.answer()


# ==========================================
# 🎛 CALLBACK — НАСТРОЙКИ ПОЛЬЗОВАТЕЛЯ
# ==========================================
@dp.callback_query(F.data.startswith("set_"))
async def process_settings_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    setting_key = callback.data.replace("set_", "")
    current = db_get_settings(user_id)
    new_value = not current[setting_key]
    db_set_setting(user_id, setting_key, new_value)

    await callback.message.edit_reply_markup(reply_markup=settings_keyboard(user_id))
    status_text = "Активирован" if new_value else "Деактивирован"
    await callback.answer(f"Модуль: {status_text}", show_alert=False)


# ==========================================
# 💬 ЛИЧНЫЕ СООБЩЕНИЯ
# ==========================================
@dp.message()
async def private_messages(message: Message):
    db_upsert_user(
        message.from_user.id,
        message.from_user.full_name,
        message.from_user.username or "Скрыт"
    )
    instruction = (
        "💎 <b>ТЕНЕВОЙ МОНИТОРИНГ ЧАТОВ</b> 💎\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "1️⃣ Настройки Telegram -> Telegram для бизнеса -> Чат-боты.\n"
        "2️⃣ Вставьте мой юзернейм и добавьте.\n"
        "3️⃣ Убедитесь, что есть доступ к нужным чатам.\n\n"
        "🎛 <i>Меню конфигурации: /settings</i>"
    )
    await message.answer(instruction)


# ==========================================
# 🔗 BUSINESS CONNECTION
# ==========================================
@dp.business_connection()
async def b_connection(connection: BusinessConnection):
    if connection.is_enabled:
        connections_map[connection.id] = connection.user_chat_id
        db_save_connection(connection.id, connection.user_chat_id)
        try:
            await bot.send_photo(
                connection.user_chat_id,
                photo=IMG_SETTINGS,
                caption="💠 <b>АЛГОРИТМЫ ЗАПУЩЕНЫ</b>\n━━━━━━━━━━━━━━━━━━━━\nКанал перехвата установлен. Ожидаю активность.\n\n🎛 Управление: /settings"
            )
        except Exception:
            await bot.send_message(connection.user_chat_id,
                                   "💠 <b>АЛГОРИТМЫ ЗАПУЩЕНЫ</b>\nОжидаю активность. Управление: /settings")
    else:
        connections_map.pop(connection.id, None)
        db_delete_connection(connection.id)
        try:
            await bot.send_message(connection.user_chat_id,
                                   "🔌 <b>СВЯЗЬ РАЗОРВАНА</b>\nБот отключен от бизнес-аккаунта.")
        except Exception:
            pass


# ==========================================
# 📤 ОТПРАВКА АЛЕРТОВ
# ==========================================
async def send_alert_with_image(target_id, text, img_url, silent=False):
    try:
        await bot.send_photo(target_id, photo=img_url, caption=text, disable_notification=silent)
    except Exception:
        await bot.send_message(target_id, text, disable_notification=silent)


async def send_recovered_media(target_id, alert_text, m_type, m_id, silent=False):
    try:
        if m_type == 'photo':
            await bot.send_photo(target_id, m_id, caption=alert_text, disable_notification=silent)
        elif m_type == 'video':
            await bot.send_video(target_id, m_id, caption=alert_text, disable_notification=silent)
        elif m_type == 'video_note':
            await bot.send_message(target_id, alert_text, disable_notification=silent)
            await bot.send_video_note(target_id, m_id, disable_notification=silent)
        elif m_type == 'voice':
            await bot.send_message(target_id, alert_text, disable_notification=silent)
            await bot.send_voice(target_id, m_id, disable_notification=silent)
        elif m_type == 'document':
            await bot.send_document(target_id, m_id, caption=alert_text, disable_notification=silent)
        else:
            await bot.send_message(target_id, alert_text, disable_notification=silent)
    except Exception:
        await bot.send_message(target_id, alert_text + "\n<i>(Файл поврежден)</i>", disable_notification=silent)


# ==========================================
# 💬 BUSINESS MESSAGE
# ==========================================
@dp.business_message()
async def handle_messages(message: Message):
    owner_id = await get_owner(message.business_connection_id, bot)

    author_info_full = get_user_info(message.from_user, compact=False)
    author_info_compact = get_user_info(message.from_user, compact=True)
    text = message.text or message.caption

    media_id, media_type = None, None
    if text:
        display_text = f"<blockquote>{text}</blockquote>"
    else:
        if message.photo:
            display_text, media_id, media_type = "<i>[📸 Фото]</i>", message.photo[-1].file_id, 'photo'
        elif message.video:
            display_text, media_id, media_type = "<i>[🎥 Видео]</i>", message.video.file_id, 'video'
        elif message.video_note:
            display_text, media_id, media_type = "<i>[⏺ Кружок]</i>", message.video_note.file_id, 'video_note'
        elif message.voice:
            display_text, media_id, media_type = "<i>[🎤 Голосовое]</i>", message.voice.file_id, 'voice'
        elif message.document:
            display_text, media_id, media_type = "<i>[📎 Документ]</i>", message.document.file_id, 'document'
        else:
            display_text = "<i>[Медиа-ассет]</i>"

    cache_key = f"{message.chat.id}_{message.message_id}"
    msg_cache[cache_key] = {
        "text": display_text,
        "author_full": author_info_full,
        "author_compact": author_info_compact,
        "date": message.date.strftime("%H:%M"),
        "media_id": media_id,
        "media_type": media_type
    }


# ==========================================
# ✍️ РЕДАКТИРОВАНИЕ
# ==========================================
@dp.edited_business_message()
async def catch_edited(message: Message):
    owner_id = await get_owner(message.business_connection_id, bot)
    settings = db_get_settings(owner_id)
    if not settings["edited"]:
        return

    cache_key = f"{message.chat.id}_{message.message_id}"
    original = msg_cache.get(cache_key)
    if not original:
        return

    author = original['author_compact'] if settings["compact"] else original['author_full']
    new_text_raw = message.text or message.caption
    new_display = f"<blockquote>{new_text_raw}</blockquote>" if new_text_raw else "<i>[Текст стерт]</i>"

    if settings["compact"]:
        alert_text = f"✍️ Изменено: {author}\n🟣 {original['text']}\n🔵 {new_display}"
    else:
        alert_text = (
            f"🔮 <b>ИЗМЕНЕННОЕ СООБЩЕНИЕ</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>Автор:</b> {author}\n\n"
            f"🟣 <b>Исходник:</b>\n{original['text']}\n"
            f"🔵 <b>Новый код:</b>\n{new_display}"
        )

    await send_alert_with_image(owner_id, alert_text, IMG_EDITED, settings["silent"])

    plain_preview = f"👤 {author}\n🟣 {original['text']}\n🔵 {new_display}"
    db_save_log(owner_id, "edited", plain_preview)

    msg_cache[cache_key]["text"] = new_display


# ==========================================
# 🗑 УДАЛЕНИЕ
# ==========================================
@dp.deleted_business_messages()
async def catch_deleted(deleted: BusinessMessagesDeleted):
    owner_id = await get_owner(deleted.business_connection_id, bot)
    settings = db_get_settings(owner_id)
    if not settings["deleted"]:
        return

    chat_id = deleted.chat.id
    for msg_id in deleted.message_ids:
        cache_key = f"{chat_id}_{msg_id}"
        if cache_key not in msg_cache:
            continue

        data = msg_cache[cache_key]
        author = data['author_compact'] if settings["compact"] else data['author_full']

        if settings["compact"]:
            alert_text = f"🗑 Удалено: {author}\n{data['text']}"
        else:
            alert_text = (
                f"💎 <b>УДАЛЕННОЕ СООБЩЕНИЕ</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 <b>Ликвидатор:</b> {author}\n"
                f"⏱ <b>Таймкод:</b> {data['date']}\n\n"
                f"📦 <b>Содержимое:</b>\n{data['text']}"
            )

        if data.get('media_id'):
            await send_recovered_media(owner_id, alert_text, data['media_type'], data['media_id'], settings["silent"])
        else:
            await send_alert_with_image(owner_id, alert_text, IMG_DELETED, settings["silent"])

        plain_preview = f"👤 {author} • ⏱ {data['date']}\n{data['text']}"
        db_save_log(owner_id, "deleted", plain_preview)


# ==========================================
# 🚀 ЗАПУСК
# ==========================================
async def main():
    # Восстанавливаем соединения из БД
    global connections_map
    connections_map = db_load_connections()
    print(f"✅ Бот запущен. БД: {DB_PATH}. Соединений восстановлено: {len(connections_map)}")
    print(f"👥 Пользователей в базе: {len(db_get_users())}")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
