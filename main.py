import asyncio
import logging
import sqlite3
import csv
import io
import os
import random
import re
import uuid
from datetime import datetime, timedelta
import requests
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command, CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram import Router
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from dotenv import load_dotenv
import zalgo_text.zalgo as zalgo
import pyfiglet
from googletrans import Translator
import qrcode
from gtts import gTTS
from PIL import Image
import matplotlib.pyplot as plt
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Загрузка переменных окружения
load_dotenv()
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

# Инициализация API клиентов
translator = Translator()

# Инициализация базы данных
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        language TEXT DEFAULT 'ru',
        joined_at TEXT,
        captcha_passed INTEGER DEFAULT 0
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
    c.execute("""CREATE TABLE IF NOT EXISTS reminders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        text TEXT,
        remind_at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS welcome_messages (
        chat_id INTEGER PRIMARY KEY,
        message TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS feedback (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        text TEXT,
        created_at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS channel_settings (
        chat_id INTEGER PRIMARY KEY,
        captcha_enabled INTEGER DEFAULT 0,
        captcha_mode TEXT DEFAULT 'button',
        captcha_text TEXT DEFAULT 'Подтвердите, что вы не бот'
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS admin_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER,
        admin_id INTEGER,
        action TEXT,
        target_user_id INTEGER,
        created_at TEXT
    )""")
    conn.commit()
    conn.close()

init_db()

