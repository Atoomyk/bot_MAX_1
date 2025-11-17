# user_database.py
import os
import re
import logging
from datetime import datetime
import psycopg2
from dotenv import load_dotenv

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

    def _connect(self):
        """Устанавливает соединение с базой данных PostgreSQL."""
        try:
            self.conn = psycopg2.connect(
                dbname=DB_NAME,
                user=DB_USER,
                password=DB_PASSWORD,
                host=DB_HOST,
                port=DB_PORT
            )
            self.cursor = self.conn.cursor()
            logging.info("INFO: Успешное подключение к PostgreSQL для UserDatabase.")
        except psycopg2.Error as e:
            logging.error(f"ERROR: Не удалось подключиться к PostgreSQL: {e}")
            # В реальном приложении здесь нужно поднять исключение или завершить работу

    def _init_db(self):
        """Создает таблицу users, если она не существует, и добавляет отсутствующие колонки."""
        if not self.conn:
            return

        try:
            # Создаем таблицу users
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

            # Проверяем существование колонок и добавляем их если нужно
            self._add_column_if_not_exists('birth_date', 'VARCHAR(10)')
            self._add_column_if_not_exists('registration_date', 'TEXT')

            self.conn.commit()
            logging.info("INFO: Таблица users проверена/создана.")
        except psycopg2.Error as e:
            logging.error(f"ERROR: Ошибка при инициализации таблицы users: {e}")
            self.conn.rollback()

    def _add_column_if_not_exists(self, column_name: str, column_type: str):
        """Добавляет колонку в таблицу users, если она не существует."""
        try:
            check_column_query = """
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name='users' and column_name=%s;
            """
            self.cursor.execute(check_column_query, (column_name,))
            if not self.cursor.fetchone():
                add_column_query = f"ALTER TABLE users ADD COLUMN {column_name} {column_type};"
                self.cursor.execute(add_column_query)
                logging.info(f"INFO: Добавлена колонка {column_name} в таблицу users.")
        except psycopg2.Error as e:
            logging.error(f"ERROR: Ошибка при добавлении колонки {column_name}: {e}")
            self.conn.rollback()

    def is_user_registered(self, chat_id: str) -> bool:
        """Проверяет, зарегистрирован ли пользователь."""
        if not self.conn:
            return False

        try:
            self.cursor.execute("SELECT 1 FROM users WHERE chat_id = %s", (chat_id,))
            result = self.cursor.fetchone()
            return result is not None
        except psycopg2.Error as e:
            logging.error(f"ERROR: Database query failed - User {chat_id}, Error: {str(e)}")
            return False

    def get_user_greeting(self, chat_id: str) -> str:
        """Возвращает приветственное имя пользователя (имя и отчество)."""
        if not self.conn:
            return "гость"

        try:
            self.cursor.execute("SELECT fio FROM users WHERE chat_id = %s", (chat_id,))
            row = self.cursor.fetchone()
            if not row:
                return "гость"
            fio = row[0].split()
            return " ".join(fio[1:]) if len(fio) >= 2 else fio[0]
        except psycopg2.Error as e:
            logging.error(f"ERROR: Failed to get user greeting - User {chat_id}, Error: {str(e)}")
            return "гость"

    def validate_fio(self, fio: str) -> bool:
        """Валидация ФИО: Фамилия Имя Отчество (кириллица, первая буква заглавная, разрешены дефисы в фамилии)."""
        result = bool(re.match(r"^[А-ЯЁ][а-яё]+(-[А-ЯЁ][а-яё]+)? [А-ЯЁ][а-яё]+ [А-ЯЁ][а-яё]+$", fio))
        if not result:
            logging.warning(f"WARNING: FIO validation failed - FIO: {fio}")
        return result

    def validate_phone(self, phone: str) -> bool:
        """Валидация телефона: формат +7XXXXXXXXXX."""
        result = bool(re.match(r"^\+7\d{10}$", phone))
        if not result:
            logging.warning(f"WARNING: Phone validation failed - Phone: {phone}")
        return result

    def validate_birth_date(self, date_str: str) -> bool:
        """Проверка формата даты рождения: DD.MM.YYYY."""
        # Проверяем формат
        if not re.match(r"^\d{2}\.\d{2}\.\d{4}$", date_str):
            logging.warning(f"WARNING: Birth date validation failed - format - Date: {date_str}")
            return False

        # Проверяем, что дата валидна
        try:
            day, month, year = map(int, date_str.split('.'))
            datetime(year, month, day)
            return True
        except ValueError:
            logging.warning(f"WARNING: Birth date validation failed - invalid date - Date: {date_str}")
            return False

    def register_user(self, chat_id: str, fio: str, phone: str, birth_date: str) -> bool:
        """Регистрирует пользователя в базе данных."""
        if not self.conn:
            return False

        try:
            # Получаем текущую дату и время в формате ГГГГ-ММ-ДД ЧЧ:ММ:СС
            registration_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            insert_query = """
            INSERT INTO users (chat_id, fio, phone, birth_date, registration_date) 
            VALUES (%s, %s, %s, %s, %s)
            """
            self.cursor.execute(insert_query, (chat_id, fio, phone, birth_date, registration_date))
            self.conn.commit()

            logging.info(f"User {chat_id}: user registered in database")
            return True

        except psycopg2.IntegrityError as e:
            logging.error(f"ERROR: User registration failed - duplicate - User {chat_id}, FIO: {fio}, Phone: {phone}")
            self.conn.rollback()
            return False
        except psycopg2.Error as e:
            logging.error(f"ERROR: User registration failed - database error - User {chat_id}, Error: {str(e)}")
            self.conn.rollback()
            return False

    def close_connection(self):
        """Закрывает соединение с базой данных."""
        if self.cursor:
            self.cursor.close()
        if self.conn:
            self.conn.close()
            logging.info("INFO: Соединение с PostgreSQL закрыто.")


# Экземпляр базы, который импортируется в боте
db = UserDatabase()