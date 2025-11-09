# user_database.py
import sqlite3
import re

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
                phone TEXT UNIQUE NOT NULL
            )
        """)
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
        return bool(re.match(r"^[А-ЯЁ][а-яё]+ [А-ЯЁ][а-яё]+ [А-ЯЁ][а-яё]+$", fio))

    def validate_phone(self, phone: str) -> bool:
        return bool(re.match(r"^\+7\d{10}$", phone))

    def register_user(self, chat_id: str, fio: str, phone: str) -> bool:
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO users (chat_id, fio, phone) VALUES (?, ?, ?)",
                (chat_id, fio, phone)
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
