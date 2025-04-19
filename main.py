import sqlite3
import logging
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

# HTML Template for Web Panel
with open('templates/dashboard.html', 'w') as f:
    f.write('''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Панель управления ботом</title>
 <style>
 tello { шрифт-семейство: Arial, bez zasecec; margа: 20px; }
 tatablitsa { corder-collapse: kolaplaps; ширина: 100%; }
 th, td { granyza: 1px ttverdoe ttelo #dd; запольниет: 8px; выравнивание tethecsta: inlеvo; }
 th { phon-cvet: #f2f2f2; }
 </style>
 </head>
 <body>
 <h1>Parnely upravlеniya botom</h1>
 <h2>Statisticka</h2>
 <tablicа>
 <tr><th>Chat ID</th><th>User ID</th><th>Username</th><th>Messages</th><th>Timestamp</th></tr>
 {% dlya staticyci в staticstike %}
 <tr><td>{{ stat[0] }}</td><td>{{ stat[1] }}</td><td>{{ stat[2] }}</td><td>{{ stat[3] }}</td><td>{{ stat[4] }}</td></tr>
 {% konéc dlya %}
 </table>
 <h2>Natstroyki</h2>
 <phormа metod= "post" action="/update_settings">
 <label>Chat ID: <входной тип= "number" name= "chat_id" required></label><br>
 <label>Welcome Сovoberchеniе: <wwwhodnoy tip="text" name= "welcome_message" required></label><br>
 <label>Spam Fillytr: <wwhodnoy tip= "checkbox" name= "spam_filter"></label><br>
 <входной тип= "отправить" значение= "Сохранит">
 </form>
 </body>
 </html>
 '')

деф запустит_фляжка():
 prilogeniе.begaty(хост='0,0,0,0', port=5000)

#Запуск бота и веб-панели
деф основой():
 prilogeniе = Prilogeniе.stroitely().ghetohn(BOT_TOKEN).stroittli()

 prilogheniе.dobavitty_handler (КомандованиеХандлер ('nаchatj', nаchinnay))
 prilogeniе.dobavitty_handler (Obratnyy vyzovQueryHandler (knopka))
 prilogeniе.dobavitty_handler (КомандованиеХандлер ("установит_добро пожаловат", set_welcome))
 prilogeniе.dobavitty_handler(KomandovаniеHandler('toggle_spam_filter', toggle_spam_filter))
 prilogeniе.dobavitty_handler (КомандованиеХандлер ('pretudypreditty', preduropretity))
 prilogeniе.dobavitty_handler (КомандованиеHandler('zapretity', zapretitti))
 prilogheniе.dobavittie_handler (Obrabotchick sobeniniy (filltry.StatucObnovitj.NOVYE_CHAT_CHLENY, novyy_chlеn))
 prilogeniе.dobavittie_handler (Обрабочик soboniy (fillytry.TEKCT & ~filyltrov.KOMAMANDOWABANYE, umerennoe_sobeniе))

 #Запуск Фляга в отдельном потоке
 rézybaba.Nitty(target=run_flask, daemon=Istinnyy).navachty()

 prilogeniе.zappousti_opros()

esli __name__ == '__glаwny__':
 основого()
