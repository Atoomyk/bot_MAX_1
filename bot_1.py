# bot_1.py
"""Главный файл запуска бота"""
import asyncio

from bot_config import (
    bot, dp, WEBHOOK_MODE, WEBHOOK_PORT,
    init_sync_service, reminder_handler
)
import bot_config
# Импортируем обработчики для регистрации
import bot_handlers
from bot_utils import (
    setup_webhook, keepalive_worker, chat_cleanup_worker,
    notification_worker, booking_states_cleanup_worker,
    stop_all_tasks, send_other_options_menu
)
from logging_config import log_system_event

# Устанавливаем функцию для reminder_handler
reminder_handler.send_other_options_menu = send_other_options_menu


async def main():
    """Главная функция запуска бота"""
    global keepalive_task, chat_cleanup_task, booking_cleanup_task

    log_system_event("bot", "starting", webhook_mode=WEBHOOK_MODE, port=WEBHOOK_PORT)

    # Инициализация сервиса синхронизации
    init_sync_service()

    # Запуск планировщика задач синхронизации
    if bot_config.scheduler_manager:
        scheduler_started = bot_config.scheduler_manager.start_scheduler()
        if scheduler_started:
            log_system_event("sync", "scheduler_started")
        else:
            log_system_event("sync", "scheduler_failed")
    else:
        log_system_event("sync", "scheduler_skipped", reason="Service not initialized")

    # Запускаем фоновые задачи
    keepalive_task = asyncio.create_task(keepalive_worker())
    log_system_event("keepalive", "worker_started")

    chat_cleanup_task = asyncio.create_task(chat_cleanup_worker())
    log_system_event("chat_cleanup", "worker_started")

    booking_cleanup_task = asyncio.create_task(booking_states_cleanup_worker())
    log_system_event("booking_cleanup", "worker_started")

    notification_task = asyncio.create_task(notification_worker())
    log_system_event("notification", "worker_started")

    # Настраиваем вебхук
    webhook_success = await setup_webhook()

    if not webhook_success:
        log_system_event("bot", "webhook_setup_failed")
        await stop_all_tasks(keepalive_task, chat_cleanup_task, booking_cleanup_task, notification_task)
        return

    log_system_event("bot", "webhook_server_starting", port=WEBHOOK_PORT)

    try:
        # Запускаем вебхук сервер
        if WEBHOOK_MODE == "direct":
            await dp.handle_webhook(
                bot=bot,
                host='0.0.0.0',
                port=WEBHOOK_PORT,
                log_level='info'
            )
        else:
            await dp.handle_webhook(
                bot=bot,
                host='0.0.0.0',
                port=80,
                log_level='info'
            )
    finally:
        # Останавливаем все задачи при завершении работы
        await stop_all_tasks(keepalive_task, chat_cleanup_task, booking_cleanup_task, notification_task)

        # Останавливаем планировщик синхронизации
        if bot_config.scheduler_manager:
            await bot_config.scheduler_manager.wait_for_scheduler()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log_system_event("bot", "stopped_manually")
    except Exception as e:
        log_system_event("bot", "crashed", error=str(e))
        raise
