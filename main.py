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
import plotly.express as px
import pandas as pd
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
DB_PATH = os.getenv("DB_PATH", "textstyler.db")
ADMIN_ID = int(os.getenv("ADMIN_ID", "123456789"))
GIGACHAT_AUTH_KEY = os.getenv("GIGACHAT_AUTH_KEY")
GIGACHAT_CLIENT_ID = os.getenv("GIGACHAT_CLIENT_ID")
if not API_TOKEN:
    raise ValueError("BOT_TOKEN not found in .env file")
if not GIGACHAT_AUTH_KEY:
    logger.warning("GIGACHAT_AUTH_KEY not found in .env, GigaChat features will use fallback")
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
        language TEXT DEFAULT 'en',
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

# Локализация
LANGUAGES = {
    "en": {
        "welcome": "Welcome to TextStyler Pro! Use /style to style text, /preset for templates, or try inline mode with @{}",
        "style_menu": "Choose a style:",
        "preset_menu": "Choose a preset:",
        "stats": "Total users: {}\nStylizations: {}\nTop style: {}",
        "admin_menu": "Admin Panel:\n- /users: List users\n- /stats: Statistics\n- /graph: Activity graph\n- /broadcast: Send message to all\n- /set_group_template: Set group template",
        "history": "Your stylizations:\n{}",
        "no_history": "No stylizations yet.",
        "enter_text": "Enter text to style in {}:",
        "broadcast_sent": "Broadcast sent to {} users.",
        "style_restricted": "Style '{}' is restricted for you.",
        "auto_formatted": "Text auto-formatted based on keyword '{}'.",
        "help": "Use /style, /preset, /random, /history, /export_pdf, or inline mode @{}",
        "gigachat_error": "GigaChat API error, using fallback: {}",
        "pdf_exported": "Text exported to PDF!",
        "set_group_template": "Choose a preset for this group:",
        "group_template_set": "Preset '{}' set for this group.",
        "choose_tone": "Choose tone for smart reply:"
    },
    "ru": {
        "welcome": "Добро пожаловать в TextStyler Pro! Используйте /style для стилизации текста, /preset для шаблонов или попробуйте инлайн-режим с @{}",
        "style_menu": "Выберите стиль:",
        "preset_menu": "Выберите шаблон:",
        "stats": "Всего пользователей: {}\nСтилизаций: {}\nПопулярный стиль: {}",
        "admin_menu": "Админ-панель:\n- /users: Список пользователей\n- /stats: Статистика\n- /graph: График активности\n- /broadcast: Рассылка всем\n- /set_group_template: Установить шаблон группы",
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
    "important": lambda text: f"💥 IMPORTANT: {text} 💥",
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
    "sarcastic": "Respond in a sarcastic and witty tone",
    "friendly": "Respond in a warm and friendly tone",
    "formal": "Respond in a professional and formal tone",
    "neutral": "Respond in a neutral and straightforward tone"
}

# FSM для ожидания текста и тона
class StyleStates(StatesGroup):
    waiting_for_style_text = State()
    waiting_for_preset_text = State()
    waiting_for_smartreply_tone = State()
    waiting_for_smartreply_text = State()

# Функция для получения языка пользователя
def get_user_language(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT language FROM users WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else "en"

# Проверка ограничений стилей
def is_style_restricted(user_id, style):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT 1 FROM restricted_styles WHERE user_id = ? AND style = ?", (user_id, style))
    result = c.fetchone()
    conn.close()
    return bool(result)

# Функция для экспорта текста в PDF
def export_to_pdf(text, filename="output.pdf"):
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
        "gigachadify": f"Make this text sound extremely confident and powerful, like a GigaChad: {text}",
        "make_post": f"Format this text as a stylish social media post: {text}",
        "smartreply": f"{TONES.get(tone, 'Respond in a neutral tone')} to this message: {text}",
        "rewrite": f"Rewrite this text in a more elegant and stylish way: {text}"
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
        [InlineKeyboardButton(text="➕ Add to Group", url=f"https://t.me/{bot_username}?startgroup=true")],
        [InlineKeyboardButton(text="📘 Help", callback_data="help"),
         InlineKeyboardButton(text="🌐 Language", callback_data="lang")]
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
        [InlineKeyboardButton(text="Bold", callback_data="style_bold"),
         InlineKeyboardButton(text="Italic", callback_data="style_italic")],
        [InlineKeyboardButton(text="Mono", callback_data="style_mono"),
         InlineKeyboardButton(text="Strike", callback_data="style_strike")],
        [InlineKeyboardButton(text="Star", callback_data="style_star"),
         InlineKeyboardButton(text="Fire", callback_data="style_fire")],
        [InlineKeyboardButton(text="Zalgo", callback_data="style_zalgo"),
         InlineKeyboardButton(text="Mirror", callback_data="style_mirror")],
        [InlineKeyboardButton(text="ASCII", callback_data="style_ascii")]
    ])
    await message.answer(LANGUAGES[lang]["style_menu"], reply_markup=keyboard)

