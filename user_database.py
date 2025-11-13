# user_database.py
import sqlite3
import re
import logging
from datetime import datetime


class UserDatabase:
    def __init__(self, db_name="users.db"):
        self.db_name = db_name
        self._init_db()

    def _init_db(self):
        try:
            conn = sqlite3.connect(self.db_name)
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    chat_id TEXT PRIMARY KEY,
                    fio TEXT NOT NULL,
                    phone TEXT UNIQUE NOT NULL,
                    birth_date TEXT NOT NULL,
                    registration_date TEXT NOT NULL
                )
            """)

            # Миграция: добавляем поле birth_date если его нет
            try:
                cursor.execute("ALTER TABLE users ADD COLUMN birth_date TEXT")
            except sqlite3.OperationalError:
                # Поле уже существует
                pass

            # Миграция: добавляем поле registration_date если его нет
            try:
                cursor.execute("ALTER TABLE users ADD COLUMN registration_date TEXT")
            except sqlite3.OperationalError:
                # Поле уже существует
                pass

            conn.commit()
            conn.close()
            logging.info("Bot: Database initialized successfully")
        except Exception as e:
            logging.error(f"ERROR: Database initialization failed - {str(e)}")
            raise

    def is_user_registered(self, chat_id: str) -> bool:
        try:
            conn = sqlite3.connect(self.db_name)
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM users WHERE chat_id = ?", (chat_id,))
            result = cursor.fetchone()
            conn.close()
            return result is not None
        except Exception as e:
            logging.error(f"ERROR: Database query failed - User {chat_id}, Error: {str(e)}")
            return False

    def get_user_greeting(self, chat_id: str) -> str:
        try:
            conn = sqlite3.connect(self.db_name)
            cursor = conn.cursor()
            cursor.execute("SELECT fio FROM users WHERE chat_id = ?", (chat_id,))
            row = cursor.fetchone()
            conn.close()
            if not row:
                return "гость"
            fio = row[0].split()
            return " ".join(fio[1:]) if len(fio) >= 2 else fio[0]
        except Exception as e:
            logging.error(f"ERROR: Failed to get user greeting - User {chat_id}, Error: {str(e)}")
            return "гость"

    def validate_fio(self, fio: str) -> bool:
        # Разрешаем дефисы в фамилии (первом слове)
        result = bool(re.match(r"^[А-ЯЁ][а-яё]+(-[А-ЯЁ][а-яё]+)? [А-ЯЁ][а-яё]+ [А-ЯЯЁ][а-яё]+$", fio))
        if not result:
            logging.warning(f"WARNING: FIO validation failed - FIO: {fio}")
        return result

    def validate_phone(self, phone: str) -> bool:
        result = bool(re.match(r"^\+7\d{10}$", phone))
        if not result:
            logging.warning(f"WARNING: Phone validation failed - Phone: {phone}")
        return result

    def validate_birth_date(self, date_str: str) -> bool:
        """Проверка формата даты рождения: 13.03.2003"""
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
        try:
            conn = sqlite3.connect(self.db_name)
            cursor = conn.cursor()

            # Получаем текущую дату и время в формате ГГГГ-ММ-ДД ЧЧ:ММ:СС
            registration_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            cursor.execute(
                "INSERT INTO users (chat_id, fio, phone, birth_date, registration_date) VALUES (?, ?, ?, ?, ?)",
                (chat_id, fio, phone, birth_date, registration_date)
            )
            conn.commit()
            conn.close()

            logging.info(f"User {chat_id}: user registered in database")
            return True

        except sqlite3.IntegrityError as e:
            logging.error(f"ERROR: User registration failed - duplicate - User {chat_id}, FIO: {fio}, Phone: {phone}")
            return False
        except Exception as e:
            logging.error(f"ERROR: User registration failed - database error - User {chat_id}, Error: {str(e)}")
            return False
        finally:
            try:
                conn.close()
            except:
                pass


# Экземпляр базы, который импортируется в боте
db = UserDatabase()