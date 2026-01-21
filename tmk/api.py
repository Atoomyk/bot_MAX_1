"""
FastAPI endpoints для интеграции с МИС
"""
import os
from datetime import datetime, timedelta
from typing import Optional
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

from logging_config import log_system_event, log_security_event
from tmk.models import (
    TelemedCreateRequest,
    TelemedUpdateRequest,
    TelemedCreateResponse,
    TelemedUpdateResponse
)
from tmk.database import TelemedDatabase
from tmk.sferum_client import SferumClient
from tmk.reminder_service import ReminderService
from tmk.message_builder import build_cancellation_message
from tmk.utils import normalize_phone, parse_datetime_with_tz, MOSCOW_TZ
from user_database import db as user_db

load_dotenv()

MIS_API_TOKEN = os.getenv("MIS_API_TOKEN")


# Глобальные переменные для зависимостей (будут инициализированы в create_tmk_app)
tmk_db: Optional[TelemedDatabase] = None
reminder_service: Optional[ReminderService] = None
bot_instance = None


def verify_token(authorization: str = Header(...)) -> bool:
    """
    Проверка токена авторизации из заголовка
    
    Args:
        authorization: Заголовок Authorization
        
    Returns:
        True если токен валидный
        
    Raises:
        HTTPException: Если токен невалидный
    """
    if not authorization.startswith("Bearer "):
        log_security_event("tmk_api", "invalid_auth_format")
        raise HTTPException(status_code=401, detail="Invalid authorization format")
    
    token = authorization.replace("Bearer ", "")
    
    if token != MIS_API_TOKEN:
        log_security_event("tmk_api", "invalid_token", token=token[:10] + "...")
        raise HTTPException(status_code=401, detail="Invalid token")
    
    return True