# Обработчик /preset
@router.message(Command("preset"))
async def preset_command(message: types.Message):
    lang = get_user_language(message.from_user.id)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Header", callback_data="preset_header"),
         InlineKeyboardButton(text="Announcement", callback_data="preset_announcement")],
        [InlineKeyboardButton(text="Meme", callback_data="preset_meme"),
         InlineKeyboardButton(text="Quote", callback_data="preset_quote")],
        [InlineKeyboardButton(text="Alert", callback_data="preset_alert"),
         InlineKeyboardButton(text="Holiday", callback_data="preset_holiday")],
        [InlineKeyboardButton(text="Joke", callback_data="preset_joke"),
         InlineKeyboardButton(text="Important", callback_data="preset_important")]
    ])
    await message.answer(LANGUAGES[lang]["preset_menu"], reply_markup=keyboard)

# Обработчик /random
@router.message(Command("random"))
async def random_command(message: types.Message):
    text = message.text.replace("/random", "").strip() or "Sample text"
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
        [InlineKeyboardButton(text="✅ Copy", callback_data=f"copy_{styled_text}"),
         InlineKeyboardButton(text="✏️ Edit", callback_data=f"edit_{style}")],
        [InlineKeyboardButton(text="📄 Export PDF", callback_data=f"export_pdf_{styled_text}")]
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
        format_type = preset or style or "unknown"
        history_text += f"{i}. {format_type}: {text} ({created_at})\n"
    
    await message.answer(LANGUAGES[lang]["history"].format(history_text))

# Обработчик /clear
@router.message(Command("clear"))
async def clear_command(message: types.Message):
    text = message.text.replace("/clear", "").strip() or "Sample text"
    clean_text = re.sub(r'<[^>]+>|`{1,3}|[\*_~]', '', text)
    await message.answer(clean_text)

# Обработчик /export_pdf
@router.message(Command("export_pdf"))
async def export_pdf_command(message: types.Message):
    text = message.text.replace("/export_pdf", "").strip() or "Sample text"
    filename = f"output_{message.from_user.id}.pdf"
    export_to_pdf(text, filename)
    
    lang = get_user_language(message.from_user.id)
    await message.answer_document(types.FSInputFile(filename), caption=LANGUAGES[lang]["pdf_exported"])
    os.remove(filename)

# Обработчик /set_group_template
@router.message(Command("set_group_template"))
async def set_group_template_command(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("Access denied")
        return
    
    if not message.chat.type in ["group", "supergroup"]:
        await message.answer("This command can only be used in groups.")
        return
    
    lang = get_user_language(message.from_user.id)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Header", callback_data="group_preset_header"),
         InlineKeyboardButton(text="Announcement", callback_data="group_preset_announcement")],
        [InlineKeyboardButton(text="Meme", callback_data="group_preset_meme"),
         InlineKeyboardButton(text="Quote", callback_data="group_preset_quote")],
        [InlineKeyboardButton(text="Alert", callback_data="group_preset_alert"),
         InlineKeyboardButton(text="Holiday", callback_data="group_preset_holiday")],
        [InlineKeyboardButton(text="Joke", callback_data="group_preset_joke"),
         InlineKeyboardButton(text="Important", callback_data="group_preset_important")]
    ])
    await message.answer(LANGUAGES[lang]["set_group_template"], reply_markup=keyboard)

