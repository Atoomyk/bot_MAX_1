# bot_handlers.py
"""Обработчики событий бота"""
import time
from maxapi.types import BotStarted, MessageCallback, MessageCreated

from bot_config import (
    bot, dp, db, user_states, processed_events,
    sync_service, sync_command_handler, ADMIN_ID,
    registration_handler, reminder_handler, support_handler
)
from bot_utils import (
    anti_duplicate, cleanup_processed_events, create_keyboard,
    send_main_menu, send_other_options_menu
)
from logging_config import log_user_event, log_system_event, log_security_event


# --- ОБРАБОТЧИКИ СОБЫТИЙ ---

@dp.bot_started()
@anti_duplicate()
async def bot_started(event: BotStarted):
    """Обработка запуска бота"""
    chat_id = event.chat_id
    chat_id_str = str(chat_id)

    log_user_event(chat_id_str, "bot_started")

    current_time = time.time()
    last_bot_start = processed_events.get(chat_id_str, {}).get('last_bot_start', 0)

    if current_time - last_bot_start < 30:
        log_user_event(chat_id_str, "bot_started_ignored_duplicate")
        return

    if chat_id_str not in processed_events:
        processed_events[chat_id_str] = {}
    processed_events[chat_id_str]['last_bot_start'] = current_time

    try:
        if db.is_user_registered(chat_id_str):
            greeting_name = db.get_user_greeting(chat_id_str)
            log_user_event(chat_id_str, "already_registered")
        else:
            log_user_event(chat_id_str, "new_user_detected")
            keyboard = create_keyboard([[
                {'type': 'callback', 'text': 'Продолжить', 'payload': "start_continue"}
            ]])

            await event.bot.send_message(
                chat_id=chat_id,
                text='Здравствуйте! 👩‍⚕️\n\nВы обратились в Медицинский информационно-аналитический центр города Севастополя.\nНаша система позволяет Вам удобно и быстро решить следующие задачи:\n\n📌 Записаться на приём к врачу;\n📌 Вызвать врача на дом;\n📌 Записаться на профилактический медосмотр/диспансеризацию;\n📌 Прикрепиться к поликлинике;\n📌 Получать уведомления о записи к врачу с возможностью её отмены;\n📌 Найти ближайшие государственные медицинские учреждения.',
                attachments=[keyboard] if keyboard else []
            )
    except Exception as e:
        log_system_event("bot_started", "message_send_failed", error=str(e), chat_id=chat_id_str)