def create_tmk_app(bot, tmk_database: TelemedDatabase, reminder_svc: ReminderService) -> FastAPI:
    """
    Создание FastAPI приложения для интеграции с МИС
    
    Args:
        bot: Экземпляр MAX бота
        tmk_database: Экземпляр базы данных ТМК
        reminder_svc: Экземпляр сервиса напоминаний
        
    Returns:
        Настроенное FastAPI приложение
    """
    global tmk_db, reminder_service, bot_instance
    tmk_db = tmk_database
    reminder_service = reminder_svc
    bot_instance = bot
    
    app = FastAPI(
        title="MAX TMK Integration API",
        description="API для интеграции телемедицинских консультаций с МИС",
        version="1.0.0"
    )
    
    @app.post("/services/telemed", response_model=TelemedCreateResponse)
    async def create_telemed_session(
        request: TelemedCreateRequest,
        authorized: bool = Depends(verify_token)
    ):
        """
        Создание новой записи на телемедицинскую консультацию
        
        Процесс:
        1. Создание чата через MAX API
        2. Поиск пациента по телефону в БД
        3. Сохранение сессии в БД
        4. Добавление напоминаний в очередь
        5. Отправка первого сообщения пациенту
        6. Возврат ответа в МИС
        """
        log_system_event(
            "tmk_api",
            "create_request_received",
            external_id=request.externalId,
            schedule_date=request.scheduleDate
        )
        
        try:
            # 1. Создание чата через MAX API
            doctor_fio = request.doctor.get_full_name()
            patient_fio = request.patient.get_full_name()
            
            chat_data = await SferumClient.create_telemedicine_chat(
                doctor_fio=doctor_fio,
                patient_fio=patient_fio
            )
            
            if not chat_data:
                log_system_event(
                    "tmk_api",
                    "chat_creation_failed",
                    external_id=request.externalId
                )
                return TelemedCreateResponse(
                    status="error",
                    id="",
                    message="Не удалось создать чат после 3 попыток",
                    error="MAX API error"
                )
            
            # 2. Парсинг даты консультации
            schedule_date = parse_datetime_with_tz(request.scheduleDate)
            
            # 3. Расчёт времени напоминаний
            reminder_24h_at = schedule_date - timedelta(hours=24)
            reminder_15m_at = schedule_date - timedelta(minutes=15)
            
            # 4. Поиск пациента по телефону
            patient_phone = normalize_phone(
                request.patient.phone if request.patient.phone else ""
            )
            
            # Если телефон не передан, пытаемся взять из СНИЛС или ОМС (маловероятно)
            if not patient_phone or patient_phone == "+":
                log_system_event(
                    "tmk_api",
                    "patient_phone_missing",
                    external_id=request.externalId
                )
            
            user_id = None
            if patient_phone and patient_phone != "+":
                user = user_db.get_user_by_phone(patient_phone)
                if user:
                    user_id = user['user_id']
                    log_system_event(
                        "tmk_api",
                        "patient_found",
                        external_id=request.externalId,
                        user_id=user_id,
                        phone=patient_phone
                    )
                else:
                    log_system_event(
                        "tmk_api",
                        "patient_not_found",
                        external_id=request.externalId,
                        phone=patient_phone
                    )
            
            # 5. Подготовка данных для БД
            session_data = {
                "external_id": request.externalId,
                "user_id": user_id,
                "patient_phone": patient_phone,
                "patient_fio": patient_fio,
                "patient_snils": request.patient.SNILS,
                "patient_oms_number": request.patient.OMS.number,
                "patient_oms_series": request.patient.OMS.series,
                "patient_birth_date": request.patient.birthDate,
                "patient_sex": request.patient.sex.value,
                "doctor_fio": doctor_fio,
                "doctor_snils": request.doctor.SNILS,
                "doctor_specialization": request.doctor.specialization,
                "doctor_position": request.doctor.position,
                "clinic_name": request.clinic.name,
                "clinic_address": request.clinic.address,
                "clinic_mo_oid": request.clinic.MO_OID,
                "clinic_phone": request.clinic.phone,
                "schedule_date": schedule_date,
                "status": request.status.value,
                "pay_method": request.payMethod.value,
                "chat_id": chat_data["chat_id"],
                "chat_invite_link": chat_data["invite_link"],
                "reminder_24h_at": reminder_24h_at,
                "reminder_15m_at": reminder_15m_at
            }
            
            # 6. Сохранение в БД
            session_id = tmk_db.create_session(session_data)
            
            if not session_id:
                log_system_event(
                    "tmk_api",
                    "session_creation_failed",
                    external_id=request.externalId
                )
                return TelemedCreateResponse(
                    status="error",
                    id="",
                    message="Ошибка при сохранении в БД",
                    error="Database error"
                )
            
            # 7. Добавление напоминаний в очередь
            now = datetime.now(MOSCOW_TZ)
            
            if reminder_24h_at > now:
                await reminder_service.add_reminder(session_id, '24h', reminder_24h_at)
            
            if reminder_15m_at > now:
                await reminder_service.add_reminder(session_id, '15m', reminder_15m_at)
            
            # 8. Отправка первого сообщения пациенту (если найден)
            if user_id:
                session = tmk_db.get_session_by_id(session_id)
                await reminder_service.send_initial_message(user_id, session)
                
                log_system_event(
                    "tmk_api",
                    "initial_message_sent",
                    session_id=session_id,
                    user_id=user_id
                )
            
            # 9. Возврат ответа в МИС
            log_system_event(
                "tmk_api",
                "session_created_successfully",
                session_id=session_id,
                external_id=request.externalId,
                chat_invite_link=chat_data["invite_link"]
            )
            
            return TelemedCreateResponse(
                status="success",
                id=session_id,
                chat_invite_link=chat_data["invite_link"],
                message="Консультация создана"
            )
        
        except Exception as e:
            log_system_event(
                "tmk_api",
                "create_request_error",
                external_id=request.externalId,
                error=str(e)
            )
            
            return TelemedCreateResponse(
                status="error",
                id="",
                message="Внутренняя ошибка сервера",
                error=str(e)
            )
    
    @app.put("/services/telemed/{external_id}", response_model=TelemedUpdateResponse)
    async def update_telemed_session(
        external_id: str,
        request: TelemedUpdateRequest,
        authorized: bool = Depends(verify_token)
    ):
        """
        Обновление/отмена записи на телемедицинскую консультацию
        
        Процесс:
        1. Поиск сессии по external_id
        2. Обновление статуса в БД
        3. Отправка сообщения об отмене пациенту
        4. Возврат ответа в МИС
        
        Примечание: Напоминания не удаляются из очереди,
        они просто не отправятся из-за статуса CANCELLED
        """
        log_system_event(
            "tmk_api",
            "update_request_received",
            external_id=external_id,
            new_status=request.status.value
        )
        
        try:
            # 1. Поиск сессии
            session = tmk_db.get_session_by_external_id(external_id)
            
            if not session:
                log_system_event(
                    "tmk_api",
                    "session_not_found",
                    external_id=external_id
                )
                return TelemedUpdateResponse(
                    status="error",
                    id="",
                    message="Консультация не найдена",
                    error="Session not found"
                )
            
            session_id = str(session['id'])
            
            # 2. Обновление статуса
            success = tmk_db.update_status(external_id, request.status.value)
            
            if not success:
                log_system_event(
                    "tmk_api",
                    "status_update_failed",
                    external_id=external_id
                )
                return TelemedUpdateResponse(
                    status="error",
                    id=session_id,
                    message="Ошибка при обновлении статуса",
                    error="Database error"
                )
            
            # 3. Отправка сообщения об отмене пациенту (если найден)
            if request.status.value == "CANCELLED" and session['user_id']:
                message_text = build_cancellation_message(session)
                
                # Получаем chat_id пользователя
                chat_id = user_db.get_last_chat_id(session['user_id'])
                if chat_id:
                    await bot_instance.send_message(
                        chat_id=chat_id,
                        text=message_text
                    )
                
                log_system_event(
                    "tmk_api",
                    "cancellation_message_sent",
                    session_id=session_id,
                    user_id=session['user_id']
                )
            
            # 4. Возврат ответа
            log_system_event(
                "tmk_api",
                "session_updated_successfully",
                session_id=session_id,
                external_id=external_id,
                new_status=request.status.value
            )
            
            return TelemedUpdateResponse(
                status="success",
                id=session_id,
                message=f"Статус обновлён на {request.status.value}"
            )
        
        except Exception as e:
            log_system_event(
                "tmk_api",
                "update_request_error",
                external_id=external_id,
                error=str(e)
            )
            
            return TelemedUpdateResponse(
                status="error",
                id="",
                message="Внутренняя ошибка сервера",
                error=str(e)
            )
    
    @app.get("/health")
    async def health_check():
        """Проверка здоровья сервиса"""
        return {"status": "healthy", "service": "tmk"}
    
    return app
