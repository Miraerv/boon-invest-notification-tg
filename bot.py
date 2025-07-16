#!/usr/bin/env python
# pylint: disable=unused-argument
import logging
import threading
import redis
import json
import asyncio
import os
from dotenv import load_dotenv

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

REDIS_HOST = os.getenv("REDIS_HOST", 'localhost')
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_CHANNEL = 'user_registered'

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

ADMIN_CHAT_IDS_STR = os.getenv("ADMIN_CHAT_IDS")
ADMIN_CHAT_IDS = []
if ADMIN_CHAT_IDS_STR:
    try:
        # Преобразуем строку '[id1, id2]' в список [id1, id2]
        ADMIN_CHAT_IDS = json.loads(ADMIN_CHAT_IDS_STR)
        if not isinstance(ADMIN_CHAT_IDS, list):
             logger.warning("ADMIN_CHAT_IDS в .env не является списком. Установлено пустое значение.")
             ADMIN_CHAT_IDS = []
    except json.JSONDecodeError:
        logging.error("Ошибка парсинга ADMIN_CHAT_IDS. Убедитесь, что это валидный JSON-массив, например: [12345, 67890]")
        ADMIN_CHAT_IDS = []

def redis_listener(application: Application, loop: asyncio.AbstractEventLoop):
    try:
        r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0, decode_responses=True)
        pubsub = r.pubsub()
        pubsub.subscribe(REDIS_CHANNEL)
        logger.info(f"Подписан на канал Redis: {REDIS_CHANNEL} на {REDIS_HOST}:{REDIS_PORT}")
    except redis.exceptions.ConnectionError as e:
        logger.error(f"Не удалось подключиться к Redis: {e}")
        return # Завершаем поток, если нет подключения

    for message in pubsub.listen():
        if message['type'] == 'message':
            try:
                logger.info(f"Получено сообщение из Redis: {message['data']}")
                user_data = json.loads(message['data'])
                
                # Создаем текст уведомления
                text = (
                    f"Новый пользователь зарегистрирован!\n\n"
                    f"Имя: {user_data.get('name', 'N/A')}\n"
                    f"Фамилия: {user_data.get('surname', 'N/A')}\n"
                    f"Телефон: {user_data.get('phone', 'N/A')}\n"
                    f"Email: {user_data.get('email', 'N/A')}"
                )
                
                # Безопасно вызываем асинхронную функцию из потока, используя переданный event loop
                asyncio.run_coroutine_threadsafe(
                    send_notification(application, text), loop
                )

            except json.JSONDecodeError:
                logger.error("Ошибка декодирования JSON из Redis")
            except Exception as e:
                logger.error(f"Произошла ошибка в слушателе Redis: {e}")

async def send_notification(application: Application, text: str):
    if not ADMIN_CHAT_IDS:
        logger.warning("Список ADMIN_CHAT_IDS пуст. Уведомление не отправлено.")
        return

    tasks = [application.bot.send_message(chat_id=chat_id, text=text) for chat_id in ADMIN_CHAT_IDS]
    
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for chat_id, result in zip(ADMIN_CHAT_IDS, results):
        if isinstance(result, Exception):
            logger.error(f"Не удалось отправить сообщение в чат {chat_id}: {result}")
        else:
            logger.info(f"Уведомление успешно отправлено в чат {chat_id}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    await update.message.reply_html(
        f"Привет, {user.mention_html()}!\n"
    )

def main() -> None:
    if not BOT_TOKEN:
        logger.critical("Ошибка: BOT_TOKEN не найден. Пожалуйста, добавьте его в .env файл.")
        return
    if not ADMIN_CHAT_IDS:
        logger.critical("Ошибка: ADMIN_CHAT_IDS не найден или пуст. Пожалуйста, добавьте его в .env файл в формате [id1, id2].")
        return

    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))

    loop = asyncio.get_event_loop()
    
    redis_thread = threading.Thread(
        target=redis_listener, args=(application, loop), daemon=True
    )
    redis_thread.start()
    
    logger.info("Бот запущен и готов к работе...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