@dp.message_callback()
@anti_duplicate()
async def message_callback(event: MessageCallback):
    """Обработка нажатий на инлайн-кнопки"""
    try:
        if len(processed_events) > 1000:
            cleanup_processed_events()

        chat_id = event.message.recipient.chat_id
        chat_id_str = str(chat_id)
        payload = event.callback.payload

        log_user_event(chat_id_str, "button_pressed", payload=payload)

        # Обработка callback-ов для записей к врачу
        if payload.startswith("view_appointment:"):
            try:
                appointment_id = int(payload.split(":")[1])
                log_user_event(chat_id_str, "appointment_details_viewed", appointment_id=appointment_id)
                if sync_service and sync_service.notifier:
                    await sync_service.notifier.send_appointment_details(chat_id, appointment_id)
                else:
                    await event.bot.send_message(
                        chat_id=chat_id,
                        text="Сервис записей временно недоступен. Пожалуйста, попробуйте позже."
                    )
            except (ValueError, IndexError):
                log_system_event("appointment_view_error", "invalid_appointment_id", payload=payload, chat_id=chat_id_str)
                await event.bot.send_message(
                    chat_id=chat_id,
                    text="Ошибка при обработке запроса. Пожалуйста, попробуйте еще раз."
                )
            return

        elif payload == "view_appointments_list":
            log_user_event(chat_id_str, "appointments_list_viewed")
            if sync_service and sync_service.notifier:
                await sync_service.notifier.send_appointments_list(chat_id)
            else:
                await event.bot.send_message(
                    chat_id=chat_id,
                    text="Сервис записей временно недоступен. Пожалуйста, попробуйте позже."
                )
            return

        elif payload.startswith("cancel_appointment:"):
            log_user_event(chat_id_str, "appointment_cancel_attempted", payload=payload)
            if payload == "cancel_appointment:stub":
                await event.bot.send_message(
                    chat_id=chat_id,
                    text="⏳ Функция отмены записи в настоящее время недоступна.\n\n"
                         "Для отмены записи обратитесь в регистратуру медицинского учреждения "
                         "или воспользуйтесь порталом Госуслуги."
                )
            return

        # Обработка админских callback для синхронизации
        if sync_command_handler and chat_id == ADMIN_ID:
            if payload.startswith("sync_"):
                log_system_event("admin_callback", "sync_callback_received", payload=payload, chat_id=chat_id_str)
                handled = await sync_command_handler.handle_callback(event, payload)
                if handled:
                    log_system_event("admin_callback", "sync_callback_handled", payload=payload, chat_id=chat_id_str)
                    return

        # Обработка callback-ов регистрации
        if payload == "start_continue":
            log_user_event(chat_id_str, "registration_start_clicked")
            await registration_handler.send_agreement_message(event.bot, chat_id)

        elif payload == "agreement_accepted":
            log_security_event(chat_id_str, "consent_accepted")
            await registration_handler.start_registration_process(event.bot, chat_id)

        elif payload == "confirm_phone":
            log_user_event(chat_id_str, "phone_confirmed")
            await registration_handler.handle_phone_confirmation(event.bot, chat_id_str, chat_id)

        elif payload == "reject_phone":
            log_user_event(chat_id_str, "phone_rejected")
            await registration_handler.handle_incorrect_phone(event.bot, chat_id)

        elif payload == "correct_fio":
            log_user_event(chat_id_str, "fio_correction_requested")
            await registration_handler.handle_data_correction(event.bot, chat_id_str, chat_id, 'fio')

        elif payload == "correct_birth_date":
            log_user_event(chat_id_str, "birth_date_correction_requested")
            await registration_handler.handle_data_correction(event.bot, chat_id_str, chat_id, 'birth_date')

        elif payload == "confirm_data":
            log_user_event(chat_id_str, "registration_data_confirmed")
            greeting_name = await registration_handler.handle_data_confirmation(event.bot, chat_id_str, chat_id)
            if greeting_name:
                await send_main_menu(event.bot, chat_id, greeting_name)

        # Обработка основных callback-ов
        elif payload == "other_options":
            log_user_event(chat_id_str, "other_options_menu_opened")
            await send_other_options_menu(event.bot, chat_id)

        elif payload == "back_to_main":
            log_user_event(chat_id_str, "back_to_main_menu")
            if db.is_user_registered(chat_id_str):
                greeting_name = db.get_user_greeting(chat_id_str)
                await send_main_menu(event.bot, chat_id, greeting_name)
            else:
                keyboard = create_keyboard([[
                    {'type': 'callback', 'text': 'Начать регистрацию', 'payload': "start_continue"}
                ]])
                await event.bot.send_message(
                    chat_id=chat_id,
                    text="Для использования бота необходимо зарегистрироваться.",
                    attachments=[keyboard] if keyboard else []
                )

        # Управление напоминаниями
        elif payload == "reminders_settings":
            log_user_event(chat_id_str, "reminders_settings_opened")
            await reminder_handler.send_reminder_settings(event.bot, chat_id)
            return

        elif payload == "reminders_yes":
            log_user_event(chat_id_str, "reminders_enabled")
            await reminder_handler.enable_reminders(event.bot, chat_id)
            return

        elif payload == "reminders_no":
            log_user_event(chat_id_str, "reminders_disabled")
            await reminder_handler.disable_reminders(event.bot, chat_id)
            return

        elif payload == "reminders_back":
            log_user_event(chat_id_str, "reminders_back_clicked")
            await reminder_handler.go_back(event.bot, chat_id)
            return

        # Онлайн чат с поддержкой
        elif payload == "support_request":
            log_user_event(chat_id_str, "support_chat_requested")
            chat_id_str = str(chat_id)
            if db.is_user_registered(chat_id_str):
                greeting_name = db.get_user_greeting(chat_id_str)
                user_phone = ""

                try:
                    if hasattr(db, 'get_user_phone'):
                        user_phone = db.get_user_phone(chat_id_str)
                    else:
                        user_data = db.get_user_data(chat_id_str)
                        user_phone = user_data.get('phone', '') if user_data else ''
                except Exception as phone_error:
                    log_system_event("phone_retrieval_error", str(phone_error), chat_id=chat_id_str)
                    user_phone = "Не указан"

                user_data = {
                    'fio': greeting_name,
                    'phone': user_phone
                }

                await support_handler.handle_support_request(event.bot, chat_id, user_data)
            else:
                keyboard = create_keyboard([[
                    {'type': 'callback', 'text': 'Начать регистрацию', 'payload': "start_continue"}
                ]])
                await event.bot.send_message(
                    chat_id=chat_id,
                    text="❌ Для использования онлайн-чата с поддержкой необходимо сначала зарегистрироваться.",
                    attachments=[keyboard] if keyboard else []
                )

    except Exception as e:
        chat_id_str = str(event.message.recipient.chat_id) if hasattr(event, 'message') and hasattr(event.message, 'recipient') else 'unknown'
        log_system_event("callback_error", str(e), chat_id=chat_id_str)
        user_states.pop(chat_id_str, None)
        try:
            await event.bot.send_message(
                chat_id=event.message.recipient.chat_id,
                text="Произошла ошибка при обработке запроса. Пожалуйста, попробуйте еще раз."
            )
        except Exception as send_error:
            log_system_event("callback_error_send_failed", str(send_error), chat_id=chat_id_str)