# Локализация
LANGUAGES = {
    "ru": {
        "welcome": "Добро пожаловать в TextStyler Pro! Пройдите капчу, чтобы начать. Используйте /style для стилизации текста, /preset для шаблонов или /guide для инструкции.",
        "style_menu": "🌟 Выберите стиль:",
        "preset_menu": "🎨 Выберите шаблон:",
        "admin_menu": "⚙️ Админ-панель:\n- /users: 👥 Список пользователей\n- /broadcast: 📢 Рассылка всем\n- /set_group_template: 🖌️ Установить шаблон группы\n- /ban: 🚫 Бан\n- /mute: 🔇 Мут\n- /stats: 📊 Статистика",
        "history": "📜 Ваши стилизации:\n{}",
        "no_history": "Пока нет стилизаций.",
        "enter_text": "✍️ Введите текст для стилизации в {}:",
        "broadcast_sent": "📬 Рассылка отправлена {} пользователям.",
        "style_restricted": "🚫 Стиль '{}' ограничен для вас.",
        "auto_formatted": "✅ Текст отформатирован по ключевому слову '{}'.",
        "help": "ℹ️ Используйте /style, /preset, /random, /history, /export_pdf, /smartreply, /poll, /quiz, /translate, /qrcode, /voice, /quote, /wiki, /joke, /riddle, /dice, /remind, /guide",
        "gigachat_error": "⚠️ Ошибка GigaChat API: {}. Используется запасной вариант.",
        "pdf_exported": "📄 Текст экспортирован в PDF!",
        "set_group_template": "🖌️ Выберите шаблон для группы:",
        "group_template_set": "✅ Шаблон '{}' установлен.",
        "choose_tone": "🎭 Выберите тон для ответа:",
        "top_styles": "🏆 Топ-5 стилей:\n{}",
        "top_users": "👑 Топ-5 пользователей:\n{}",
        "feedback_sent": "🙏 Спасибо за отзыв!",
        "reminder_set": "⏰ Напоминание на {} минут.",
        "welcome_set": "👋 Приветственное сообщение установлено.",
        "captcha_prompt": "🔒 Пройдите капчу: {} = ?",
        "captcha_success": "✅ Капча пройдена! Используйте /guide для инструкции.",
        "captcha_failed": "❌ Неверный ответ. Попробуйте снова.",
        "captcha_button": "🔒 Нажмите, чтобы подтвердить, что вы не бот",
        "captcha_text_prompt": "🔒 Выберите текст: {}",
        "captcha_math_prompt": "🔒 Решите: {}",
        "captcha_enabled": "✅ Капча включена в чате {}",
        "captcha_disabled": "❌ Капча отключена в чате {}",
        "admin_stats": "📊 Статистика:\n- Пользователей: {}\n- Активность за 7 дней: {}\n\n👥 Пользователи:\n{}",
        "rules_set": "✅ Правила установлены.",
        "filter_set": "✅ Фильтр установлен: {}",
        "log_channel_set": "✅ Лог-канал установлен: {}",
        "guide": "📖 **Инструкция по TextStyler Pro**\n\n1. **Стилизация текста**:\n- /style — выберите стиль (🌟 жирный, 🔥 огонь, и т.д.)\n- /preset — шаблоны (📢 объявление, 🎉 праздник)\n- /random — случайный стиль\n\n2. **Интерактивные функции**:\n- /poll — создайте опрос 📊\n- /quiz — викторина ❓\n- /translate — перевод 🌐\n- /qrcode — QR-коды 📷\n- /voice — текст в речь 🎙️\n\n3. **Интеграции**:\n- /quote — цитаты 💬\n- /wiki — Википедия 📚\n\n4. **Развлечения**:\n- /joke — шутки 😜\n- /riddle — загадки 🧠\n- /dice — кубик 🎲\n\n5. **Утилиты**:\n- /remind — напоминания ⏰\n- /guide — эта инструкция 📖\n\n6. **Админ-команды** (для ID {}):\n- /ban, /mute, /stats, /admin_stats, /setrules, /filters, /setlog\n\n7. **Каналы и группы**:\n- /captcha — настройка капчи\n- /setrules — установка правил\n- /setwelcome — приветственное сообщение\n\n**Капча**: Новые пользователи проходят капчу (например, 2 + 3 = ?).\n\nДобавьте бота в группу или канал: /startgroup\nПоддержка: @TextStylerSupport"
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
    "ascii": lambda text: f"<pre>{pyfiglet.figlet_format(text, font='standard')}</pre>",
    "gradient": lambda text: "".join(f"🌈{char}🌈" for char in text),
    "bubble": lambda text: "".join(chr(0x1F170 + ord(c.upper()) - ord('A')) if c.isalpha() else c for c in text),
    "smallcaps": lambda text: "".join(chr(0x1D43 + ord(c) - ord('a')) if c.islower() else c for c in text),
    "upside": lambda text: "".join(chr(0x1D6D + ord(c) - ord('a')) if c.islower() else c for c in text[::-1]),
    "double": lambda text: "".join(c + c for c in text),
    "emojify": lambda text: " ".join(f"{word} 📝" for word in text.split()),
    "textshadow": lambda text: f"{text} ➡️",
    "customemoji": lambda text, emoji="✨": f"{emoji} {text} {emoji}"
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

# Триггеры
TRIGGERS = {
    "важно": {"preset": "important"},
    "срочно": {"preset": "alert"},
    "праздник": {"preset": "holiday"},
    "шутка": {"preset": "joke"}
}

# Тоны
TONES = {
    "sarcastic": "Отвечай в саркастичном и остроумном тоне",
    "friendly": "Отвечай в тёплом и дружелюбном тоне",
    "formal": "Отвечай в профессиональном и формальном тоне",
    "neutral": "Отвечай в нейтральном и прямолинейном тоне"
}

# FSM состояния
class StyleStates(StatesGroup):
    waiting_for_style_text = State()
    waiting_for_preset_text = State()
    waiting_for_smartreply_tone = State()
    waiting_for_smartreply_text = State()
    waiting_for_reminder = State()
    waiting_for_feedback = State()
    waiting_for_welcome = State()
    waiting_for_captcha = State()
    waiting_for_captcha_config = State()
    waiting_for_rules = State()
    waiting_for_filter = State()
    waiting_for_log_channel = State()

# Утилиты
def get_user_language(user_id):
    return "ru"

def is_style_restricted(user_id, style):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT 1 FROM restricted_styles WHERE user_id = ? AND style = ?", (user_id, style))
    result = c.fetchone()
    conn.close()
    return bool(result)

def has_passed_captcha(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT captcha_passed FROM users WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    return bool(result and result[0])

def set_captcha_passed(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET captcha_passed = 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def generate_captcha(mode="button"):
    if mode == "button":
        return None, None, ["Подтвердить"]
    elif mode == "math":
        a, b = random.randint(1, 10), random.randint(1, 10)
        correct = a + b
        question = f"{a} + {b}"
        answers = [correct, correct + random.randint(1, 5), correct - random.randint(1, 5)]
        random.shuffle(answers)
        return question, correct, answers
    elif mode == "text":
        texts = ["Солнце", "Луна", "Звезда"]
        correct = random.choice(texts)
        answers = texts.copy()
        random.shuffle(answers)
        return correct, correct, answers

def export_to_pdf(text, filename="/tmp/output.pdf"):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
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

def get_group_template(chat_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT preset FROM group_templates WHERE chat_id = ?", (chat_id,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else None

def get_channel_settings(chat_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT captcha_enabled, captcha_mode, captcha_text FROM channel_settings WHERE chat_id = ?", (chat_id,))
    result = c.fetchone()
    conn.close()
    return {"enabled": result[0], "mode": result[1], "text": result[2]} if result else {"enabled": 0, "mode": "button", "text": "Подтвердите, что вы не бот"}

def set_channel_settings(chat_id, enabled, mode, text):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO channel_settings (chat_id, captcha_enabled, captcha_mode, captcha_text) VALUES (?, ?, ?, ?)",
              (chat_id, enabled, mode, text))
    conn.commit()
    conn.close()

@retry(stop=stop_after_attempt(3), wait=wait_fixed(2), retry=retry_if_exception_type(requests.RequestException))
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
        logger.info("GigaChat token obtained successfully")
        return data.get('access_token'), data.get('expires_at')
    except Exception as e:
        logger.error(f"Failed to get GigaChat token: {e}")
        raise

@retry(stop=stop_after_attempt(3), wait=wait_fixed(2), retry=retry_if_exception_type(requests.RequestException))
def call_gigachat_api(text, command, tone=None):
    if not GIGACHAT_AUTH_KEY:
        logger.warning("GIGACHAT_AUTH_KEY not set")
        return None
    token, expires_at = get_gigachat_token()
    if not token:
        logger.error("No GigaChat token available")
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
        logger.info(f"GigaChat API call successful for command: {command}")
        return data['choices'][0]['message']['content']
    except Exception as e:
        logger.error(f"GigaChat API error: {e}")
        return None

# Обработчики капчи
async def send_captcha(message: types.Message, state: FSMContext, chat_id=None, user_id=None):
    lang = get_user_language(user_id or message.from_user.id)
    settings = get_channel_settings(chat_id or message.chat.id)
    mode = settings["mode"]
    question, correct, answers = generate_captcha(mode)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=str(ans), callback_data=f"captcha_{ans}_{correct}_{chat_id or message.chat.id}_{user_id or message.from_user.id}") for ans in answers]
    ])
    await state.set_state(StyleStates.waiting_for_captcha)
    await state.update_data(correct_answer=correct, chat_id=chat_id or message.chat.id, user_id=user_id or message.from_user.id)
    if mode == "button":
        await bot.send_message(chat_id or message.chat.id, settings["text"], reply_markup=keyboard)
    elif mode == "math":
        await bot.send_message(chat_id or message.chat.id, LANGUAGES[lang]["captcha_math_prompt"].format(question), reply_markup=keyboard)
    elif mode == "text":
        await bot.send_message(chat_id or message.chat.id, LANGUAGES[lang]["captcha_text_prompt"].format(", ".join(answers)), reply_markup=keyboard)

@router.callback_query(lambda c: c.data.startswith("captcha_"))
async def process_captcha(callback: types.CallbackQuery, state: FSMContext):
    lang = get_user_language(callback.from_user.id)
    data = callback.data.split("_")
    user_answer = data[1]
    correct_answer = data[2]
    chat_id = int(data[3])
    user_id = int(data[4])
    if user_answer == correct_answer:
        set_captcha_passed(user_id)
        await bot.restrict_chat_member(chat_id, user_id, permissions=types.ChatPermissions(can_send_messages=True), until_date=None)
        bot_username = (await bot.get_me()).username
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить в группу", url=f"https://t.me/{bot_username}?startgroup=true")],
            [InlineKeyboardButton(text="📖 Инструкция", callback_data="guide")]
        ])
        await callback.message.edit_text(LANGUAGES[lang]["captcha_success"], reply_markup=keyboard)
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT message FROM welcome_messages WHERE chat_id = ?", (chat_id,))
        welcome = c.fetchone()
        conn.close()
        if welcome:
            await bot.send_message(chat_id, welcome[0].format(mention=f"@{callback.from_user.username or callback.from_user.first_name}"))
    else:
        await callback.message.edit_text(LANGUAGES[lang]["captcha_failed"])
        await asyncio.sleep(300)  # 5 минут
        settings = get_channel_settings(chat_id)
        if settings["enabled"]:
            try:
                await bot.ban_chat_member(chat_id, user_id)
                await bot.unban_chat_member(chat_id, user_id)
            except:
                pass
            await callback.message.delete()
    await callback.answer()
    await state.clear()

