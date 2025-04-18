import asyncio
import logging
import sqlite3
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command, CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram import Router
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from datetime import datetime
import os
from dotenv import load_dotenv
import random
import zalgo_text.zalgo as zalgo
import pyfiglet
import re
import requests
import uuid
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib import colors

# Загрузка переменных из .env
load_dotenv()

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация бота
API_TOKEN = os.getenv("BOT_TOKEN")
DB_PATH = os.getenv("DB_PATH", "/tmp/textstyler.db")
ADMIN_ID = int(os.getenv("ADMIN_ID", "123456789"))
GIGACHAT_AUTH_KEY = os.getenv("GIGACHAT_AUTH_KEY")
GIGACHAT_CLIENT_ID = os.getenv("GIGACHAT_CLIENT_ID")
if not API_TOKEN:
    raise ValueError("BOT_TOKEN not found in .env file")
bot = Bot(token=API_TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher()
router = Router()
dp.include_router(router)

# Инициализация базы данных
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        language TEXT DEFAULT 'ru',
        joined_at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS stylizations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        style TEXT,
        preset TEXT,
        text TEXT,
        created_at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS triggers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        keyword TEXT,
        style TEXT,
        preset TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS restricted_styles (
        user_id INTEGER,
        style TEXT,
        PRIMARY KEY (user_id, style)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS group_templates (
        chat_id INTEGER PRIMARY KEY,
        preset TEXT
    )""")
    conn.commit()
    conn.close()

init_db()

# Локализация (только русский язык)
LANGUAGES = {
    "ru": {
        "welcome": "Добро пожаловать в TextStyler Pro! Используйте /style для стилизации текста, /preset для шаблонов или попробуйте инлайн-режим с @{}",
        "style_menu": "Выберите стиль:",
        "preset_menu": "Выберите шаблон:",
        "admin_menu": "Админ-панель:\n- /users: Список пользователей\n- /broadcast: Рассылка всем\n- /set_group_template: Установить шаблон группы",
        "history": "Ваши стилизации:\n{}",
        "no_history": "Пока нет стилизаций.",
        "enter_text": "Введите текст для стилизации в {}:",
        "broadcast_sent": "Рассылка отправлена {} пользователям.",
        "style_restricted": "Стиль '{}' ограничен для вас.",
        "auto_formatted": "Текст автоматически отформатирован по ключевому слову '{}'.",
        "help": "Используйте /style, /preset, /random, /history, /export_pdf или инлайн-режим @{}",
        "gigachat_error": "Ошибка API GigaChat, используется запасной вариант: {}",
        "pdf_exported": "Текст экспортирован в PDF!",
        "set_group_template": "Выберите шаблон для этой группы:",
        "group_template_set": "Шаблон '{}' установлен для этой группы.",
        "choose_tone": "Выберите тон для умного ответа:"
    }
}

# Стили
STYLES = {
    "bold": lambda text: f"<b>{text}</b>",
    "italic": lambda text: f"<i>{text}</i>",
    "mono": lambda text: f"<code>{text}</code>",
    "strike": lambda text: f"<s>{text}</s>",
    "link": lambda text: f"<a href='https://example.com'>{text}</a>",
    "cursive": lambda text: "".join(chr(0x1D4D0 + ord(c) - ord('a')) if c.islower() else c for c in text),
    "box": lambda text: f"🅱 {text} 🅾",
    "monospace": lambda text: f"🇲🇴🇳🇴🇸🇵🇦🇨🇪 {text}",
    "star": lambda text: f"★ {text} ★",
    "fire": lambda text: f"🔥 {text} 🔥",
    "circle": lambda text: f"◉ {text} ◉",
    "important": lambda text: f"💥 ВАЖНО: {text} 💥",
    "zalgo": lambda text: zalgo.zalgo().zalgofy(text),
    "mirror": lambda text: text[::-1],
    "ascii": lambda text: f"<pre>{pyfiglet.figlet_format(text, font='standard')}</pre>"
}

# Пресеты
PRESETS = {
    "header": lambda text: f"<b>✨ {text} ✨</b>",
    "announcement": lambda text: f"📢 <b>{text}</b> 📢",
    "meme": lambda text: f"😂 {text.upper()} 😂",
    "quote": lambda text: f"💬 <i>{text}</i> 💬",
    "alert": lambda text: f"🚨 <b>{text}</b> 🚨",
    "holiday": lambda text: f"🎉 {text} 🎉",
    "joke": lambda text: f"😜 {text} 😜",
    "important": lambda text: f"💥 <b>{text}</b> 💥"
}

# Триггеры для автоформатирования
TRIGGERS = {
    "важно": {"preset": "important"},
    "срочно": {"style": "alert"},
    "праздник": {"preset": "holiday"},
    "шутка": {"preset": "joke"}
}

# Тоны для /smartreply
TONES = {
    "sarcastic": "Отвечай в саркастичном и остроумном тоне",
    "friendly": "Отвечай в тёплом и дружелюбном тоне",
    "formal": "Отвечай в профессиональном и формальном тоне",
    "neutral": "Отвечай в нейтральном и прямолинейном тоне"
}

# FSM для ожидания текста и тона
class StyleStates(StatesGroup):
    waiting_for_style_text = State()
    waiting_for_preset_text = State()
    waiting_for_smartreply_tone = State()
    waiting_for_smartreply_text = State()

# Функция для получения языка пользователя
def get_user_language(user_id):
    return "ru"  # Всегда русский язык

# Проверка ограничений стилей
def is_style_restricted(user_id, style):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT 1 FROM restricted_styles WHERE user_id = ? AND style = ?", (user_id, style))
    result = c.fetchone()
    conn.close()
    return bool(result)

# Функция для экспорта текста в PDF
def export_to_pdf(text, filename="/tmp/output.pdf"):
    c = canvas.Canvas(filename, pagesize=A4)
    c.setFont("Helvetica", 12)
    y = 800
    for line in text.split("\n"):
        c.drawString(50, y, line[:100])
        y -= 20
        if y < 50:
            c.showPage()
            y = 800
    c.save()
    return filename

# Функция для получения шаблона группы
def get_group_template(chat_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT preset FROM group_templates WHERE chat_id = ?", (chat_id,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else None

# Функция для получения токена GigaChat
def get_gigachat_token():
    url = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    payload = {'scope': 'GIGACHAT_API_PERS'}
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
        'Accept': 'application/json',
        'RqUID': str(uuid.uuid4()),
        'Authorization': f'Basic {GIGACHAT_AUTH_KEY}'
    }
    
    try:
        response = requests.post(url, headers=headers, data=payload, verify=False)
        response.raise_for_status()
        data = response.json()
        return data.get('access_token'), data.get('expires_at')
    except Exception as e:
        logger.error(f"Failed to get GigaChat token: {e}")
        return None, None

# Функция для вызова GigaChat API
def call_gigachat_api(text, command, tone=None):
    if not GIGACHAT_AUTH_KEY:
        return None
    
    token, expires_at = get_gigachat_token()
    if not token:
        return None
    
    url = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {token}'
    }
    
    prompts = {
        "gigachadify": f"Сделай этот текст максимально уверенным и мощным, как у ГигаЧада: {text}",
        "make_post": f"Оформи этот текст как стильный пост для соцсетей: {text}",
        "smartreply": f"{TONES.get(tone, 'Отвечай в нейтральном тоне')} на это сообщение: {text}",
        "rewrite": f"Перепиши этот текст более элегантно и стильно: {text}"
    }
    
    payload = {
        "model": "GigaChat",
        "messages": [
            {"role": "user", "content": prompts[command]}
        ],
        "max_tokens": 200
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload, verify=False)
        response.raise_for_status()
        data = response.json()
        return data['choices'][0]['message']['content']
    except Exception as e:
        logger.error(f"GigaChat API error: {e}")
        return None

# Обработчик /start
@router.message(CommandStart())
async def start_command(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username or "Unknown"
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, username, joined_at) VALUES (?, ?, ?)",
              (user_id, username, datetime.now().isoformat()))
    conn.commit()
    conn.close()

    lang = get_user_language(user_id)
    bot_username = (await bot.get_me()).username
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить в группу", url=f"https://t.me/{bot_username}?startgroup=true")],
        [InlineKeyboardButton(text="📘 Помощь", callback_data="help")]
    ])
    await message.answer(LANGUAGES[lang]["welcome"].format(bot_username), reply_markup=keyboard)

# Обработчик /help
@router.message(Command("help"))
async def help_command(message: types.Message):
    lang = get_user_language(message.from_user.id)
    bot_username = (await bot.get_me()).username
    await message.answer(LANGUAGES[lang]["help"].format(bot_username))

# Обработчик /style
@router.message(Command("style"))
async def style_command(message: types.Message):
    lang = get_user_language(message.from_user.id)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Жирный", callback_data="style_bold"),
         InlineKeyboardButton(text="Курсив", callback_data="style_italic")],
        [InlineKeyboardButton(text="Моно", callback_data="style_mono"),
         InlineKeyboardButton(text="Зачёркнутый", callback_data="style_strike")],
        [InlineKeyboardButton(text="Звезда", callback_data="style_star"),
         InlineKeyboardButton(text="Огонь", callback_data="style_fire")],
        [InlineKeyboardButton(text="Залго", callback_data="style_zalgo"),
         InlineKeyboardButton(text="Зеркало", callback_data="style_mirror")],
        [InlineKeyboardButton(text="ASCII", callback_data="style_ascii")]
    ])
    await message.answer(LANGUAGES[lang]["style_menu"], reply_markup=keyboard)

# Обработчик /preset
@router.message(Command("preset"))
async def preset_command(message: types.Message):
    lang = get_user_language(message.from_user.id)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Заголовок", callback_data="preset_header"),
         InlineKeyboardButton(text="Объявление", callback_data="preset_announcement")],
        [InlineKeyboardButton(text="Мем", callback_data="preset_meme"),
         InlineKeyboardButton(text="Цитата", callback_data="preset_quote")],
        [InlineKeyboardButton(text="Тревога", callback_data="preset_alert"),
         InlineKeyboardButton(text="Праздник", callback_data="preset_holiday")],
        [InlineKeyboardButton(text="Шутка", callback_data="preset_joke"),
         InlineKeyboardButton(text="Важное", callback_data="preset_important")]
    ])
    await message.answer(LANGUAGES[lang]["preset_menu"], reply_markup=keyboard)

# Обработчик /random
@router.message(Command("random"))
async def random_command(message: types.Message):
    text = message.text.replace("/random", "").strip() or "Пример текста"
    style = random.choice(list(STYLES.keys()))
    
    if is_style_restricted(message.from_user.id, style):
        lang = get_user_language(message.from_user.id)
        await message.answer(LANGUAGES[lang]["style_restricted"].format(style))
        return
    
    styled_text = STYLES[style](text)
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO stylizations (user_id, style, text, created_at) VALUES (?, ?, ?, ?)",
              (message.from_user.id, style, text, datetime.now().isoformat()))
    conn.commit()
    conn.close()
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Копировать", callback_data=f"copy_{styled_text}"),
         InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"edit_{style}")],
        [InlineKeyboardButton(text="📄 Экспорт в PDF", callback_data=f"export_pdf_{styled_text}")]
    ])
    await message.answer(styled_text, reply_markup=keyboard)

# Обработчик /history
@router.message(Command("history"))
async def history_command(message: types.Message):
    lang = get_user_language(message.from_user.id)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT style, preset, text, created_at FROM stylizations WHERE user_id = ? ORDER BY created_at DESC LIMIT 5",
              (message.from_user.id,))
    stylizations = c.fetchall()
    conn.close()
    
    if not stylizations:
        await message.answer(LANGUAGES[lang]["no_history"])
        return
    
    history_text = ""
    for i, (style, preset, text, created_at) in enumerate(stylizations, 1):
        format_type = preset or style or "неизвестно"
        history_text += f"{i}. {format_type}: {text} ({created_at})\n"
    
    await message.answer(LANGUAGES[lang]["history"].format(history_text))

# Обработчик /clear
@router.message(Command("clear"))
async def clear_command(message: types.Message):
    text = message.text.replace("/clear", "").strip() or "Пример текста"
    clean_text = re.sub(r'<[^>]+>|`{1,3}|[\*_~]', '', text)
    await message.answer(clean_text)

# Обработчик /export_pdf
@router.message(Command("export_pdf"))
async def export_pdf_command(message: types.Message):
    text = message.text.replace("/export_pdf", "").strip() or "Пример текста"
    filename = f"/tmp/output_{message.from_user.id}.pdf"
    export_to_pdf(text, filename)
    
    lang = get_user_language(message.from_user.id)
    await message.answer_document(types.FSInputFile(filename), caption=LANGUAGES[lang]["pdf_exported"])
    os.remove(filename)

# Обработчик /set_group_template
@router.message(Command("set_group_template"))
async def set_group_template_command(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("Доступ запрещён")
        return
    
    if not message.chat.type in ["group", "supergroup"]:
        await message.answer("Эта команда доступна только в группах.")
        return
    
    lang = get_user_language(message.from_user.id)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Заголовок", callback_data="group_preset_header"),
         InlineKeyboardButton(text="Объявление", callback_data="group_preset_announcement")],
        [InlineKeyboardButton(text="Мем", callback_data="group_preset_meme"),
         InlineKeyboardButton(text="Цитата", callback_data="group_preset_quote")],
        [InlineKeyboardButton(text="Тревога", callback_data="group_preset_alert"),
         InlineKeyboardButton(text="Праздник", callback_data="group_preset_holiday")],
        [InlineKeyboardButton(text="Шутка", callback_data="group_preset_joke"),
         InlineKeyboardButton(text="Важное", callback_data="group_preset_important")]
    ])
    await message.answer(LANGUAGES[lang]["set_group_template"], reply_markup=keyboard)

# Обработчик /admin_panel
@router.message(Command("admin_panel"))
async def admin_panel_command(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("Доступ запрещён")
        return
    
    lang = get_user_language(message.from_user.id)
    await message.answer(LANGUAGES[lang]["admin_menu"])

# Обработчик /users
@router.message(Command("users"))
async def users_command(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("Доступ запрещён")
        return
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, username, joined_at FROM users ORDER BY joined_at DESC LIMIT 10")
    users = c.fetchall()
    conn.close()
    
    response = "Недавние пользователи:\n"
    for user_id, username, joined_at in users:
        response += f"ID: {user_id}, @{username}, Присоединился: {joined_at}\n"
    await message.answer(response or "Пользователи не найдены.")

# Обработчик /broadcast
@router.message(Command("broadcast"))
async def broadcast_command(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("Доступ запрещён")
        return
    
    text = message.text.replace("/broadcast", "").strip()
    if not text:
        await message.answer("Укажите сообщение для рассылки.")
        return
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id FROM users")
    users = c.fetchall()
    conn.close()
    
    sent_count = 0
    for (user_id,) in users:
        try:
            await bot.send_message(user_id, text)
            sent_count += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.error(f"Не удалось отправить рассылку пользователю {user_id}: {e}")
    
    lang = get_user_language(message.from_user.id)
    await message.answer(LANGUAGES[lang]["broadcast_sent"].format(sent_count))

# Обработчик /smartreply
@router.message(Command("smartreply"))
async def smartreply_command(message: types.Message, state: FSMContext):
    lang = get_user_language(message.from_user.id)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Саркастичный", callback_data="tone_sarcastic"),
         InlineKeyboardButton(text="Дружелюбный", callback_data="tone_friendly")],
        [InlineKeyboardButton(text="Формальный", callback_data="tone_formal"),
         InlineKeyboardButton(text="Нейтральный", callback_data="tone_neutral")]
    ])
    await message.answer(LANGUAGES[lang]["choose_tone"], reply_markup=keyboard)
    await state.set_state(StyleStates.waiting_for_smartreply_tone)
    await state.update_data(text=message.text.replace("/smartreply", "").strip() or "Пример текста")

# Инлайн-режим
@router.inline_query()
async def inline_query(inline_query: types.InlineQuery):
    text = inline_query.query or "Пример текста"
    results = [
        types.InlineQueryResultArticle(
            id="bold", title="Жирный", description=f"Жирный: {text}",
            input_message_content=types.InputTextMessageContent(message_text=STYLES["bold"](text))
        ),
        types.InlineQueryResultArticle(
            id="italic", title="Курсив", description=f"Курсив: {text}",
            input_message_content=types.InputTextMessageContent(message_text=STYLES["italic"](text))
        ),
        types.InlineQueryResultArticle(
            id="fire", title="Огонь", description=f"Огонь: {text}",
            input_message_content=types.InputTextMessageContent(message_text=STYLES["fire"](text))
        ),
        types.InlineQueryResultArticle(
            id="zalgo", title="Залго", description=f"Залго: {text}",
            input_message_content=types.InputTextMessageContent(message_text=STYLES["zalgo"](text))
        )
    ]
    await inline_query.answer(results, cache_time=1)

# Обработчик callback-запросов
@router.callback_query()
async def callback_query(callback: types.CallbackQuery, state: FSMContext):
    data = callback.data
    lang = get_user_language(callback.from_user.id)
    
    if data.startswith("style_"):
        style = data.replace("style_", "")
        if is_style_restricted(callback.from_user.id, style):
            await callback.message.edit_text(LANGUAGES[lang]["style_restricted"].format(style))
            await callback.answer()
            return
        await state.set_state(StyleStates.waiting_for_style_text)
        await state.update_data(style=style)
        await callback.message.edit_text(LANGUAGES[lang]["enter_text"].format(style), reply_markup=None)
    elif data.startswith("preset_"):
        preset = data.replace("preset_", "")
        await state.set_state(StyleStates.waiting_for_preset_text)
        await state.update_data(preset=preset)
        await callback.message.edit_text(LANGUAGES[lang]["enter_text"].format(preset), reply_markup=None)
    elif data.startswith("group_preset_"):
        preset = data.replace("group_preset_", "")
        if callback.message.chat.type not in ["group", "supergroup"]:
            await callback.message.edit_text("Эта команда доступна только в группах.")
            await callback.answer()
            return
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO group_templates (chat_id, preset) VALUES (?, ?)",
                  (callback.message.chat.id, preset))
        conn.commit()
        conn.close()
        await callback.message.edit_text(LANGUAGES[lang]["group_template_set"].format(preset))
    elif data == "help":
        bot_username = (await bot.get_me()).username
        await callback.message.edit_text(LANGUAGES[lang]["help"].format(bot_username))
    elif data.startswith("copy_"):
        styled_text = data.replace("copy_", "")
        await callback.message.edit_text(styled_text, reply_markup=None)
    elif data.startswith("export_pdf_"):
        styled_text = data.replace("export_pdf_", "")
        filename = f"/tmp/output_{callback.from_user.id}.pdf"
        export_to_pdf(styled_text, filename)
        await callback.message.answer_document(types.FSInputFile(filename), caption=LANGUAGES[lang]["pdf_exported"])
        os.remove(filename)
    elif data.startswith("tone_"):
        tone = data.replace("tone_", "")
        data = await state.get_data()
        text = data.get("text", "Пример текста")
        
        result = call_gigachat_api(text, "smartreply", tone)
        if not result:
            fallback_responses = {
                "sarcastic": f"😏 Ох, {text}? Серьёзно? Это... впечатляет. 😏",
                "friendly": f"😊 Эй, {text} звучит круто! Продолжай в том же духе! 😊",
                "formal": f"Уважаемый пользователь, ваше сообщение '{text}' принято. Спасибо.",
                "neutral": f"Спасибо за сообщение: {text}."
            }
            result = fallback_responses[tone]
            await callback.message.answer(LANGUAGES[lang]["gigachat_error"].format(result))
        
        styled_text = result
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Копировать", callback_data=f"copy_{styled_text}"),
             InlineKeyboardButton(text="📄 Экспорт в PDF", callback_data=f"export_pdf_{styled_text}")]
        ])
        await callback.message.edit_text(styled_text, reply_markup=keyboard)
        await state.clear()
    
    await callback.answer()

# Обработчик текста для стилей
@router.message(StyleStates.waiting_for_style_text)
async def process_style_text(message: types.Message, state: FSMContext):
    data = await state.get_data()
    style = data.get("style")
    text = message.text.strip()
    
    if is_style_restricted(message.from_user.id, style):
        lang = get_user_language(message.from_user.id)
        await message.answer(LANGUAGES[lang]["style_restricted"].format(style))
        await state.clear()
        return
    
    styled_text = STYLES[style](text)
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO stylizations (user_id, style, text, created_at) VALUES (?, ?, ?, ?)",
              (message.from_user.id, style, text, datetime.now().isoformat()))
    conn.commit()
    conn.close()
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Копировать", callback_data=f"copy_{styled_text}"),
         InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"edit_{style}")],
        [InlineKeyboardButton(text="📄 Экспорт в PDF", callback_data=f"export_pdf_{styled_text}")]
    ])
    await message.answer(styled_text, reply_markup=keyboard)
    await state.clear()

# Обработчик текста для пресетов
@router.message(StyleStates.waiting_for_preset_text)
async def process_preset_text(message: types.Message, state: FSMContext):
    data = await state.get_data()
    preset = data.get("preset")
    text = message.text.strip()
    
    styled_text = PRESETS[preset](text)
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO stylizations (user_id, preset, text, created_at) VALUES (?, ?, ?, ?)",
              (message.from_user.id, preset, text, datetime.now().isoformat()))
    conn.commit()
    conn.close()
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Копировать", callback_data=f"copy_{styled_text}"),
         InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"edit_{preset}")],
        [InlineKeyboardButton(text="📄 Экспорт в PDF", callback_data=f"export_pdf_{styled_text}")]
    ])
    await message.answer(styled_text, reply_markup=keyboard)
    await state.clear()

# Автоформатирование и шаблоны групп
@router.message()
async def auto_format(message: types.Message):
    text = message.text.lower()
    styled_text = None
    style = None
    preset = None
    
    # Проверка шаблона группы
    if message.chat.type in ["group", "supergroup"]:
        group_preset = get_group_template(message.chat.id)
        if group_preset:
            styled_text = PRESETS[group_preset](message.text)
            preset = group_preset
    
    # Проверка триггеров
    if not styled_text:
        for keyword, config in TRIGGERS.items():
            if keyword in text:
                style = config.get("style")
                preset = config.get("preset")
                if style and not is_style_restricted(message.from_user.id, style):
                    styled_text = STYLES[style](message.text)
                elif preset:
                    styled_text = PRESETS[preset](message.text)
                break
    
    if styled_text:
        lang = get_user_language(message.from_user.id)
        if preset in TRIGGERS.values():
            await message.reply(LANGUAGES[lang]["auto_formatted"].format(keyword))
        await message.answer(styled_text)
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO stylizations (user_id, style, preset, text, created_at) VALUES (?, ?, ?, ?, ?)",
                  (message.from_user.id, style, preset, message.text, datetime.now().isoformat()))
        conn.commit()
        conn.close()

# Обработчик GigaChat команд (кроме smartreply)
@router.message(Command("gigachadify", "make_post", "rewrite"))
async def gigachat_command(message: types.Message):
    command = message.text.split()[0][1:]
    text = message.text.replace(f"/{command}", "").strip() or "Пример текста"
    lang = get_user_language(message.from_user.id)
    
    result = call_gigachat_api(text, command)
    
    if not result:
        fallback_responses = {
            "gigachadify": f"💪 <b>МАКСИМАЛЬНЫЙ {text.upper()}! ПОЛНАЯ МОЩЬ!</b> 💪",
            "make_post": f"📜 <b>Эпичный пост:</b> {text} ✨ #TextStylerPro",
            "rewrite": f"🖋 Переписано: {text.capitalize()} в стильном виде."
        }
        result = fallback_responses[command]
        await message.answer(LANGUAGES[lang]["gigachat_error"].format(result))
    
    styled_text = result
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Копировать", callback_data=f"copy_{styled_text}"),
         InlineKeyboardButton(text="📄 Экспорт в PDF", callback_data=f"export_pdf_{styled_text}")]
    ])
    await message.answer(styled_text, reply_markup=keyboard)

# Запуск бота с опросом
if __name__ == "__main__":
    asyncio.run(dp.start_polling(bot))