@dp.message_created()
@anti_duplicate()
async def handle_message(event: MessageCreated):
    """Обработка всех текстовых сообщений"""
    try:
        if len(processed_events) > 1000:
            cleanup_processed_events()

        chat_id = event.message.recipient.chat_id
        chat_id_str = str(chat_id)

        is_admin = (chat_id == ADMIN_ID) if ADMIN_ID else False

        # Обработка админских команд для синхронизации
        if is_admin and event.message.body and event.message.body.text:
            message_text = event.message.body.text.strip()
            
            # Импортируем sync_command_handler динамически, так как он может быть инициализирован позже
            from bot_config import sync_command_handler
            
            if sync_command_handler:
                handled = await sync_command_handler.handle_message(event)
                if handled:
                    return

            # Обработка сообщений администратора через support_handler
            processed = await support_handler.process_admin_message(event.bot, chat_id, message_text)
            if processed:
                log_system_event("admin_command", "handled_by_support", command=message_text, chat_id=chat_id_str)
                return

        if not event.message.body:
            return

        if event.message.body.attachments:
            contact_processed = await registration_handler.process_contact_message(
                event, chat_id_str, chat_id
            )
            if contact_processed:
                return

        if not event.message.sender:
            return

        if not event.message.body.text:
            return

        message_text = event.message.body.text.strip()
        if not message_text:
            return

        # Логируем сообщения пользователей (но не команды админа, они уже залогированы выше)
        is_admin_msg = (chat_id == ADMIN_ID) if ADMIN_ID else False
        if not (is_admin_msg and message_text.startswith("/")):
            log_user_event(chat_id_str, "message_sent", text=message_text)

        if not db.is_user_registered(chat_id_str) and chat_id_str not in user_states:
            log_user_event(chat_id_str, "message_ignored_unregistered")
            keyboard = create_keyboard([[
                {'type': 'callback', 'text': 'Начать регистрацию', 'payload': "start_continue"}
            ]])
            await event.bot.send_message(
                chat_id=chat_id,
                text="Для использования бота необходимо зарегистрироваться.",
                attachments=[keyboard] if keyboard else []
            )
            return

        registration_processed = await registration_handler.process_text_input(
            chat_id_str, message_text, event.bot, chat_id
        )

        if registration_processed:
            return

        chat_processed = await support_handler.process_user_message(event.bot, chat_id, message_text)
        if chat_processed:
            return

        if db.is_user_registered(chat_id_str):
            greeting_name = db.get_user_greeting(chat_id_str)
            await send_main_menu(event.bot, chat_id, greeting_name)
            return

        if not user_states.get(chat_id_str):
            keyboard = create_keyboard([[
                {'type': 'callback', 'text': 'Начать регистрацию', 'payload': "start_continue"}
            ]])
            await event.bot.send_message(
                chat_id=chat_id,
                text="Для использования бота необходимо зарегистрироваться.",
                attachments=[keyboard] if keyboard else []
            )

    except Exception as e:
        chat_id_str = str(event.message.recipient.chat_id) if hasattr(event, 'message') and hasattr(event.message, 'recipient') else 'unknown'
        log_system_event("message_handler_error", str(e), chat_id=chat_id_str)
        user_states.pop(chat_id_str, None)

        try:
            await event.bot.send_message(
                chat_id=event.message.recipient.chat_id,
                text="Произошла ошибка при обработке сообщения. Пожалуйста, попробуйте еще раз."
            )
        except Exception as send_error:
            log_system_event("message_error_send_failed", str(send_error), chat_id=chat_id_str)