# Обработчики команд
@router.message(CommandStart())
async def start_command(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username or "Unknown"
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, username, joined_at, captcha_passed) VALUES (?, ?, ?, ?)",
              (user_id, username, datetime.now().isoformat(), 0))
    conn.commit()
    conn.close()
    if not has_passed_captcha(user_id):
        await send_captcha(message, state)
    else:
        lang = get_user_language(user_id)
        bot_username = (await bot.get_me()).username
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить в группу", url=f"https://t.me/{bot_username}?startgroup=true")],
            [InlineKeyboardButton(text="📖 Инструкция", callback_data="guide")]
        ])
        await message.answer(LANGUAGES[lang]["welcome"], reply_markup=keyboard)

@router.message(Command("guide"))
async def guide_command(message: types.Message):
    lang = get_user_language(message.from_user.id)
    await message.answer(LANGUAGES[lang]["guide"].format(ADMIN_ID))

@router.message(Command("help"))
async def help_command(message: types.Message):
    if not has_passed_captcha(message.from_user.id):
        await message.answer("Пройдите капчу с помощью /start")
        return
    lang = get_user_language(message.from_user.id)
    bot_username = (await bot.get_me()).username
    await message.answer(LANGUAGES[lang]["help"].format(bot_username))

@router.message(Command("style"))
async def style_command(message: types.Message):
    if not has_passed_captcha(message.from_user.id):
        await message.answer("Пройдите капчу с помощью /start")
        return
    lang = get_user_language(message.from_user.id)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌟 Жирный", callback_data="style_bold"),
         InlineKeyboardButton(text="📜 Курсив", callback_data="style_italic")],
        [InlineKeyboardButton(text="💻 Моно", callback_data="style_mono"),
         InlineKeyboardButton(text="✂️ Зачёркнутый", callback_data="style_strike")],
        [InlineKeyboardButton(text="✨ Звезда", callback_data="style_star"),
         InlineKeyboardButton(text="🔥 Огонь", callback_data="style_fire")],
        [InlineKeyboardButton(text="👻 Залго", callback_data="style_zalgo"),
         InlineKeyboardButton(text="🔄 Зеркало", callback_data="style_mirror")],
        [InlineKeyboardButton(text="🖼️ ASCII", callback_data="style_ascii"),
         InlineKeyboardButton(text="🌈 Градиент", callback_data="style_gradient")],
        [InlineKeyboardButton(text="🅰️ Пузырьки", callback_data="style_bubble"),
         InlineKeyboardButton(text="🔡 Мал. заглавные", callback_data="style_smallcaps")],
        [InlineKeyboardButton(text="🙃 Перевёрнутый", callback_data="style_upside"),
         InlineKeyboardButton(text="🔤 Удвоенный", callback_data="style_double")]
    ])
    await message.answer(LANGUAGES[lang]["style_menu"], reply_markup=keyboard)

@router.message(Command("preset"))
async def preset_command(message: types.Message):
    if not has_passed_captcha(message.from_user.id):
        await message.answer("Пройдите капчу с помощью /start")
        return
    lang = get_user_language(message.from_user.id)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏷️ Заголовок", callback_data="preset_header"),
         InlineKeyboardButton(text="📢 Объявление", callback_data="preset_announcement")],
        [InlineKeyboardButton(text="😂 Мем", callback_data="preset_meme"),
         InlineKeyboardButton(text="💬 Цитата", callback_data="preset_quote")],
        [InlineKeyboardButton(text="🚨 Тревога", callback_data="preset_alert"),
         InlineKeyboardButton(text="🎉 Праздник", callback_data="preset_holiday")],
        [InlineKeyboardButton(text="😜 Шутка", callback_data="preset_joke"),
         InlineKeyboardButton(text="💥 Важное", callback_data="preset_important")]
    ])
    await message.answer(LANGUAGES[lang]["preset_menu"], reply_markup=keyboard)

@router.message(Command("random"))
async def random_command(message: types.Message):
    if not has_passed_captcha(message.from_user.id):
        await message.answer("Пройдите капчу с помощью /start")
        return
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
        [InlineKeyboardButton(text="👍", callback_data="like"),
         InlineKeyboardButton(text="👎", callback_data="dislike")],
        [InlineKeyboardButton(text="✅ Копировать", callback_data=f"copy_{styled_text}"),
         InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"edit_{style}")],
        [InlineKeyboardButton(text="📄 Экспорт в PDF", callback_data=f"export_pdf_{styled_text}")]
    ])
    await message.answer(styled_text, reply_markup=keyboard)

@router.message(Command("poll"))
async def poll_command(message: types.Message):
    if not has_passed_captcha(message.from_user.id):
        await message.answer("Пройдите капчу с помощью /start")
        return
    lang = get_user_language(message.from_user.id)
    text = message.text.replace("/poll", "").strip()
    if not text:
        await message.answer("📊 Укажите вопрос для опроса, например: /poll Какой стиль лучше? | Опция1 | Опция2")
        return
    parts = text.split("|")
    question = parts[0].strip()
    options = [opt.strip() for opt in parts[1:]] if len(parts) > 1 else ["Да", "Нет"]
    await message.answer_poll(question=question, options=options, is_anonymous=True)

