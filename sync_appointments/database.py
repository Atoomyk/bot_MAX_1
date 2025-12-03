# sync_appointments/database.py
"""
Работа с таблицей appointments в базе данных.
"""

import logging
import json
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class AppointmentsDatabase:
    """
    Класс для работы с таблицей записей к врачу.
    """

    def __init__(self, db_connection):
        """
        Инициализация с подключением к БД.

        Args:
            db_connection: Объект подключения к PostgreSQL
        """
        self.conn = db_connection.conn
        self.cursor = db_connection.cursor
        self._init_appointments_table()

    def _init_appointments_table(self) -> None:
        """
        Создание таблицы appointments и необходимых индексов.
        """
        if not self.conn:
            logger.error("Нет подключения к базе данных")
            return

        try:
            # Создание таблицы appointments
            create_table_query = """
            CREATE TABLE IF NOT EXISTS appointments (
                id BIGSERIAL PRIMARY KEY,
                user_id VARCHAR(255) NOT NULL,
                appointment_json JSONB NOT NULL,
                external_visit_time TIMESTAMP,
                external_mo_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                CONSTRAINT fk_user
                    FOREIGN KEY (user_id) 
                    REFERENCES users(chat_id)
                    ON DELETE CASCADE
            );
            """
            self.cursor.execute(create_table_query)

            # Создание индексов
            indexes = [
                ("idx_appointments_user_id", "appointments (user_id)"),
                ("idx_appointments_user_visit_mo",
                 "appointments (user_id, external_visit_time, external_mo_name)",
                 True),  # UNIQUE индекс
                ("idx_appointments_visit_time", "appointments (external_visit_time)"),
                ("idx_appointments_created_at", "appointments (created_at)")
            ]

            for index_name, index_def, *unique in indexes:
                try:
                    unique_clause = "UNIQUE" if unique and unique[0] else ""
                    self.cursor.execute(f"""
                        CREATE {unique_clause} INDEX IF NOT EXISTS {index_name}
                        ON {index_def};
                    """)
                except Exception as e:
                    logger.warning(f"Не удалось создать индекс {index_name}: {e}")

            self.conn.commit()
            logger.info("Таблица appointments проверена/создана")

        except Exception as e:
            logger.error(f"Ошибка инициализации таблицы appointments: {e}")
            if self.conn:
                self.conn.rollback()

    def appointment_exists(self, user_id: str, visit_time: datetime, mo_name: str) -> bool:
        """
        Проверяет, существует ли уже запись с такими же данными.

        Args:
            user_id: ID пользователя (chat_id)
            visit_time: Дата и время приема
            mo_name: Название мед учреждения

        Returns:
            True если запись уже существует
        """
        try:
            query = """
            SELECT 1 FROM appointments 
            WHERE user_id = %s 
            AND external_visit_time = %s 
            AND external_mo_name = %s
            LIMIT 1
            """
            self.cursor.execute(query, (user_id, visit_time, mo_name))
            return self.cursor.fetchone() is not None

        except Exception as e:
            logger.error(f"Ошибка проверки существования записи: {e}")
            return False

    def add_appointment(self, user_id: str, appointment_data: Dict[str, Any],
                        visit_time: datetime, mo_name: str) -> bool:
        """
        Добавляет новую запись к врачу.

        Args:
            user_id: ID пользователя (chat_id)
            appointment_data: Данные о записи в формате словаря
            visit_time: Дата и время приема
            mo_name: Название мед учреждения

        Returns:
            True если запись успешно добавлена
        """
        try:
            # Преобразуем данные в JSON
            appointment_json = json.dumps(appointment_data, ensure_ascii=False)

            query = """
            INSERT INTO appointments 
            (user_id, appointment_json, external_visit_time, external_mo_name)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (user_id, external_visit_time, external_mo_name) 
            DO NOTHING
            """

            self.cursor.execute(query, (user_id, appointment_json, visit_time, mo_name))
            self.conn.commit()

            if self.cursor.rowcount > 0:
                logger.info(f"Добавлена новая запись для user_id={user_id}, время={visit_time}")
                return True
            else:
                logger.debug(f"Запись уже существует для user_id={user_id}, время={visit_time}")
                return False

        except Exception as e:
            logger.error(f"Ошибка добавления записи: {e}")
            if self.conn:
                self.conn.rollback()
            return False

    def get_user_appointments(self, user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Получает список записей пользователя.

        Args:
            user_id: ID пользователя (chat_id)
            limit: Максимальное количество записей

        Returns:
            Список записей пользователя
        """
        try:
            query = """
            SELECT id, appointment_json, external_visit_time, external_mo_name, created_at
            FROM appointments 
            WHERE user_id = %s
            ORDER BY external_visit_time DESC
            LIMIT %s
            """

            self.cursor.execute(query, (user_id, limit))
            rows = self.cursor.fetchall()

            appointments = []
            for row in rows:
                try:
                    appointment_data = json.loads(row[1])  # appointment_json
                    appointments.append({
                        'id': row[0],
                        'data': appointment_data,
                        'visit_time': row[2],
                        'mo_name': row[3],
                        'created_at': row[4]
                    })
                except json.JSONDecodeError as e:
                    logger.error(f"Ошибка парсинга JSON записи id={row[0]}: {e}")

            return appointments

        except Exception as e:
            logger.error(f"Ошибка получения записей пользователя {user_id}: {e}")
            return []

    def get_appointment_by_id(self, appointment_id: int, user_id: str = None) -> Optional[Dict[str, Any]]:
        """
        Получает запись по ID.

        Args:
            appointment_id: ID записи
            user_id: Опционально - ID пользователя для проверки принадлежности

        Returns:
            Данные записи или None
        """
        try:
            if user_id:
                query = """
                SELECT appointment_json FROM appointments 
                WHERE id = %s AND user_id = %s
                """
                params = (appointment_id, user_id)
            else:
                query = "SELECT appointment_json FROM appointments WHERE id = %s"
                params = (appointment_id,)

            self.cursor.execute(query, params)
            row = self.cursor.fetchone()

            if row:
                return json.loads(row[0])
            return None

        except Exception as e:
            logger.error(f"Ошибка получения записи id={appointment_id}: {e}")
            return None

    def cleanup_old_appointments(self, days_to_keep: int = 365) -> int:
        """
        Удаляет записи старше указанного количества дней.

        Args:
            days_to_keep: Хранить записи не старше этого количества дней

        Returns:
            Количество удаленных записей
        """
        try:
            cutoff_date = datetime.now() - timedelta(days=days_to_keep)

            query = """
            DELETE FROM appointments 
            WHERE external_visit_time < %s 
            RETURNING id
            """

            self.cursor.execute(query, (cutoff_date,))
            deleted_count = self.cursor.rowcount
            self.conn.commit()

            logger.info(f"Удалено {deleted_count} записей старше {days_to_keep} дней")
            return deleted_count

        except Exception as e:
            logger.error(f"Ошибка очистки старых записей: {e}")
            if self.conn:
                self.conn.rollback()
            return 0

    def get_stats(self) -> Dict[str, Any]:
        """
        Получает статистику по записям.

        Returns:
            Словарь со статистикой
        """
        try:
            stats = {}

            # Общее количество записей
            self.cursor.execute("SELECT COUNT(*) FROM appointments")
            stats['total_appointments'] = self.cursor.fetchone()[0] or 0

            # Количество уникальных пользователей с записями
            self.cursor.execute("SELECT COUNT(DISTINCT user_id) FROM appointments")
            stats['unique_users'] = self.cursor.fetchone()[0] or 0

            # Последняя добавленная запись
            self.cursor.execute("""
                SELECT MAX(created_at) FROM appointments
            """)
            stats['last_sync'] = self.cursor.fetchone()[0]

            # Записи по дням (последние 7 дней)
            self.cursor.execute("""
                SELECT DATE(created_at) as day, COUNT(*) 
                FROM appointments 
                WHERE created_at >= CURRENT_DATE - INTERVAL '7 days'
                GROUP BY DATE(created_at)
                ORDER BY day DESC
            """)
            stats['last_7_days'] = dict(self.cursor.fetchall())

            return stats

        except Exception as e:
            logger.error(f"Ошибка получения статистики: {e}")
            return {}