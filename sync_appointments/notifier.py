# sync_appointments/notifier.py
"""
Отправка уведомлений пользователям о новых записях.
Вся информация об записи помещается прямо в сообщение.
"""

import logging
import asyncio
from datetime import datetime
from typing import List, Dict, Any, Optional
from maxapi.utils.inline_keyboard import AttachmentType
from maxapi.types import Attachment, ButtonsPayload, CallbackButton

from .utils import format_appointment_for_user, is_within_allowed_hours

logger = logging.getLogger(__name__)


class Notifier:
    """
    Класс для отправки уведомлений пользователям.
    """

    def __init__(self, bot_instance, appointments_db, user_database):
        """
        Инициализация notifier.

        Args:
            bot_instance: Экземпляр бота MAX API
            appointments_db: Экземпляр базы данных записей
            user_database: Экземпляр базы данных пользователей
        """
        self.bot = bot_instance
        self.appointments_db = appointments_db
        self.user_db = user_database
        self.sent_count = 0
        self.skipped_count = 0
        self.error_count = 0

    async def send_notification(self, user_id: int, appointments: List[Dict[str, Any]]) -> bool:
        """
        Отправляет уведомление пользователю о новых записях.
        Вся информация об записи помещается прямо в сообщение.

        Args:
            user_id: ID пользователя в MAX (chat_id как int)
            appointments: Список новых записей пользователя

        Returns:
            True если уведомление отправлено успешно
        """
        try:
            user_id_str = str(user_id)

            # Проверяем время отправки
            if not is_within_allowed_hours():
                logger.info(f"Пропущена отправка уведомления для {user_id_str} вне разрешенных часов")
                self.skipped_count += 1
                return False

            # Формируем сообщение
            message = self._format_notification_message(appointments)
            if not message:
                logger.warning(f"Не удалось сформировать сообщение для {user_id_str}")
                self.error_count += 1
                return False

            # Получаем chat_id для отправки (адрес доставки)
            chat_id = self.user_db.get_last_chat_id(user_id)
            if not chat_id:
                logger.warning(f"Не найден chat_id для пользователя {user_id}, уведомление не может быть отправлено")
                self.error_count += 1
                return False

            # Создаем клавиатуру только с кнопкой отмены (если есть ID записи)
            keyboard = self._create_notification_keyboard(appointments)

            # Отправляем сообщение
            await self.bot.send_message(
                chat_id=chat_id,
                text=message,
                attachments=[keyboard] if keyboard else []
            )

            self.sent_count += 1
            logger.info(f"Уведомление отправлено пользователю {user_id_str}")
            return True

        except Exception as e:
            self.error_count += 1
            logger.error(f"Ошибка отправки уведомления пользователю {user_id}: {e}")
            return False

    def _format_notification_message(self, appointments: List[Dict[str, Any]]) -> str:
        """
        Форматирует сообщение с уведомлением.
        Включает ВСЮ информацию о записи(ях).

        Args:
            appointments: Список новых записей

        Returns:
            Отформатированное сообщение
        """
        try:
            if not appointments:
                return ""

            if len(appointments) == 1:
                # Одна запись - полная информация
                appointment = appointments[0]

                # Извлекаем данные из appointment_data
                appointment_data = appointment.get('appointment_data', {})
                metadata = appointment.get('metadata', {})
                matching_data = appointment.get('matching_data', {})

                # Данные о пациенте
                patient_fio = matching_data.get('full_fio', 'не указано')

                # Дата и время приема
                visit_time = metadata.get('visit_time')
                if visit_time:
                    date_str = visit_time.strftime('%d.%m.%Y')
                    time_str = visit_time.strftime('%H:%M')
                    datetime_info = f"{date_str} в {time_str}"
                else:
                    datetime_info = "не указано"

                # Информация о мед учреждении
                mo_name = appointment_data.get('Мед учреждение', 'не указано')
                mo_address = appointment_data.get('Адрес мед учреждения', 'не указано')

                # Информация о враче
                doctor_fio = appointment_data.get('ФИО врача', 'не указано')
                doctor_position = appointment_data.get('Должность врача', 'не указано')

                # Формируем полное сообщение
                message = (
                    f"🔔 У вас новая запись к врачу!\n\n"
                    f"👤 Пациент: {patient_fio}\n"
                    f"📅 Дата и время: {datetime_info}\n"
                    f"🏥 Учреждение: {mo_name}\n"
                    f"📍 Адрес: {mo_address}\n"
                    f"👨‍⚕️ Врач: {doctor_fio}\n"
                    f"💼 Должность: {doctor_position}\n"
                )

                # Добавляем ID записи если есть
                if appointment.get('db_id'):
                    message += f"\n📝 ID записи: {appointment['db_id']}"

                message += f"\n\nℹ️ Для отмены записи используйте кнопку ниже."

            else:
                # Несколько записей
                message = "🔔 У вас новые записи к врачу!\n\n"

                for i, appointment in enumerate(appointments, 1):
                    appointment_data = appointment.get('appointment_data', {})
                    metadata = appointment.get('metadata', {})

                    # Дата и время
                    visit_time = metadata.get('visit_time')
                    if visit_time:
                        date_str = visit_time.strftime('%d.%m.%Y')
                        time_str = visit_time.strftime('%H:%M')
                        datetime_info = f"{date_str} {time_str}"
                    else:
                        datetime_info = "не указано"

                    # Учреждение и врач
                    mo_name = appointment_data.get('Мед учреждение', 'не указано')
                    doctor_fio = appointment_data.get('ФИО врача', 'не указано')

                    message += f"📅 Запись #{i}:\n"
                    message += f"   Дата/время: {datetime_info}\n"
                    message += f"   Учреждение: {mo_name}\n"
                    message += f"   Врач: {doctor_fio}\n"

                    # Добавляем ID если есть
                    if appointment.get('db_id'):
                        message += f"   ID: {appointment['db_id']}\n"

                    message += "\n"

            return message

        except Exception as e:
            logger.error(f"Ошибка форматирования сообщения: {e}")
            return "У вас новые записи к врачу. Для получения информации обратитесь в регистратуру."

    def _create_notification_keyboard(self, appointments: List[Dict[str, Any]]) -> Optional[Attachment]:
        """
        Создает клавиатуру только с кнопкой отмены записи.
        Показывается только если есть ID записи в БД и запись активна.

        Args:
            appointments: Список новых записей

        Returns:
            Объект Attachment с клавиатурой или None
        """
        try:
            if not appointments:
                return None

            # Проверяем, есть ли ID записи в БД
            has_db_id = any(appointment.get('db_id') for appointment in appointments)

            if not has_db_id:
                logger.debug("Нет ID записей в БД, кнопка отмены не показывается")
                return None

            buttons = []

            # Создаем кнопку отмены для каждой записи с ID
            active_appointments_count = 0
            for appointment in appointments:
                appointment_id = appointment.get('db_id')
                if not appointment_id:
                    continue
                
                # Проверяем статус записи, если appointments_db доступен
                if self.appointments_db:
                    try:
                        appointment_info = self.appointments_db.get_appointment_by_id_with_status(appointment_id)
                        if appointment_info and appointment_info.get('status') != 'active':
                            logger.debug(f"Запись {appointment_id} не активна, кнопка отмены не показывается")
                            continue
                    except Exception as e:
                        logger.warning(f"Не удалось проверить статус записи {appointment_id}: {e}")
                        # Продолжаем, если не удалось проверить статус
                
                active_appointments_count += 1
                
                # Формируем текст кнопки в зависимости от количества активных записей
                if active_appointments_count == 1 and len(appointments) == 1:
                    button_text = "❌ Отменить запись"
                else:
                    # Для нескольких записей добавляем номер записи
                    # Используем порядковый номер из списка appointments
                    appointment_index = appointments.index(appointment) + 1
                    button_text = f"❌ Отменить запись #{appointment_index}"
                
                buttons.append([
                    CallbackButton(
                        text=button_text,
                        payload=f"cancel_appointment:{appointment_id}"
                    )
                ])

            if not buttons:
                return None

            buttons_payload = ButtonsPayload(buttons=buttons)
            return Attachment(
                type=AttachmentType.INLINE_KEYBOARD,
                payload=buttons_payload
            )

        except Exception as e:
            logger.error(f"Ошибка создания клавиатуры: {e}")
            return None

    async def send_batch_notifications(self, user_appointments: Dict[int, List[Dict[str, Any]]]) -> Dict[str, Any]:
        """
        Отправляет пакет уведомлений нескольким пользователям.

        Args:
            user_appointments: Словарь {user_id: [appointments]}

        Returns:
            Статистика отправки
        """
        results = {
            'total_users': len(user_appointments),
            'sent': 0,
            'skipped': 0,
            'errors': 0,
            'details': {}
        }

        tasks = []

        for user_id, appointments in user_appointments.items():
            task = asyncio.create_task(self._send_single_with_stats(user_id, appointments, results))
            tasks.append(task)

        # Ждем завершения всех задач
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        results['sent'] = self.sent_count
        results['skipped'] = self.skipped_count
        results['errors'] = self.error_count

        logger.info(f"Пакетная отправка завершена: отправлено {self.sent_count}, "
                    f"пропущено {self.skipped_count}, ошибок {self.error_count}")

        return results

    async def _send_single_with_stats(self, user_id: int, appointments: List[Dict[str, Any]],
                                      results: Dict[str, Any]) -> None:
        """
        Отправляет уведомление одному пользователю и записывает статистику.
        """
        try:
            success = await self.send_notification(user_id, appointments)

            if success:
                results['details'][str(user_id)] = 'sent'
            else:
                # Проверяем, была ли ошибка или пропуск по времени
                current_hour = datetime.now().hour
                if 21 <= current_hour or current_hour < 8:
                    results['details'][str(user_id)] = 'skipped_time'
                else:
                    results['details'][str(user_id)] = 'error'

        except Exception as e:
            results['details'][str(user_id)] = f'error: {str(e)}'
            logger.error(f"Ошибка при отправке уведомления пользователю {user_id}: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """
        Возвращает статистику отправки уведомлений.

        Returns:
            Словарь со статистикой
        """
        return {
            'sent': self.sent_count,
            'skipped': self.skipped_count,
            'errors': self.error_count,
            'total_attempted': self.sent_count + self.skipped_count + self.error_count
        }