@router.message(Command("quiz"))
async def quiz_command(message: types.Message):
    if not has_passed_captcha(message.from_user.id):
        await message.answer("Пройдите капчу с помощью /start")
        return
    lang = get_user_language(message.from_user.id)
    text = message.text.replace("/quiz", "").strip()
    if not text:
        await message.answer("❓ Укажите вопрос и ответы, например: /quiz Столица Франции? | Париж | Лондон | Берлин | Париж")
        return
    parts = text.split("|")
    question = parts[0].strip()
    options = [opt.strip() for opt in parts[1:-1]] if len(parts) > 2 else ["Да", "Нет"]
    correct = parts[-1].strip() if len(parts) > 1 else options[0]
    correct_option_id = options.index(correct) if correct in options else 0
    await message.answer_poll(
        question=question,
        options=options,
        type="quiz",
        correct_option_id=correct_option_id,
        is_anonymous=False
    )

@router.message(Command("translate"))
async def translate_command(message: types.Message):
    if not has_passed_captcha(message.from_user.id):
        await message.answer("Пройдите капчу с помощью /start")
        return
    lang = get_user_language(message.from_user.id)
    text = message.text.replace("/translate", "").strip()
    if not text:
        await message.answer("🌐 Укажите текст и язык, например: /translate Привет, мир! en")
        return
    parts = text.rsplit(" ", 1)
    text_to_translate = parts[0]
    dest_lang = parts[1] if len(parts) > 1 else "en"
    try:
        translated = translator.translate(text_to_translate, dest=dest_lang)
        await message.answer(f"Перевод ({dest_lang}): {translated.text}")
    except Exception as e:
        await message.answer(f"⚠️ Ошибка: {str(e)}")

@router.message(Command("qrcode"))
async def qrcode_command(message: types.Message):
    if not has_passed_captcha(message.from_user.id):
        await message.answer("Пройдите капчу с помощью /start")
        return
    lang = get_user_language(message.from_user.id)
    text = message.text.replace("/qrcode", "").strip() or "Пример текста"
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    filename = f"/tmp/qr_{message.from_user.id}.png"
    img.save(filename)
    await message.answer_photo(types.FSInputFile(filename))
    os.remove(filename)

@router.message(Command("voice"))
async def voice_command(message: types.Message):
    if not has_passed_captcha(message.from_user.id):
        await message.answer("Пройдите капчу с помощью /start")
        return
    lang = get_user_language(message.from_user.id)
    text = message.text.replace("/voice", "").strip() or "Пример текста"
    tts = gTTS(text=text, lang="ru")
    filename = f"/tmp/voice_{message.from_user.id}.mp3"
    tts.save(filename)
    await message.answer_voice(types.FSInputFile(filename))
    os.remove(filename)

@router.message(Command("anonymize"))
async def anonymize_command(message: types.Message):
    if not has_passed_captcha(message.from_user.id):
        await message.answer("Пройдите капчу с помощью /start")
        return
    lang = get_user_language(message.from_user.id)
    text = message.text.replace("/anonymize", "").strip()
    if not text:
        await message.answer("🕵️ Укажите текст для анонимного сообщения.")
        return
    if message.chat.type not in ["group", "supergroup"]:
        await message.answer("Эта команда работает только в группах.")
        return
    await message.chat.send_message(f"Анонимное сообщение: {text}")

@router.message(Command("ban"))
async def ban_command(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("🚫 Доступ запрещён")
        return
    if not message.reply_to_message:
        await message.answer("Ответьте на сообщение пользователя для бана.")
        return
    user_id = message.reply_to_message.from_user.id
    await message.chat.ban(user_id)
    await message.answer(f"Пользователь {user_id} забанен.")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO admin_logs (chat_id, admin_id, action, target_user_id, created_at) VALUES (?, ?, ?, ?, ?)",
              (message.chat.id, message.from_user.id, "ban", user_id, datetime.now().isoformat()))
    conn.commit()
    conn.close()

@router.message(Command("mute"))
async def mute_command(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("🚫 Доступ запрещён")
        return
    if not message.reply_to_message:
        await message.answer("Ответьте на сообщение пользователя и укажите время в минутах, например: /mute 30")
        return
    user_id = message.reply_to_message.from_user.id
    minutes = int(message.text.replace("/mute", "").strip() or 30)
    until_date = datetime.now() + timedelta(minutes=minutes)
    await message.chat.restrict(user_id, permissions=types.ChatPermissions(can_send_messages=False), until_date=until_date)
    await message.answer(f"Пользователь {user_id} заглушен на {minutes} минут.")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO admin_logs (chat_id, admin_id, action, target_user_id, created_at) VALUES (?, ?, ?, ?, ?)",
              (message.chat.id, message.from_user.id, "mute", user_id, datetime.now().isoformat()))
    conn.commit()
    conn.close()

@router.message(Command("pin"))
async def pin_command(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("🚫 Доступ запрещён")
        return
    if not message.reply_to_message:
        await message.answer("Ответьте на сообщение для закрепления.")
        return
    await message.reply_to_message.pin()
    await message.answer("📌 Сообщение закреплено.")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO admin_logs (chat_id, admin_id, action, target_user_id, created_at) VALUES (?, ?, ?, ?, ?)",
              (message.chat.id, message.from_user.id, "pin", None, datetime.now().isoformat()))
    conn.commit()
    conn.close()