# Обработчик /admin_panel
@router.message(Command("admin_panel"))
async def admin_panel_command(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("Access denied")
        return
    
    lang = get_user_language(message.from_user.id)
    await message.answer(LANGUAGES[lang]["admin_menu"])

# Обработчик /users
@router.message(Command("users"))
async def users_command(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("Access denied")
        return
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, username, joined_at FROM users ORDER BY joined_at DESC LIMIT 10")
    users = c.fetchall()
    conn.close()
    
    response = "Recent users:\n"
    for user_id, username, joined_at in users:
        response += f"ID: {user_id}, @{username}, Joined: {joined_at}\n"
    await message.answer(response or "No users found.")

# Обработчик /stats
@router.message(Command("stats"))
async def stats_command(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("Access denied")
        return
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    total_users = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM stylizations")
    total_stylizations = c.fetchone()[0]
    c.execute("SELECT style, COUNT(*) as count FROM stylizations GROUP BY style ORDER BY count DESC LIMIT 1")
    top_style = c.fetchone()
    top_style = top_style[0] if top_style else "None"
    conn.close()
    
    lang = get_user_language(message.from_user.id)
    await message.answer(LANGUAGES[lang]["stats"].format(total_users, total_stylizations, top_style))

# Обработчик /graph
@router.message(Command("graph"))
async def graph_command(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("Access denied")
        return
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT created_at, style FROM stylizations")
    data = c.fetchall()
    conn.close()
    
    df = pd.DataFrame(data, columns=["created_at", "style"])
    df["created_at"] = pd.to_datetime(df["created_at"])
    df["date"] = df["created_at"].dt.date
    
    activity = df.groupby("date").size().reset_index(name="count")
    fig1 = px.line(activity, x="date", y="count", title="Activity Over Time")
    fig1.write_to_file("activity_graph.html")
    
    top_styles = df["style"].value_counts().reset_index(name="count")
    fig2 = px.pie(top_styles, values="count", names="style", title="Top Styles")
    fig2.write_to_file("top_styles.png")
    
    await message.answer_document(types.FSInputFile("activity_graph.html"))
    await message.answer_document(types.FSInputFile("top_styles.png"))

# Обработчик /broadcast
@router.message(Command("broadcast"))
async def broadcast_command(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("Access denied")
        return
    
    text = message.text.replace("/broadcast", "").strip()
    if not text:
        await message.answer("Please provide a message to broadcast.")
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
            logger.error(f"Failed to send broadcast to {user_id}: {e}")
    
    lang = get_user_language(message.from_user.id)
    await message.answer(LANGUAGES[lang]["broadcast_sent"].format(sent_count))

# Обработчик /smartreply
@router.message(Command("smartreply"))
async def smartreply_command(message: types.Message, state: FSMContext):
    lang = get_user_language(message.from_user.id)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Sarcastic", callback_data="tone_sarcastic"),
         InlineKeyboardButton(text="Friendly", callback_data="tone_friendly")],
        [InlineKeyboardButton(text="Formal", callback_data="tone_formal"),
         InlineKeyboardButton(text="Neutral", callback_data="tone_neutral")]
    ])
    await message.answer(LANGUAGES[lang]["choose_tone"], reply_markup=keyboard)
    await state.set_state(StyleStates.waiting_for_smartreply_tone)
    await state.update_data(text=message.text.replace("/smartreply", "").strip() or "Sample text")

# Инлайн-режим
@router.inline_query()
async def inline_query(inline_query: types.InlineQuery):
    text = inline_query.query or "Sample text"
    results = [
        types.InlineQueryResultArticle(
            id="bold", title="Bold", description=f"Bold: {text}",
            input_message_content=types.InputTextMessageContent(message_text=STYLES["bold"](text))
        ),
        types.InlineQueryResultArticle(
            id="italic", title="Italic", description=f"Italic: {text}",
            input_message_content=types.InputTextMessageContent(message_text=STYLES["italic"](text))
        ),
        types.InlineQueryResultArticle(
            id="fire", title="Fire", description=f"Fire: {text}",
            input_message_content=types.InputTextMessageContent(message_text=STYLES["fire"](text))
        ),
        types.InlineQueryResultArticle(
            id="zalgo", title="Zalgo", description=f"Zalgo: {text}",
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
            await callback.message.edit_text("This command can only be used in groups.")
            await callback.answer()
            return
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO group_templates (chat_id, preset) VALUES (?, ?)",
                  (callback.message.chat.id, preset))
        conn.commit()
        conn.close()
        await callback.message.edit_text(LANGUAGES[lang]["group_template_set"].format(preset))
    elif data == "lang":
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🇷🇺 Русский", callback_data="set_lang_ru"),
             InlineKeyboardButton(text="🇬🇧 English", callback_data="set_lang_en")]
        ])
        await callback.message.edit_text("Choose language:", reply_markup=keyboard)
    elif data.startswith("set_lang_"):
        lang = data.replace("set_lang_", "")
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE users SET language = ? WHERE user_id = ?", (lang, callback.from_user.id))
        conn.commit()
        conn.close()
        await callback.message.edit_text(f"Language set to {lang}")
    elif data.startswith("copy_"):
        styled_text = data.replace("copy_", "")
        await callback.message.edit_text(styled_text, reply_markup=None)
    elif data.startswith("export_pdf_"):
        styled_text = data.replace("export_pdf_", "")
        filename = f"output_{callback.from_user.id}.pdf"
        export_to_pdf(styled_text, filename)
        await callback.message.answer_document(types.FSInputFile(filename), caption=LANGUAGES[lang]["pdf_exported"])
        os.remove(filename)
    elif data == "help":
        bot_username = (await bot.get_me()).username
        await callback.message.edit_text(LANGUAGES[lang]["help"].format(bot_username))
    elif data.startswith("tone_"):
        tone = data.replace("tone_", "")
        data = await state.get_data()
        text = data.get("text", "Sample text")
        
        result = call_gigachat_api(text, "smartreply", tone)
        if not result:
            fallback_responses = {
                "sarcastic": f"😏 Oh, {text}? Really? That's... impressive. 😏",
                "friendly": f"😊 Hey, {text} sounds awesome! Keep it up! 😊",
                "formal": f"Dear user, your message '{text}' has been noted. Thank you.",
                "neutral": f"Thanks for sharing: {text}."
            }
            result = fallback_responses[tone]
            await callback.message.answer(LANGUAGES[lang]["gigachat_error"].format(result))
        
        styled_text = result
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Copy", callback_data=f"copy_{styled_text}"),
             InlineKeyboardButton(text="📄 Export PDF", callback_data=f"export_pdf_{styled_text}")]
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
        [InlineKeyboardButton(text="✅ Copy", callback_data=f"copy_{styled_text}"),
         InlineKeyboardButton(text="✏️ Edit", callback_data=f"edit_{style}")],
        [InlineKeyboardButton(text="📄 Export PDF", callback_data=f"export_pdf_{styled_text}")]
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
        [InlineKeyboardButton(text="✅ Copy", callback_data=f"copy_{styled_text}"),
         InlineKeyboardButton(text="✏️ Edit", callback_data=f"edit_{preset}")],
        [InlineKeyboardButton(text="📄 Export PDF", callback_data=f"export_pdf_{styled_text}")]
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
    text = message.text.replace(f"/{command}", "").strip() or "Sample text"
    lang = get_user_language(message.from_user.id)
    
    result = call_gigachat_api(text, command)
    
    if not result:
        fallback_responses = {
            "gigachadify": f"💪 <b>ULTIMATE {text.upper()}! MAXIMUM POWER!</b> 💪",
            "make_post": f"📜 <b>Epic Post:</b> {text} ✨ #TextStylerPro",
            "rewrite": f"🖋 Rewritten: {text.capitalize()} in a stylish way."
        }
        result = fallback_responses[command]
        await message.answer(LANGUAGES[lang]["gigachat_error"].format(result))
    
    styled_text = result
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Copy", callback_data=f"copy_{styled_text}"),
         InlineKeyboardButton(text="📄 Export PDF", callback_data=f"export_pdf_{styled_text}")]
    ])
    await message.answer(styled_text, reply_markup=keyboard)

# Запуск бота
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
