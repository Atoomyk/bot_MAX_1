"""
Обработчики callback кнопок согласия пациента на ТМК
"""
from datetime import datetime
from maxapi.types import MessageCallback, Attachment, CallbackButton, ButtonsPayload
from maxapi.utils.inline_keyboard import AttachmentType

from logging_config import log_user_event, log_system_event
from tmk.database import TelemedDatabase
from tmk.message_builder import build_late_consent_message, build_consent_confirmation_message
from tmk.utils import MOSCOW_TZ
from user_database import db as user_db


async def handle_tmk_consent(event: MessageCallback, bot, db: TelemedDatabase):
    """
    Обработка нажатия кнопки 'Согласен' на ТМК
    
    Args:
        event: Событие callback от maxapi
        bot: Экземпляр бота
        db: Экземпляр базы данных ТМК
    
    Returns:
        True если событие обработано, False если нет
    """
    payload = event.callback.payload
    
    # Проверяем, что это наш callback
    if not payload.startswith("tmk_consent_"):
        return False
    
    try:
        user_id = int(event.from_user.user_id)
        
        # Извлекаем session_id из payload
        session_id = payload.split("_")[2]
        
        log_user_event(
            user_id=user_id,
            action="tmk_consent_clicked",
            session_id=session_id
        )
        
        # Получаем данные сессии
        session = db.get_session_by_id(session_id)
        
        if not session:
            log_system_event(
                "tmk_handlers",
                "session_not_found",
                session_id=session_id
            )
            return True
        
        # Проверяем статус консультации
        if session['status'] == 'CANCELLED':
            log_system_event(
                "tmk_handlers",
                "consent_cancelled_session",
                session_id=session_id
            )
            return True
        
        # Проверяем: не прошла ли уже консультация
        now = datetime.now(MOSCOW_TZ)
        schedule_date = session['schedule_date']
        
        if now > schedule_date:
            log_system_event(
                "tmk_handlers",
                "consent_after_consultation",
                session_id=session_id
            )
            return True
        
        # Проверяем: не было ли уже согласия
        if session['consent_at'] is not None:
            log_system_event(
                "tmk_handlers",
                "consent_already_given",
                session_id=session_id
            )
            return True
        
        # Обновляем согласие в БД (message_id = None, так как структура event.message не содержит id)
        consent_time = datetime.now(MOSCOW_TZ)
        success = db.update_consent(
            session_id=session_id,
            consent_at=consent_time,
            message_id=None
        )
        
        if not success:
            log_system_event(
                "tmk_handlers",
                "consent_update_failed",
                session_id=session_id
            )
            return True
        
        log_user_event(
            user_id=user_id,
            action="tmk_consent_recorded",
            session_id=session_id,
            consent_at=consent_time.isoformat()
        )
        
        # Получаем chat_id пользователя
        chat_id = user_db.get_last_chat_id(user_id)
        
        # Отправляем подтверждающее сообщение с кнопкой "Главное меню"
        if chat_id:
            # Создаем клавиатуру с кнопкой "Главное меню"
            main_menu_button = CallbackButton(text="Главное меню", payload="main_menu")
            buttons_payload = ButtonsPayload(buttons=[[main_menu_button]])
            keyboard = Attachment(
                type=AttachmentType.INLINE_KEYBOARD,
                payload=buttons_payload
            )
            
            confirmation_text = build_consent_confirmation_message()
            
            await bot.send_message(
                chat_id=chat_id,
                text=confirmation_text,
                attachments=[keyboard]
            )
            
            log_system_event(
                "tmk_handlers",
                "consent_confirmation_sent",
                session_id=session_id,
                user_id=user_id
            )
        
        # Проверяем: прошло ли 15-минутное напоминание?
        if session['reminder_15m_sent_at'] is not None:
            # Напоминание уже отправлено, отправляем ссылку сразу
            message_text = build_late_consent_message(session)
            
            if chat_id:
                await bot.send_message(
                    chat_id=chat_id,
                    text=message_text
                )
            
            log_system_event(
                "tmk_handlers",
                "late_consent_link_sent",
                session_id=session_id,
                user_id=user_id
            )
        
        return True
        
    except Exception as e:
        log_system_event(
            "tmk_handlers",
            "consent_handler_error",
            error=str(e),
            user_id=user_id if 'user_id' in locals() else 0
        )
        return False
