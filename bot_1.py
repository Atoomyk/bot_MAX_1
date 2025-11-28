# bot.py
import asyncio
import os
import time
import re
import aiohttp
from functools import wraps
from dotenv import load_dotenv

from maxapi import Bot, Dispatcher
from maxapi.types import (
    BotStarted,
    MessageCallback,
    MessageCreated,
    Attachment,
    ButtonsPayload,
    CallbackButton,
    LinkButton,
    RequestContactButton
)
from maxapi.utils.inline_keyboard import AttachmentType

from support_handler import init_support_handler
from registration_handler import RegistrationHandler
from reminder_handler import ReminderHandler

# Импорт системы логирования
from logging_config import setup_logging, log_user_event, log_system_event, log_data_event, log_security_event

# Настройка логирования
setup_logging()

# Загрузка переменных окружения
load_dotenv()
TOKEN = os.getenv("MAXAPI_TOKEN")
WEBHOOK_MODE = os.getenv("WEBHOOK_MODE", "xtunnel")  # xtunnel или direct
XTUNNEL_URL = os.getenv("XTUNNEL_URL")
DIRECT_WEBHOOK_URL = os.getenv("DIRECT_WEBHOOK_URL")
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", "8083"))

# Определение URL вебхука в зависимости от режима
if WEBHOOK_MODE == "direct" and DIRECT_WEBHOOK_URL:
    WEBHOOK_URL = DIRECT_WEBHOOK_URL
    log_system_event("webhook", "mode_direct", url=WEBHOOK_URL)
else:
    WEBHOOK_URL = XTUNNEL_URL
    log_system_event("webhook", "mode_xtunnel", url=WEBHOOK_URL)

bot = Bot(TOKEN)
dp = Dispatcher()

# Константы API
MAX_API_BASE_URL = "https://platform-api.max.ru"
HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Authorization": f"{TOKEN}"
}

# Ссылки для кнопок главного меню
GOSUSLUGI_APPOINTMENT_URL = "https://www.gosuslugi.ru/10700"
GOSUSLUGI_MEDICAL_EXAM_URL = "https://www.gosuslugi.ru/647521/1/form"
GOSUSLUGI_DOCTOR_HOME_URL = "https://www.gosuslugi.ru/600361"
GOSUSLUGI_ATTACH_TO_POLYCLINIC_URL = "https://www.gosuslugi.ru/600360"
CONTACT_CENTER_URL = "https://sevmiac.ru/ekc/"
MAP_OF_MEDICAL_INSTITUTIONS_URL = "https://yandex.ru/maps/959/"

# Импорт базы данных
from user_database import db

# Глобальные переменные
user_states = {}
processed_events = {}  # Объединенная защита от дублирования

# Инициализация обработчиков
support_handler = init_support_handler(user_states)
registration_handler = RegistrationHandler(user_states)  # Новый обработчик регистрации
# === Инициализация обработчика напоминаний ===
reminder_handler = ReminderHandler(db, None)


# --- ФУНКЦИИ ДЛЯ ПОДДЕРЖАНИЯ АКТИВНОСТИ ---

async def make_keepalive_request(session):
    """Периодические запросы для поддержания активности бота"""
    try:
        # Простой запрос к API MAX для проверки статуса
        async with session.get(f"{MAX_API_BASE_URL}/me", headers=HEADERS) as response:
            if response.status == 200:
                log_system_event("keepalive", "success", status=response.status)
            else:
                log_system_event("keepalive", "failed", status=response.status,
                               response_text=await response.text())
    except Exception as e:
        log_system_event("keepalive", "error", error=str(e))


async def keepalive_worker():
    """Фоновая задача для периодических запросов поддержания активности"""
    # Создаем одну сессию для всех запросов
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                await make_keepalive_request(session)
                # Ждем 15 минут перед следующим запросом
                await asyncio.sleep(900)  # 900 секунд = 15 минут
            except asyncio.CancelledError:
                log_system_event("keepalive", "worker_stopped")
                break
            except Exception as e:
                log_system_event("keepalive", "worker_error", error=str(e))
                # При ошибке ждем 5 минут перед повторной попыткой
                await asyncio.sleep(300)


# Глобальная переменная для хранения задачи keepalive
keepalive_task = None


# --- УНИВЕРСАЛЬНЫЕ ФУНКЦИИ ---

