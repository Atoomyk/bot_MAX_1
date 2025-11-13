# logging_config.py
import logging
import logging.handlers
import queue
import re
from datetime import datetime
import os


class MaskingFilter(logging.Filter):
    """Фильтр для маскирования персональных данных в логах"""

    def __init__(self):
        super().__init__()

    def mask_phone(self, phone):
        """Маскирует номер телефона: +79781234567 -> +7978*****67"""
        if phone and len(phone) >= 8:
            return phone[:4] + '*' * (len(phone) - 7) + phone[-3:]
        return phone

    def mask_fio(self, fio):
        """Маскирует ФИО: Иванов Иван Иванович -> Ива*** И*** ***ович"""
        if not fio:
            return fio

        parts = fio.split()
        if len(parts) >= 3:
            # Фамилия
            if len(parts[0]) > 2:
                parts[0] = parts[0][:3] + '***'
            # Имя
            if len(parts[1]) > 1:
                parts[1] = parts[1][:1] + '***'
            # Отчество
            if len(parts[2]) > 3:
                parts[2] = '***' + parts[2][-3:]

        return ' '.join(parts)

    def filter(self, record):
        """Применяет маскирование к сообщению лога"""
        try:
            if hasattr(record, 'msg') and record.msg:
                # Маскирование телефонов
                phone_pattern = r'(\+7\d{10})'
                record.msg = re.sub(phone_pattern,
                                    lambda m: self.mask_phone(m.group(1)),
                                    record.msg)

                # Маскирование ФИО (простая эвристика)
                fio_pattern = r'([А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+)'
                record.msg = re.sub(fio_pattern,
                                    lambda m: self.mask_fio(m.group(1)),
                                    record.msg)

            # Также маскируем аргументы, если они есть
            if hasattr(record, 'args') and record.args:
                new_args = []
                for arg in record.args:
                    if isinstance(arg, str):
                        # Маскирование в аргументах
                        arg = re.sub(r'(\+7\d{10})',
                                     lambda m: self.mask_phone(m.group(1)),
                                     arg)
                        arg = re.sub(r'([А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+)',
                                     lambda m: self.mask_fio(m.group(1)),
                                     arg)
                    new_args.append(arg)
                record.args = tuple(new_args)

        except Exception as e:
            # В случае ошибки маскирования - пишем оригинальный лог
            logging.getLogger('masking_error').warning(f"Masking error: {e}")

        return True


def setup_logging():
    """Настройка системы логирования"""

    # Создаем папку для логов если её нет
    log_dir = 'logs'
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    # Основной логгер
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # Очередь для асинхронной записи
    log_queue = queue.Queue(-1)  # Неограниченная очередь

    # Форматтер для логов
    formatter = logging.Formatter(
        '[%(asctime)s] %(levelname)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # 1. Обработчик для файлов (с ротацией по дням)
    file_handler = logging.handlers.TimedRotatingFileHandler(
        filename=os.path.join(log_dir, 'bot.log'),
        when='midnight',  # Ротация в полночь
        interval=1,  # Каждый день
        backupCount=30,  # Хранить 30 дней
        encoding='utf-8'
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    file_handler.suffix = '%Y-%m-%d'  # bot_2024-01-15.log

    # 2. Обработчик для консоли
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)  # Одинаковый уровень с файлами
    console_handler.setFormatter(formatter)

    # 3. QueueHandler для асинхронной записи
    queue_handler = logging.handlers.QueueHandler(log_queue)

    # QueueListener для обработки очереди в фоновом режиме
    queue_listener = logging.handlers.QueueListener(
        log_queue,
        file_handler,
        console_handler,
        respect_handler_level=True
    )

    # Добавляем фильтр маскирования ко всем обработчикам
    masking_filter = MaskingFilter()
    file_handler.addFilter(masking_filter)
    console_handler.addFilter(masking_filter)

    # Очищаем существующие обработчики
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    # Добавляем обработчики
    logger.addHandler(queue_handler)

    # Запускаем фоновый процесс записи логов
    queue_listener.start()

    # Регистрируем функцию остановки при выходе
    import atexit
    atexit.register(queue_listener.stop)

    logging.info("=== Logging system initialized ===")
    logging.info(f"Log files location: {os.path.abspath(log_dir)}")
    logging.info("Logging level: INFO (files and console)")


# Утилиты для удобного логирования
def log_user_event(user_id, event, details=""):
    """Логирует события пользователя"""
    details_str = f" - {details}" if details else ""
    logging.info(f"User {user_id}: {event}{details_str}")


def log_bot_event(event, details=""):
    """Логирует события бота"""
    details_str = f" - {details}" if details else ""
    logging.info(f"Bot: {event}{details_str}")


def log_error(event, error_details=""):
    """Логирует ошибки"""
    error_str = f" - {error_details}" if error_details else ""
    logging.error(f"ERROR: {event}{error_str}")


def log_warning(event, warning_details=""):
    """Логирует предупреждения"""
    warning_str = f" - {warning_details}" if warning_details else ""
    logging.warning(f"WARNING: {event}{warning_str}")


if __name__ == "__main__":
    # Тестирование системы логирования
    setup_logging()

    log_bot_event("System test started")
    log_user_event("123456", "registration started", "FIO: Иванов Иван Иванович, Phone: +79781234567")
    log_user_event("123456", "invalid phone format", "Phone: +7999")
    log_warning("Database connection slow", "Response time: 2.5s")
    log_error("API call failed", "MaxAPI timeout")

    log_bot_event("System test completed")