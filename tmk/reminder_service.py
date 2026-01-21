"""
Сервис напоминаний о телемедицинских консультациях
In-memory очередь с восстановлением после рестарта
"""
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Tuple
from queue import PriorityQueue
import pytz

from maxapi import Bot
from maxapi.types import Attachment, CallbackButton, ButtonsPayload
from maxapi.utils.inline_keyboard import AttachmentType

from logging_config import log_system_event
from tmk.database import TelemedDatabase
from tmk.message_builder import (
    build_initial_message,
    build_reminder_24h_with_consent,
    build_reminder_24h_without_consent,
    build_reminder_15m_with_link,
    build_reminder_15m_without_consent
)
from tmk.utils import MOSCOW_TZ
from user_database import db as user_db


class ReminderService:
    """Сервис управления напоминаниями о ТМК"""
    
    def __init__(self, bot: Bot, db: TelemedDatabase):
        """
        Args:
            bot: Экземпляр MAX бота
            db: Экземпляр базы данных ТМК
        """
        self.bot = bot
        self.db = db
        self.queue: PriorityQueue = PriorityQueue()
        self.running: bool = False
        self.task: Optional[asyncio.Task] = None
    
    async def start(self):
        """Запуск сервиса напоминаний"""
        if self.running:
            log_system_event("reminder_service", "already_running")
            return
        
        self.running = True
        
        # Загрузка неотправленных напоминаний из БД
        await self._load_pending_reminders()
        
        # Запуск фонового процесса обработки очереди
        self.task = asyncio.create_task(self._process_queue())
        
        log_system_event("reminder_service", "started")
    
    async def stop(self):
        """Остановка сервиса"""
        self.running = False
        
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        
        log_system_event("reminder_service", "stopped")
    
    async def _load_pending_reminders(self):
        """Загрузка неотправленных напоминаний из БД в очередь"""
        log_system_event("reminder_service", "loading_pending_reminders")
        
        sessions = self.db.get_pending_reminders()
        
        loaded_count = 0
        for session in sessions:
            session_id = str(session['id'])
            
            # Добавляем напоминание за 24 часа
            if session['reminder_24h_sent_at'] is None and session['reminder_24h_at']:
                if session['reminder_24h_at'] > datetime.now(MOSCOW_TZ):
                    await self.add_reminder(session_id, '24h', session['reminder_24h_at'])
                    loaded_count += 1
            
            # Добавляем напоминание за 15 минут
            if session['reminder_15m_sent_at'] is None and session['reminder_15m_at']:
                if session['reminder_15m_at'] > datetime.now(MOSCOW_TZ):
                    await self.add_reminder(session_id, '15m', session['reminder_15m_at'])
                    loaded_count += 1
        
        log_system_event(
            "reminder_service",
            "reminders_loaded",
            count=loaded_count,
            sessions=len(sessions)
        )
    
    async def add_reminder(self, session_id: str, reminder_type: str, send_at: datetime):
        """
        Добавление напоминания в очередь
        
        Args:
            session_id: UUID сессии
            reminder_type: Тип ('24h' или '15m')
            send_at: Время отправки
        """
        # Преобразуем в timestamp для сортировки в очереди
        timestamp = send_at.timestamp()
        
        # Добавляем в очередь (сортировка по времени)
        await asyncio.get_event_loop().run_in_executor(
            None,
            self.queue.put,
            (timestamp, session_id, reminder_type)
        )
        
        log_system_event(
            "reminder_service",
            "reminder_added",
            session_id=session_id,
            reminder_type=reminder_type,
            send_at=send_at.isoformat()
        )
    
    async def _process_queue(self):
        """Основной цикл обработки очереди напоминаний"""
        log_system_event("reminder_service", "queue_processing_started")
        
        while self.running:
            try:
                # Проверяем, есть ли элементы в очереди
                if self.queue.empty():
                    # Ждём 60 секунд перед следующей проверкой
                    await asyncio.sleep(60)
                    continue
                
                # Получаем следующее напоминание (без удаления из очереди)
                timestamp, session_id, reminder_type = await asyncio.get_event_loop().run_in_executor(
                    None,
                    self.queue.queue[0].__getitem__,
                    slice(None)
                )
                
                # Конвертируем timestamp в datetime
                send_at = datetime.fromtimestamp(timestamp, tz=MOSCOW_TZ)
                now = datetime.now(MOSCOW_TZ)
                
                # Вычисляем время ожидания
                wait_seconds = (send_at - now).total_seconds()
                
                if wait_seconds > 60:
                    # Если ждать больше минуты - спим минуту и проверяем снова
                    await asyncio.sleep(60)
                    continue
                
                elif wait_seconds > 0:
                    # Ждём точное время
                    await asyncio.sleep(wait_seconds)
                
                # Удаляем из очереди
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    self.queue.get
                )
                
                # Отправляем напоминание
                await self._send_reminder(session_id, reminder_type)
                
            except Exception as e:
                log_system_event(
                    "reminder_service",
                    "queue_processing_error",
                    error=str(e)
                )
                await asyncio.sleep(60)
    
    async def _send_reminder(self, session_id: str, reminder_type: str):
        """
        Отправка напоминания пациенту
        
        Args:
            session_id: UUID сессии
            reminder_type: Тип напоминания ('24h' или '15m')
        """
        log_system_event(
            "reminder_service",
            "sending_reminder",
            session_id=session_id,
            reminder_type=reminder_type
        )
        
        # Получаем данные сессии
        session = self.db.get_session_by_id(session_id)
        
        if not session:
            log_system_event(
                "reminder_service",
                "session_not_found",
                session_id=session_id
            )
            return
        
        # Проверяем статус (не отменена ли консультация)
        if session['status'] == 'CANCELLED':
            log_system_event(
                "reminder_service",
                "session_cancelled_skip",
                session_id=session_id
            )
            return
        
        # Проверяем, не отправлялось ли уже это напоминание
        if session[f'reminder_{reminder_type}_sent_at'] is not None:
            log_system_event(
                "reminder_service",
                "reminder_already_sent",
                session_id=session_id,
                reminder_type=reminder_type
            )
            return
        
        # Проверяем наличие user_id (найден ли пациент)
        if not session['user_id']:
            log_system_event(
                "reminder_service",
                "user_not_found",
                session_id=session_id,
                phone=session['patient_phone']
            )
            # TODO: Отправка в чат ТМК как fallback
            return
        
        user_id = session['user_id']
        
        # Формируем сообщение в зависимости от типа напоминания
        if reminder_type == '24h':
            await self._send_24h_reminder(user_id, session)
        elif reminder_type == '15m':
            await self._send_15m_reminder(user_id, session)
        
        # Обновляем БД (защита от дублей)
        success = self.db.update_reminder_sent(session_id, reminder_type)
        
        if success:
            log_system_event(
                "reminder_service",
                "reminder_sent_successfully",
                session_id=session_id,
                reminder_type=reminder_type,
                user_id=user_id
            )
        else:
            log_system_event(
                "reminder_service",
                "reminder_already_sent_by_another_instance",
                session_id=session_id,
                reminder_type=reminder_type
            )
    
    async def _send_24h_reminder(self, user_id: int, session: dict):
        """Отправка напоминания за 24 часа"""
        # Получаем chat_id пользователя
        chat_id = user_db.get_last_chat_id(user_id)
        if not chat_id:
            log_system_event(
                "reminder_service",
                "chat_id_not_found",
                user_id=user_id
            )
            return
        
        # Проверяем наличие согласия
        has_consent = session['consent_at'] is not None
        
        if has_consent:
            message_text = build_reminder_24h_with_consent(session)
            # Согласие уже есть, кнопку не показываем
            await self.bot.send_message(
                chat_id=chat_id,
                text=message_text
            )
        else:
            message_text = build_reminder_24h_without_consent(session)
            # Согласия нет, показываем кнопку
            await self._send_with_consent_button(user_id, session, message_text)
    
    async def _send_15m_reminder(self, user_id: int, session: dict):
        """Отправка напоминания за 15 минут"""
        # Получаем chat_id пользователя
        chat_id = user_db.get_last_chat_id(user_id)
        if not chat_id:
            log_system_event(
                "reminder_service",
                "chat_id_not_found",
                user_id=user_id
            )
            return
        
        # Проверяем наличие согласия
        has_consent = session['consent_at'] is not None
        
        if has_consent:
            # Отправляем со ссылкой на чат
            message_text = build_reminder_15m_with_link(session)
            await self.bot.send_message(
                chat_id=chat_id,
                text=message_text
            )
        else:
            # Отправляем информационное сообщение без ссылки
            message_text = build_reminder_15m_without_consent(session)
            await self.bot.send_message(
                chat_id=chat_id,
                text=message_text
            )
    
    async def _send_with_consent_button(self, user_id: int, session: dict, message_text: str):
        """
        Отправка сообщения с кнопкой согласия
        
        Args:
            user_id: ID пользователя
            session: Данные сессии
            message_text: Текст сообщения
        """
        session_id = str(session['id'])
        
        # Получаем chat_id пользователя
        chat_id = user_db.get_last_chat_id(user_id)
        if not chat_id:
            log_system_event(
                "reminder_service",
                "chat_id_not_found",
                user_id=user_id
            )
            return
        
        # Создаём кнопку согласия
        consent_button = CallbackButton(
            text="Согласен",
            payload=f"tmk_consent_{session_id}"
        )
        
        buttons_attachment = Attachment(
            type=AttachmentType.INLINE_KEYBOARD,
            payload=ButtonsPayload(
                buttons=[[consent_button]]
            )
        )
        
        try:
            await self.bot.send_message(
                chat_id=chat_id,
                text=message_text,
                attachments=[buttons_attachment]
            )
        except Exception as e:
            log_system_event(
                "reminder_service",
                "send_message_error",
                error=str(e),
                user_id=user_id,
                chat_id=chat_id
            )
    
    async def send_initial_message(self, user_id: int, session: dict):
        """
        Отправка первого сообщения при создании ТМК
        
        Args:
            user_id: ID пользователя
            session: Данные сессии
        """
        message_text = build_initial_message(session)
        await self._send_with_consent_button(user_id, session, message_text)