def anti_duplicate(rate_limit=1.0):
    """Декоратор для защиты от дублирования событий"""

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            event = args[0] if args else None
            chat_id = None

            # Получаем chat_id из разных типов событий
            if hasattr(event, 'message') and hasattr(event.message, 'recipient'):
                chat_id = str(event.message.recipient.chat_id)
            elif hasattr(event, 'chat_id'):
                chat_id = str(event.chat_id)

            if not chat_id:
                return await func(*args, **kwargs)

            # Проверяем частоту запросов
            current_time = time.time()
            if chat_id in processed_events:
                last_time = processed_events[chat_id].get('last_time', 0)
                if current_time - last_time < rate_limit:
                    return

            # Обновляем время последнего обработки
            if chat_id not in processed_events:
                processed_events[chat_id] = {}
            processed_events[chat_id]['last_time'] = current_time

            return await func(*args, **kwargs)

        return wrapper

    return decorator


def cleanup_processed_events():
    """Очистка старых записей для экономии памяти"""
    global processed_events
    current_time = time.time()
    # Удаляем записи старше 1 часа
    expired_chats = [
        chat_id for chat_id, data in processed_events.items()
        if current_time - data.get('last_time', 0) > 3600
    ]
    for chat_id in expired_chats:
        del processed_events[chat_id]


def create_keyboard(buttons_config):
    """Универсальная функция создания клавиатуры"""
    if not buttons_config:
        return None

    # Поддерживаем разные форматы кнопок
    formatted_buttons = []
    for row in buttons_config:
        button_row = []
        for button in row:
            if isinstance(button, dict):
                # Создаем кнопку из словаря
                if button.get('type') == 'callback':
                    btn = CallbackButton(text=button['text'], payload=button['payload'])
                elif button.get('type') == 'link':
                    btn = LinkButton(text=button['text'], url=button['url'])
                elif button.get('type') == 'contact':
                    btn = RequestContactButton(text=button['text'])
                else:
                    continue
                button_row.append(btn)
            else:
                # Уже созданная кнопка
                button_row.append(button)
        if button_row:
            formatted_buttons.append(button_row)

    if not formatted_buttons:
        return None

    buttons_payload = ButtonsPayload(buttons=formatted_buttons)
    return Attachment(
        type=AttachmentType.INLINE_KEYBOARD,
        payload=buttons_payload
    )


# --- ФУНКЦИИ УПРАВЛЕНИЯ ВЕБХУКАМИ ---