@router.message(Command("stats"))
async def stats_command(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("🚫 Доступ запрещён")
        return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    total_users = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM stylizations")
    total_styles = c.fetchone()[0]
    conn.close()
    await message.answer(f"📊 Статистика:\n- Пользователей: {total_users}\n- Стилизаций: {total_styles}")

@router.message(Command("admin_stats"))
async def admin_stats_command(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("🚫 Доступ запрещён")
        return
    lang = get_user_language(message.from_user.id)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    total_users = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM stylizations WHERE created_at > ?",
              ((datetime.now() - timedelta(days=7)).isoformat(),))
    recent_activity = c.fetchone()[0]
    c.execute("SELECT user_id, username, joined_at FROM users LIMIT 10")
    users = c.fetchall()
    user_info = "\n".join(f"ID: {u[0]}, @{u[1] or 'NoUsername'}, Регистрация: {u[2]}" for u in users)
    conn.close()
    await message.answer(LANGUAGES[lang]["admin_stats"].format(total_users, recent_activity, user_info))

@router.message(Command("clearhistory"))
async def clear_history_command(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("🚫 Доступ запрещён")
        return
    user_id = message.reply_to_message.from_user.id if message.reply_to_message else message.from_user.id
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM stylizations WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    await message.answer(f"🗑️ История стилизаций для пользователя {user_id} очищена.")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO admin_logs (chat_id, admin_id, action, target_user_id, created_at) VALUES (?, ?, ?, ?, ?)",
              (message.chat.id, message.from_user.id, "clearhistory", user_id, datetime.now().isoformat()))
    conn.commit()
    conn.close()

@router.message(Command("restrictstyle"))
async def restrict_style_command(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("🚫 Доступ запрещён")
        return
    parts = message.text.replace("/restrictstyle", "").strip().split()
    if len(parts) != 2:
        await message.answer("Укажите user_id и стиль, например: /restrictstyle 123456789 bold")
        return
    user_id, style = parts
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO restricted_styles (user_id, style) VALUES (?, ?)", (int(user_id), style))
    conn.commit()
    conn.close()
    await message.answer(f"🚫 Стиль {style} ограничен для пользователя {user_id}.")
    c.execute("INSERT INTO admin_logs (chat_id, admin_id, action, target_user_id, created_at) VALUES (?, ?, ?, ?, ?)",
              (message.chat.id, message.from_user.id, "restrictstyle", int(user_id), datetime.now().isoformat()))
    conn.commit()
    conn.close()

@router.message(Command("setwelcome"))
async def set_welcome_command(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await message.answer("🚫 Доступ запрещён")
        return
    lang = get_user_language(message.from_user.id)
    await state.set_state(StyleStates.waiting_for_welcome)
    await state.update_data(chat_id=message.chat.id)
    await message.answer("👋 Введите приветственное сообщение для новых участников.")

@router.message(Command("setrules"))
async def set_rules_command(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await message.answer("🚫 Доступ запрещён")
        return
    lang = get_user_language(message.from_user.id)
    await state.set_state(StyleStates.waiting_for_rules)
    await state.update_data(chat_id=message.chat.id)
    await message.answer("📜 Введите правила чата.")

@router.message(Command("filters"))
async def filters_command(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await message.answer("🚫 Доступ запрещён")
        return
    lang = get_user_language(message.from_user.id)
    await state.set_state(StyleStates.waiting_for_filter)
    await state.update_data(chat_id=message.chat.id)
    await message.answer("🚫 Введите слово или фразу для фильтрации.")

@router.message(Command("setlog"))
async def set_log_command(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await message.answer("🚫 Доступ запрещён")
        return
    lang = get_user_language(message.from_user.id)
    await state.set_state(StyleStates.waiting_for_log_channel)
    await state.update_data(admin_id=message.from_user.id)
    await message.answer("📝 Укажите ID канала для логов (например, -1001234567890).")

@router.message(Command("captcha"))
async def captcha_command(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await message.answer("🚫 Доступ запрещён")
        return
    lang = get_user_language(message.from_user.id)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔛 Включить", callback_data="captcha_enable"),
         InlineKeyboardButton(text="🔴 Выключить", callback_data="captcha_disable")],
        [InlineKeyboardButton(text="🛠️ Настроить", callback_data="captcha_configure")]
    ])
    await state.set_state(StyleStates.waiting_for_captcha_config)
    await state.update_data(chat_id=message.chat.id)
    await message.answer("🔒 Настройка капчи:", reply_markup=keyboard)

@router.message(Command("exportdb"))
async def export_db_command(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("🚫 Доступ запрещён")
        return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM stylizations")
    rows = c.fetchall()
    columns = [desc[0] for desc in c.description]
    conn.close()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(columns)
    writer.writerows(rows)
    filename = f"/tmp/stylizations_{message.from_user.id}.csv"
    with open(filename, "w") as f:
        f.write(output.getvalue())
    await message.answer_document(types.FSInputFile(filename), caption="📂 Экспорт базы данных")
    os.remove(filename)

@router.message(Command("topstyles"))
async def top_styles_command(message: types.Message):
    if not has_passed_captcha(message.from_user.id):
        await message.answer("Пройдите капчу с помощью /start")
        return
    lang = get_user_language(message.from_user.id)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT style, COUNT(*) as count FROM stylizations WHERE style IS NOT NULL GROUP BY style ORDER BY count DESC LIMIT 5")
    styles = c.fetchall()
    conn.close()
    response = "\n".join(f"{style}: {count} раз" for style, count in styles)
    await message.answer(LANGUAGES[lang]["top_styles"].format(response or "Стили пока не использовались."))

@router.message(Command("topusers"))
async def top_users_command(message: types.Message):
    if not has_passed_captcha(message.from_user.id):
        await message.answer("Пройдите капчу с помощью /start")
        return
    lang = get_user_language(message.from_user.id)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, username, COUNT(*) as count FROM stylizations JOIN users ON stylizations.user_id = users.user_id GROUP BY user_id ORDER BY count DESC LIMIT 5")
    users = c.fetchall()
    conn.close()
    response = "\n".join(f"@{username} ({user_id}): {count} стилизаций" for user_id, username, count in users)
    await message.answer(LANGUAGES[lang]["top_users"].format(response or "Пользователи пока не активны."))

@router.message(Command("usage"))
async def usage_command(message: types.Message):
    if not has_passed_captcha(message.from_user.id):
        await message.answer("Пройдите капчу с помощью /start")
        return
    lang = get_user_language(message.from_user.id)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT style, preset, COUNT(*) as count FROM stylizations WHERE created_at > ? GROUP BY style, preset",
              ((datetime.now() - timedelta(days=7)).isoformat(),))
    usage = c.fetchall()
    conn.close()
    response = "📈 Использование за неделю:\n" + "\n".join(f"{style or preset}: {count} раз" for style, preset, count in usage)
    await message.answer(response or "Нет данных за последнюю неделю.")

@router.message(Command("activity"))
async def activity_command(message: types.Message):
    if not has_passed_captcha(message.from_user.id):
        await message.answer("Пройдите капчу с помощью /start")
        return
    lang = get_user_language(message.from_user.id)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT strftime('%Y-%m-%d', created_at) as day, COUNT(*) as count FROM stylizations WHERE created_at > ? GROUP BY day",
              ((datetime.now() - timedelta(days=7)).isoformat(),))
    data = c.fetchall()
    conn.close()
    if not data:
        await message.answer("📉 Нет активности за последнюю неделю.")
        return
    days, counts = zip(*data)
    plt.figure(figsize=(8, 4))
    plt.plot(days, counts)
    plt.xlabel("Дата")
    plt.ylabel("Стилизации")
    plt.xticks(rotation=45)
    filename = f"/tmp/activity_{message.from_user.id}.png"
    plt.savefig(filename, bbox_inches="tight")
    plt.close()
    await message.answer_photo(types.FSInputFile(filename))
    os.remove(filename)

@router.message(Command("feedback"))
async def feedback_command(message: types.Message, state: FSMContext):
    if not has_passed_captcha(message.from_user.id):
        await message.answer("Пройдите капчу с помощью /start")
        return
    lang = get_user_language(message.from_user.id)
    await state.set_state(StyleStates.waiting_for_feedback)
    await state.update_data(user_id=message.from_user.id)
    await message.answer("📝 Введите ваш отзыв или предложение.")

@router.message(Command("quote"))
async def quote_command(message: types.Message):
    if not has_passed_captcha(message.from_user.id):
        await message.answer("Пройдите капчу с помощью /start")
        return
    lang = get_user_language(message.from_user.id)
    response = requests.get("https://api.quotable.io/random")
    if response.ok:
        quote = response.json()
        await message.answer(f"💬 \"{quote['content']}\" — {quote['author']}")
    else:
        await message.answer("Не удалось загрузить цитату.")

@router.message(Command("wiki"))
async def wiki_command(message: types.Message):
    if not has_passed_captcha(message.from_user.id):
        await message.answer("Пройдите капчу с помощью /start")
        return
    lang = get_user_language(message.from_user.id)
    query = message.text.replace("/wiki", "").strip() or "Википедия"
    try:
        summary = wikipedia.summary(query, sentences=2)
        await message.answer(summary)
    except Exception as e:
        await message.answer(f"⚠️ Ошибка: {str(e)}")

@router.message(Command("joke"))
async def joke_command(message: types.Message):
    if not has_passed_captcha(message.from_user.id):
        await message.answer("Пройдите капчу с помощью /start")
        return
    lang = get_user_language(message.from_user.id)
    response = requests.get("https://official-joke-api.appspot.com/random_joke")
    if response.ok:
        joke = response.json()
        await message.answer(f"😜 {joke['setup']}\n{joke['punchline']}")
    else:
        await message.answer("Не удалось загрузить шутку.")

@router.message(Command("riddle"))
async def riddle_command(message: types.Message):
    if not has_passed_captcha(message.from_user.id):
        await message.answer("Пройдите капчу с помощью /start")
        return
    lang = get_user_language(message.from_user.id)
    riddles = [
        {"question": "Что всегда впереди, но никогда не приходит?", "answer": "Завтра"},
        {"question": "Что летает без крыльев?", "answer": "Время"}
    ]
    riddle = random.choice(riddles)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧠 Показать ответ", callback_data=f"riddle_answer_{riddle['answer']}")]
    ])
    await message.answer(riddle["question"], reply_markup=keyboard)

@router.message(Command("dice"))
async def dice_command(message: types.Message):
    if not has_passed_captcha(message.from_user.id):
        await message.answer("Пройдите капчу с помощью /start")
        return
    lang = get_user_language(message.from_user.id)
    result = random.randint(1, 6)
    await message.answer(f"🎲 Выпало: {result}")

@router.message(Command("remind"))
async def remind_command(message: types.Message, state: FSMContext):
    if not has_passed_captcha(message.from_user.id):
        await message.answer("Пройдите капчу с помощью /start")
        return
    lang = get_user_language(message.from_user.id)
    text = message.text.replace("/remind", "").strip()
    if not text:
        await message.answer("⏰ Укажите текст и время, например: /remind Встреча через 10 минут")
        return
    await state.set_state(StyleStates.waiting_for_reminder)
    await state.update_data(reminder_text=text, user_id=message.from_user.id)
    await message.answer("Через сколько минут напомнить?")

@router.message(Command("backup"))
async def backup_command(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("🚫 Доступ запрещён")
        return
    filename = f"/tmp/backup_{message.from_user.id}.db"
    import shutil
    shutil.copy(DB_PATH, filename)
    await message.answer_document(types.FSInputFile(filename), caption="💾 Резервная копия базы данных")
    os.remove(filename)

@router.message(Command("smartreply"))
async def smartreply_command(message: types.Message, state: FSMContext):
    if not has_passed_captcha(message.from_user.id):
        await message.answer("Пройдите капчу с помощью /start")
        return
    lang = get_user_language(message.from_user.id)
    if not message.reply_to_message:
        await message.answer("Ответьте на сообщение для умного ответа.")
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="😏 Сарказм", callback_data="tone_sarcastic"),
         InlineKeyboardButton(text="😊 Дружелюбно", callback_data="tone_friendly")],
        [InlineKeyboardButton(text="📝 Формально", callback_data="tone_formal"),
         InlineKeyboardButton(text="😐 Нейтрально", callback_data="tone_neutral")]
    ])
    await state.set_state(StyleStates.waiting_for_smartreply_tone)
    await state.update_data(original_text=message.reply_to_message.text)
    await message.answer(LANGUAGES[lang]["choose_tone"], reply_markup=keyboard)

