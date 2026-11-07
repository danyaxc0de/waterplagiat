import telebot
from telebot import types
import sqlite3, threading, time, requests, random
from flask import Flask

# === НАСТРОЙКИ ===
TOKEN = "7887018808:AAFWJEzATYYENIHdavQWeYT6lxWxuNHM8wA"
ADMIN_ID = 8192413936

bot = telebot.TeleBot(TOKEN)

# --- БАЗА ---
db_lock = threading.Lock()
conn = sqlite3.connect("refast.db", check_same_thread=False)
cursor = conn.cursor()
with db_lock:
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY, 
        gems REAL DEFAULT 3.0,
        referrer_id INTEGER DEFAULT NULL
    )''')
    conn.commit()

def get_gems(uid):
    with db_lock:
        cursor.execute("SELECT gems FROM users WHERE user_id = ?", (uid,))
        res = cursor.fetchone()
        if not res:
            cursor.execute("INSERT INTO users (user_id) VALUES (?)", (uid,))
            conn.commit()
            return 3.0
        return res[0]

def add_gems(uid, amount):
    with db_lock:
        cursor.execute("UPDATE users SET gems = gems + ? WHERE user_id = ?", (amount, uid))
        conn.commit()

def spend_gems(uid, amount):
    with db_lock:
        cursor.execute("UPDATE users SET gems = gems - ? WHERE user_id = ?", (amount, uid))
        conn.commit()

# --- РЕРАЙТ ---
def rewrite_text(text):
    try:
        prompt = f"Перепиши этот текст своими словами, сделай его уникальным, убери 'воду' и канцеляризмы. Сохрани смысл. Текст: {text}"
        url = "https://text.pollinations.ai/openai"
        payload = {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": prompt}]}
        r = requests.post(url, json=payload, timeout=40)
        if r.status_code == 200:
            return r.json().get("choices", [{}])[0].get("message", {}).get("content", "Ошибка")
    except: pass
    return "Не удалось переписать текст."

def main_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("✍️ Переписать текст"), types.KeyboardButton("💎 Гемы"))
    return markup

# --- ХЕНДЛЕРЫ ---
@bot.message_handler(commands=['start'])
def cmd_start(message):
    uid = message.from_user.id
    args = message.text.split()
    ref_id = None
    if len(args) > 1 and args[1].startswith("ref_"):
        try: ref_id = int(args[1].replace("ref_", ""))
        except: pass
    
    if ref_id and ref_id != uid:
        with db_lock:
            cursor.execute("SELECT referrer_id FROM users WHERE user_id = ?", (uid,))
            res = cursor.fetchone()
            if not res or res[0] is None:
                cursor.execute("UPDATE users SET referrer_id = ? WHERE user_id = ?", (ref_id, uid))
                conn.commit()
                add_gems(ref_id, 3.0)
                try: bot.send_message(ref_id, "🎉 По твоей ссылке зашел друг! +3 гема.")
                except: pass
    
    bot.send_message(uid, f"👋 Привет! Это бот для рерайта текста.\n💎 Твои гемы: {get_gems(uid)}\n\nОтправь мне текст, и я перепишу его так, чтобы антиплагиат его пропустил!", reply_markup=main_menu())

@bot.message_handler(func=lambda m: m.text == "💎 Гемы")
def show_gems(message):
    uid = message.from_user.id
    ref_link = f"https://t.me/{bot.get_me().username}?start=ref_{uid}"
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton("Купить 10 гемов (10 ⭐)", callback_data="buy_10"))
    markup.add(types.InlineKeyboardButton("Купить 50 гемов (50 ⭐)", callback_data="buy_50"))
    bot.send_message(uid, f"💎 У тебя {get_gems(uid)} гемов.\n\n🔗 Твоя реф. ссылка:\n`{ref_link}`", parse_mode="Markdown", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("buy_"))
def buy_gems(call):
    amount = int(call.data.split("_")[1])
    bot.send_invoice(
        chat_id=call.message.chat.id, title=f"{amount} гемов", description="Покупка гемов",
        invoice_payload=f"gems_{amount}", provider_token="", currency="XTR",
        prices=[types.LabeledPrice(label=f"{amount} гемов", amount=amount)]
    )

@bot.pre_checkout_query_handler(func=lambda query: True)
def checkout(query): bot.answer_pre_checkout_query(query.id, ok=True)

@bot.message_handler(content_types=['successful_payment'])
def got_payment(message):
    amount = int(message.successful_payment.invoice_payload.split("_")[1])
    add_gems(message.from_user.id, float(amount))
    bot.send_message(message.from_user.id, f"✅ Ты купил {amount} гемов!")

@bot.message_handler(func=lambda m: m.text == "✍️ Переписать текст")
def ask_text(message):
    if get_gems(message.from_user.id) < 1:
        return bot.send_message(message.from_user.id, "❌ У тебя нет гемов! Купи в меню 'Гемы'.")
    bot.send_message(message.from_user.id, "📝 Отправь текст (до 1000 символов):")

@bot.message_handler(func=lambda m: True and not m.text.startswith('/'))
def process_text(message):
    uid = message.from_user.id
    text = message.text
    if len(text) < 10:
        return bot.send_message(uid, "❌ Слишком короткий текст.")
    
    if get_gems(uid) < 1:
        return bot.send_message(uid, "❌ Нет гемов! Купи в меню.")
        
    msg = bot.send_message(uid, "⏳ Переписываю (это займет 15 сек)...")
    new_text = rewrite_text(text)
    spend_gems(uid, 1)
    
    bot.edit_message_text(f"✅ **Готовый текст:**\n\n{new_text}\n\n(Списано 1 💎. Остаток: {get_gems(uid)})", uid, msg.message_id, parse_mode="Markdown")

# === АДМИНКА ===
@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if message.from_user.id != ADMIN_ID: return
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton("📊 Статистика", callback_data="adm_stats"))
    markup.add(types.InlineKeyboardButton("📢 Рассылка", callback_data="adm_broadcast"))
    bot.send_message(ADMIN_ID, "👑 **Админ-панель**", reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data == "adm_stats")
def adm_stats(call):
    if call.from_user.id != ADMIN_ID: return
    with db_lock:
        cursor.execute("SELECT COUNT(*), SUM(gems) FROM users")
        count, total_gems = cursor.fetchone()
    bot.answer_callback_query(call.id)
    bot.send_message(ADMIN_ID, f"📊 **Пользователей:** {count}\n💎 **Гемов:** {round(total_gems or 0, 2)}")

@bot.callback_query_handler(func=lambda call: call.data == "adm_broadcast")
def adm_broadcast(call):
    if call.from_user.id != ADMIN_ID: return
    bot.answer_callback_query(call.id)
    msg = bot.send_message(ADMIN_ID, "Текст для рассылки:")
    bot.register_next_step_handler(msg, process_broadcast)

def process_broadcast(message):
    text = message.text
    with db_lock:
        cursor.execute("SELECT user_id FROM users")
        users = cursor.fetchall()
    success, failed = 0, 0
    for u in users:
        try: bot.send_message(u[0], text); success += 1
        except: failed += 1
    bot.send_message(ADMIN_ID, f"✅ Рассылка завершена.\nУспешно: {success}\nОшибок: {failed}")

# === ЗАПУСК ===
if __name__ == "__main__":
    # Flask в отдельном потоке (чтобы Render видел порт)
    app = Flask(__name__)
    @app.route('/')
    def home(): return "Bot is running"
    def run_web():
        app.run(host='0.0.0.0', port=8080)
    threading.Thread(target=run_web, daemon=True).start()
    
    # Бот в главном потоке
    print("Бот готов.")
    while True:
        try: 
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as e:
            print(f"Ошибка: {e}")
            time.sleep(5)
