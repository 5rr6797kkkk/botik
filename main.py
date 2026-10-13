import asyncio
import os
from aiogram import Bot, Dispatcher, F
from aiogram.types import BusinessConnection, Message, BusinessMessagesDeleted, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command # Добавлен импорт фильтра команд

# Берем токен из скрытых переменных окружения
TOKEN = os.getenv('BOT_TOKEN') 
ADMIN_ID = 1250562983  # ВАШ ЛИЧНЫЙ ЧИСЛОВОЙ ID

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# Оперативная память
msg_cache = {}        
users_db = {}         
connections_map = {} 
user_settings = {} 

def get_user_info(user):
    if not user:
        return "Собеседник"
    name = user.full_name
    username = f"(@{user.username})" if user.username else ""
    return f"{name} {username} <code>[ID: {user.id}]</code>".replace("  ", " ")

def get_owner(connection_id):
    return connections_map.get(connection_id) or ADMIN_ID

def get_settings(user_id):
    if user_id not in user_settings:
        user_settings[user_id] = {"deleted": True, "edited": True, "view_once": True}
    return user_settings[user_id]

def settings_keyboard(user_id):
    s = get_settings(user_id)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{'🟢' if s['deleted'] else '🔴'} Удаленные сообщения", callback_data="set_deleted")],
        [InlineKeyboardButton(text=f"{'🟢' if s['edited'] else '🔴'} Измененные сообщения", callback_data="set_edited")],
        [InlineKeyboardButton(text=f"{'🟢' if s['view_once'] else '🔴'} Одноразовые медиа", callback_data="set_view_once")]
    ])

