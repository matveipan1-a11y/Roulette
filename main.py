import os
import json
import random
import threading
import time
from collections import Counter

import requests
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ------------------ Flask-приложение (обязательно для Render) ------------------
web_app = Flask(__name__)

@web_app.route('/')
def home():
    return "Bot is alive"

@web_app.route('/health')
def health():
    return "OK"

# ------------------ Конфигурация бота ------------------
TOKEN = os.environ["TELEGRAM_TOKEN"]  # Берётся из переменной окружения Render
HISTORY_FILE = "roulette_history.json"
STATS_FILE = "strategy_stats.json"

# ------------------ Функции истории и статистики ------------------
def load_history():
    if not os.path.exists(HISTORY_FILE):
        return []
    with open(HISTORY_FILE, 'r') as f:
        return json.load(f)

def save_history(data):
    with open(HISTORY_FILE, 'w') as f:
        json.dump(data, f)

def load_strategy_stats():
    if not os.path.exists(STATS_FILE):
        return {}
    with open(STATS_FILE, 'r') as f:
        return json.load(f)

def save_strategy_stats(stats):
    with open(STATS_FILE, 'w') as f:
        json.dump(stats, f)

def update_strategy_stats(strategy, hit):
    stats = load_strategy_stats()
    if strategy not in stats:
        stats[strategy] = {"wins": 0, "total": 0}
    stats[strategy]["total"] += 1
    if hit:
        stats[strategy]["wins"] += 1
    save_strategy_stats(stats)

def choose_best_strategy():
    stats = load_strategy_stats()
    if not stats:
        return "cold"
    best_strat = None
    best_rate = -1
    best_total = 0
    for strat, data in stats.items():
        total = data["total"]
        if total == 0:
            rate = 0
        else:
            rate = data["wins"] / total
        if rate > best_rate or (rate == best_rate and total > best_total):
            best_rate = rate
            best_strat = strat
            best_total = total
    return best_strat if best_strat else "cold"

def get_cold_numbers(history, top_n=3):
    if not history:
        return list(range(37))[:top_n]
    all_numbers = set(range(37))
    last_occurrence = {}
    for num in all_numbers:
        try:
            idx = list(reversed(history)).index(num)
            last_occurrence[num] = idx + 1
        except ValueError:
            last_occurrence[num] = float('inf')
    sorted_nums = sorted(last_occurrence.items(), key=lambda x: x[1], reverse=True)
    return [num for num, _ in sorted_nums[:top_n]]

def get_hot_numbers(history, top_n=3):
    if not history:
        return list(range(37))[:top_n]
    counter = Counter(history)
    return [num for num, _ in counter.most_common(top_n)]

def get_recommendation(history, strategy):
    if strategy == "cold":
        top = get_cold_numbers(history, top_n=1)
        number = top[0] if top else random.randint(0, 36)
        top3 = get_cold_numbers(history, top_n=3)
        desc = f"Холодные номера (топ-3): {', '.join(map(str, top3))}"
    elif strategy == "hot":
        top = get_hot_numbers(history, top_n=1)
        number = top[0] if top else random.randint(0, 36)
        top3 = get_hot_numbers(history, top_n=3)
        desc = f"Горячие номера (топ-3): {', '.join(map(str, top3))}"
    else:  # random
        number = random.randint(0, 36)
        desc = "Случайный выбор"
    return number, desc

# ------------------ Обработчики Telegram ------------------
last_advice = {"number": None, "strategy": None}
forced_strategy = None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🎰 Бот-самообучаемый советчик\n\n"
        "Отправляйте выпавшие числа (0-36). Бот запомнит, сравнит с прошлым советом и "
        "выдаст новую рекомендацию, автоматически выбирая лучшую тактику (по статистике попаданий).\n\n"
        "Команды:\n"
        "/strat – статистика тактик\n"
        "/stats – статистика бросков\n"
        "/reset – сброс\n"
        "/mode cold|hot|random – принудительная тактика"
    )
    await update.message.reply_text(text)

async def show_strategy_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats = load_strategy_stats()
    if not stats:
        await update.message.reply_text("Статистики тактик пока нет.")
        return
    lines = ["📊 Статистика попаданий:"]
    for strat, data in stats.items():
        total = data["total"]
        wins = data["wins"]
        rate = f"{wins/total*100:.1f}%" if total > 0 else "0%"
        lines.append(f"• {strat}: {wins}/{total} ({rate})")
    best = choose_best_strategy()
    lines.append(f"\n🏆 Сейчас выбрана: {best}")
    await update.message.reply_text("\n".join(lines))

