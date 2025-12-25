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
<<<<<<< Updated upstream
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
=======
            create_table_query = """
            CREATE TABLE IF NOT EXISTS users (
                chat_id VARCHAR(255) PRIMARY KEY,
                fio TEXT NOT NULL,
                phone VARCHAR(20) UNIQUE NOT NULL,
                birth_date VARCHAR(10) NOT NULL,
                snils VARCHAR(14),
                oms VARCHAR(16),
                gender VARCHAR(10),
                registration_date TEXT NOT NULL
            );
            """
            self.cursor.execute(create_table_query)

            self._add_column_if_not_exists('birth_date', 'VARCHAR(10)')
            self._add_column_if_not_exists('registration_date', 'TEXT')
            self._add_column_if_not_exists('snils', 'VARCHAR(14)')
            self._add_column_if_not_exists('oms', 'VARCHAR(16)')
            self._add_column_if_not_exists('gender', 'VARCHAR(10)')

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
>>>>>>> Stashed changes
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

<<<<<<< Updated upstream
            conn.commit()
            conn.close()
            logging.info("Bot: Database initialized successfully")
        except Exception as e:
            logging.error(f"ERROR: Database initialization failed - {str(e)}")
            raise
=======
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
    # Получение полных данных пользователя для записи к врачу
    # ---------------------------------------------------------------------
    def get_user_full_data(self, chat_id: str):
        """
        Возвращает dict {fio, birth_date, phone, snils, oms, gender} или None
        """
        try:
            self.cursor.execute(
                "SELECT fio, birth_date, phone, snils, oms, gender FROM users WHERE chat_id = %s",
                (chat_id,)
            )
            row = self.cursor.fetchone()
            if row:
                return {
                    'fio': row[0],
                    'birth_date': row[1],
                    'phone': row[2],
                    'snils': row[3],
                    'oms': row[4],
                    'gender': row[5]
                }
            return None
        except psycopg2.Error as e:
            log_system_event("database", "get_user_full_data_error", error=str(e), chat_id=chat_id)
            return None

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
>>>>>>> Stashed changes

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

<<<<<<< Updated upstream
    def register_user(self, chat_id: str, fio: str, phone: str, birth_date: str) -> bool:
        try:
            conn = sqlite3.connect(self.db_name)
            cursor = conn.cursor()

            # Получаем текущую дату и время в формате ГГГГ-ММ-ДД ЧЧ:ММ:СС
            registration_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            cursor.execute(
                "INSERT INTO users (chat_id, fio, phone, birth_date, registration_date) VALUES (?, ?, ?, ?, ?)",
                (chat_id, fio, phone, birth_date, registration_date)
=======
        today = datetime.today()
        if birth_date > today:
            return False

        age = today.year - birth_date.year - (
            (today.month, today.day) < (birth_date.month, birth_date.day)
        )

        return 18 <= age <= 150

    def validate_snils(self, snils: str) -> bool:
        """Простая проверка формата СНИЛС (11 цифр)"""
        snils_cleaned = re.sub(r'[\s\-]', '', snils)
        return bool(re.match(r"^\d{11}$", snils_cleaned))

    def validate_oms(self, oms: str) -> bool:
        """Простая проверка формата ОМС (16 цифр)"""
        oms_cleaned = re.sub(r'[\s\-]', '', oms)
        return bool(re.match(r"^\d{16}$", oms_cleaned))

    def validate_gender(self, gender: str) -> bool:
        return gender in ["Мужской", "Женский"]

    def get_user_phone(self, chat_id: str) -> str:
        try:
            self.cursor.execute("SELECT phone FROM users WHERE chat_id = %s", (chat_id,))
            row = self.cursor.fetchone()
            return row[0] if row else "Не указан"
        except psycopg2.Error:
            return "Не указан"

    def validate_user_data(self, fio, phone, birth_date, snils=None, oms=None, gender=None):
        base_valid = (
            self.validate_fio(fio)
            and self.validate_phone(phone)
            and self.validate_birth_date(birth_date)
        )
        if snils and not self.validate_snils(snils):
            return False
        if oms and not self.validate_oms(oms):
            return False
        if gender and not self.validate_gender(gender):
            return False
        return base_valid

    def register_user(self, chat_id: str, fio: str, phone: str, birth_date: str, snils: str = None, oms: str = None, gender: str = None) -> bool:
        if not self.validate_user_data(fio, phone, birth_date, snils, oms, gender):
            return False

        try:
            reg_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            phone_cleaned = re.sub(r'[\s\-]', '', phone)
            snils_cleaned = re.sub(r'[\s\-]', '', snils) if snils else None
            oms_cleaned = re.sub(r'[\s\-]', '', oms) if oms else None

            self.cursor.execute(
                """
                INSERT INTO users (chat_id, fio, phone, birth_date, snils, oms, gender, registration_date)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (chat_id, fio, phone_cleaned, birth_date, snils_cleaned, oms_cleaned, gender, reg_date)
>>>>>>> Stashed changes
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