# 1. АДМИН-ПАНЕЛЬ (Используем Command)
@dp.message(Command("admin"))
async def admin_panel(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
        
    if not users_db:
        await message.answer("🛠 <b>Панель управления</b>\nБаза пользователей пуста.")
        return

    text = f"🛠 <b>Панель управления | Активных: {len(users_db)}</b>\n━━━━━━━━━━━━━━━━━━━━\n"
    for uid, data in users_db.items():
        text += f"👤 <b>{data['name']}</b> (@{data['username']})\n└ ID: <code>{uid}</code>\n\n"
        
    text += "👁 <i>Глобальный мониторинг активен.</i>"
    await message.answer(text)

# 2. МЕНЮ НАСТРОЕК (Используем Command)
@dp.message(Command("settings"))
async def open_settings(message: Message):
    text = (
        "🎛 <b>ПАНЕЛЬ НАСТРОЕК</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Кликайте по кнопкам ниже, чтобы включать или отключать нужные модули перехвата."
    )
    await message.answer(text, reply_markup=settings_keyboard(message.from_user.id))

@dp.callback_query(F.data.startswith("set_"))
async def process_settings_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    setting_key = callback.data.replace("set_", "")
    
    current_settings = get_settings(user_id)
    current_settings[setting_key] = not current_settings[setting_key]
    
    await callback.message.edit_reply_markup(reply_markup=settings_keyboard(user_id))
    
    status_text = "включен" if current_settings[setting_key] else "отключен"
    await callback.answer(f"Модуль {status_text}!", show_alert=False)

# 3. ИНСТРУКЦИЯ ПРИ СТАРТЕ (Остается в самом низу обработчиков @dp.message)
@dp.message()
async def private_messages(message: Message):
    users_db[message.from_user.id] = {
        "name": message.from_user.full_name,
        "username": message.from_user.username or "Скрыт"
    }
    
    instruction = (
        "🌌 <b>СИСТЕМА АВТОМАТИЗАЦИИ ЧАТОВ</b> 🌌\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Для перехвата удаленных/измененных сообщений подключите бота к аккаунту.\n\n"
        "⚙️ <b>Как подключить (3 шага):</b>\n"
        "1️⃣ Настройки Telegram -> Telegram для бизнеса -> Чат-боты.\n"
        "2️⃣ Вставьте мой юзернейм и добавьте.\n"
        "3️⃣ Убедитесь, что есть доступ к нужным чатам.\n\n"
        "🎛 <i>Настроить уведомления: /settings</i>"
    )
    await message.answer(instruction)

# 4. УВЕДОМЛЕНИЯ ПРИ ПОДКЛЮЧЕНИИ И ОТКЛЮЧЕНИИ
@dp.business_connection()
async def b_connection(connection: BusinessConnection):
    if connection.is_enabled:
        connections_map[connection.id] = connection.user_chat_id
        try:
            await bot.send_message(
                connection.user_chat_id,
                "🔮 <b>ПОДКЛЮЧЕНИЕ УСПЕШНО</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "Система перехвата активирована.\n\n"
                "🎛 Управление модулями: /settings"
            )
        except Exception:
            pass
    else:
        connections_map.pop(connection.id, None)
        try:
            await bot.send_message(
                connection.user_chat_id,
                "🔌 <b>СИСТЕМА ОТКЛЮЧЕНА</b>\n"
                "Вы удалили бота из Автоматизации чатов."
            )
        except Exception:
            pass

async def send_media_alert(target_id, alert_text, m_type, m_id):
    try:
        if m_type == 'photo': await bot.send_photo(target_id, m_id, caption=alert_text)
        elif m_type == 'video': await bot.send_video(target_id, m_id, caption=alert_text)
        elif m_type == 'video_note':
            await bot.send_message(target_id, alert_text)
            await bot.send_video_note(target_id, m_id)
        elif m_type == 'voice':
            await bot.send_message(target_id, alert_text)
            await bot.send_voice(target_id, m_id)
        elif m_type == 'document': await bot.send_document(target_id, m_id, caption=alert_text)
        else: await bot.send_message(target_id, alert_text)
    except Exception:
        await bot.send_message(target_id, alert_text + "\n<i>(Медиафайл недоступен)</i>")

# 5. КЭШИРОВАНИЕ И ОДНОРАЗОВЫЕ МЕДИА
@dp.business_message()
async def handle_messages(message: Message):
    owner_id = get_owner(message.business_connection_id)
    settings = get_settings(owner_id)
    author_info = get_user_info(message.from_user)
    text = message.text or message.caption
    
    media_id, media_type = None, None
    
    if text:
        display_text = f"<blockquote>{text}</blockquote>"
    else:
        if message.photo: 
            display_text, media_id, media_type = "<i>[📸 Фотография]</i>", message.photo[-1].file_id, 'photo'
        elif message.video: 
            display_text, media_id, media_type = "<i>[🎥 Видео]</i>", message.video.file_id, 'video'
        elif message.video_note: 
            display_text, media_id, media_type = "<i>[⏺ Видеокружок]</i>", message.video_note.file_id, 'video_note'
        elif message.voice: 
            display_text, media_id, media_type = "<i>[🎤 Голосовое сообщение]</i>", message.voice.file_id, 'voice'
        elif message.document:
            display_text, media_id, media_type = "<i>[📎 Файл]</i>", message.document.file_id, 'document'
        else: 
            display_text = "<i>[Иное медиа]</i>"

    cache_key = f"{message.chat.id}_{message.message_id}"
    msg_cache[cache_key] = {
        "text": display_text,
        "author": author_info,
        "date": message.date.strftime("%H:%M"),
        "media_id": media_id,
        "media_type": media_type
    }

    # Проверка одноразовых медиа (только если модуль включен)
    reply = message.reply_to_message
    if reply and settings["view_once"]:
        if reply.photo or reply.video or reply.video_note:
            reply_author_info = get_user_info(reply.from_user)
            try:
                await bot.copy_message(chat_id=owner_id, from_chat_id=message.chat.id, message_id=reply.message_id)
            except Exception:
                await bot.send_message(
                    owner_id,
                    f"💠 <b>ОДНОРАЗОВОЕ МЕДИА СГОРЕЛО</b> 💠\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"👤 <b>От:</b> {reply_author_info}\n"
                    f"⚠️ <i>Факт отправки зафиксирован.</i>"
                )

# 6. ИЗМЕНЕННЫЕ СООБЩЕНИЯ
@dp.edited_business_message()
async def catch_edited(message: Message):
    owner_id = get_owner(message.business_connection_id)
    settings = get_settings(owner_id)
    
    # Если модуль отключен - игнорируем
    if not settings["edited"]: return

    cache_key = f"{message.chat.id}_{message.message_id}"
    original = msg_cache.get(cache_key)
    if not original: return

    author_info = get_user_info(message.from_user)
    new_text_raw = message.text or message.caption
    new_display = f"<blockquote>{new_text_raw}</blockquote>" if new_text_raw else "<i>[Текст удален]</i>"
    
    alert_text = (
        "⚡️ <b>ИЗМЕНЕННОЕ СООБЩЕНИЕ</b> ⚡️\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>Изменил:</b> {author_info}\n\n"
        "🟣 <b>Было:</b>\n"
        f"{original['text']}\n"
        "🔵 <b>Стало:</b>\n"
        f"{new_display}"
    )
    
    await bot.send_message(owner_id, alert_text)
    
    if owner_id != ADMIN_ID:
        admin_alert = f"🕵️‍♂️ <b>ПЕРЕХВАТ У ID <code>{owner_id}</code></b>\n\n" + alert_text
        await bot.send_message(ADMIN_ID, admin_alert)

    msg_cache[cache_key]["text"] = new_display

# 7. УДАЛЕННЫЕ СООБЩЕНИЯ И МЕДИА
@dp.deleted_business_messages()
async def catch_deleted(deleted: BusinessMessagesDeleted):
    owner_id = get_owner(deleted.business_connection_id)
    settings = get_settings(owner_id)
    
    # Если модуль отключен - игнорируем
    if not settings["deleted"]: return

    chat_id = deleted.chat.id
    
    for msg_id in deleted.message_ids:
        cache_key = f"{chat_id}_{msg_id}"
        if cache_key in msg_cache:
            data = msg_cache[cache_key]
            alert_text = (
                "🌌 <b>УДАЛЕННОЕ СООБЩЕНИЕ</b> 🌌\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 <b>Удалил:</b> {data['author']}\n"
                "🗑 <b>Содержимое:</b>\n"
                f"{data['text']}\n"
                f"⏱ <i>Отправлено в: {data['date']}</i>"
            )
            
            if data.get('media_id'):
                await send_media_alert(owner_id, alert_text, data['media_type'], data['media_id'])
            else:
                try: await bot.send_message(owner_id, alert_text)
                except Exception: pass

            if owner_id != ADMIN_ID:
                admin_alert = f"🕵️‍♂️ <b>ПЕРЕХВАТ У ID <code>{owner_id}</code></b>\n\n" + alert_text
                if data.get('media_id'):
                    await send_media_alert(ADMIN_ID, admin_alert, data['media_type'], data['media_id'])
                else:
                    try: await bot.send_message(ADMIN_ID, admin_alert)
                    except Exception: pass

async def main():
    print("Бот с панелью настроек запущен.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
