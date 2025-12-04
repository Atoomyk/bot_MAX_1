# bot_config.py
"""Конфигурация и инициализация бота"""
import os
from dotenv import load_dotenv
from maxapi import Bot, Dispatcher
from maxapi.types import (
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
from logging_config import setup_logging, log_system_event
from sync_appointments.service import SyncService
from sync_appointments.scheduler import SchedulerManager
from commands.sync_command import SyncCommandHandler
from user_database import db

# Настройка логирования
setup_logging()

# Загрузка переменных окружения
load_dotenv()
TOKEN = os.getenv("MAXAPI_TOKEN")
WEBHOOK_MODE = os.getenv("WEBHOOK_MODE", "xtunnel")
XTUNNEL_URL = os.getenv("XTUNNEL_URL")
DIRECT_WEBHOOK_URL = os.getenv("DIRECT_WEBHOOK_URL")
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", "8083"))

# ID администратора
ADMIN_ID = os.getenv("ADMIN_ID")
if ADMIN_ID:
    ADMIN_ID = int(ADMIN_ID)

# URL внешней системы МИС
MIS_API_URL = os.getenv("MIS_API_URL")

# Определение URL вебхука
if WEBHOOK_MODE == "direct" and DIRECT_WEBHOOK_URL:
    WEBHOOK_URL = DIRECT_WEBHOOK_URL
    log_system_event("webhook", "mode_direct", url=WEBHOOK_URL)
else:
    WEBHOOK_URL = XTUNNEL_URL
    log_system_event("webhook", "mode_xtunnel", url=WEBHOOK_URL)

# Инициализация бота и диспетчера
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

# Глобальные переменные
user_states = {}
processed_events = {}

# Глобальные переменные для синхронизации записей
sync_service = None
sync_command_handler = None
scheduler_manager = None


def init_sync_service():
    """Инициализирует сервис синхронизации записей"""
    global sync_service, sync_command_handler, scheduler_manager

    try:
        if MIS_API_URL and ADMIN_ID:
            sync_service = SyncService(db, bot, MIS_API_URL)
            scheduler_manager = SchedulerManager(sync_service)
            sync_command_handler = SyncCommandHandler(sync_service, int(ADMIN_ID))
            log_system_event("sync", "service_initialized", url=MIS_API_URL)
        else:
            reason = ""
            if not MIS_API_URL:
                reason += "MIS_API_URL отсутствует "
            if not ADMIN_ID:
                reason += "ADMIN_ID отсутствует "
            log_system_event("sync", "init_skipped", reason=reason.strip())
    except Exception as e:
        log_system_event("sync", "init_error", error=str(e))


# Инициализация обработчиков
support_handler = init_support_handler(user_states)
registration_handler = RegistrationHandler(user_states)
reminder_handler = ReminderHandler(db, None)

# Устанавливаем бот в обработчики
support_handler.set_bot(bot)