async def get_webhook_subscriptions():
    """Получить список всех вебхук-подписок"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{MAX_API_BASE_URL}/subscriptions", headers=HEADERS) as response:
                if response.status == 200:
                    data = await response.json()
                    subscriptions = data.get('subscriptions', [])
                    return subscriptions
                else:
                    log_system_event("webhook", "get_subscriptions_failed", status=response.status)
                    return []
    except Exception as e:
        log_system_event("webhook", "get_subscriptions_error", error=str(e))
        return []


async def delete_webhook_subscription(url: str) -> bool:
    """Удалить конкретную вебхук-подписку"""
    try:
        import urllib.parse
        encoded_url = urllib.parse.quote(url, safe='')
        delete_url = f"{MAX_API_BASE_URL}/subscriptions?url={encoded_url}"

        async with aiohttp.ClientSession() as session:
            async with session.delete(delete_url, headers=HEADERS) as response:
                if response.status == 200:
                    log_system_event("webhook", "subscription_deleted", url=url)
                    return True
                else:
                    error_text = await response.text()
                    log_system_event("webhook", "delete_subscription_failed", url=url, error=error_text)
                    return False
    except Exception as e:
        log_system_event("webhook", "delete_subscription_error", url=url, error=str(e))
        return False


async def delete_all_webhook_subscriptions() -> bool:
    """Удалить все вебхук-подписки"""
    log_system_event("webhook", "cleanup_started")

    subscriptions = await get_webhook_subscriptions()

    if not subscriptions:
        log_system_event("webhook", "cleanup_completed", message="No subscriptions to delete")
        return True

    log_system_event("webhook", "subscriptions_found", count=len(subscriptions))

    success_count = 0
    for subscription in subscriptions:
        url = subscription.get('url')
        if url:
            success = await delete_webhook_subscription(url)
            if success:
                success_count += 1
            # Небольшая задержка между запросами
            await asyncio.sleep(0.5)

    result = success_count == len(subscriptions)
    if result:
        log_system_event("webhook", "cleanup_completed", deleted_count=success_count)
    else:
        log_system_event("webhook", "cleanup_partial", deleted_count=success_count, total_count=len(subscriptions))

    return result


async def setup_webhook():
    """Настраивает вебхук в зависимости от режима работы"""
    log_system_event("webhook", "setup_started", mode=WEBHOOK_MODE, url=WEBHOOK_URL)

    # Сначала удаляем все старые вебхуки
    cleanup_success = await delete_all_webhook_subscriptions()

    if not cleanup_success:
        log_system_event("webhook", "cleanup_warning", message="Cleanup completed with errors, but continuing")

    # Затем настраиваем новый вебхук
    try:
        await bot.subscribe_webhook(
            url=WEBHOOK_URL,
            update_types=["message_created", "message_callback", "bot_started"]
        )
        log_system_event("webhook", "setup_completed", url=WEBHOOK_URL, mode=WEBHOOK_MODE)

        # Проверяем результат
        final_subscriptions = await get_webhook_subscriptions()
        if final_subscriptions:
            log_system_event("webhook", "setup_verified", count=len(final_subscriptions))
            return True
        else:
            log_system_event("webhook", "setup_failed", message="No subscriptions after setup")
            return False

    except Exception as e:
        log_system_event("webhook", "setup_error", error=str(e))
        return False


# --- ОСНОВНЫЕ ФУНКЦИИ БОТА ---

def create_main_menu_keyboard():
    """Создает клавиатуру главного меню"""
    buttons_config = [
        [{'type': 'link', 'text': 'Записаться на приём к врачу', 'url': GOSUSLUGI_APPOINTMENT_URL}],
        [{'type': 'link', 'text': 'Профосмотр/диспансеризация', 'url': GOSUSLUGI_MEDICAL_EXAM_URL}],
        [{'type': 'link', 'text': 'Вызов врача на дом', 'url': GOSUSLUGI_DOCTOR_HOME_URL}],
        [{'type': 'link', 'text': 'Прикрепление к поликлинике', 'url': GOSUSLUGI_ATTACH_TO_POLYCLINIC_URL}],
        [{'type': 'callback', 'text': '🔍 Другие возможности', 'payload': "other_options"}]
    ]
    return create_keyboard(buttons_config)


def create_other_options_keyboard():
    """Создает клавиатуру меню 'Другие возможности'"""
    buttons_config = [
        [{'type': 'link', 'text': '🏥 Ближайшие гос мед учреждения', 'url': MAP_OF_MEDICAL_INSTITUTIONS_URL}],
        [{'type': 'link', 'text': '📞 Единый контакт-центр здравоохранения Севастополя', 'url': CONTACT_CENTER_URL}],
        [{'type': 'callback', 'text': '🔔 Вкл/откл напоминаний', 'payload': "toggle_reminders"}],
        [{'type': 'callback', 'text': '✉️ Написать в поддержку', 'payload': "support_request"}],
        [{'type': 'callback', 'text': '⬅️ Назад', 'payload': "back_to_main"}]
    ]
    return create_keyboard(buttons_config)


async def send_main_menu(bot_instance: Bot, chat_id: int, greeting_name: str):
    """Отправляет главное меню с приветствием"""
    keyboard = create_main_menu_keyboard()
    await bot_instance.send_message(
        chat_id=chat_id,
        text=f"Здравствуйте, {greeting_name}!\n\nВыберите услугу:",
        attachments=[keyboard] if keyboard else []
    )


async def send_other_options_menu(bot_instance: Bot, chat_id: int):
    """Отправляет меню 'Другие возможности'"""
    keyboard = create_keyboard([
        [{'type': 'link', 'text': '🏥 Ближайшие гос мед учреждения', 'url': MAP_OF_MEDICAL_INSTITUTIONS_URL}],
        [{'type': 'link', 'text': '📞 Единый контакт-центр здравоохранения Севастополя', 'url': CONTACT_CENTER_URL}],
        [{'type': 'callback', 'text': '🔔 Вкл/откл напоминаний', 'payload': "reminders_settings"}],
        [{'type': 'callback', 'text': '✉️ Написать в поддержку', 'payload': "support_request"}],
        [{'type': 'callback', 'text': '⬅️ Назад', 'payload': "back_to_main"}]
    ])
    await bot_instance.send_message(
        chat_id=chat_id,
        text="🔍 Другие возможности:",
        attachments=[keyboard] if keyboard else []
    )


reminder_handler.send_other_options_menu = send_other_options_menu


# --- ОБРАБОТЧИКИ СОБЫТИЙ ---

@dp.bot_started()
@anti_duplicate()
async def bot_started(event: BotStarted):
    """Обработка запуска бота"""
    chat_id = event.chat_id
    chat_id_str = str(chat_id)

    log_user_event(chat_id_str, "bot_started")

    # Проверяем, не обрабатывали ли мы недавно это событие
    current_time = time.time()
    last_bot_start = processed_events.get(chat_id_str, {}).get('last_bot_start', 0)

    # Если событие было менее 30 секунд назад - игнорируем
    if current_time - last_bot_start < 30:
        log_user_event(chat_id_str, "bot_started_ignored_duplicate")
        return

    # Сохраняем время обработки
    if chat_id_str not in processed_events:
        processed_events[chat_id_str] = {}
    processed_events[chat_id_str]['last_bot_start'] = current_time

    try:
        if db.is_user_registered(chat_id_str):
            greeting_name = db.get_user_greeting(chat_id_str)
            log_user_event(chat_id_str, "already_registered")
            # НЕ отправляем главное меню, если пользователь уже в системе
            # await send_main_menu(event.bot, chat_id, greeting_name)
        else:
            log_user_event(chat_id_str, "new_user_detected")
            keyboard = create_keyboard([[
                {'type': 'callback', 'text': 'Продолжить', 'payload': "start_continue"}
            ]])

            await event.bot.send_message(
                chat_id=chat_id,
                text='Здравствуйте! 👩‍⚕️\n\nВы обратились в Медицинский информационно-аналитический центр города Севастополя.\nНаша система позволяет Вам удобно и быстро решить следующие задачи:\n\n📌 Записаться на приём к врачу;\n📌 Вызвать врача на дом;\n📌 Записаться на профилактический медосмотр/диспансеризацию;\n📌 Прикрепиться к поликлинике;\n📌 Получать уведомления о записи к врачу с возможностью её отмены;\n📌 Найти ближайшие государственные медицинские учреждения.',
                attachments=[keyboard] if keyboard else []
            )
    except Exception as e:
        log_system_event("bot_started", "message_send_failed", error=str(e), chat_id=chat_id_str)


@dp.message_callback()
@anti_duplicate()
async def message_callback(event: MessageCallback):
    """Обработка нажатий на инлайн-кнопки"""
    try:
        # Очистка старых событий при достижении лимита
        if len(processed_events) > 1000:
            cleanup_processed_events()

        chat_id = event.message.recipient.chat_id
        chat_id_str = str(chat_id)
        payload = event.callback.payload

        log_user_event(chat_id_str, "button_pressed", payload=payload)

        # Обработка callback-ов регистрации
        if payload == "start_continue":
            await registration_handler.send_agreement_message(event.bot, chat_id)

        elif payload == "agreement_accepted":
            log_security_event(chat_id_str, "consent_accepted")
            await registration_handler.start_registration_process(event.bot, chat_id)

        elif payload == "confirm_phone":
            await registration_handler.handle_phone_confirmation(event.bot, chat_id_str, chat_id)

        elif payload == "reject_phone":
            log_user_event(chat_id_str, "phone_rejected")
            await registration_handler.handle_incorrect_phone(event.bot, chat_id)

        elif payload == "correct_fio":
            await registration_handler.handle_data_correction(event.bot, chat_id_str, chat_id, 'fio')

        elif payload == "correct_birth_date":
            await registration_handler.handle_data_correction(event.bot, chat_id_str, chat_id, 'birth_date')

        elif payload == "confirm_data":
            greeting_name = await registration_handler.handle_data_confirmation(event.bot, chat_id_str, chat_id)
            if greeting_name:
                await send_main_menu(event.bot, chat_id, greeting_name)

        # Обработка основных callback-ов
        elif payload == "other_options":
            await send_other_options_menu(event.bot, chat_id)

        elif payload == "back_to_main":
            greeting_name = db.get_user_greeting(chat_id_str)
            await send_main_menu(event.bot, chat_id, greeting_name)

        # === Управление напоминаниями ===
        elif payload == "reminders_settings":
            await reminder_handler.send_reminder_settings(event.bot, chat_id)
            return

        elif payload == "reminders_yes":
            await reminder_handler.enable_reminders(event.bot, chat_id)
            return

        elif payload == "reminders_no":
            await reminder_handler.disable_reminders(event.bot, chat_id)
            return

        elif payload == "reminders_back":
            await reminder_handler.go_back(event.bot, chat_id)
            return

        elif payload == "support_request":
            chat_id_str = str(chat_id)
            if db.is_user_registered(chat_id_str):
                user_data = {
                    'fio': db.get_user_greeting(chat_id_str),
                    'phone': db.get_user_phone(chat_id_str) if hasattr(db, 'get_user_phone') else "Не указан"
                }
                await support_handler.handle_support_request(event.bot, chat_id, user_data)
            else:
                # Для незарегистрированных пользователей предлагаем начать регистрацию
                keyboard = create_keyboard([[
                    {'type': 'callback', 'text': 'Начать регистрацию', 'payload': "start_continue"}
                ]])
                await event.bot.send_message(
                    chat_id=chat_id,
                    text="❌ Для обращения в поддержку необходимо сначала зарегистрироваться.",
                    attachments=[keyboard] if keyboard else []
                )

    except Exception as e:
        log_system_event("callback_error", str(e), chat_id=chat_id_str)
        # Удаляем состояние при ошибке
        user_states.pop(chat_id_str, None)


@dp.message_created()
@anti_duplicate()
async def handle_message(event: MessageCreated):
    """Обработка всех текстовых сообщений"""
    try:
        # Очистка старых событий при достижении лимита
        if len(processed_events) > 1000:
            cleanup_processed_events()

        chat_id = event.message.recipient.chat_id
        chat_id_str = str(chat_id)

        # Проверяем базовые условия
        if not event.message.body or not event.message.body.text:
            if event.message.body and event.message.body.attachments:
                # Обработка контактов через registration_handler
                contact_processed = await registration_handler.process_contact_message(event, chat_id_str, chat_id)
                if contact_processed:
                    return
            return

        if not event.message.sender:
            return

        message_text = event.message.body.text.strip()
        if not message_text:
            return

        log_user_event(chat_id_str, "message_sent", text=message_text)

        # Если пользователь не зарегистрирован и не в процессе регистрации, игнорируем
        if not db.is_user_registered(chat_id_str) and chat_id_str not in user_states:
            log_user_event(chat_id_str, "message_ignored_unregistered")
            return

        # Пытаемся обработать сообщение как часть процесса регистрации
        registration_processed = await registration_handler.process_text_input(
            chat_id_str, message_text, event.bot, chat_id
        )

        if registration_processed:
            return

        # Если сообщение не обработано как часть регистрации, проверяем другие состояния
        state_info = user_states.get(chat_id_str)
        if not state_info:
            if db.is_user_registered(chat_id_str):
                greeting_name = db.get_user_greeting(chat_id_str)
                await event.bot.send_message(chat_id=chat_id, text="✅ Вы уже в системе.")
                await send_main_menu(event.bot, chat_id, greeting_name)
            return

        state = state_info.get('state')
        user_data = state_info.get('data', {})

        # Обработка состояния поддержки
        if state == 'waiting_support_message':
            await support_handler.process_support_message(event.bot, chat_id, message_text)

    except Exception as e:
        chat_id_str = str(event.message.recipient.chat_id) if hasattr(event, 'message') and hasattr(event.message,
                                                                                                    'recipient') else 'unknown'
        log_system_event("message_handler_error", str(e), chat_id=chat_id_str)
        user_states.pop(chat_id_str, None)


# --- ЗАПУСК ВЕБХУКА ---
async def main():
    global keepalive_task

    log_system_event("bot", "starting", webhook_mode=WEBHOOK_MODE, port=WEBHOOK_PORT)

    # Запускаем фоновую задачу для поддержания активности
    keepalive_task = asyncio.create_task(keepalive_worker())
    log_system_event("keepalive", "worker_started")

    # Настраиваем вебхук в Max API
    webhook_success = await setup_webhook()

    if not webhook_success:
        log_system_event("bot", "webhook_setup_failed")
        # Останавливаем keepalive задачу при ошибке
        if keepalive_task:
            keepalive_task.cancel()
        return

    log_system_event("bot", "webhook_server_starting", port=WEBHOOK_PORT)

    try:
        # Запускаем вебхук сервер
        if WEBHOOK_MODE == "direct":
            # Режим для продакшена - слушаем на указанном порту
            await dp.handle_webhook(
                bot=bot,
                host='0.0.0.0',
                port=WEBHOOK_PORT,
                log_level='info'
            )
        else:
            # Режим для разработки через Xtunnel
            await dp.handle_webhook(
                bot=bot,
                host='0.0.0.0',
                port=80,
                log_level='info'
            )
    finally:
        # Останавливаем keepalive задачу при завершении работы
        if keepalive_task:
            keepalive_task.cancel()
            try:
                await keepalive_task
            except asyncio.CancelledError:
                pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log_system_event("bot", "stopped_manually")
    except Exception as e:
        log_system_event("bot", "crashed", error=str(e))
        raise