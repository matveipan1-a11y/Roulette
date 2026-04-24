import os
import asyncio
from flask import Flask
from telegram import Bot
from telegram.ext import ApplicationBuilder

app = Flask(__name__)

TOKEN = os.environ["TELEGRAM_TOKEN"]

@app.route('/')
def home():
    return "OK"

async def check_telegram():
    """Печатает в лог информацию о боте и соединении"""
    print("Начинаю проверку Telegram API...")
    try:
        async with Bot(TOKEN) as bot:
            me = await bot.get_me()
            print(f"✅ Успешно подключён к @{me.username} (id: {me.id})")
    except Exception as e:
        print(f"❌ Ошибка подключения: {type(e).__name__}: {e}")

def run_bot():
    print("Запуск проверки Telegram...")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(check_telegram())
    print("Проверка завершена. Запускаю поллинг (если дошли сюда)...")
    # Не запускаем поллинг, просто держим процесс
    while True:
        pass

if __name__ == '__main__':
    import threading
    t = threading.Thread(target=run_bot)
    t.daemon = True
    t.start()

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
