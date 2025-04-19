import sqlite3
import logging
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ContextTypes
from transformers import pipeline
from flask import Flask, render_template, request
import threading
import datetime

# Конфигурация
BOT_TOKEN = "7935425343:AAECbjFJvLHkeTvwHAKDG8uvmy-KiWcPtns"
ADMIN_TELEGRAM_ID = 650154766

# Настройка логирования
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация нейросети для анализа текста (модерация спама)
classifier = pipeline("text-classification", model="distilbert-base-uncased-finetuned-sst-2-english")

# Инициализация базы данных SQLite
def init_db():
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS stats
                 (chat_id INTEGER, user_id INTEGER, username TEXT, message_count INTEGER, timestamp TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS settings
                 (chat_id INTEGER, welcome_message TEXT, spam_filter BOOLEAN)''')
    conn.commit()
    conn.close()

init_db()

# Проверка, является ли пользователь администратором
def is_admin(user_id):
    return user_id == ADMIN_TELEGRAM_ID

# Telegram Bot
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Статистика", callback_data='stats')],
        [InlineKeyboardButton("Настройки", callback_data='settings')],
        [InlineKeyboardButton("Модерация", callback_data='moderate')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text('Привет! Я бот для управления каналами и группами.', reply_markup=reply_markup)

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id

    if query.data == 'stats':
        conn = sqlite3.connect('bot.db')
        c = conn.cursor()
        c.execute('SELECT user_id, username, message_count FROM stats WHERE chat_id=?', (chat_id,))
        stats = c.fetchall()
        conn.close()
        response = "Статистика:\n" + "\n".join([f"@{row[1]}: {row[2]} сообщений" for row in stats])
        await query.message.reply_text(response or "Нет данных.")
    elif query.data == 'settings':
        if is_admin(query.from_user.id):
            await query.message.reply_text("Выберите настройку: /set_welcome <текст> или /toggle_spam_filter")
        else:
            await query.message.reply_text("Только администратор может изменять настройки.")
    elif query.data == 'moderate':
        if is_admin(query.from_user.id):
            await query.message.reply_text("Модерация: используйте /warn @username или /ban @username")
        else:
            await query.message.reply_text("Только администратор может модерировать.")

async def set_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.message.from_user.id):
        await update.message.reply_text("Только администратор может изменять настройки.")
        return

    chat_id = update.message.chat_id
    welcome_message = " ".join(context.args) or "Добро пожаловать!"
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO settings (chat_id, welcome_message, spam_filter) VALUES (?, ?, ?)',
              (chat_id, welcome_message, 1))
    conn.commit()
    conn.close()
    await update.message.reply_text(f"Приветственное сообщение установлено: {welcome_message}")

async def toggle_spam_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.message.from_user.id):
        await update.message.reply_text("Только администратор может изменять настройки.")
        return

    chat_id = update.message.chat_id
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute('SELECT spam_filter FROM settings WHERE chat_id=?', (chat_id,))
    current = c.fetchone()
    new_value = not current[0] if current else True
    c.execute('INSERT OR REPLACE INTO settings (chat_id, welcome_message, spam_filter) VALUES (?, ?, ?)',
              (chat_id, "Добро пожаловать!", new_value))
    conn.commit()
    conn.close()
    await update.message.reply_text(f"Фильтр спама: {'включен' if new_value else 'выключен'}")

async def new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute('SELECT welcome_message FROM settings WHERE chat_id=?', (chat_id,))
    welcome_message = c.fetchone()
    welcome_message = welcome_message[0] if welcome_message else "Добро пожаловать!"
    conn.close()
    for user in update.message.new_chat_members:
        await update.message.reply_text(f"{welcome_message}, @{user.username}!")

async def moderate_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    user = update.message.from_user
    text = update.message.text

    # Проверка на спам с помощью нейросети
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute('SELECT spam_filter FROM settings WHERE chat_id=?', (chat_id,))
    spam_filter = c.fetchone()
    if spam_filter and spam_filter[0]:
        result = classifier(text)[0]
        if result['label'] == 'NEGATIVE' and result['score'] > 0.9:
            await update.message.delete()
            await update.message.reply_text(f"@{user.username}, ваше сообщение удалено как спам.")
            return

    # Обновление статистики
    c.execute('SELECT message_count FROM stats WHERE chat_id=? AND user_id=?', (chat_id, user.id))
    current_count = c.fetchone()
    new_count = (current_count[0] + 1) if current_count else 1
    c.execute('INSERT OR REPLACE INTO stats (chat_id, user_id, username, message_count, timestamp) VALUES (?, ?, ?, ?, ?)',
              (chat_id, user.id, user.username, new_count, datetime.datetime.now().isoformat()))
    conn.commit()
    conn.close()

async def warn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.message.from_user.id):
        await update.message.reply_text("Только администратор может выдавать предупреждения.")
        return

    if context.args:
        username = context.args[0].replace('@', '')
        await update.message.reply_text(f"@{username}, предупреждение! Повторите, и будете забанены.")
    else:
        await update.message.reply_text("Укажите пользователя: /warn @username")

async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.message.from_user.id):
        await update.message.reply_text("Только администратор может банить пользователей.")
        return

    if context.args:
        username = context.args[0].replace('@', '')
        await update.message.reply_text(f"@{username} забанен.")
        # Реальный бан требует прав администратора и метода kickChatMember
    else:
        await update.message.reply_text("Укажите пользователя: /ban @username")

# Flask Web Panel
app = Flask(__name__)

@app.route('/')
def dashboard():
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute('SELECT chat_id, user_id, username, message_count, timestamp FROM stats')
    stats = c.fetchall()
    c.execute('SELECT chat_id, welcome_message, spam_filter FROM settings')
    settings = c.fetchall()
    conn.close()
    return render_template('dashboard.html', stats=stats, settings=settings)

@app.route('/update_settings', methods=['POST'])
def update_settings():
    chat_id = int(request.form['chat_id'])
    welcome_message = request.form['welcome_message']
    spam_filter = 'spam_filter' in request.form
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO settings (chat_id, welcome_message, spam_filter) VALUES (?, ?, ?)',
              (chat_id, welcome_message, spam_filter))
    conn.commit()
    conn.close()
    return "Настройки обновлены!"

# Создать папку templates, если она не существует
os.makedirs('templates', exist_ok=True)

# HTML Template for Web Panel
with open('templates/dashboard.html', 'w') as f:
    f.write('''<!DOCTYPE html>
<html>
<head>
    <title>Панель управления ботом</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        table { border-collapse: collapse; width: 100%; }
        th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
        th { background-color: #f2f2f2; }
    </style>
</head>
<body>
    <h1>Панель управления ботом</h1>
    <h2>Статистика</h2>
    <table>
        <tr><th>Chat ID</th><th>User ID</th><th>Username</th><th>Messages</th><th>Timestamp</th></tr>
        {% for stat in stats %}
        <tr><td>{{ stat[0] }}</td><td>{{ stat[1] }}</td><td>{{ stat[2] }}</td><td>{{ stat[3] }}</td><td>{{ stat[4] }}</td></tr>
        {% endfor %}
    </table>
    <h2>Настройки</h2>
    <form method="post" action="/update_settings">
        <label>Chat ID: <input type="number" name="chat_id" required></label><br>
        <label>Welcome Message: <input type="text" name="welcome_message" required></label><br>
        <label>Spam Filter: <input type="checkbox" name="spam_filter"></label><br>
        <input type="submit" value="Сохранить">
    </form>
</body>
</html>''')

defdef run_flask():run_flask():
 app.run(host='0.0.0.0', port=5000)run(host='0.0.0.0', port=5000)

# Запуск бота и веб-панели
defdef main():main():
 приложение = Application.builder().token(BOT_TOKEN).build()builder().token(BOT_TOKEN).build()

 application.add_handler(CommandHandler('start', start))add_handler(CommandHandler('start', start))
 приложение.add_handler (CallbackQueryHandler (кнопка))add_handler(CallbackQueryHandler(button))
 приложение.add_handler(CommandHandler('set_welcome', set_welcome))add_handler(CommandHandler('set_welcome', set_welcome))
 application.add_handler(CommandHandler('toggle_spam_filter', toggle_spam_filter))add_handler(CommandHandler('toggle_spam_filter', toggle_spam_filter))
 application.add_handler(CommandHandler('предупредить', предупредить))add_handler(CommandHandler('warn', warn))
 application.add_handler(CommandHandler('ban', ban))add_handler(CommandHandler('ban', ban))
 application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_member))add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_member))
 application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, mederate_message))add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, moderate_message))

 #Запуск Фляга в отдельном потоке# Запуск Flask в отдельном потоке
 threading.Thread(target=run_flask, daemon=True).start()Thread(target=run_flask, daemon=True).start()

 application.run_polling()run_polling()

ifесли __name__ == '__main__':'__main__':
 основнойmain()
