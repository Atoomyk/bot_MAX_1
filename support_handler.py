# support_handler.py
import os
import smtplib
import asyncio
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
from datetime import datetime

# Загрузка переменных окружения
load_dotenv()

# Настройки SMTP из .env
SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USERNAME = os.getenv("SMTP_USERNAME")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
SUPPORT_EMAIL = os.getenv("SUPPORT_EMAIL", SMTP_USERNAME)

# Импорт системы логирования
from logging_config import log_system_event, log_user_event


class SupportHandler:
    def __init__(self, user_states):
        self.smtp_server = SMTP_SERVER
        self.smtp_port = SMTP_PORT
        self.smtp_username = SMTP_USERNAME
        self.smtp_password = SMTP_PASSWORD
        self.support_email = SUPPORT_EMAIL
        self.user_states = user_states

    async def send_support_email(self, user_data: dict, message: str, chat_id: str) -> bool:
        """Отправляет email в поддержку от имени пользователя"""
        try:
            subject = f"Обращение в поддержку от пользователя {user_data.get('fio', 'Неизвестно')}"

            body = f"""
            Новое обращение в поддержку:

            Пользователь: {user_data.get('fio', 'Не указано')}
            Телефон: {user_data.get('phone', 'Не указано')}
            Chat ID: {chat_id}
            Дата обращения: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

            Сообщение:
            {message}

            ---
            Автоматическое уведомление от бота МИАЦ
            """

            msg = MIMEMultipart()
            msg['From'] = self.smtp_username
            msg['To'] = self.support_email
            msg['Subject'] = subject
            msg.attach(MIMEText(body, 'plain', 'utf-8'))

            await asyncio.get_event_loop().run_in_executor(
                None,
                self._send_sync_email,
                msg
            )

            log_user_event(chat_id, "support_message_sent", message_preview=message[:50])
            return True

        except Exception as e:
            log_system_event("support_email", "send_failed", error=str(e), chat_id=chat_id)
            return False

    def _send_sync_email(self, msg: MIMEMultipart):
        """Синхронная отправка email"""
        try:
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_username, self.smtp_password)
                server.send_message(msg)
        except Exception as e:
            raise e

    async def handle_support_request(self, bot, chat_id: int, user_data: dict):
        """Обрабатывает запрос на поддержку - запрашивает сообщение"""
        from user_database import db

        chat_id_str = str(chat_id)

        # Используем переданный user_states
        self.user_states[chat_id_str] = {
            'state': 'waiting_support_message',
            'data': user_data
        }

        log_user_event(chat_id_str, "support_request_started")

        await bot.send_message(
            chat_id=chat_id,
            text="📝 Напишите ваше сообщение в поддержку:\n\nОпишите подробно вашу проблему или вопрос, и мы обязательно вам ответим."
        )

    async def process_support_message(self, bot, chat_id: int, message_text: str):
        """Обрабатывает полученное сообщение для поддержки"""
        chat_id_str = str(chat_id)
        state_info = self.user_states.get(chat_id_str, {})

        if state_info.get('state') != 'waiting_support_message':
            return False

        user_data = state_info.get('data', {})

        # Отправка email
        success = await self.send_support_email(user_data, message_text, chat_id_str)

        if success:
            await bot.send_message(
                chat_id=chat_id,
                text="✅ Ваше сообщение отправлено в поддержку!\n\nМы рассмотрим ваше обращение и свяжемся с вами в ближайшее время."
            )
            log_user_event(chat_id_str, "support_message_delivered")
        else:
            await bot.send_message(
                chat_id=chat_id,
                text="❌ Произошла ошибка при отправке сообщения. Пожалуйста, попробуйте позже или свяжитесь с администратором @admin_MIAC"
            )
            log_user_event(chat_id_str, "support_message_failed")

        # Очистка состояния
        self.user_states.pop(chat_id_str, None)

        # Возврат в главное меню
        from user_database import db
        if db.is_user_registered(chat_id_str):
            greeting_name = db.get_user_greeting(chat_id_str)
            from bot_1_win11 import send_main_menu  # Или создай эту функцию доступной
            await send_main_menu(bot, chat_id, greeting_name)
        else:
            await bot.send_message(
                chat_id=chat_id,
                text="🔄 Возвращаюсь в главное меню..."
            )

        return success


# Создадим экземпляр позже, после инициализации user_states
support_handler = None


def init_support_handler(user_states_dict):
    """Инициализация поддержки после создания user_states"""
    global support_handler
    support_handler = SupportHandler(user_states_dict)
    return support_handler