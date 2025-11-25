# user_database.py
import os
import re
import logging
from datetime import datetime
import psycopg2
from dotenv import load_dotenv

# Настройка логгирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

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
            if self.conn:
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
                # Безопасное добавление колонки
                add_column_query = "ALTER TABLE users ADD COLUMN {} {}".format(
                    column_name, column_type
                )
                self.cursor.execute(add_column_query)
                logging.info(f"INFO: Добавлена колонка {column_name} в таблицу users.")
        except psycopg2.Error as e:
            logging.error(f"ERROR: Ошибка при добавлении колонки {column_name}: {e}")
            if self.conn:
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
        # Убираем лишние пробелы
        fio_cleaned = ' '.join(fio.split())
        result = bool(re.match(r"^[А-ЯЁ][а-яё]+(-[А-ЯЁ][а-яё]+)? [А-ЯЁ][а-яё]+ [А-ЯЁ][а-яё]+$", fio_cleaned))
        if not result:
            logging.warning(f"WARNING: FIO validation failed - FIO: {fio}")
        return result

    def validate_phone(self, phone: str) -> bool:
        """Валидация телефона: формат +7XXXXXXXXXX."""
        # Убираем все пробелы и дефисы
        phone_cleaned = re.sub(r'[\s\-]', '', phone)
        result = bool(re.match(r"^\+7\d{10}$", phone_cleaned))
        if not result:
            logging.warning(f"WARNING: Phone validation failed - Phone: {phone}")
        return result

    def validate_birth_date(self, date_str: str) -> bool:
        """Проверка формата даты рождения: DD.MM.YYYY и возраст 18–150 лет."""
        # Проверяем формат
        if not re.match(r"^\d{2}\.\d{2}\.\d{4}$", date_str):
            logging.warning(f"WARNING: Birth date validation failed - format - Date: {date_str}")
            return False

        try:
            day, month, year = map(int, date_str.split('.'))
            birth_date = datetime(year, month, day)
        except ValueError:
            logging.warning(f"WARNING: Birth date validation failed - invalid date - Date: {date_str}")
            return False

        # Проверяем, что дата не в будущем
        today = datetime.today()
        if birth_date > today:
            logging.warning(f"WARNING: Birth date validation failed - future date - Date: {date_str}")
            return False

        # Проверяем возраст
        age = today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))

        if age < 18 or age > 150:
            logging.warning(f"WARNING: Birth date validation failed - age out of range ({age}) - Date: {date_str}")
            return False

        return True

    def get_user_phone(self, chat_id: str) -> str:
        """Получить телефон пользователя по chat_id"""
        if not self.conn:
            return "Не указан"

        try:
            self.cursor.execute("SELECT phone FROM users WHERE chat_id = %s", (chat_id,))
            result = self.cursor.fetchone()
            return result[0] if result else "Не указан"
        except psycopg2.Error as e:
            logging.error(f"ERROR: Ошибка получения телефона: {e}")
            return "Не указан"

    def validate_user_data(self, fio: str, phone: str, birth_date: str) -> bool:
        """Проверяет все данные пользователя перед регистрацией."""
        return (self.validate_fio(fio) and
                self.validate_phone(phone) and
                self.validate_birth_date(birth_date))

    def register_user(self, chat_id: str, fio: str, phone: str, birth_date: str) -> bool:
        """Регистрирует пользователя в базе данных."""
        if not self.conn:
            return False

        # Проверяем валидность данных перед регистрацией
        if not self.validate_user_data(fio, phone, birth_date):
            logging.error(f"ERROR: User registration failed - invalid data - User {chat_id}")
            return False

        try:
            # Получаем текущую дату и время в формате ГГГГ-ММ-ДД ЧЧ:ММ:СС
            registration_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # Очищаем телефон от пробелов и дефисов
            phone_cleaned = re.sub(r'[\s\-]', '', phone)

            insert_query = """
            INSERT INTO users (chat_id, fio, phone, birth_date, registration_date) 
            VALUES (%s, %s, %s, %s, %s)
            """
            self.cursor.execute(insert_query, (chat_id, fio, phone_cleaned, birth_date, registration_date))
            self.conn.commit()

            logging.info(f"INFO: User {chat_id}: user registered in database")
            return True

        except psycopg2.IntegrityError as e:
            logging.error(f"ERROR: User registration failed - duplicate - User {chat_id}, FIO: {fio}, Phone: {phone}")
            if self.conn:
                self.conn.rollback()
            return False
        except psycopg2.Error as e:
            logging.error(f"ERROR: User registration failed - database error - User {chat_id}, Error: {str(e)}")
            if self.conn:
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