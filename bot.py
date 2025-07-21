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
REDIS_CHANNEL_REGISTRATION = 'user_registered'
REDIS_CHANNEL_APPLICATION = 'application'  # Новый канал для заявок

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
        # Подписываемся на оба канала
        pubsub.subscribe(REDIS_CHANNEL_REGISTRATION, REDIS_CHANNEL_APPLICATION)
        logger.info(f"Подписан на каналы Redis: {REDIS_CHANNEL_REGISTRATION}, {REDIS_CHANNEL_APPLICATION} на {REDIS_HOST}:{REDIS_PORT}")
    except redis.exceptions.ConnectionError as e:
        logger.error(f"Не удалось подключиться к Redis: {e}")
        return # Завершаем поток, если нет подключения

    for message in pubsub.listen():
        if message['type'] == 'message':
            try:
                channel = message['channel']
                logger.info(f"Получено сообщение из Redis канала {channel}: {message['data']}")
                data = json.loads(message['data'])

                # Обработка сообщений в зависимости от канала
                if channel == REDIS_CHANNEL_REGISTRATION:
                    text = create_registration_notification(data)
                elif channel == REDIS_CHANNEL_APPLICATION:
                    text = create_application_notification(data)
                else:
                    logger.warning(f"Неизвестный канал: {channel}")
                    continue

                # Безопасно вызываем асинхронную функцию из потока
                asyncio.run_coroutine_threadsafe(
                    send_notification(application, text), loop
                )

            except json.JSONDecodeError:
                logger.error("Ошибка декодирования JSON из Redis")
            except Exception as e:
                logger.error(f"Произошла ошибка в слушателе Redis: {e}")

def create_registration_notification(user_data: dict) -> str:
    """Создает текст уведомления о регистрации пользователя"""
    name = user_data.get('name', 'N/A')
    surname = user_data.get('surname', 'N/A')
    phone = user_data.get('phone', 'N/A')
    email = user_data.get('email', 'N/A')

    # Создаем WhatsApp ссылку
    clean_phone = ''.join(filter(str.isdigit, str(phone)))  # Убираем все нецифровые символы
    message = f"{name}, приветствую"
    whatsapp_url = f"https://api.whatsapp.com/send?phone={clean_phone}&text={message}"

    return (
        f"🆕 Новый пользователь зарегистрирован!\n\n"
        f"👤 Имя: {name}\n"
        f"👤 Фамилия: {surname}\n"
        f"📞 Телефон: {phone}\n"
        f"📧 Email: {email}\n\n"
        f"💬 [Написать в WhatsApp]({whatsapp_url})"
    )

def create_application_notification(application_data: dict) -> str:
    """Создает текст уведомления о новой заявке"""
    name = application_data.get('name', 'N/A')
    phone = application_data.get('phone', 'N/A')
    amount = application_data.get('amount', 'N/A')

    # Создаем WhatsApp ссылку
    clean_phone = ''.join(filter(str.isdigit, str(phone)))  # Убираем все нецифровые символы
    message = f"{name}, приветствую!"
    whatsapp_url = f"https://api.whatsapp.com/send?phone={clean_phone}&text={message}"

    return (
        f"📋 Новая заявка!\n\n"
        f"👤 Имя: {name}\n"
        f"📞 Телефон: {phone}\n"
        f"💰 Сумма: {amount} руб.\n"
        f"💬 [Написать в WhatsApp]({whatsapp_url})"
    )

async def send_notification(application: Application, text: str):
    if not ADMIN_CHAT_IDS:
        logger.warning("Список ADMIN_CHAT_IDS пуст. Уведомление не отправлено.")
        return

    tasks = [application.bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode='Markdown',
        disable_web_page_preview=True
    ) for chat_id in ADMIN_CHAT_IDS]

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
