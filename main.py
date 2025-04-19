import sqlite3
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ContextTypes
from transformers import pipeline
from flask import Flask, render_template, request
import threading
import datetime

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
        await query.message.reply_text("Выберите настройку: /set_welcome <текст> или /toggle_spam_filter")
    elif query.data == 'moderate':
        await query.message.reply_text("Модерация: используйте /warn @username или /ban @username")

async def set_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    c.execute('INSERT OR REPLACE INTO stats (chat_id, user_id, username, message_count, timestamp) VALUES (?, ?, ?, ?, ?)',
              (chat_id, user.id, user.username, 1, datetime.datetime.now().isoformat()))
    conn.commit()
    conn.close()

async def warn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        username = context.args[0].replace('@', '')
        await update.message.reply_text(f"@{username}, предупреждение! Повторите, и будете забанены.")
    else:
        await update.message.reply_text("Укажите пользователя: /warn @username")

async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

# HTML Template for Web Panel
with open('templates/dashboard.html', 'w') as f:
    f.write('''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Панель управления ботом</title>
        <style>
 тело { шрифт-семейство: Arial, без засечек; маржа: 20px; }
 таблица { corder-collapse: коллапс; ширина: 100%; }
 th, td { граница: 1px твердое тело #ddd; заполнение: 8px; выравнивание текста: влево; }
 th { фон-цвет: #f2f2f2; }
 </style>
 </head>
 <body>
 <h1>Parnely upravlеniya botom</h1>
 <h2>Statisticka</h2>
 <таблица>
 <tr><th>Chat ID</th><th>User ID</th><th>Username</th><th>Messages</th><th>Timestamp</th></tr>
 {% для статистики в статистике %}
 <tr><td>{{ stat[0] }}</td><td>{{ stat[1] }}</td><td>{{ stat[2] }}</td><td>{{ stat[3] }}</td><td>{{ stat[4] }}</td></tr>
 {% конец для %}
 </table>
 <h2>Natstroyki</h2>
 <форма метод= "post" action="/update_settings">
 <label>Chat ID: <input type= "number" name= "chat_id" required></label><br>
 <label>Welcome Сообщение: <входной тип="text" name= "welcome_message" required></label><br>
 <label>Spam Фильтр: <входной тип= "checkbox" name= "spam_filter"></label><br>
 <input type= "submit" value= "Сохранит">
 </form>
 </body>
 </html>
 '')

деф запустить_flask():
 приложение.бегать(хост='0,0,0,0', порт=5000)

#Запуск бота и веб-панели
деф основной():
    #Замените 'YOUR_BOT_TOKEN' на токена, полюченного от @BotFather
 приложение = Приложение.строитель().жетон('ТВОЙ_БОТ_ТОКЕН').строить()

 приложение.добавить_handler(КомандованиеHandler('начать', начинай))
 приложение.добавить_handler(Обратный вызовQueryHandler(кнопка))
 приложение.добавить_handler(КомандованиеHandler("установить_добро пожаловать", set_welcome))
 приложение.добавить_handler(КомандованиеHandler('toggle_spam_filter', toggle_spam_filter))
 приложение.добавить_handler(КомандованиеHandler('предупредить', предупредить))
 приложение.добавить_handler(КомандованиеHandler('запретить', запретить))
 приложение.добавить_handler(Обработчик сообщений(фильтры.СтатусОбновить.НОВЫЕ_ЧАТ_ЧЛЕНЫ, новый_член))
 приложение.добавить_handler(Обработчик сообщений(фильтры.ТЕКСТ & ~фильтров.КОМАНДОВАНИЕ, умеренное_сообщение))

    #Запуск Фляга в отдельном потоке
 резьба.Нить(target=run_flask, daemon=Истинный).начать()

 приложение.запустить_опрос()

если __name__ == '__главный__':
    основной()