@router.message(Command("gigachadify"))
async def gigachadify_command(message: types.Message):
    if not has_passed_captcha(message.from_user.id):
        await message.answer("Пройдите капчу с помощью /start")
        return
    lang = get_user_language(message.from_user.id)
    text = message.text.replace("/gigachadify", "").strip() or "Пример текста"
    result = call_gigachat_api(text, "gigachadify")
    if result:
        await message.answer(result)
    else:
        await message.answer(LANGUAGES[lang]["gigachat_error"].format("текст в стиле ГигаЧада не сгенерирован"))

@router.message(Command("make_post"))
async def make_post_command(message: types.Message):
    if not has_passed_captcha(message.from_user.id):
        await message.answer("Пройдите капчу с помощью /start")
        return
    lang = get_user_language(message.from_user.id)
    text = message.text.replace("/make_post", "").strip() or "Пример поста"
    result = call_gigachat_api(text, "make_post")
    if result:
        await message.answer(result)
    else:
        await message.answer(LANGUAGES[lang]["gigachat_error"].format("пост не сгенерирован"))

@router.message(Command("rewrite"))
async def rewrite_command(message: types.Message):
    if not has_passed_captcha(message.from_user.id):
        await message.answer("Пройдите капчу с помощью /start")
        return
    lang = get_user_language(message.from_user.id)
    text = message.text.replace("/rewrite", "").strip() or "Пример текста"
    result = call_gigachat_api(text, "rewrite")
    if result:
        await message.answer(result)
    else:
        await message.answer(LANGUAGES[lang]["gigachat_error"].format("текст не переписан"))

