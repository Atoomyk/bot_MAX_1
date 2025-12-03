# support_handler.py
import os
import json
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional, List, Any
from dataclasses import dataclass, asdict
import time

from dotenv import load_dotenv

# Импорт системы логирования
from logging_config import log_user_event, log_system_event, log_security_event

# Загрузка переменных окружения
load_dotenv()

# Настройки из .env
ADMIN_ID = os.getenv("ADMIN_ID")
if ADMIN_ID:
    ADMIN_ID = int(ADMIN_ID)

# Константы
TICKETS_DIR = Path("tickets")
INACTIVITY_TIMEOUT = 7200  # 2 часа в секундах
LOG_RETENTION_DAYS = 30  # Хранить логи 30 дней


@dataclass
class ChatMessage:
    """Структура сообщения в чате"""
    from_user: str  # "user" или "admin"
    text: str
    time: str


@dataclass
class ChatLog:
    """Структура лога чата"""
    user_id: int
    user_name: str
    user_phone: str
    admin_id: Optional[int]
    start_time: str
    end_time: Optional[str]
    messages: List[ChatMessage]


class SupportHandler:
    def __init__(self, user_states: Dict):
        self.user_states = user_states
        self.admin_id = ADMIN_ID

        # Структуры для управления чатами
        self.active_chats: Dict[int, Dict] = {}  # user_id -> chat_info
        self.waiting_queue: List[Dict] = []  # Очередь ожидающих пользователей
        self.admin_active_chat: Optional[int] = None  # user_id с которым общается админ
        self.chat_logs: Dict[int, ChatLog] = {}  # Активные логи чатов

        # Создаем папку для логов
        self._ensure_tickets_dir()

        # Запускаем фоновую задачу для проверки неактивности
        self._cleanup_task = None

    def _ensure_tickets_dir(self):
        """Создает папку для логов если ее нет"""
        if not TICKETS_DIR.exists():
            TICKETS_DIR.mkdir(exist_ok=True)
            log_system_event("support_chat", "tickets_dir_created")

    async def start_cleanup_task(self):
        """Запускает фоновую задачу для очистки"""
        self._cleanup_task = asyncio.create_task(self._cleanup_worker())

    async def _cleanup_worker(self):
        """Фоновая задача для проверки неактивности и очистки старых логов"""
        while True:
            try:
                await self._check_inactive_chats()
                await self._cleanup_old_logs()
                await asyncio.sleep(300)  # Проверяем каждые 5 минут
            except Exception as e:
                log_system_event("support_chat", "cleanup_error", error=str(e))
                await asyncio.sleep(60)

    async def _check_inactive_chats(self):
        """Проверяет и завершает неактивные чаты"""
        current_time = time.time()
        chats_to_end = []

        for user_id, chat_info in list(self.active_chats.items()):
            last_activity = chat_info.get('last_activity', 0)
            if current_time - last_activity > INACTIVITY_TIMEOUT:
                chats_to_end.append(user_id)

        for user_id in chats_to_end:
            await self._auto_end_chat(user_id)

    async def _auto_end_chat(self, user_id: int):
        """Автоматическое завершение чата по неактивности"""
        chat_info = self.active_chats.get(user_id)
        if not chat_info:
            return

        # Завершаем чат
        await self._end_chat(
            user_id=user_id,
            ended_by="system",
            reason="inactivity"
        )

        log_system_event("support_chat", "auto_ended", user_id=user_id)

    async def _cleanup_old_logs(self):
        """Удаляет старые логи (старше 30 дней)"""
        try:
            cutoff_date = datetime.now() - timedelta(days=LOG_RETENTION_DAYS)

            for log_file in TICKETS_DIR.glob("*.json"):
                try:
                    # Пытаемся получить дату из имени файла
                    file_date_str = log_file.stem.split('_')[-1]
                    file_date = datetime.strptime(file_date_str, "%Y-%m-%d_%H-%M")

                    if file_date < cutoff_date:
                        log_file.unlink()
                        log_system_event("support_chat", "old_log_deleted", file=log_file.name)
                except (ValueError, IndexError):
                    continue
        except Exception as e:
            log_system_event("support_chat", "cleanup_logs_error", error=str(e))

    def _create_log_filename(self, user_id: int) -> str:
        """Создает имя файла для лога"""
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
        return f"{user_id}_{timestamp}.json"

    def _save_chat_log(self, user_id: int, end_chat: bool = False):
        """Сохраняет лог чата в файл"""
        try:
            if user_id not in self.chat_logs:
                return

            chat_log = self.chat_logs[user_id]

            if end_chat:
                chat_log.end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # Конвертируем в словарь
            log_dict = {
                "user_id": chat_log.user_id,
                "user_name": chat_log.user_name,
                "user_phone": chat_log.user_phone,
                "admin_id": chat_log.admin_id,
                "start_time": chat_log.start_time,
                "end_time": chat_log.end_time,
                "messages": [
                    {
                        "from": msg.from_user,
                        "text": msg.text,
                        "time": msg.time
                    }
                    for msg in chat_log.messages
                ]
            }

            # Сохраняем в файл
            filename = self._create_log_filename(user_id)
            filepath = TICKETS_DIR / filename

            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(log_dict, f, ensure_ascii=False, indent=2)

            if end_chat:
                log_user_event(str(user_id), "chat_log_saved", filename=filename)
                # Удаляем из памяти после сохранения
                del self.chat_logs[user_id]
            else:
                log_user_event(str(user_id), "chat_log_updated", filename=filename)

        except Exception as e:
            log_system_event("support_chat", "save_log_error", error=str(e), user_id=user_id)

    async def handle_support_request(self, bot, chat_id: int, user_data: dict):
        """Обрабатывает запрос на поддержку - запускает онлайн чат"""
        chat_id_str = str(chat_id)

        # Проверяем, не в чате ли уже пользователь
        if chat_id in self.active_chats:
            await bot.send_message(
                chat_id=chat_id,
                text="Вы уже находитесь в чате с техподдержкой.\n\nЧтобы выйти — отправьте цифру 0."
            )
            return

        # Проверяем, есть ли свободный оператор
        if self.admin_active_chat is not None:
            # Оператор занят - добавляем в очередь
            self.waiting_queue.append({
                'user_id': chat_id,
                'user_data': user_data,
                'timestamp': time.time()
            })

            await bot.send_message(
                chat_id=chat_id,
                text="⏳ Оператор занят. Вы добавлены в очередь ожидания.\n\nКак только оператор освободится, с вами свяжутся."
            )

            log_user_event(chat_id_str, "added_to_waiting_queue")
            return

        # Создаем новый чат
        self._create_new_chat(chat_id, user_data)

        # Отправляем сообщение пользователю
        await bot.send_message(
            chat_id=chat_id,
            text="⏳ Ждем подключения оператора...\n\nОпишите вашу проблему или вопрос. Как только оператор подключится, он увидит все ваши сообщения.\n\nЧтобы выйти из чата — отправьте цифру 0."
        )

        # Уведомляем администратора
        await self._notify_admin_new_chat(bot, chat_id, user_data)

        log_user_event(chat_id_str, "chat_requested")

    def _create_new_chat(self, user_id: int, user_data: dict):
        """Создает новую структуру чата"""
        # Создаем лог чата
        chat_log = ChatLog(
            user_id=user_id,
            user_name=user_data.get('fio', 'Неизвестно'),
            user_phone=user_data.get('phone', 'Не указан'),
            admin_id=None,
            start_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            end_time=None,
            messages=[]
        )

        # Сохраняем в памяти
        self.chat_logs[user_id] = chat_log

        # Добавляем в активные чаты
        self.active_chats[user_id] = {
            'user_data': user_data,
            'last_activity': time.time(),
            'waiting_for_admin': True,
            'messages_queue': []  # Сообщения, отправленные до подключения админа
        }

        log_user_event(str(user_id), "chat_created")

    async def _notify_admin_new_chat(self, bot, user_id: int, user_data: dict):
        """Уведомляет администратора о новом чате"""
        if not self.admin_id:
            log_system_event("support_chat", "no_admin_id")
            return

        try:
            message = (
                f"🆕 Новый чат от пользователя:\n\n"
                f"👤 ID: {user_id}\n"
                f"👤 Имя: {user_data.get('fio', 'Неизвестно')}\n"
                f"📞 Телефон: {user_data.get('phone', 'Не указан')}\n\n"
                f"Для подключения отправьте:\n"
                f"/chat {user_id}"
            )

            await bot.send_message(
                chat_id=self.admin_id,
                text=message
            )

            log_system_event("support_chat", "admin_notified", user_id=user_id)

        except Exception as e:
            log_system_event("support_chat", "notify_admin_error", error=str(e))

    async def connect_admin_to_chat(self, bot, admin_id: int, user_id: int) -> bool:
        """Подключает администратора к чату с пользователем"""
        # Проверяем права админа
        if admin_id != self.admin_id:
            await bot.send_message(
                chat_id=admin_id,
                text="❌ У вас нет прав администратора."
            )
            return False

        # Проверяем, не занят ли уже админ
        if self.admin_active_chat is not None:
            await bot.send_message(
                chat_id=admin_id,
                text=f"❌ У вас уже есть активный чат с пользователем {self.admin_active_chat}.\n\nЗавершите его командой /end"
            )
            return False

        # Проверяем, существует ли чат
        if user_id not in self.active_chats:
            await bot.send_message(
                chat_id=admin_id,
                text=f"❌ Чат с пользователем {user_id} не найден или уже завершен."
            )
            return False

        # Проверяем, не подключен ли уже другой админ
        chat_info = self.active_chats[user_id]
        if not chat_info.get('waiting_for_admin', True):
            await bot.send_message(
                chat_id=admin_id,
                text="❌ Этот чат уже обрабатывается другим оператором."
            )
            return False

        # Подключаем админа
        self.admin_active_chat = user_id
        chat_info['waiting_for_admin'] = False
        chat_info['admin_id'] = admin_id
        chat_info['last_activity'] = time.time()

        # Обновляем лог
        if user_id in self.chat_logs:
            self.chat_logs[user_id].admin_id = admin_id

        # Отправляем подтверждение админу
        await bot.send_message(
            chat_id=admin_id,
            text=f"✅ Вы начали чат с пользователем {user_id}.\n\nВсе ваши текстовые сообщения будут пересылаться ему.\n\nДля завершения чата отправьте /end или цифру 0."
        )

        # Отправляем накопленные сообщения от пользователя админу
        messages_queue = chat_info.get('messages_queue', [])
        if messages_queue:
            await bot.send_message(
                chat_id=admin_id,
                text=f"📨 Сообщения от пользователя (отправлены до вашего подключения):"
            )

            for msg in messages_queue:
                await bot.send_message(
                    chat_id=admin_id,
                    text=f"👤 Пользователь: {msg}"
                )

        # Очищаем очередь
        chat_info['messages_queue'] = []

        log_user_event(str(user_id), "admin_connected", admin_id=admin_id)
        log_security_event(str(admin_id), "chat_started", user_id=user_id)

        return True

    async def process_user_message(self, bot, user_id: int, message_text: str) -> bool:
        """Обрабатывает сообщение от пользователя в чате"""
        # Проверяем команду выхода
        if message_text.strip() == "0":
            await self._end_chat(user_id, "user", "user_exit")
            return True

        # Проверяем, в чате ли пользователь
        if user_id not in self.active_chats:
            return False

        chat_info = self.active_chats[user_id]
        chat_info['last_activity'] = time.time()

        # Добавляем сообщение в лог
        if user_id in self.chat_logs:
            self.chat_logs[user_id].messages.append(
                ChatMessage(
                    from_user="user",
                    text=message_text,
                    time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                )
            )
            self._save_chat_log(user_id)

        # Если админ еще не подключен, сохраняем в очередь
        if chat_info.get('waiting_for_admin', True):
            messages_queue = chat_info.get('messages_queue', [])
            messages_queue.append(message_text)
            chat_info['messages_queue'] = messages_queue
            return True

        # Если админ подключен - пересылаем сообщение
        admin_id = chat_info.get('admin_id')
        if admin_id:
            try:
                await bot.send_message(
                    chat_id=admin_id,
                    text=f"👤 Пользователь {user_id}:\n{message_text}"
                )
                return True
            except Exception as e:
                log_system_event("support_chat", "forward_to_admin_error",
                                 error=str(e), user_id=user_id)

        return False

    async def process_admin_message(self, bot, admin_id: int, message_text: str) -> bool:
        """Обрабатывает сообщение от администратора"""
        # Проверяем права
        if admin_id != self.admin_id:
            return False

        # Проверяем команду выхода
        if message_text.strip() in ["0", "/end"]:
            if self.admin_active_chat:
                await self._end_chat(self.admin_active_chat, "admin", "admin_exit")
            else:
                await bot.send_message(
                    chat_id=admin_id,
                    text="❌ У вас нет активного чата для завершения."
                )
            return True

        # Проверяем, есть ли активный чат
        if not self.admin_active_chat:
            # Если админ отправляет /chat <user_id>
            if message_text.startswith("/chat "):
                try:
                    user_id_str = message_text.split()[1]
                    user_id = int(user_id_str)
                    return await self.connect_admin_to_chat(bot, admin_id, user_id)
                except (ValueError, IndexError):
                    await bot.send_message(
                        chat_id=admin_id,
                        text="❌ Неверный формат команды. Используйте: /chat <user_id>"
                    )
                    return True
            return False

        user_id = self.admin_active_chat

        # Проверяем, существует ли чат
        if user_id not in self.active_chats:
            await bot.send_message(
                chat_id=admin_id,
                text="❌ Чат с пользователем не найден или уже завершен."
            )
            self.admin_active_chat = None
            return False

        chat_info = self.active_chats[user_id]
        chat_info['last_activity'] = time.time()

        # Добавляем сообщение в лог
        if user_id in self.chat_logs:
            self.chat_logs[user_id].messages.append(
                ChatMessage(
                    from_user="admin",
                    text=message_text,
                    time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                )
            )
            self._save_chat_log(user_id)

        # Пересылаем сообщение пользователю
        try:
            await bot.send_message(
                chat_id=user_id,
                text=f"👨‍⚕️ Оператор:\n{message_text}"
            )
            return True
        except Exception as e:
            log_system_event("support_chat", "forward_to_user_error",
                             error=str(e), user_id=user_id)
            await bot.send_message(
                chat_id=admin_id,
                text=f"❌ Не удалось отправить сообщение пользователю {user_id}."
            )
            return False

    async def _end_chat(self, user_id: int, ended_by: str, reason: str):
        """Завершает чат"""
        chat_info = self.active_chats.get(user_id)
        if not chat_info:
            return

        # Отправляем уведомления
        if ended_by == "user":
            # Пользователю
            await self._send_message_to_user(user_id,
                                             "Чат с техподдержкой завершён.")

            # Админу (если подключен)
            if chat_info.get('admin_id'):
                await self._send_message_to_admin(chat_info['admin_id'],
                                                  f"Пользователь {user_id} завершил чат.")

        elif ended_by == "admin":
            # Пользователю
            await self._send_message_to_user(user_id,
                                             "Оператор завершил чат.")

            # Админу
            if chat_info.get('admin_id'):
                await self._send_message_to_admin(chat_info['admin_id'],
                                                  f"Чат с пользователем {user_id} завершён.")

        elif ended_by == "system":
            # Пользователю
            await self._send_message_to_user(user_id,
                                             "Чат автоматически завершен из-за неактивности.")

            # Админу (если подключен)
            if chat_info.get('admin_id'):
                await self._send_message_to_admin(chat_info['admin_id'],
                                                  f"Чат с пользователем {user_id} автоматически завершен.")

        # Сохраняем лог
        self._save_chat_log(user_id, end_chat=True)

        # Очищаем структуры
        if user_id in self.active_chats:
            del self.active_chats[user_id]

        if self.admin_active_chat == user_id:
            self.admin_active_chat = None

        # Проверяем очередь ожидания
        await self._check_waiting_queue()

        log_user_event(str(user_id), "chat_ended", ended_by=ended_by, reason=reason)

    async def _send_message_to_user(self, user_id: int, message: str):
        """Отправляет сообщение пользователю (через бота)"""
        # Эта функция будет вызываться из bot.py
        # Сохраняем сообщение для отправки
        if user_id not in self.active_chats:
            self.active_chats[user_id] = {}

        self.active_chats[user_id]['pending_notification'] = message

    async def _send_message_to_admin(self, admin_id: int, message: str):
        """Отправляет сообщение админу (через бота)"""
        # Эта функция будет вызываться из bot.py
        # Сохраняем сообщение для отправки
        if 'admin_notifications' not in self.__dict__:
            self.admin_notifications = {}

        self.admin_notifications[admin_id] = message

    async def _check_waiting_queue(self):
        """Проверяет очередь ожидания и уведомляет админа о следующем пользователе"""
        if not self.waiting_queue or self.admin_active_chat is not None:
            return

        # Берем первого пользователя из очереди
        next_chat = self.waiting_queue.pop(0)
        user_id = next_chat['user_id']
        user_data = next_chat['user_data']

        # Создаем новый чат
        self._create_new_chat(user_id, user_data)

        # Уведомляем админа
        if self.admin_id:
            await self._notify_admin_new_chat(self._get_bot(), user_id, user_data)

        log_system_event("support_chat", "next_user_notified", user_id=user_id)

    def _get_bot(self):
        """Получает экземпляр бота (будет установлен из bot.py)"""
        # Этот метод будет переопределен в bot.py
        return None

    def set_bot(self, bot):
        """Устанавливает экземпляр бота для отправки сообщений"""
        self._bot_instance = bot

    def _get_bot(self):
        """Получает экземпляр бота"""
        return self._bot_instance


# Глобальный экземпляр
support_handler = None


def init_support_handler(user_states_dict):
    """Инициализация поддержки после создания user_states"""
    global support_handler
    support_handler = SupportHandler(user_states_dict)
    return support_handler