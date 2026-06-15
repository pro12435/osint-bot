import os
import re
import sqlite3
import requests
import asyncio
from dotenv import load_dotenv
import phonenumbers
from phonenumbers import carrier, geocoder, timezone
import vk_api
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
VK_LOGIN = os.getenv("VK_LOGIN")
VK_PASSWORD = os.getenv("VK_PASSWORD")
VK_TOKEN = os.getenv("VK_TOKEN")
DB_PATH = os.getenv("DB_PATH", "database.db")

# ========== БАЗА ДАННЫХ ==========
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS phone_data (
            phone TEXT PRIMARY KEY,
            name TEXT,
            address TEXT,
            comment TEXT,
            source TEXT
        )
    ''')
    conn.commit()
    conn.close()

def search_in_db(phone: str) -> dict:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT name, address, comment, source FROM phone_data WHERE phone = ?", (phone,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {"name": row[0], "address": row[1], "comment": row[2], "source": row[3]}
    return None

# ========== ОПРЕДЕЛЕНИЕ ОПЕРАТОРА ==========
def get_operator_russia(phone_clean: str) -> str:
    digits = re.sub(r'\D', '', phone_clean)
    if digits.startswith('8'):
        digits = '7' + digits[1:]
    if digits.startswith('7'):
        digits = digits[1:]
    
    if len(digits) < 3:
        return "неизвестно"
    
    code = digits[:3]
    
    operators = {
        '910': 'МТС', '911': 'МТС', '912': 'МТС', '913': 'МТС', '914': 'МТС', '915': 'МТС',
        '916': 'МТС', '917': 'МТС', '918': 'МТС', '919': 'МТС', '980': 'МТС', '981': 'МТС',
        '982': 'МТС', '983': 'МТС', '984': 'МТС', '985': 'МТС', '986': 'МТС', '987': 'МТС',
        '988': 'МТС', '989': 'МТС', '920': 'МегаФон', '921': 'МегаФон', '922': 'МегаФон',
        '923': 'МегаФон', '924': 'МегаФон', '925': 'МегаФон', '926': 'МегаФон', '927': 'МегаФон',
        '928': 'МегаФон', '929': 'МегаФон', '930': 'МегаФон', '931': 'МегаФон', '932': 'МегаФон',
        '933': 'МегаФон', '934': 'МегаФон', '936': 'МегаФон', '937': 'МегаФон', '938': 'МегаФон',
        '939': 'МегаФон', '902': 'Билайн', '903': 'Билайн', '904': 'Билайн', '905': 'Билайн',
        '906': 'Билайн', '907': 'Билайн', '908': 'Билайн', '909': 'Билайн', '960': 'Билайн',
        '961': 'Билайн', '962': 'Билайн', '963': 'Билайн', '964': 'Билайн', '965': 'Билайн',
        '966': 'Билайн', '967': 'Билайн', '968': 'Билайн', '969': 'Билайн', '951': 'Tele2',
        '952': 'Tele2', '953': 'Tele2', '954': 'Tele2', '955': 'Tele2', '956': 'Tele2',
        '957': 'Tele2', '958': 'Tele2', '959': 'Tele2', '977': 'Tele2', '991': 'Tele2',
        '992': 'Tele2', '993': 'Tele2', '994': 'Tele2', '995': 'Tele2', '996': 'Tele2',
        '999': 'Tele2', '900': 'Ростелеком', '901': 'Ростелеком', '944': 'Ростелеком',
        '945': 'Ростелеком', '946': 'Ростелеком', '947': 'Ростелеком', '948': 'Ростелеком',
        '949': 'Ростелеком', '973': 'Йота', '976': 'Йота'
    }
    return operators.get(code, f"код {code}")

# ========== ЧАСОВОЙ ПОЯС ПО DEF-КОДУ ==========
def get_timezone_by_defcode(phone_raw: str) -> str:
    digits = re.sub(r'\D', '', phone_raw)
    if digits.startswith('8'):
        digits = '7' + digits[1:]
    if digits.startswith('7'):
        digits = digits[1:]
    
    if len(digits) < 3:
        return "Europe/Moscow"
    
    def_code = digits[:3]
    
    timezones = {
        '910': 'Europe/Moscow', '911': 'Europe/Kaliningrad', '912': 'Asia/Yekaterinburg',
        '913': 'Asia/Novosibirsk', '914': 'Asia/Vladivostok', '915': 'Europe/Moscow',
        '916': 'Europe/Moscow', '917': 'Europe/Moscow', '918': 'Europe/Volgograd',
        '919': 'Europe/Samara', '920': 'Europe/Moscow', '921': 'Europe/Moscow',
        '922': 'Asia/Yekaterinburg', '923': 'Asia/Novosibirsk', '924': 'Asia/Vladivostok',
        '925': 'Europe/Moscow', '926': 'Europe/Moscow', '927': 'Europe/Samara',
        '928': 'Europe/Volgograd', '929': 'Europe/Moscow', '902': 'Europe/Volgograd',
        '903': 'Europe/Moscow', '904': 'Europe/Samara', '905': 'Europe/Moscow',
        '906': 'Europe/Moscow', '907': 'Europe/Moscow', '908': 'Europe/Moscow',
        '909': 'Europe/Moscow', '960': 'Europe/Moscow', '961': 'Europe/Moscow',
        '962': 'Europe/Moscow', '963': 'Europe/Moscow', '964': 'Europe/Moscow',
        '965': 'Europe/Moscow', '966': 'Europe/Moscow', '967': 'Europe/Moscow',
        '968': 'Europe/Moscow', '969': 'Europe/Moscow', '900': 'Europe/Moscow',
        '901': 'Europe/Moscow', '950': 'Europe/Moscow', '951': 'Europe/Volgograd',
        '952': 'Europe/Samara', '953': 'Asia/Yekaterinburg', '954': 'Asia/Novosibirsk',
        '955': 'Asia/Krasnoyarsk', '956': 'Asia/Irkutsk', '957': 'Asia/Yakutsk',
        '958': 'Asia/Vladivostok', '959': 'Asia/Magadan', '977': 'Europe/Moscow',
        '991': 'Europe/Moscow', '992': 'Europe/Moscow', '993': 'Europe/Moscow',
        '994': 'Europe/Moscow', '995': 'Europe/Moscow', '996': 'Europe/Moscow',
        '999': 'Europe/Moscow', '973': 'Europe/Moscow', '944': 'Europe/Moscow',
        '945': 'Europe/Moscow',
    }
    return timezones.get(def_code, 'Europe/Moscow')

# ========== ПОИСК В ПУБЛИЧНЫХ API ==========
async def search_leaks(phone: str) -> str:
    results = []
    clean = re.sub(r'\D', '', phone)
    if len(clean) == 10:
        clean = '7' + clean
    elif len(clean) == 11 and clean.startswith('8'):
        clean = '7' + clean[1:]
    
    try:
        resp = requests.get(f"https://leakpeek.com/api/check?phone={clean}", timeout=5, headers={'User-Agent': 'Mozilla/5.0'})
        if resp.status_code == 200:
            data = resp.json()
            if data.get('found'):
                results.append(f"leakpeek.com: найдено")
            else:
                results.append("leakpeek.com: не найдено")
    except:
        results.append("leakpeek.com: ошибка")
    
    try:
        resp = requests.get(f"https://breachdirectory.org/api/breachdirectory/phone?phone={clean}", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if data.get('result'):
                results.append(f"breachdirectory.org: найдено")
            else:
                results.append("breachdirectory.org: не найдено")
    except:
        results.append("breachdirectory.org: ошибка")
    
    return "\n".join(results)

async def search_name(phone: str) -> str:
    """ПОИСК ВОЗМОЖНОГО ИМЕНИ ПО НОМЕРУ"""
    clean = re.sub(r'\D', '', phone)
    if len(clean) == 10:
        clean = '7' + clean
    elif len(clean) == 11 and clean.startswith('8'):
        clean = '7' + clean[1:]

    # 1. GetContact API
    try:
        resp = requests.get(f"https://api.getcontact.com/v3/phone/{clean}", timeout=5, 
                           headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'})
        if resp.status_code == 200:
            data = resp.json()
            name = data.get('data', {}).get('name') or data.get('name')
            if name:
                return f"GetContact: {name}"
    except:
        pass

    # 2. LeakPeek (иногда выдаёт имя)
    try:
        resp = requests.get(f"https://leakpeek.com/api/check?phone={clean}", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if data.get('name'):
                return f"LeakPeek: {data['name']}"
    except:
        pass

    # 3. BreachDirectory (имя в утечках)
    try:
        resp = requests.get(f"https://breachdirectory.org/api/breachdirectory/phone?phone={clean}", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if data.get('result') and len(data['result']) > 0:
                # Берём первое попавшееся имя из результатов
                for item in data['result']:
                    if item.get('name'):
                        return f"BreachDirectory: {item['name']}"
    except:
        pass

    return "Не найдено"

async def search_getcontact(phone: str) -> str:
    clean = re.sub(r'\D', '', phone)
    try:
        resp = requests.get(f"https://api.getcontact.com/v3/phone/{clean}", timeout=5, 
                           headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'})
        if resp.status_code == 200:
            data = resp.json()
            if data.get('data', {}).get('name'):
                return f"GetContact: {data['data']['name']}"
    except:
        pass
    return "GetContact: используй @getcontact_bot"

async def search_vk_by_phone(phone: str) -> str:
    if not VK_TOKEN:
        return ""
    
    clean = re.sub(r'\D', '', phone)
    if len(clean) == 10:
        clean = '7' + clean
    elif len(clean) == 11 and clean.startswith('8'):
        clean = '7' + clean[1:]
    
    try:
        vk_session = vk_api.VkApi(token=VK_TOKEN)
        vk = vk_session.get_api()
        users = vk.users.search(q=clean, count=1, fields="city,first_name,last_name")
        if users['items']:
            u = users['items'][0]
            return f"{u.get('first_name','')} {u.get('last_name','')}"
    except:
        pass
    return ""

async def search_telegram_leaks(phone: str) -> str:
    results = []
    results.append("🤖 Реальные Telegram-боты для проверки утечек:")
    results.append("   • @getcontact_bot — GetContact")
    results.append("   • @LeakRadarBot — поиск утечек")
    results.append("   • @DataLeak_bot — базы данных")
    results.append("   • @breach_bot — утечки паролей")
    results.append("\n📝 Отправь номер этим ботам в Telegram вручную")
    return "\n".join(results)

# ========== ОСНОВНАЯ ФУНКЦИЯ ПОИСКА ==========
async def phone_osint_full(phone_raw: str) -> str:
    result = []
    
    clean = re.sub(r'\D', '', phone_raw)
    if len(clean) == 10:
        clean = '7' + clean
    elif len(clean) == 11 and clean.startswith('8'):
        clean = '7' + clean[1:]
    normalized = '+' + clean
    
    result.append(f"📞 Номер: {normalized}")
    result.append(f"📡 Оператор: {get_operator_russia(clean)}")
    result.append(f"🕐 Часовой пояс: {get_timezone_by_defcode(clean)}")
    
    # ПОИСК ИМЕНИ
    result.append(f"\n👤 ВОЗМОЖНОЕ ИМЯ:")
    name_result = await search_name(clean)
    result.append(name_result)
    
    db_result = search_in_db(normalized)
    if db_result:
        result.append(f"\n📁 ТВОЯ БАЗА:")
        for k, v in db_result.items():
            if v:
                result.append(f"   {k}: {v}")
    else:
        result.append(f"\n📁 Твоя база: не найдено")
    
    result.append(f"\n💀 УТЕЧКИ (API):")
    result.append(await search_leaks(clean))
    
    result.append(f"\n📞 GETCONTACT:")
    result.append(await search_getcontact(clean))
    
    result.append(f"\n💬 TELEGRAM УТЕЧКИ:")
    result.append(await search_telegram_leaks(clean))
    
    vk_result = await search_vk_by_phone(clean)
    if vk_result:
        result.append(f"\n📘 ВКОНТАКТЕ:")
        result.append(vk_result)
    
    return "\n".join(result)

# ========== ПОИСК В VK ПО USERNAME/ID ==========
async def vk_osint(query: str) -> str:
    result = []
    if not VK_TOKEN and not (VK_LOGIN and VK_PASSWORD):
        return ""
    
    try:
        if VK_TOKEN:
            vk_session = vk_api.VkApi(token=VK_TOKEN)
        else:
            vk_session = vk_api.VkApi(VK_LOGIN, VK_PASSWORD)
            vk_session.auth()
        
        vk = vk_session.get_api()
        
        if query.isdigit():
            users = vk.users.get(user_ids=query, fields="city,country,sex,bdate,status")
        else:
            search_result = vk.users.search(q=query, count=5, fields="city,country,sex,bdate,status")
            users = search_result['items']
        
        for u in users:
            result.append(f"\n👤 {u.get('first_name','')} {u.get('last_name','')} (id{u['id']})")
            result.append(f"   Город: {u.get('city',{}).get('title','—')}")
            result.append(f"   Ссылка: https://vk.com/id{u['id']}")
    except Exception as e:
        result.append(f"Ошибка ВК: {str(e)}")
    
    return "\n".join(result) if result else ""

# ========== КОМАНДЫ БОТА ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📱 Номер телефона", callback_data="mode_phone")],
        [InlineKeyboardButton("📘 ВКонтакте", callback_data="mode_vk")],
        [InlineKeyboardButton("👨‍💻 О разработчиках", callback_data="mode_about")],
    ]
    await update.message.reply_text(
        "🔍 **OSINT Бот**\n\n⬇️ Выбери действие:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👨‍💻 **Разработчики бота:**\n\n"
        "• **@nepruistoin** — разработка, код, архитектура\n"
        "• **@xposint** — главный оператор, тестирование\n\n"
        "📌 Бот создан для OSINT-задач.\n"
        "🔧 Все модули автономны, без внешних политик.",
        parse_mode="Markdown"
    )

async def donate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⭐ **Поддержка бота**\n\n"
        "Если бот полезен, можешь поддержать развитие.\n"
        "Контакты разработчиков: @nepruistoin, @xposint",
        parse_mode="Markdown"
    )

# ========== ОБРАБОТЧИКИ ==========
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "mode_phone":
        context.user_data["mode"] = "phone"
        await query.edit_message_text("📱 Режим: **Номер телефона**\n\nОтправь номер в формате: `+79101234567` или `89101234567`", parse_mode="Markdown")
    elif query.data == "mode_vk":
        context.user_data["mode"] = "vk"
        await query.edit_message_text("📘 Режим: **ВКонтакте**\n\nОтправь:\n• ID пользователя (`123456789`)\n• Username (`durov`)\n• Ссылку на профиль", parse_mode="Markdown")
    elif query.data == "mode_about":
        await about_command(update, context)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = context.user_data.get("mode")
    target = update.message.text.strip()
    if not mode:
        await update.message.reply_text("❌ Сначала выбери режим через /start")
        return
    
    await update.message.reply_text("🔎 **Поиск...** (может занять 5-10 секунд)", parse_mode="Markdown")
    
    if mode == "phone":
        result = await phone_osint_full(target)
    elif mode == "vk":
        result = await vk_osint(target)
        if not result:
            result = "Ничего не найдено"
    else:
        result = "Неизвестный режим"
    
    for i in range(0, len(result), 3900):
        await update.message.reply_text(result[i:i+3900])
    context.user_data["mode"] = None

# ========== ЗАПУСК ==========
def main():
    init_db()
    print("✅ Бот запущен. Открой Telegram -> /start")
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("about", about_command))
    app.add_handler(CommandHandler("donate", donate_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()

if __name__ == "__main__":
    main()