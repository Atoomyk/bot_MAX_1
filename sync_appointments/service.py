# sync_appointments/service.py
"""
Основной сервис синхронизации записей к врачу.
"""

import logging
from typing import Dict, Any, Optional
from datetime import datetime

from .fetcher import Fetcher
from .parser import Parser
from .matcher import Matcher
from .database import AppointmentsDatabase
from .notifier import Notifier
from .cancel_service import CancelService

logger = logging.getLogger(__name__)


class SyncService:
    """
    Основной сервис для координации всей синхронизации.
    """

    def __init__(self, user_database, bot_instance, mis_url: str = None):
        """
        Инициализация сервиса синхронизации.

        Args:
            user_database: База данных пользователей
            bot_instance: Экземпляр бота MAX API
            mis_url: URL внешней системы МИС
        """
        self.user_db = user_database
        self.bot = bot_instance
        self.mis_url = mis_url

        # Инициализация компонентов
        self.fetcher = Fetcher(base_url=mis_url)
        self.parser = Parser()
        self.matcher = Matcher(user_database)
        self.appointments_db = AppointmentsDatabase(user_database)
        self.notifier = Notifier(bot_instance, self.appointments_db, user_database)
        self.cancel_service = CancelService()

        self.last_sync_time = None
        self.last_sync_result = None

    async def run_sync(self) -> Dict[str, Any]:
        """
        Запускает полный процесс синхронизации.

        Returns:
            Словарь с результатами синхронизации
        """
        logger.info("=" * 60)
        logger.info("НАЧАЛО СИНХРОНИЗАЦИИ ЗАПИСЕЙ К ВРАЧУ")
        logger.info("=" * 60)

        start_time = datetime.now()

        try:
            # 1. Получение данных из внешней системы
            logger.info("1. Получение данных из внешней системы МИС...")
            raw_data = await self.fetcher.fetch_data()

            if raw_data is None:
                error_msg = "Не удалось получить данные из внешней системы"
                logger.error(error_msg)
                return self._create_error_result(error_msg, start_time)

            # 2. Парсинг данных
            logger.info("2. Парсинг полученных данных...")
            parsed_records = self.parser.parse_response(raw_data)

            if not parsed_records:
                logger.warning("Нет данных для обработки после парсинга")
                return self._create_success_result([], start_time, 0, 0, 0)

            # 3. Сопоставление пациентов с пользователями бота
            logger.info("3. Сопоставление пациентов с пользователями бота...")
            matching_results = self.matcher.batch_match(parsed_records)

            matched_records = matching_results['matched']
            unmatched_records = matching_results['unmatched']

            if not matched_records:
                logger.warning("Не найдено сопоставлений с пользователями бота")
                return self._create_success_result([], start_time,
                                                   len(parsed_records), 0, 0)

            # 4. Сохранение записей в БД и сбор новых записей для уведомлений
            logger.info("4. Сохранение записей в базу данных...")
            user_new_appointments = {}
            total_saved = 0
            skipped_reminders_off = 0
            skipped_already_exists = 0

            for match in matched_records:
                user_id = match['user_id']
                patient_data = match['patient_data']

                # Получаем данные записи
                appointment_data = patient_data['appointment_data']
                metadata = patient_data['metadata']
                visit_time = metadata['visit_time']
                mo_name = metadata['mo_name']

                logger.info(f"Обработка записи для user_id={user_id}, время={visit_time}, МО={mo_name}")

                # Проверяем, включены ли уведомления у пользователя
                reminders_status = self.matcher.get_user_reminders_status(user_id)
                if not reminders_status:
                    logger.warning(f"Уведомления отключены для пользователя {user_id}, запись НЕ БУДЕТ сохранена")
                    skipped_reminders_off += 1
                    continue

                logger.debug(f"Уведомления включены для пользователя {user_id}")

                # Проверяем, не существует ли уже такая запись
                if self.appointments_db.appointment_exists(user_id, visit_time, mo_name):
                    logger.warning(f"Запись уже существует для user_id={user_id}, время={visit_time}, МО={mo_name}")
                    skipped_already_exists += 1
                    continue

                logger.debug(f"Запись не найдена в БД, сохраняем...")

                # Сохраняем запись в БД
                success = self.appointments_db.add_appointment(
                    user_id=user_id,
                    appointment_data=appointment_data,
                    visit_time=visit_time,
                    mo_name=mo_name
                )

                if success:
                    logger.info(f"✓ Запись успешно сохранена для user_id={user_id}")
                    total_saved += 1

                    # Получаем ID сохраненной записи для кнопки отмены
                    db_id = self._get_last_inserted_id(user_id, visit_time, mo_name)

                    # Добавляем в список для уведомлений
                    if user_id not in user_new_appointments:
                        user_new_appointments[user_id] = []

                    # Получаем ВСЕ данные для уведомления (как в force_sync_with_mock)
                    user_new_appointments[user_id].append({
                        # ID записи в БД для кнопки отмены
                        'db_id': db_id,
                        # Данные для отображения
                        'matching_data': patient_data.get('matching_data', {}),
                        'appointment_data': appointment_data,
                        'metadata': metadata,
                        # Добавляем оригинальные поля для простоты доступа
                        'patient_fio': patient_data.get('matching_data', {}).get('full_fio', 'не указано'),
                        'visit_time': visit_time,
                        'mo_name': mo_name,
                        'mo_address': appointment_data.get('Адрес мед учреждения', 'не указано'),
                        'doctor_fio': appointment_data.get('ФИО врача', 'не указано'),
                        'doctor_position': appointment_data.get('Должность врача', 'не указано')
                    })

            # 5. Отправка уведомлений пользователям
            logger.info("5. Отправка уведомлений пользователям...")
            notification_results = None

            if user_new_appointments:
                # Конвертируем user_id из str в int для MAX API
                user_appointments_int = {}
                for user_id_str, appointments in user_new_appointments.items():
                    try:
                        user_id_int = int(user_id_str)
                        user_appointments_int[user_id_int] = appointments
                    except ValueError:
                        logger.error(f"Некорректный user_id: {user_id_str}")
                        continue

                notification_results = await self.notifier.send_batch_notifications(user_appointments_int)
            else:
                logger.info("Нет новых записей для уведомлений")

            # 6. Формирование итогового результата
            logger.info("6. Формирование отчета о синхронизации...")
            result = self._create_success_result(
                parsed_records=parsed_records,
                start_time=start_time,
                total_parsed=len(parsed_records),
                total_matched=len(matched_records),
                total_saved=total_saved,
                unmatched_count=len(unmatched_records),
                notification_results=notification_results
            )

            self.last_sync_time = datetime.now()
            self.last_sync_result = result

            logger.info("=" * 60)
            logger.info("СИНХРОНИЗАЦИЯ УСПЕШНО ЗАВЕРШЕНА")
            logger.info("=" * 60)

            return result

        except Exception as e:
            error_msg = f"Критическая ошибка синхронизации: {e}"
            logger.error(error_msg, exc_info=True)
            return self._create_error_result(error_msg, start_time)

    def _get_last_inserted_id(self, user_id: str, visit_time: datetime, mo_name: str) -> Optional[int]:
        """
        Получает ID последней вставленной записи.

        Args:
            user_id: ID пользователя
            visit_time: Время приема
            mo_name: Название мед учреждения

        Returns:
            ID записи или None
        """
        try:
            query = """
            SELECT id FROM appointments 
            WHERE user_id = %s 
            AND external_visit_time = %s 
            AND external_mo_name = %s
            AND status = 'active'
            ORDER BY created_at DESC
            LIMIT 1
            """
            self.appointments_db.cursor.execute(query, (user_id, visit_time, mo_name))
            row = self.appointments_db.cursor.fetchone()
            return row[0] if row else None
        except Exception as e:
            logger.error(f"Ошибка получения ID записи: {e}")
            return None

    def _create_success_result(self, parsed_records, start_time,
                               total_parsed, total_matched, total_saved,
                               unmatched_count=0, notification_results=None) -> Dict[str, Any]:
        """
        Создает словарь с результатами успешной синхронизации.
        """
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()

        parser_stats = self.parser.get_stats()
        matcher_stats = self.matcher.get_stats()
        notifier_stats = self.notifier.get_stats() if notification_results else {}

        result = {
            'success': True,
            'timestamp': end_time.isoformat(),
            'duration_seconds': duration,
            'summary': {
                'total_received': total_parsed,
                'successfully_parsed': parser_stats.get('processed', 0),
                'parse_errors': parser_stats.get('errors', 0),
                'patients_matched': total_matched,
                'patients_unmatched': unmatched_count,
                'new_appointments_saved': total_saved,
                'match_rate_percent': matcher_stats.get('match_rate', 0),
                'parse_success_rate_percent': parser_stats.get('success_rate', 0)
            },
            'notifications': notifier_stats,
            'components': {
                'parser': parser_stats,
                'matcher': matcher_stats,
                'notifier': notifier_stats
            }
        }

        logger.info(f"РЕЗУЛЬТАТЫ СИНХРОНИЗАЦИИ:")
        logger.info(f"  • Получено записей: {total_parsed}")
        logger.info(f"  • Успешно распаршено: {parser_stats.get('processed', 0)}")
        logger.info(f"  • Найдено пациентов: {total_matched}")
        logger.info(f"  • Сохранено новых записей: {total_saved}")
        logger.info(f"  • Уведомлений отправлено: {notifier_stats.get('sent', 0)}")
        logger.info(f"  • Время выполнения: {duration:.2f} сек")

        return result

    def _create_error_result(self, error_message: str, start_time: datetime) -> Dict[str, Any]:
        """
        Создает словарь с результатами при ошибке синхронизации.
        """
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()

        result = {
            'success': False,
            'timestamp': end_time.isoformat(),
            'duration_seconds': duration,
            'error': error_message,
            'summary': {
                'total_received': 0,
                'successfully_parsed': 0,
                'parse_errors': 0,
                'patients_matched': 0,
                'patients_unmatched': 0,
                'new_appointments_saved': 0
            }
        }

        return result

    async def run_cleanup(self, days_to_keep: int = 365) -> Dict[str, Any]:
        """
        Запускает очистку старых записей.

        Args:
            days_to_keep: Хранить записи не старше этого количества дней

        Returns:
            Результаты очистки
        """
        logger.info("Запуск очистки старых записей...")
        start_time = datetime.now()

        try:
            deleted_count = self.appointments_db.cleanup_old_appointments(days_to_keep)

            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()

            result = {
                'success': True,
                'timestamp': end_time.isoformat(),
                'duration_seconds': duration,
                'deleted_count': deleted_count,
                'days_to_keep': days_to_keep
            }

            logger.info(f"Очистка завершена. Удалено записей: {deleted_count}")
            return result

        except Exception as e:
            logger.error(f"Ошибка очистки старых записей: {e}")

            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()

            return {
                'success': False,
                'timestamp': end_time.isoformat(),
                'duration_seconds': duration,
                'error': str(e),
                'deleted_count': 0
            }

    async def health_check(self) -> Dict[str, Any]:
        """
        Проверяет состояние всех компонентов системы.

        Returns:
            Словарь с результатами проверки
        """
        checks = {
            'external_api': False,
            'database': False,
            'bot_connection': False,
            'overall': False
        }

        try:
            # Проверка внешнего API
            checks['external_api'] = await self.fetcher.health_check()

            # Проверка базы данных
            checks['database'] = self._check_database_connection()

            # Проверка соединения с ботом (упрощенно)
            checks['bot_connection'] = True  # В реальном коде нужно проверить

            # Общая проверка
            checks['overall'] = all([
                checks['external_api'],
                checks['database'],
                checks['bot_connection']
            ])

            logger.debug(f"Health check results: {checks}")

        except Exception as e:
            logger.error(f"Ошибка health check: {e}")

        return checks

    def _check_database_connection(self) -> bool:
        """
        Проверяет подключение к базе данных.
        """
        try:
            if not self.user_db.conn:
                return False

            self.user_db.cursor.execute("SELECT 1")
            return True
        except Exception:
            return False

    def get_status(self) -> Dict[str, Any]:
        """
        Возвращает текущий статус сервиса синхронизации.

        Returns:
            Словарь со статусом
        """
        stats = self.appointments_db.get_stats()

        status = {
            'last_sync_time': self.last_sync_time.isoformat() if self.last_sync_time else None,
            'last_sync_success': self.last_sync_result.get('success') if self.last_sync_result else None,
            'database_stats': stats,
            'components_status': {
                'fetcher': self.fetcher.get_request_info() if hasattr(self.fetcher, 'get_request_info') else {},
                'parser': self.parser.get_stats() if hasattr(self.parser, 'get_stats') else {},
                'matcher': self.matcher.get_stats() if hasattr(self.matcher, 'get_stats') else {},
                'notifier': self.notifier.get_stats() if hasattr(self.notifier, 'get_stats') else {}
            }
        }

        return status

    async def force_sync_with_mock(self, mock_file_path: str) -> Dict[str, Any]:
        """
        Запускает синхронизацию с использованием мок-данных из файла.

        Args:
            mock_file_path: Путь к файлу с тестовыми данными

        Returns:
            Результаты синхронизации
        """
        logger.info(f"Запуск синхронизации с мок-данными из {mock_file_path}")
        start_time = datetime.now()

        try:
            # 1. Читаем файл напрямую
            import json
            import os

            if not os.path.exists(mock_file_path):
                error_msg = f"Файл не найден: {mock_file_path}"
                logger.error(error_msg)
                return self._create_error_result(error_msg, datetime.now())

            with open(mock_file_path, 'r', encoding='utf-8') as f:
                mock_data = json.load(f)

            logger.info(f"Загружено {len(mock_data.get('InformerResult', []))} записей из мок-файла")

            # 2. Парсинг данных (прямо в сервисе)
            logger.info("Парсинг мок-данных...")
            parsed_records = self.parser.parse_response(mock_data)

            if not parsed_records:
                logger.warning("Нет данных для обработки после парсинга мок-файла")
                return self._create_success_result([], datetime.now(), 0, 0, 0)

            # 3. Сопоставление пациентов с пользователями бота
            logger.info("Сопоставление пациентов с пользователями бота...")
            matching_results = self.matcher.batch_match(parsed_records)

            matched_records = matching_results['matched']
            unmatched_records = matching_results['unmatched']

            if not matched_records:
                logger.warning("Не найдено сопоставлений с пользователями бота")
                return self._create_success_result(parsed_records, datetime.now(),
                                                   len(parsed_records), 0, 0)

            # 4. Сохранение записей в БД и сбор новых записей для уведомлений
            logger.info("4. Сохранение записей в базу данных...")
            user_appointments = {}
            total_saved = 0

            for match in matched_records:
                user_id = match['user_id']
                patient_data = match['patient_data']

                # Проверяем, включены ли уведомления у пользователя
                if not self.matcher.get_user_reminders_status(user_id):
                    logger.debug(f"Уведомления отключены для пользователя {user_id}, пропускаем")
                    continue

                # Получаем данные записи
                appointment_data = patient_data['appointment_data']
                metadata = patient_data['metadata']

                # Проверяем, не существует ли уже такая запись
                visit_time = metadata['visit_time']
                mo_name = metadata['mo_name']

                if self.appointments_db.appointment_exists(user_id, visit_time, mo_name):
                    logger.debug(f"Запись уже существует для user_id={user_id}")
                    continue

                # Сохраняем запись в БД
                success = self.appointments_db.add_appointment(
                    user_id=user_id,
                    appointment_data=appointment_data,
                    visit_time=visit_time,
                    mo_name=mo_name
                )

                if success:
                    total_saved += 1

                    # Получаем ID сохраненной записи для кнопки отмены
                    db_id = self._get_last_inserted_id(user_id, visit_time, mo_name)

                    # Подготавливаем данные для уведомления
                    if user_id not in user_appointments:
                        user_appointments[user_id] = []

                    # Получаем ВСЕ данные для уведомления
                    user_appointments[user_id].append({
                        # ID записи в БД для кнопки отмены
                        'db_id': db_id,
                        # Данные для отображения
                        'matching_data': patient_data.get('matching_data', {}),
                        'appointment_data': appointment_data,
                        'metadata': metadata,
                        # Добавляем оригинальные поля для простоты доступа
                        'patient_fio': patient_data.get('matching_data', {}).get('full_fio', 'не указано'),
                        'visit_time': visit_time,
                        'mo_name': mo_name,
                        'mo_address': appointment_data.get('Адрес мед учреждения', 'не указано'),
                        'doctor_fio': appointment_data.get('ФИО врача', 'не указано'),
                        'doctor_position': appointment_data.get('Должность врача', 'не указано')
                    })

            # 5. Отправка уведомлений пользователям
            logger.info("5. Отправка уведомлений пользователям...")
            notification_results = None

            if user_appointments:
                # Конвертируем user_id из str в int для MAX API
                user_appointments_int = {}
                for user_id_str, appointments in user_appointments.items():
                    try:
                        user_id_int = int(user_id_str)
                        user_appointments_int[user_id_int] = appointments
                    except ValueError:
                        logger.error(f"Некорректный user_id: {user_id_str}")
                        continue

                notification_results = await self.notifier.send_batch_notifications(user_appointments_int)
            else:
                logger.info("Нет пользователей для уведомлений")

            # 6. Формируем результат
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()

            parser_stats = self.parser.get_stats()
            matcher_stats = self.matcher.get_stats()
            notifier_stats = self.notifier.get_stats() if notification_results else {}

            result = {
                'success': True,
                'timestamp': end_time.isoformat(),
                'duration_seconds': duration,
                'summary': {
                    'total_received': len(parsed_records),
                    'successfully_parsed': parser_stats.get('processed', 0),
                    'parse_errors': parser_stats.get('errors', 0),
                    'patients_matched': len(matched_records),
                    'patients_unmatched': len(unmatched_records),
                    'new_appointments_saved': total_saved,
                },
                'notifications': notifier_stats
            }

            logger.info(f"МОК-СИНХРОНИЗАЦИЯ ЗАВЕРШЕНА:")
            logger.info(f"  • Обработано записей: {len(parsed_records)}")
            logger.info(f"  • Найдено пациентов: {len(matched_records)}")
            logger.info(f"  • Сохранено записей в БД: {total_saved}")
            logger.info(f"  • Отправлено уведомлений: {notifier_stats.get('sent', 0)}")

            return result

        except json.JSONDecodeError as e:
            error_msg = f"Ошибка чтения JSON файла: {e}"
            logger.error(error_msg)
            return self._create_error_result(error_msg, datetime.now())

        except Exception as e:
            logger.error(f"Ошибка синхронизации с мок-данными: {e}", exc_info=True)
            return self._create_error_result(str(e), datetime.now())