# Callback-обработчики
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
    elif data.startswith("tone_"):
        tone = data.replace("tone_", "")
        data_state = await state.get_data()
        original_text = data_state.get("original_text")
        result = call_gigachat_api(original_text, "smartreply", tone)
        if result:
            await callback.message.edit_text(result)
        else:
            await callback.message.edit_text(LANGUAGES[lang]["gigachat_error"].format("ответ не сгенерирован"))
        await state.clear()
    elif data == "guide":
        await callback.message.edit_text(LANGUAGES[lang]["guide"].format(ADMIN_ID))
    elif data in ["like", "dislike"]:
        await callback.answer("Спасибо за реакцию!")
    elif data.startswith("riddle_answer_"):
        answer = data.replace("riddle_answer_", "")
        await callback.message.edit_text(f"🧠 Ответ: {answer}")
    elif data == "captcha_enable":
        data_state = await state.get_data()
        chat_id = data_state.get("chat_id")
        set_channel_settings(chat_id, 1, "button", "Подтвердите, что вы не бот")
        await callback.message.edit_text(LANGUAGES[lang]["captcha_enabled"].format(chat_id))
        await state.clear()
    elif data == "captcha_disable":
        data_state = await state.get_data()
        chat_id = data_state.get("chat_id")
        set_channel_settings(chat_id, 0, "button", "Подтвердите, что вы не бот")
        await callback.message.edit_text(LANGUAGES[lang]["captcha_disabled"].format(chat_id))
        await state.clear()
    elif data == "captcha_configure":
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔘 Кнопка", callback_data="captcha_mode_button"),
             InlineKeyboardButton(text="📝 Текст", callback_data="captcha_mode_text")],
            [InlineKeyboardButton(text="➕ Математика", callback_data="captcha_mode_math")]
        ])
        await callback.message.edit_text("🔒 Выберите режим капчи:", reply_markup=keyboard)
    elif data.startswith("captcha_mode_"):
        mode = data.replace("captcha_mode_", "")
        data_state = await state.get_data()
        chat_id = data_state.get("chat_id")
        set_channel_settings(chat_id, 1, mode, "Подтвердите, что вы не бот")
        await callback.message.edit_text(LANGUAGES[lang]["captcha_enabled"].format(chat_id))
        await state.clear()
    await callback.answer()

# Обработчики состояний
@router.message(StyleStates.waiting_for_style_text)
async def process_style_text(message: types.Message, state: FSMContext):
    if not has_passed_captcha(message.from_user.id):
        await message.answer("Пройдите капчу с помощью /start")
        return
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
        [InlineKeyboardButton(text="👍", callback_data="like"),
         InlineKeyboardButton(text="👎", callback_data="dislike")],
        [InlineKeyboardButton(text="✅ Копировать", callback_data=f"copy_{styled_text}"),
         InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"edit_{style}")],
        [InlineKeyboardButton(text="📄 Экспорт в PDF", callback_data=f"export_pdf_{styled_text}")]
    ])
    await message.answer(styled_text, reply_markup=keyboard)
    await state.clear()

@router.message(StyleStates.waiting_for_preset_text)
async def process_preset_text(message: types.Message, state: FSMContext):
    if not has_passed_captcha(message.from_user.id):
        await message.answer("Пройдите капчу с помощью /start")
        return
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
        [InlineKeyboardButton(text="👍", callback_data="like"),
         InlineKeyboardButton(text="👎", callback_data="dislike")],
        [InlineKeyboardButton(text="✅ Копировать", callback_data=f"copy_{styled_text}"),
         InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"edit_preset_{preset}")],
        [InlineKeyboardButton(text="📄 Экспорт в PDF", callback_data=f"export_pdf_{styled_text}")]
    ])
    await message.answer(styled_text, reply_markup=keyboard)
    await state.clear()

@router.message(StyleStates.waiting_for_reminder)
async def process_reminder(message: types.Message, state: FSMContext):
    if not has_passed_captcha(message.from_user.id):
        await message.answer("Пройдите капчу с помощью /start")
        return
    lang = get_user_language(message.from_user.id)
    try:
        minutes = int(message.text.strip())
    except ValueError:
        await message.answer("⏰ Укажите число минут.")
        return
    data = await state.get_data()
    user_id = data.get("user_id")
    reminder_text = data.get("reminder_text")
    remind_at = (datetime.now() + timedelta(minutes=minutes)).isoformat()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO reminders (user_id, text, remind_at) VALUES (?, ?, ?)",
              (user_id, reminder_text, remind_at))
    conn.commit()
    conn.close()
    await message.answer(LANGUAGES[lang]["reminder_set"].format(minutes))
    await state.clear()
    async def send_reminder():
        await asyncio.sleep(minutes * 60)
        await bot.send_message(user_id, f"⏰ Напоминание: {reminder_text}")
    asyncio.create_task(send_reminder())

