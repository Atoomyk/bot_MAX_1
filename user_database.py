import os
import re
from datetime import datetime
import psycopg2
from dotenv import load_dotenv
from logging_config import log_system_event

load_dotenv()

# --- Конфигурация PostgreSQL ---
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")


class UserDatabase:
    def __init__(self):
        self.conn = None
        self.cursor = None
        self._connect()
        self._init_db()
        self._create_reminders_table()  # ← создаём таблицу напоминаний

    # ---------------------------------------------------------------------
    # Подключение
    # ---------------------------------------------------------------------
    def _connect(self):
        try:
            self.conn = psycopg2.connect(
                dbname=DB_NAME,
                user=DB_USER,
                password=DB_PASSWORD,
                host=DB_HOST,
                port=DB_PORT
            )
            self.cursor = self.conn.cursor()
            log_system_event("database", "user_db_connected")
        except psycopg2.Error as e:
            log_system_event("database", "user_db_connection_failed", error=str(e))

    # ---------------------------------------------------------------------
    # Инициализация таблицы users
    # ---------------------------------------------------------------------
    def _init_db(self):
        if not self.conn:
            return

        try:
            create_table_query = """
            CREATE TABLE IF NOT EXISTS users (
                chat_id VARCHAR(255) PRIMARY KEY,
                fio TEXT NOT NULL,
                phone VARCHAR(20) UNIQUE NOT NULL,
                birth_date VARCHAR(10) NOT NULL,
                registration_date TEXT NOT NULL
            );
            """
            self.cursor.execute(create_table_query)

            self._add_column_if_not_exists('birth_date', 'VARCHAR(10)')
            self._add_column_if_not_exists('registration_date', 'TEXT')

            self.conn.commit()
            log_system_event("database", "users_table_initialized")
        except psycopg2.Error as e:
            log_system_event("database", "users_table_init_error", error=str(e))
            if self.conn:
                self.conn.rollback()

    # ---------------------------------------------------------------------
    # Создание таблицы user_reminders
    # ---------------------------------------------------------------------
    def _create_reminders_table(self):
        """
        Создаёт таблицу напоминаний, если не существует.
        enabled = TRUE по умолчанию
        """
        try:
            query = """
            CREATE TABLE IF NOT EXISTS user_reminders (
                chat_id VARCHAR(255) PRIMARY KEY,
                enabled BOOLEAN NOT NULL DEFAULT TRUE,
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                
                CONSTRAINT fk_user_reminders_user
                    FOREIGN KEY (chat_id) 
                    REFERENCES users(chat_id)
                    ON DELETE CASCADE
            );
            """
            self.cursor.execute(query)
            
            # Миграция: переименовываем колонку user_id в chat_id, если она существует
            try:
                # Проверяем, существует ли колонка user_id
                self.cursor.execute("""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name='user_reminders' AND column_name='user_id'
                """)
                if self.cursor.fetchone():
                    # Переименовываем колонку
                    self.cursor.execute("""
                        ALTER TABLE user_reminders 
                        RENAME COLUMN user_id TO chat_id
                    """)
                    log_system_event("database", "reminders_column_renamed", column="user_id->chat_id")
            except psycopg2.Error as e:
                log_system_event("database", "reminders_column_rename_failed", error=str(e))
                # Продолжаем работу, возможно колонка уже переименована или не существует
            
            # Миграция: добавляем внешний ключ, если его нет
            try:
                # Проверяем, существует ли уже внешний ключ
                self.cursor.execute("""
                    SELECT constraint_name 
                    FROM information_schema.table_constraints 
                    WHERE table_name='user_reminders' 
                    AND constraint_type='FOREIGN KEY'
                    AND constraint_name='fk_user_reminders_user'
                """)
                if not self.cursor.fetchone():
                    # Добавляем внешний ключ
                    self.cursor.execute("""
                        ALTER TABLE user_reminders 
                        ADD CONSTRAINT fk_user_reminders_user
                        FOREIGN KEY (chat_id) 
                        REFERENCES users(chat_id)
                        ON DELETE CASCADE
                    """)
                    log_system_event("database", "reminders_foreign_key_added", constraint="fk_user_reminders_user")
            except psycopg2.Error as e:
                log_system_event("database", "reminders_foreign_key_failed", error=str(e))
                # Продолжаем работу, возможно ключ уже существует
            
            self.conn.commit()
            log_system_event("database", "reminders_table_initialized")
        except psycopg2.Error as e:
            log_system_event("database", "reminders_table_init_error", error=str(e))
            self.conn.rollback()

    # ---------------------------------------------------------------------
    # Создание записи для нового пользователя
    # ---------------------------------------------------------------------
    def init_user_reminder_record(self, chat_id: str):
        """
        Создаёт запись с enabled=TRUE, если её еще нет.
        """
        try:
            self.cursor.execute(
                "SELECT 1 FROM user_reminders WHERE chat_id = %s",
                (chat_id,)
            )
            if self.cursor.fetchone():
                return  # уже существует

            self.cursor.execute(
                """
                INSERT INTO user_reminders (chat_id, enabled, updated_at)
                VALUES (%s, TRUE, NOW())
                """,
                (chat_id,)
            )
            self.conn.commit()
            log_system_event("database", "reminder_record_created", chat_id=chat_id)

        except psycopg2.Error as e:
            log_system_event("database", "reminder_record_create_error", error=str(e), chat_id=chat_id)
            self.conn.rollback()

    # ---------------------------------------------------------------------
    # Получение статуса включено/выключено
    # ---------------------------------------------------------------------
    def get_reminders_status(self, chat_id: str) -> bool:
        """
        Возвращает TRUE/FALSE.
        Если записи нет — создаёт по умолчанию TRUE.
        """
        try:
            self.cursor.execute(
                "SELECT enabled FROM user_reminders WHERE chat_id = %s",
                (chat_id,)
            )
            row = self.cursor.fetchone()

            if not row:
                # создаём запись по умолчанию
                self.init_user_reminder_record(chat_id)
                return True

            return row[0]

        except psycopg2.Error as e:
            log_system_event("database", "get_reminders_status_error", error=str(e), chat_id=chat_id)
            return True  # безопасное значение по умолчанию

    # ---------------------------------------------------------------------
    # Установка статуса
    # ---------------------------------------------------------------------
    def set_reminders_status(self, chat_id: str, enabled: bool):
        try:
            self.cursor.execute(
                """
                INSERT INTO user_reminders (chat_id, enabled, updated_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT (chat_id)
                DO UPDATE SET enabled = EXCLUDED.enabled, updated_at = NOW()
                """,
                (chat_id, enabled)
            )
            self.conn.commit()
            log_system_event("database", "reminders_status_updated", chat_id=chat_id, enabled=enabled)

        except psycopg2.Error as e:
            log_system_event("database", "reminders_status_update_error", error=str(e), chat_id=chat_id)
            self.conn.rollback()

    # ---------------------------------------------------------------------
    # Остальной исходный код
    # ---------------------------------------------------------------------
    def _add_column_if_not_exists(self, column_name: str, column_type: str):
        try:
            check_column_query = """
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name='users' and column_name=%s;
            """
            self.cursor.execute(check_column_query, (column_name,))
            if not self.cursor.fetchone():
                add_column_query = f"ALTER TABLE users ADD COLUMN {column_name} {column_type}"
                self.cursor.execute(add_column_query)
                log_system_event("database", "users_column_added", column=column_name)
        except psycopg2.Error as e:
            log_system_event("database", "users_column_add_error", error=str(e), column=column_name)
            if self.conn:
                self.conn.rollback()

    # ----- Оригинальные методы регистрации/валидации (не менялись) -----

    def is_user_registered(self, chat_id: str) -> bool:
        try:
            self.cursor.execute("SELECT 1 FROM users WHERE chat_id = %s", (chat_id,))
            return self.cursor.fetchone() is not None
        except psycopg2.Error as e:
            log_system_event("database", "query_failed", error=str(e), chat_id=chat_id)
            return False

    def get_user_greeting(self, chat_id: str) -> str:
        try:
            self.cursor.execute("SELECT fio FROM users WHERE chat_id = %s", (chat_id,))
            row = self.cursor.fetchone()
            if not row:
                return "гость"
            fio = row[0].split()
            return " ".join(fio[1:]) if len(fio) >= 2 else fio[0]
        except psycopg2.Error:
            return "гость"

    def validate_fio(self, fio: str) -> bool:
        fio_cleaned = ' '.join(fio.split())
        return bool(re.match(r"^[А-ЯЁ][а-яё]+(-[А-ЯЁ][а-яё]+)? [А-ЯЁ][а-яё]+ [А-ЯЁ][а-яё]+$", fio_cleaned))

    def validate_phone(self, phone: str) -> bool:
        phone_cleaned = re.sub(r'[\s\-]', '', phone)
        return bool(re.match(r"^\+7\d{10}$", phone_cleaned))

    def validate_birth_date(self, date_str: str) -> bool:
        if not re.match(r"^\d{2}\.\d{2}\.\d{4}$", date_str):
            return False

        try:
            day, month, year = map(int, date_str.split('.'))
            birth_date = datetime(year, month, day)
        except ValueError:
            return False

        today = datetime.today()
        if birth_date > today:
            return False

        age = today.year - birth_date.year - (
            (today.month, today.day) < (birth_date.month, birth_date.day)
        )

        return 18 <= age <= 150

    def get_user_phone(self, chat_id: str) -> str:
        try:
            self.cursor.execute("SELECT phone FROM users WHERE chat_id = %s", (chat_id,))
            row = self.cursor.fetchone()
            return row[0] if row else "Не указан"
        except psycopg2.Error:
            return "Не указан"

    def validate_user_data(self, fio, phone, birth_date):
        return (
            self.validate_fio(fio)
            and self.validate_phone(phone)
            and self.validate_birth_date(birth_date)
        )

    def register_user(self, chat_id: str, fio: str, phone: str, birth_date: str) -> bool:
        if not self.validate_user_data(fio, phone, birth_date):
            return False

        try:
            reg_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            phone_cleaned = re.sub(r'[\s\-]', '', phone)

            self.cursor.execute(
                """
                INSERT INTO users (chat_id, fio, phone, birth_date, registration_date)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (chat_id, fio, phone_cleaned, birth_date, reg_date)
            )
            self.conn.commit()

            # ⚡ Создаём запись о напоминаниях
            self.init_user_reminder_record(chat_id)

            return True

        except psycopg2.Error as e:
            log_system_event("database", "user_registration_failed", error=str(e), chat_id=chat_id)
            self.conn.rollback()
            return False

    def close_connection(self):
        if self.cursor:
            self.cursor.close()
        if self.conn:
            self.conn.close()


# Экземпляр базы данных
db = UserDatabase()
