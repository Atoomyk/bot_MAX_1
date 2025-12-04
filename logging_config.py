# logging_config.py
import logging
import logging.handlers
import os
import re

# Кастомные уровни логирования
USER_LEVEL = 25
SYSTEM_LEVEL = 24
DATA_LEVEL = 23
SECURITY_LEVEL = 22
TRANSPORT_LEVEL = 21

# Регистрация кастомных уровней
logging.addLevelName(USER_LEVEL, "USER")
logging.addLevelName(SYSTEM_LEVEL, "SYSTEM")
logging.addLevelName(DATA_LEVEL, "DATA")
logging.addLevelName(SECURITY_LEVEL, "SECURITY")
logging.addLevelName(TRANSPORT_LEVEL, "TRANSPORT")


class MaskingFilter(logging.Filter):
    """Фильтр для маскирования персональных данных в логах"""

    def mask_phone(self, phone):
        if phone and len(phone) >= 8:
            return phone[:4] + '*' * (len(phone) - 7) + phone[-3:]
        return phone

    def mask_fio(self, fio):
        if not fio:
            return fio
        parts = fio.split()
        if len(parts) >= 3:
            if len(parts[0]) > 2:
                parts[0] = parts[0][:3] + '***'
            if len(parts[1]) > 1:
                parts[1] = parts[1][:1] + '***'
            if len(parts[2]) > 3:
                parts[2] = '***' + parts[2][-3:]
        return ' '.join(parts)

    def filter(self, record):
        try:
            if hasattr(record, 'msg') and record.msg:
                # Маскирование телефонов
                phone_pattern = r'(\+7\d{10})'
                record.msg = re.sub(phone_pattern,
                                    lambda m: self.mask_phone(m.group(1)),
                                    record.msg)
                # Маскирование ФИО
                fio_pattern = r'([А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+)'
                record.msg = re.sub(fio_pattern,
                                    lambda m: self.mask_fio(m.group(1)),
                                    record.msg)
        except Exception as e:
            # Логируем ошибку маскирования, но не прерываем логирование
            logging.getLogger(__name__).warning(f"Ошибка маскирования данных: {e}")
        return True