async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    history = load_history()
    if not history:
        await update.message.reply_text("История пуста.")
        return
    total = len(history)
    counter = Counter(history)
    top3 = counter.most_common(3)
    bottom3 = counter.most_common()[:-4:-1]
    msg = (f"Всего бросков: {total}\n"
           f"Топ-3 частых: {', '.join(f'{n} ({c} раз)' for n,c in top3)}\n"
           f"Топ-3 редких: {', '.join(f'{n} ({c} раз)' for n,c in bottom3)}")
    await update.message.reply_text(msg)

async def reset_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_history([])
    save_strategy_stats({})
    global last_advice
    last_advice = {"number": None, "strategy": None}
    await update.message.reply_text("История и статистика сброшены.")

async def force_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global forced_strategy
    if not context.args:
        await update.message.reply_text("Укажите: /mode cold, /mode hot, /mode random")
        return
    mode = context.args[0].lower()
    if mode in ("cold", "hot", "random"):
        forced_strategy = mode
        await update.message.reply_text(f"✅ Тактика принудительно: {mode} (автовыбор отключён до перезапуска бота).")
    else:
        await update.message.reply_text("Неверный режим. Допустимые: cold, hot, random")

async def handle_numbers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global last_advice, forced_strategy

    text = update.message.text.strip()
    parts = text.replace(',', ' ').replace(';', ' ').split()
    numbers = []
    errors = []
    for part in parts:
        try:
            num = int(part)
            if 0 <= num <= 36:
                numbers.append(num)
            else:
                errors.append(part)
        except ValueError:
            errors.append(part)

    if errors:
        await update.message.reply_text(f"Непонятные значения пропущены: {', '.join(errors)}")
    if not numbers:
        return

    # Проверяем прошлый совет
    if last_advice["number"] is not None and last_advice["strategy"] is not None:
        hit = last_advice["number"] in numbers
        update_strategy_stats(last_advice["strategy"], hit)

    history = load_history()
    history.extend(numbers)
    save_history(history)

    strategy = forced_strategy if forced_strategy else choose_best_strategy()
    number, desc = get_recommendation(history, strategy)

    last_advice["number"] = number
    last_advice["strategy"] = strategy

    added = ', '.join(map(str, numbers))
    strat_names = {"cold": "Холодные", "hot": "Горячие", "random": "Случайно"}
    strat_disp = strat_names.get(strategy, strategy)

    stats = load_strategy_stats()
    current_total = stats.get(strategy, {}).get("total", 0)
    current_wins = stats.get(strategy, {}).get("wins", 0)
    rate = f"{current_wins/current_total*100:.1f}%" if current_total > 0 else "нет данных"

    await update.message.reply_text(
        f"✅ Добавлены: {added}\n\n"
        f"🎯 Ставка: {number}\n"
        f"🧠 Тактика: {strat_disp} (выбрана автоматически)\n"
        f"📈 Попаданий этой тактики: {current_wins}/{current_total} ({rate})\n"
        f"📊 {desc}"
    )

# ------------------ Запуск всего ------------------
def run_bot():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("strat", show_strategy_stats))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("reset", reset_all))
    app.add_handler(CommandHandler("mode", force_mode))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_numbers))
    print("Бот запущен в облаке...")
    app.run_polling()

# ------------------ Keep-alive: пингуем сами себя, чтобы Render не засыпал ------------------
def keep_alive():
    # Получаем URL этого же сервиса (автоматически предоставляется Render)
    service_url = os.environ.get("RENDER_EXTERNAL_URL", "")
    if not service_url:
        # Если переменная не задана, используем localhost (для тестов на ПК)
        service_url = "http://localhost:5000"
    while True:
        time.sleep(600)  # каждые 10 минут
        try:
            requests.get(service_url + "/health", timeout=10)
            print("Keep-alive ping sent")
        except Exception as e:
            print(f"Keep-alive failed: {e}")

if __name__ == '__main__':
    # Запускаем бота в отдельном потоке
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.daemon = True
    bot_thread.start()

    # Запускаем keep-alive поток
    keep_thread = threading.Thread(target=keep_alive)
    keep_thread.daemon = True
    keep_thread.start()

    # Запускаем Flask-сервер
    port = int(os.environ.get("PORT", 5000))
    web_app.run(host="0.0.0.0", port=port)
