# commands/sync_command.py
"""
Обработчик команды /admin_sync для ручного запуска синхронизации.
"""

import logging
from typing import Optional, Dict, Any
from maxapi.types import MessageCreated

from sync_appointments.service import SyncService

logger = logging.getLogger(__name__)


class SyncCommandHandler:
    """
    Обработчик админских команд для управления синхронизацией.
    """

    def __init__(self, sync_service: SyncService, admin_id: int):
        """
        Инициализация обработчика команд.

        Args:
            sync_service: Сервис синхронизации
            admin_id: ID администратора
        """
        self.sync_service = sync_service
        self.admin_id = admin_id
        self.is_syncing = False

    async def handle_message(self, event: MessageCreated) -> bool:
        """
        Обрабатывает сообщение, проверяя админские команды.
        """
        try:

            # Используем chat_id из recipient
            chat_id = event.message.recipient.chat_id

            # Проверяем, что это сообщение от администратора (по chat_id)
            if chat_id != self.admin_id:
                return False

            # Проверяем наличие текста сообщения
            if not event.message.body or not event.message.body.text:
                return False

            message_text = event.message.body.text.strip()

            # Обработка команд
            if message_text == "/admin_sync":
                await self._handle_sync_command(event)
                return True

            elif message_text == "/admin_sync_status":
                await self._handle_status_command(event)
                return True

            elif message_text == "/admin_sync_cleanup":
                await self._handle_cleanup_command(event)
                return True

            elif message_text == "/admin_sync_stats":
                await self._handle_stats_command(event)
                return True

            elif message_text.startswith("/admin_sync_mock"):
                await self._handle_mock_command(event, message_text)
                return True

            print(f"SYNC COMMAND DEBUG: Неизвестная команда")
            return False

        except Exception as e:
            print(f"SYNC COMMAND DEBUG: Ошибка: {e}")
            import traceback
            traceback.print_exc()
            return False


    async def _handle_sync_command(self, event: MessageCreated) -> None:
        """
        Обрабатывает команду /admin_sync.
        """
        try:
            if self.is_syncing:
                await event.bot.send_message(
                    chat_id=event.message.recipient.chat_id,
                    text="⏳ Синхронизация уже выполняется. Пожалуйста, подождите."
                )
                return

            self.is_syncing = True

            # Отправляем сообщение о начале
            await event.bot.send_message(
                chat_id=event.message.recipient.chat_id,
                text="🔄 Запуск ручной синхронизации записей к врачу..."
            )

            # Запускаем синхронизацию
            result = await self.sync_service.run_sync()

            # Формируем отчет
            if result.get('success'):
                summary = result.get('summary', {})
                message = (
                    "✅ Синхронизация завершена успешно!\n\n"
                    f"📊 Результаты:\n"
                    f"• Получено записей: {summary.get('total_received', 0)}\n"
                    f"• Успешно обработано: {summary.get('successfully_parsed', 0)}\n"
                    f"• Найдено пациентов: {summary.get('patients_matched', 0)}\n"
                    f"• Сохранено новых записей: {summary.get('new_appointments_saved', 0)}\n"
                    f"• Время выполнения: {result.get('duration_seconds', 0):.2f} сек\n\n"
                    f"⏰ Время завершения: {result.get('timestamp', 'неизвестно')}"
                )
            else:
                message = (
                    "❌ Синхронизация завершена с ошибкой!\n\n"
                    f"Ошибка: {result.get('error', 'Неизвестная ошибка')}\n"
                    f"Время выполнения: {result.get('duration_seconds', 0):.2f} сек"
                )

            await event.bot.send_message(
                chat_id=event.message.recipient.chat_id,
                text=message
            )

        except Exception as e:
            logger.error(f"Ошибка выполнения команды /admin_sync: {e}")
            await event.bot.send_message(
                chat_id=event.message.recipient.chat_id,
                text=f"❌ Произошла ошибка при выполнении синхронизации: {str(e)}"
            )
        finally:
            self.is_syncing = False

    async def _handle_status_command(self, event: MessageCreated) -> None:
        """
        Обрабатывает команду /admin_sync_status.
        """
        try:
            status = self.sync_service.get_status()

            last_sync = status.get('last_sync_time', 'никогда')
            last_success = "✅ успешно" if status.get('last_sync_success') else "❌ с ошибкой" if status.get(
                'last_sync_success') is False else "неизвестно"

            db_stats = status.get('database_stats', {})

            message = (
                "📊 Статус системы синхронизации:\n\n"
                f"🕐 Последняя синхронизация: {last_sync}\n"
                f"📈 Результат: {last_sync}\n\n"
                f"🗃️ База данных записей:\n"
                f"• Всего записей: {db_stats.get('total_appointments', 0)}\n"
                f"• Уникальных пользователей: {db_stats.get('unique_users', 0)}\n"
                f"• Последнее обновление: {db_stats.get('last_sync', 'неизвестно')}"
            )

            await event.bot.send_message(
                chat_id=event.message.recipient.chat_id,
                text=message
            )

        except Exception as e:
            logger.error(f"Ошибка выполнения команды /admin_sync_status: {e}")
            await event.bot.send_message(
                chat_id=event.message.recipient.chat_id,
                text=f"❌ Ошибка получения статуса: {str(e)}"
            )

    async def _handle_cleanup_command(self, event: MessageCreated) -> None:
        """
        Обрабатывает команду /admin_sync_cleanup.
        """
        try:
            await event.bot.send_message(
                chat_id=event.message.recipient.chat_id,
                text="🗑️ Запуск очистки старых записей (старше 1 года)..."
            )

            result = await self.sync_service.run_cleanup(days_to_keep=365)

            if result.get('success'):
                message = (
                    "✅ Очистка завершена успешно!\n\n"
                    f"🗑️ Удалено записей: {result.get('deleted_count', 0)}\n"
                    f"⏱️ Время выполнения: {result.get('duration_seconds', 0):.2f} сек"
                )
            else:
                message = (
                    "❌ Очистка завершена с ошибкой!\n\n"
                    f"Ошибка: {result.get('error', 'Неизвестная ошибка')}"
                )

            await event.bot.send_message(
                chat_id=event.message.recipient.chat_id,
                text=message
            )

        except Exception as e:
            logger.error(f"Ошибка выполнения команды /admin_sync_cleanup: {e}")
            await event.bot.send_message(
                chat_id=event.message.recipient.chat_id,
                text=f"❌ Ошибка очистки: {str(e)}"
            )

    async def _handle_stats_command(self, event: MessageCreated) -> None:
        """
        Обрабатывает команду /admin_sync_stats.
        """
        try:
            status = self.sync_service.get_status()
            components = status.get('components_status', {})

            message = "📈 Детальная статистика компонентов:\n\n"

            # Статистика парсера
            parser_stats = components.get('parser', {})
            if parser_stats:
                message += "📝 Парсер:\n"
                message += f"• Обработано: {parser_stats.get('processed', 0)}\n"
                message += f"• Ошибок: {parser_stats.get('errors', 0)}\n"
                message += f"• Успешность: {parser_stats.get('success_rate', 0):.1f}%\n\n"

            # Статистика матчера
            matcher_stats = components.get('matcher', {})
            if matcher_stats:
                message += "🔍 Матчер:\n"
                message += f"• Найдено: {matcher_stats.get('matched', 0)}\n"
                message += f"• Не найдено: {matcher_stats.get('unmatched', 0)}\n"
                message += f"• Успешность: {matcher_stats.get('match_rate', 0):.1f}%\n\n"

            # Статистика нотификатора
            notifier_stats = components.get('notifier', {})
            if notifier_stats:
                message += "🔔 Нотификатор:\n"
                message += f"• Отправлено: {notifier_stats.get('sent', 0)}\n"
                message += f"• Пропущено: {notifier_stats.get('skipped', 0)}\n"
                message += f"• Ошибок: {notifier_stats.get('errors', 0)}\n"

            await event.bot.send_message(
                chat_id=event.message.recipient.chat_id,
                text=message
            )

        except Exception as e:
            logger.error(f"Ошибка выполнения команды /admin_sync_stats: {e}")
            await event.bot.send_message(
                chat_id=event.message.recipient.chat_id,
                text=f"❌ Ошибка получения статистики: {str(e)}"
            )

    async def _handle_mock_command(self, event: MessageCreated, message_text: str) -> None:
        """
        Обрабатывает команду /admin_sync_mock [путь_к_файлу].
        """
        try:
            # Извлекаем путь к файлу из команды
            parts = message_text.split()
            if len(parts) < 2:
                await event.bot.send_message(
                    chat_id=event.message.recipient.chat_id,
                    text="❌ Укажите путь к мок-файлу: /admin_sync_mock [путь_к_файлу]"
                )
                return

            mock_file_path = parts[1]

            if self.is_syncing:
                await event.bot.send_message(
                    chat_id=event.message.recipient.chat_id,
                    text="⏳ Синхронизация уже выполняется. Пожалуйста, подождите."
                )
                return

            self.is_syncing = True

            await event.bot.send_message(
                chat_id=event.message.recipient.chat_id,
                text=f"🧪 Запуск тестовой синхронизации с мок-данными из {mock_file_path}..."
            )

            # Запускаем тестовую синхронизацию
            result = await self.sync_service.force_sync_with_mock(mock_file_path)

            # Формируем отчет
            if result.get('success'):
                summary = result.get('summary', {})
                message = (
                    "🧪 Тестовая синхронизация завершена!\n\n"
                    f"📊 Результаты:\n"
                    f"• Получено записей: {summary.get('total_received', 0)}\n"
                    f"• Успешно обработано: {summary.get('successfully_parsed', 0)}\n"
                    f"• Найдено пациентов: {summary.get('patients_matched', 0)}\n"
                    f"• Сохранено новых записей: {summary.get('new_appointments_saved', 0)}\n"
                    f"• Время выполнения: {result.get('duration_seconds', 0):.2f} сек"
                )
            else:
                message = (
                    "❌ Тестовая синхронизация завершена с ошибкой!\n\n"
                    f"Ошибка: {result.get('error', 'Неизвестная ошибка')}"
                )

            await event.bot.send_message(
                chat_id=event.message.recipient.chat_id,
                text=message
            )

        except Exception as e:
            logger.error(f"Ошибка выполнения команды /admin_sync_mock: {e}")
            await event.bot.send_message(
                chat_id=event.message.recipient.chat_id,
                text=f"❌ Ошибка тестовой синхронизации: {str(e)}"
            )
        finally:
            self.is_syncing = False

    async def handle_callback(self, event, payload: str) -> bool:
        """
        Обрабатывает callback-и от кнопок уведомлений.

        Args:
            event: Событие callback
            payload: Данные callback

        Returns:
            True если callback обработан, False если нет
        """
        try:
            chat_id = event.message.recipient.chat_id

            # Пропускаем, если не от администратора
            if chat_id != self.admin_id:
                return False

            # Обработка callback-ов администратора для управления синхронизацией
            if payload.startswith("sync_"):
                action = payload.split(":")[0] if ":" in payload else payload

                if action == "sync_start":
                    await self._handle_sync_command(event)
                    return True
                elif action == "sync_status":
                    await self._handle_status_command(event)
                    return True
                elif action == "sync_cleanup":
                    await self._handle_cleanup_command(event)
                    return True

            return False

        except Exception as e:
            logger.error(f"Ошибка обработки callback: {e}")
            return False