def setup_logging():
    """Настройка системы логирования с кастомными уровнями"""

    log_dir = 'logs'
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    logger = logging.getLogger()
    logger.setLevel(USER_LEVEL)  # Минимальный уровень - USER

    # Очищаем существующие обработчики
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    # Форматтер для логов
    formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] [%(name)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Обработчик для файлов
    file_handler = logging.handlers.TimedRotatingFileHandler(
        filename=os.path.join(log_dir, 'bot.log'),
        when='midnight',
        interval=1,
        backupCount=30,
        encoding='utf-8'
    )
    file_handler.setLevel(USER_LEVEL)
    file_handler.setFormatter(formatter)
    file_handler.suffix = '%Y-%m-%d'

    # Обработчик для консоли
    console_handler = logging.StreamHandler()
    console_handler.setLevel(USER_LEVEL)
    console_handler.setFormatter(formatter)

    # Добавляем фильтр маскирования
    masking_filter = MaskingFilter()
    file_handler.addFilter(masking_filter)
    console_handler.addFilter(masking_filter)

    # Добавляем обработчики
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    # Тестовое сообщение
    logging.log(SYSTEM_LEVEL, "Logging system initialized")


# Словари переводов для логирования
USER_EVENT_TRANSLATIONS = {
    "appointment_cancel_error": {
        "invalid_payload": "Ошибка отмены записи: некорректный идентификатор записи",
        "service_unavailable": "Ошибка отмены записи: сервис недоступен",
        "not_found": "Ошибка отмены записи: запись не найдена",
        "already_cancelled": "Ошибка отмены записи: уже отменена",
        "time_limit_exceeded": "Ошибка отмены записи: превышен лимит времени (более 3 часов)",
        "invalid_confirm_payload": "Ошибка отмены записи: некорректный идентификатор при подтверждении",
        "unknown": "Ошибка отмены записи: неизвестная ошибка"
    },
    "appointment_cancel_confirmation_shown": "Показано подтверждение отмены записи",
    "appointment_cancelled": "Запись отменена",
    "appointment_cancel_failed": "Не удалось отменить запись",
    "appointment_cancel_cancelled": "Отмена записи отменена пользователем",
    "button_pressed": {
        "cancel_appointment_back": "Нажата кнопка «Назад» в меню отмены записи",
        "other_options": "Нажата кнопка «Другие возможности»",
        "default": "Нажата кнопка"
    },
    "message_sent": "Отправлено сообщение",
    "other_options_menu_opened": "Открыто меню «Другие возможности»",
    "appointments_list_viewed": "Просмотрен список записей",
    "appointment_details_viewed": "Просмотрены детали записи",
    "bot_started": "Бот запущен",
    "already_registered": "Пользователь уже зарегистрирован",
    "new_user_detected": "Обнаружен новый пользователь",
    "registration_start_clicked": "Нажата кнопка начала регистрации",
    "phone_confirmed": "Телефон подтвержден",
    "phone_rejected": "Телефон отклонен",
    "fio_correction_requested": "Запрошена коррекция ФИО",
    "birth_date_correction_requested": "Запрошена коррекция даты рождения",
    "registration_data_confirmed": "Данные регистрации подтверждены",
    "back_to_main_menu": "Возврат в главное меню",
    "reminders_settings_opened": "Открыты настройки напоминаний",
    "reminders_enabled": "Напоминания включены",
    "reminders_disabled": "Напоминания выключены",
    "reminders_back_clicked": "Нажата кнопка «Назад» в настройках напоминаний",
    "support_chat_requested": "Запрошен чат поддержки",
    "message_ignored_unregistered": "Сообщение проигнорировано (пользователь не зарегистрирован)"
}

SYSTEM_EVENT_TRANSLATIONS = {
    "appointment": {
        "cancelled": "Запись отменена",
        "cancel_failed": "Не удалось отменить запись"
    }
}


def _translate_user_event(action, **details):
    """Переводит событие пользователя на русский"""
    if action in USER_EVENT_TRANSLATIONS:
        translation = USER_EVENT_TRANSLATIONS[action]
        
        # Если это словарь (для событий с вариантами)
        if isinstance(translation, dict):
            # Проверяем наличие ключа error или payload в details
            if "error" in details:
                error_key = details.get("error", "unknown")
                if error_key in translation:
                    base_msg = translation[error_key]
                else:
                    base_msg = translation.get("default", action)
            elif "payload" in details:
                payload = details.get("payload", "")
                # Проверяем точное совпадение
                if payload in translation:
                    base_msg = translation[payload]
                # Проверяем начало payload (для cancel_appointment:ID и т.д.)
                elif payload.startswith("cancel_appointment:"):
                    base_msg = "Нажата кнопка «Отменить запись»"
                elif payload.startswith("cancel_appointment_confirm:"):
                    base_msg = "Нажата кнопка «Да» для подтверждения отмены записи"
                else:
                    base_msg = translation.get("default", action)
            else:
                base_msg = translation.get("default", action)
        else:
            base_msg = translation
        
        # Формируем детали
        detail_parts = []
        if "appointment_id" in details:
            detail_parts.append(f"appointment_id={details['appointment_id']}")
        if "error" in details and action == "appointment_cancel_error":
            # error уже включен в перевод
            pass
        elif "payload" in details and action == "button_pressed":
            # payload уже включен в перевод
            pass
        elif "text" in details:
            detail_parts.append(f"«{details['text']}»")
        
        if detail_parts:
            return f"{base_msg} ({', '.join(detail_parts)})"
        return base_msg
    
    # Если перевода нет, возвращаем оригинал
    details_str = " ".join([f'{k}={v}' for k, v in details.items()])
    return f"{action} {details_str}" if details_str else action


def _translate_system_event(component, event, **details):
    """Переводит системное событие на русский"""
    if component in SYSTEM_EVENT_TRANSLATIONS:
        component_translations = SYSTEM_EVENT_TRANSLATIONS[component]
        if event in component_translations:
            base_msg = component_translations[event]
            
            # Формируем детали
            detail_parts = []
            if "appointment_id" in details:
                detail_parts.append(f"appointment_id={details['appointment_id']}")
            if "error" in details:
                detail_parts.append(f"ошибка: {details['error']}")
            if "chat_id" in details:
                detail_parts.append(f"chat_id={details['chat_id']}")
            
            if detail_parts:
                return f"{base_msg} ({', '.join(detail_parts)})"
            return base_msg
    
    # Если перевода нет, возвращаем оригинал
    details_str = " ".join([f'{k}={v}' for k, v in details.items()])
    return f"[{component}] {event} {details_str}" if details_str else f"[{component}] {event}"


# Утилиты для логирования
def log_user_event(user_id, action, **details):
    """Логирует действия пользователя"""
    translated_msg = _translate_user_event(action, **details)
    logging.log(USER_LEVEL, f"[chat_id={user_id}] {translated_msg}")


def log_system_event(component, event, **details):
    """Логирует системные события"""
    translated_msg = _translate_system_event(component, event, **details)
    logging.log(SYSTEM_LEVEL, translated_msg)


def log_data_event(user_id, operation, **details):
    """Логирует работу с данными"""
    details_str = " ".join([f'{k}={v}' for k, v in details.items()])
    logging.log(DATA_LEVEL, f"[user_id={user_id}] {operation} {details_str}")


def log_security_event(user_id, event, **details):
    """Логирует события безопасности"""
    details_str = " ".join([f'{k}={v}' for k, v in details.items()])
    logging.log(SECURITY_LEVEL, f"[chat_id={user_id}] {event} {details_str}")


def log_transport_event(method, endpoint, status, **details):
    """Логирует сетевые события"""
    details_str = " ".join([f'{k}={v}' for k, v in details.items()])
    logging.log(TRANSPORT_LEVEL, f"[{method} {endpoint}] status={status} {details_str}")