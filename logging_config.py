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
        except Exception:
            pass
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
        '%(asctime)s %(levelname)s %(message)s',
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


# Утилиты для логирования
def log_user_event(user_id, action, **details):
    """Логирует действия пользователя"""
    details_str = " ".join([f'{k}={v}' for k, v in details.items()])
    logging.log(USER_LEVEL, f"[chat_id={user_id}] {action} {details_str}")


def log_system_event(component, event, **details):
    """Логирует системные события"""
    details_str = " ".join([f'{k}={v}' for k, v in details.items()])
    logging.log(SYSTEM_LEVEL, f"[{component}] {event} {details_str}")


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