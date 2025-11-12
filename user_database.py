# user_database.py
import sqlite3
import re
from datetime import datetime


class UserDatabase:
    def __init__(self, db_name="users.db"):
        self.db_name = db_name
        self._init_db()

    def _init_db(self):
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

    def is_user_registered(self, chat_id: str) -> bool:
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM users WHERE chat_id = ?", (chat_id,))
        result = cursor.fetchone()
        conn.close()
        return result is not None

    def get_user_greeting(self, chat_id: str) -> str:
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        cursor.execute("SELECT fio FROM users WHERE chat_id = ?", (chat_id,))
        row = cursor.fetchone()
        conn.close()
        if not row:
            return "гость"
        fio = row[0].split()
        return " ".join(fio[1:]) if len(fio) >= 2 else fio[0]

    def validate_fio(self, fio: str) -> bool:
        # Разрешаем дефисы в фамилии (первом слове)
        return bool(re.match(r"^[А-ЯЁ][а-яё]+(-[А-ЯЁ][а-яё]+)? [А-ЯЁ][а-яё]+ [А-ЯЯЁ][а-яё]+$", fio))

    def validate_phone(self, phone: str) -> bool:
        return bool(re.match(r"^\+7\d{10}$", phone))

    def validate_birth_date(self, date_str: str) -> bool:
        """Проверка формата даты рождения: 13.03.2003"""
        # Проверяем формат
        if not re.match(r"^\d{2}\.\d{2}\.\d{4}$", date_str):
            return False

        # Проверяем, что дата валидна
        try:
            day, month, year = map(int, date_str.split('.'))
            datetime(year, month, day)
            return True
        except ValueError:
            return False

    def register_user(self, chat_id: str, fio: str, phone: str, birth_date: str) -> bool:
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        try:
            # Получаем текущую дату и время в формате ГГГГ-ММ-ДД ЧЧ:ММ:СС
            registration_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            cursor.execute(
                "INSERT INTO users (chat_id, fio, phone, birth_date, registration_date) VALUES (?, ?, ?, ?, ?)",
                (chat_id, fio, phone, birth_date, registration_date)
            )
            conn.commit()
            success = True
        except sqlite3.IntegrityError:
            success = False
        finally:
            conn.close()
        return success


# Экземпляр базы, который импортируется в боте
db = UserDatabase()