@router.message(StyleStates.waiting_for_feedback)
async def process_feedback(message: types.Message, state: FSMContext):
    if not has_passed_captcha(message.from_user.id):
        await message.answer("Пройдите капчу с помощью /start")
        return
    lang = get_user_language(message.from_user.id)
    data = await state.get_data()
    user_id = data.get("user_id")
    feedback_text = message.text.strip()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO feedback (user_id, text, created_at) VALUES (?, ?, ?)",
              (user_id, feedback_text, datetime.now().isoformat()))
    conn.commit()
    conn.close()
    await message.answer(LANGUAGES[lang]["feedback_sent"])
    await bot.send_message(ADMIN_ID, f"📝 Новый отзыв от {user_id}:\n{feedback_text}")
    await state.clear()

@router.message(StyleStates.waiting_for_welcome)
async def process_welcome(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await message.answer("🚫 Доступ запрещён")
        return
    lang = get_user_language(message.from_user.id)
    data = await state.get_data()
    chat_id = data.get("chat_id")
    welcome_text = message.text.strip()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO welcome_messages (chat_id, message) VALUES (?, ?)",
              (chat_id, welcome_text))
    conn.commit()
    conn.close()
    await message.answer(LANGUAGES[lang]["welcome_set"])
    c.execute("INSERT INTO admin_logs (chat_id, admin_id, action, target_user_id, created_at) VALUES (?, ?, ?, ?, ?)",
              (chat_id, message.from_user.id, "setwelcome", None, datetime.now().isoformat()))
    conn.commit()
    conn.close()
    await state.clear()

@router.message(StyleStates.waiting_for_rules)
async def process_rules(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await message.answer("🚫 Доступ запрещён")
        return
    lang = get_user_language(message.from_user.id)
    data = await state.get_data()
    chat_id = data.get("chat_id")
    rules_text = message.text.strip()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO welcome_messages (chat_id, message) VALUES (?, ?)",
              (chat_id, rules_text))
    conn.commit()
    conn.close()
    await message.answer(LANGUAGES[lang]["rules_set"])
    c.execute("INSERT INTO admin_logs (chat_id, admin_id, action, target_user_id, created_at) VALUES (?, ?, ?, ?, ?)",
              (chat_id, message.from_user.id, "setrules", None, datetime.now().isoformat()))
    conn.commit()
    conn.close()
    await state.clear()

@router.message(StyleStates.waiting_for_filter)
async def process_filter(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await message.answer("🚫 Доступ запрещён")
        return
    lang = get_user_language(message.from_user.id)
    data = await state.get_data()
    chat_id = data.get("chat_id")
    filter_text = message.text.strip().lower()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO triggers (keyword, style, preset) VALUES (?, ?, ?)",
              (filter_text, None, None))
    conn.commit()
    conn.close()
    await message.answer(LANGUAGES[lang]["filter_set"].format(filter_text))
    c.execute("INSERT INTO admin_logs (chat_id, admin_id, action, target_user_id, created_at) VALUES (?, ?, ?, ?, ?)",
              (chat_id, message.from_user.id, "setfilter", None, datetime.now().isoformat()))
    conn.commit()
    conn.close()
    await state.clear()

@router.message(StyleStates.waiting_for_log_channel)
async def process_log_channel(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await message.answer("🚫 Доступ запрещён")
        return
    lang = get_user_language(message.from_user.id)
    try:
        channel_id = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Укажите корректный ID канала (например, -1001234567890).")
        return
    try:
        await bot.get_chat(channel_id)
    except:
        await message.answer("❌ Бот не добавлен в указанный канал или ID некорректен.")
        return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO channel_settings (chat_id, captcha_enabled, captcha_mode, captcha_text) VALUES (?, ?, ?, ?)",
              (channel_id, 0, "button", "Подтвердите, что вы не бот"))
    conn.commit()
    conn.close()
    await message.answer(LANGUAGES[lang]["log_channel_set"].format(channel_id))
    c.execute("INSERT INTO admin_logs (chat_id, admin_id, action, target_user_id, created_at) VALUES (?, ?, ?, ?, ?)",
              (message.chat.id, message.from_user.id, "setlog", None, datetime.now().isoformat()))
    conn.commit()
    conn.close()
    await state.clear()

# Обработка новых участников
@router.message(lambda message: message.new_chat_members)
async def handle_new_members(message: types.Message, state: FSMContext):
    settings = get_channel_settings(message.chat.id)
    if not settings["enabled"]:
        return
    for member in message.new_chat_members:
        if member.id == (await bot.get_me()).id:
            continue
        await bot.restrict_chat_member(message.chat.id, member.id, permissions=types.ChatPermissions(can_send_messages=False), until_date=None)
        await send_captcha(message, state, chat_id=message.chat.id, user_id=member.id)

# Автоформатирование и шаблоны групп
@router.message()
async def auto_format(message: types.Message):
    if not has_passed_captcha(message.from_user.id):
        return
    text = message.text.lower()
    styled_text = None
    style = None
    preset = None
    if message.chat.type in ["group", "supergroup"]:
        group_preset = get_group_template(message.chat.id)
        if group_preset:
            styled_text = PRESETS[group_preset](message.text)
            preset = group_preset
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
        if preset in [v["preset"] for v in TRIGGERS.values()]:
            await message.reply(LANGUAGES[lang]["auto_formatted"].format(keyword))
        await message.answer(styled_text)
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO stylizations (user_id, style, preset, text, created_at) VALUES (?, ?, ?, ?, ?)",
                  (message.from_user.id, style, preset, message.text, datetime.now().isoformat()))
        conn.commit()
        conn.close()

# Запуск бота
if __name__ == "__main__":
    asyncio.run(dp.start_polling(bot))
