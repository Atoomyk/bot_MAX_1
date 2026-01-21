"""
Работа с базой данных для телемедицинских консультаций
"""
import uuid
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import psycopg2
from psycopg2.extras import RealDictCursor

from logging_config import log_system_event


class TelemedDatabase:
    """Класс для работы с таблицей telemed_sessions"""
    
    def __init__(self, conn):
        """
        Args:
            conn: Подключение к PostgreSQL
        """
        self.conn = conn
        self._create_table()
    
    def _create_table(self):
        """Создание таблицы telemed_sessions если не существует"""
        try:
            with self.conn.cursor() as cursor:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS telemed_sessions (
                        -- Основные идентификаторы
                        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        external_id VARCHAR(255) UNIQUE NOT NULL,
                        
                        -- Данные пациента
                        user_id BIGINT REFERENCES users(user_id) ON DELETE SET NULL,
                        patient_phone VARCHAR(20) NOT NULL,
                        patient_fio VARCHAR(255) NOT NULL,
                        patient_snils VARCHAR(14),
                        patient_oms_number VARCHAR(16),
                        patient_oms_series VARCHAR(10),
                        patient_birth_date DATE,
                        patient_sex VARCHAR(1),
                        
                        -- Данные врача
                        doctor_fio VARCHAR(255) NOT NULL,
                        doctor_snils VARCHAR(14),
                        doctor_specialization VARCHAR(255),
                        doctor_position VARCHAR(255),
                        
                        -- Данные клиники
                        clinic_name VARCHAR(255),
                        clinic_address VARCHAR(500),
                        clinic_mo_oid VARCHAR(255),
                        clinic_phone VARCHAR(20),
                        
                        -- Данные консультации
                        schedule_date TIMESTAMPTZ NOT NULL,
                        status VARCHAR(20) NOT NULL,
                        pay_method VARCHAR(20),
                        
                        -- MAX чат
                        chat_id BIGINT,
                        chat_invite_link TEXT,
                        
                        -- Напоминания
                        reminder_24h_at TIMESTAMPTZ,
                        reminder_15m_at TIMESTAMPTZ,
                        reminder_24h_sent_at TIMESTAMPTZ,
                        reminder_15m_sent_at TIMESTAMPTZ,
                        
                        -- Согласие пациента
                        consent_at TIMESTAMPTZ,
                        consent_message_id BIGINT,
                        
                        -- Метаданные
                        created_at TIMESTAMPTZ DEFAULT NOW(),
                        updated_at TIMESTAMPTZ DEFAULT NOW()
                    );
                    
                    -- Индексы
                    CREATE INDEX IF NOT EXISTS idx_telemed_external_id ON telemed_sessions(external_id);
                    CREATE INDEX IF NOT EXISTS idx_telemed_user_id ON telemed_sessions(user_id);
                    CREATE INDEX IF NOT EXISTS idx_telemed_schedule_date ON telemed_sessions(schedule_date);
                    CREATE INDEX IF NOT EXISTS idx_telemed_status ON telemed_sessions(status);
                    CREATE INDEX IF NOT EXISTS idx_telemed_reminder_24h 
                        ON telemed_sessions(reminder_24h_at, reminder_24h_sent_at);
                    CREATE INDEX IF NOT EXISTS idx_telemed_reminder_15m 
                        ON telemed_sessions(reminder_15m_at, reminder_15m_sent_at);
                """)
                self.conn.commit()
                log_system_event("tmk_database", "table_created")
        except psycopg2.Error as e:
            log_system_event("tmk_database", "table_creation_error", error=str(e))
            self.conn.rollback()
    
    def create_session(self, session_data: Dict[str, Any]) -> Optional[str]:
        """
        Создание новой сессии ТМК
        
        Args:
            session_data: Словарь с данными сессии
            
        Returns:
            UUID созданной сессии или None при ошибке
        """
        try:
            with self.conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO telemed_sessions (
                        external_id, user_id, patient_phone, patient_fio,
                        patient_snils, patient_oms_number, patient_oms_series,
                        patient_birth_date, patient_sex,
                        doctor_fio, doctor_snils, doctor_specialization, doctor_position,
                        clinic_name, clinic_address, clinic_mo_oid, clinic_phone,
                        schedule_date, status, pay_method,
                        chat_id, chat_invite_link,
                        reminder_24h_at, reminder_15m_at
                    ) VALUES (
                        %(external_id)s, %(user_id)s, %(patient_phone)s, %(patient_fio)s,
                        %(patient_snils)s, %(patient_oms_number)s, %(patient_oms_series)s,
                        %(patient_birth_date)s, %(patient_sex)s,
                        %(doctor_fio)s, %(doctor_snils)s, %(doctor_specialization)s, %(doctor_position)s,
                        %(clinic_name)s, %(clinic_address)s, %(clinic_mo_oid)s, %(clinic_phone)s,
                        %(schedule_date)s, %(status)s, %(pay_method)s,
                        %(chat_id)s, %(chat_invite_link)s,
                        %(reminder_24h_at)s, %(reminder_15m_at)s
                    )
                    RETURNING id
                """, session_data)
                
                session_id = cursor.fetchone()[0]
                self.conn.commit()
                
                log_system_event("tmk_database", "session_created", 
                                session_id=str(session_id),
                                external_id=session_data['external_id'])
                return str(session_id)
                
        except psycopg2.Error as e:
            log_system_event("tmk_database", "session_creation_error", error=str(e))
            self.conn.rollback()
            return None
    
    def get_session_by_id(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Получение сессии по внутреннему ID"""
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    SELECT * FROM telemed_sessions WHERE id = %s
                """, (session_id,))
                
                result = cursor.fetchone()
                return dict(result) if result else None
                
        except psycopg2.Error as e:
            log_system_event("tmk_database", "get_session_error", error=str(e))
            return None
    
    def get_session_by_external_id(self, external_id: str) -> Optional[Dict[str, Any]]:
        """Получение сессии по внешнему ID из МИС"""
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    SELECT * FROM telemed_sessions WHERE external_id = %s
                """, (external_id,))
                
                result = cursor.fetchone()
                return dict(result) if result else None
                
        except psycopg2.Error as e:
            log_system_event("tmk_database", "get_session_error", error=str(e))
            return None
    
    def update_consent(self, session_id: str, consent_at: datetime, 
                      message_id: Optional[int] = None) -> bool:
        """
        Обновление времени получения согласия
        
        Args:
            session_id: UUID сессии
            consent_at: Время получения согласия
            message_id: ID сообщения с кнопкой согласия
            
        Returns:
            True если обновление успешно
        """
        try:
            with self.conn.cursor() as cursor:
                cursor.execute("""
                    UPDATE telemed_sessions
                    SET consent_at = %s,
                        consent_message_id = %s,
                        updated_at = NOW()
                    WHERE id = %s
                    RETURNING id
                """, (consent_at, message_id, session_id))
                
                updated = cursor.rowcount > 0
                self.conn.commit()
                
                if updated:
                    log_system_event("tmk_database", "consent_updated", 
                                    session_id=session_id)
                
                return updated
                
        except psycopg2.Error as e:
            log_system_event("tmk_database", "consent_update_error", error=str(e))
            self.conn.rollback()
            return False
    
    def update_reminder_sent(self, session_id: str, reminder_type: str) -> bool:
        """
        Обновление времени отправки напоминания (защита от дублей)
        
        Args:
            session_id: UUID сессии
            reminder_type: Тип напоминания ('24h' или '15m')
            
        Returns:
            True если обновление успешно (ровно 1 строка обновлена)
        """
        field_name = f"reminder_{reminder_type}_sent_at"
        
        try:
            with self.conn.cursor() as cursor:
                cursor.execute(f"""
                    UPDATE telemed_sessions
                    SET {field_name} = NOW(),
                        updated_at = NOW()
                    WHERE id = %s
                      AND {field_name} IS NULL
                    RETURNING id
                """, (session_id,))
                
                updated = cursor.rowcount == 1
                self.conn.commit()
                
                if updated:
                    log_system_event("tmk_database", "reminder_marked_sent", 
                                    session_id=session_id, 
                                    reminder_type=reminder_type)
                else:
                    log_system_event("tmk_database", "reminder_already_sent", 
                                    session_id=session_id, 
                                    reminder_type=reminder_type)
                
                return updated
                
        except psycopg2.Error as e:
            log_system_event("tmk_database", "reminder_update_error", error=str(e))
            self.conn.rollback()
            return False
    
    def update_status(self, external_id: str, new_status: str) -> bool:
        """
        Обновление статуса консультации (например, отмена)
        
        Args:
            external_id: Внешний ID из МИС
            new_status: Новый статус (CANCELLED и т.д.)
            
        Returns:
            True если обновление успешно
        """
        try:
            with self.conn.cursor() as cursor:
                cursor.execute("""
                    UPDATE telemed_sessions
                    SET status = %s,
                        updated_at = NOW()
                    WHERE external_id = %s
                    RETURNING id
                """, (new_status, external_id))
                
                updated = cursor.rowcount > 0
                self.conn.commit()
                
                if updated:
                    log_system_event("tmk_database", "status_updated", 
                                    external_id=external_id, 
                                    new_status=new_status)
                
                return updated
                
        except psycopg2.Error as e:
            log_system_event("tmk_database", "status_update_error", error=str(e))
            self.conn.rollback()
            return False
    
    def get_pending_reminders(self) -> List[Dict[str, Any]]:
        """
        Получение всех неотправленных напоминаний для загрузки в очередь
        
        Returns:
            Список словарей с данными сессий
        """
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    SELECT * FROM telemed_sessions
                    WHERE status != 'CANCELLED'
                      AND (
                          (reminder_24h_sent_at IS NULL AND reminder_24h_at > NOW())
                          OR
                          (reminder_15m_sent_at IS NULL AND reminder_15m_at > NOW())
                      )
                    ORDER BY schedule_date ASC
                """)
                
                results = cursor.fetchall()
                return [dict(row) for row in results]
                
        except psycopg2.Error as e:
            log_system_event("tmk_database", "get_pending_reminders_error", error=str(e))
            return []
