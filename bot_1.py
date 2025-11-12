import asyncio
import logging
import os
import time
from dotenv import load_dotenv

from maxapi import Bot, Dispatcher
from maxapi.types import (
    BotStarted,
    MessageCallback,
    MessageCreated,
    Attachment,
    ButtonsPayload,
    CallbackButton,
    LinkButton
)
from maxapi.utils.inline_keyboard import AttachmentType

# Загрузка переменных окружения
load_dotenv()
TOKEN = os.getenv("MAXAPI_TOKEN")

X_TUNNEL_URL = "https://1eca42f8-7ea0-48de-bcf6-939849243cab.tunnel4.com"

bot = Bot(TOKEN)
dp = Dispatcher()

SOGL_LINK = "https://sevmiac.ru/company/dokumenty/"
CONTINUE_CALLBACK = "start_continue"
AGREEMENT_CALLBACK = "agreement_accepted"
ADMIN_CONTACT = "@admin_MIAC"

# Новые callback-ы для системы исправления данных
CORRECT_FIO_CALLBACK = "correct_fio"
CORRECT_BIRTH_DATE_CALLBACK = "correct_birth_date"
CORRECT_PHONE_CALLBACK = "correct_phone"
CONFIRM_DATA_CALLBACK = "confirm_data"

# Ссылки для кнопок главного меню
GOSUSLUGI_APPOINTMENT_URL = "https://www.gosuslugi.ru/10700"
GOSUSLUGI_MEDICAL_EXAM_URL = "https://www.gosuslugi.ru/647521/1/form"
GOSUSLUGI_DOCTOR_HOME_URL = "https://www.gosuslugi.ru/600361"
GOSUSLUGI_ATTACH_TO_POLYCLINIC_URL = "https://www.gosuslugi.ru/600360"
CONTACT_CENTER_URL = "https://sevmiac.ru/ekc/"
MAP_OF_MEDICAL_INSTITUTIONS_URL = "https://yandex.ru/maps/959/sevastopol/search/%D0%B1%D0%BE%D0%BB%D1%8C%D0%BD%D0%B8%D1%86%D1%8B%20%D1%81%D0%B5%D0%B2%D0%B0%D1%81%D1%82%D0%BE%D0%BF%D0%BE%D0%BB%D1%8C/?ll=33.542596%2C44.577279&profile-mode=1&sctx=ZAAAAAgCEAAaKAoSCc0iFFtBJUNAEfYM4ZhlAUtAEhIJPgXAeAYN1z8RHCjwTj49wj8iBgABAgQFBigEOABAvwdIAWIaYWRkX3NuaXBwZXQ9bWV0YXJlYWx0eS8xLnhiHGFkZF9zbmlwcGV0PW1haW5fYXNwZWN0cy8xLnhiKXJlYXJyPXNjaGVtZV9Mb2NhbC9HZW8vTWV0YVJlYWx0eUtwcz0xMDAyagJydZUBAAAAAJ0BzczMPaABAagBAL0B09dLsMIBhwGI0oWYBI%2BevdYEmM%2BXmoAChf6Czky%2F3bm7BMGrr6oE1Oz6ngT91qOQtQK8ib%2FOiAXoteKRBMXVwJYEgcLQhgaczPbLBriO%2FskE1uOJgtoFkJjwtQaD48Tekgeq8ezXBq%2FLm%2BDCBMfokZuaA8nSo%2FkEiuHzlv8GktWn1IYB7bCdwuQF04y6xTmCAifQsdC%2B0LvRjNC90LjRhtGLINGB0LXQstCw0YHRgtC%2B0L%2FQvtC70YyKAiwxODQxMDU5NTYkMTg0MTA1OTU4JDUzNDM3MjYwNTU5JDE5ODM5NTI4OTU0MpICAzk1OZoCDGRlc2t0b3AtbWFwc6oCDDE2NTc0MjkxODkzOQ%3D%3D&sll=33.542596%2C44.577279&source=wizbiz_new_map_multi&sspn=0.240326%2C0.097050&z=13"

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Импорт базы данных из отдельного файла
from user_database import db

# Словари для хранения состояний и защиты от дублирования
user_states = {}
greeted_users = set()
processed_messages = set()
processed_callbacks = set()
last_processed = {}


# --- Вспомогательные функции ---

def create_main_menu_keyboard():
    """Создает клавиатуру главного меню с 4 кнопками"""
    buttons = [
        [LinkButton(text="Записаться на приём к врачу", url=GOSUSLUGI_APPOINTMENT_URL)],
        [LinkButton(text="Профосмотр/диспансеризация", url=GOSUSLUGI_MEDICAL_EXAM_URL)],
        [LinkButton(text="Вызов врача на дом", url=GOSUSLUGI_DOCTOR_HOME_URL)],
        [LinkButton(text="Прикрепление к поликлинике", url=GOSUSLUGI_ATTACH_TO_POLYCLINIC_URL)],
        [LinkButton(text="Ближайшие гос мед учреждения", url=MAP_OF_MEDICAL_INSTITUTIONS_URL)],
        [LinkButton(text="Единый контакт-центр", url=CONTACT_CENTER_URL)]
    ]

    buttons_payload = ButtonsPayload(buttons=buttons)
    keyboard_attachment = Attachment(
        type=AttachmentType.INLINE_KEYBOARD,
        payload=buttons_payload
    )

    return keyboard_attachment


async def send_main_menu(bot_instance: Bot, chat_id: int, greeting_name: str):
    """Отправляет главное меню с приветствием"""
    keyboard = create_main_menu_keyboard()

    await bot_instance.send_message(
        chat_id=chat_id,
        text=f"Здравствуйте, {greeting_name}!\n\n"
             "Выберите услугу:",
        attachments=[keyboard]
    )


async def send_agreement_message(bot_instance: Bot, chat_id: int):
    """Отправляет сообщение с соглашением"""
    agreement_button = CallbackButton(
        text="Согласие на обработку персональных данных",
        payload=AGREEMENT_CALLBACK
    )

    buttons_payload = ButtonsPayload(buttons=[[agreement_button]])
    keyboard_attachment = Attachment(
        type=AttachmentType.INLINE_KEYBOARD,
        payload=buttons_payload
    )

    await bot_instance.send_message(
        chat_id=chat_id,
        text='Продолжая, Вы даёте согласие на обработку персональных данных.\n'
             f'Ознакомиться с документом вы можете по ссылке {SOGL_LINK}',
        attachments=[keyboard_attachment]
    )


async def start_fio_request(bot_instance: Bot, chat_id: int):
    """Начинает процесс регистрации - запрос ФИО"""
    user_states[str(chat_id)] = {'state': 'waiting_fio', 'data': {}}


    # Первое сообщение
    await bot_instance.send_message(
        chat_id=chat_id,
        text='Для начала работы необходимо пройти регистрацию.'
    )

    # Второе сообщение с инструкцией
    await bot_instance.send_message(
        chat_id=chat_id,
        text='Пожалуйста, введите ваше ФИО в формате:\n'
             'Фамилия Имя Отчество\n\n'
             'Пример: Иванов Иван Иванович'
    )

async def request_fio_correction(bot_instance: Bot, chat_id: int):
    """Запрашивает ФИО для исправления (без сообщения о регистрации)"""
    await bot_instance.send_message(
        chat_id=chat_id,
        text="Введите ваше ФИО для исправления:\n\n"
             "Формат: Фамилия Имя Отчество\n"
             "Пример: Иванов Иван Иванович"
    )


async def request_birth_date_correction(bot_instance: Bot, chat_id: int):
    """Запрашивает дату рождения для исправления (без сообщения о регистрации)"""
    await bot_instance.send_message(
        chat_id=chat_id,
        text="Введите вашу дату рождения для исправления:\n\n"
             "Формат: ДД.ММ.ГГГГ\n"
             "Пример: 13.03.2003"
    )


async def request_phone_correction(bot_instance: Bot, chat_id: int):
    """Запрашивает телефон для исправления (без сообщения о регистрации)"""
    await bot_instance.send_message(
        chat_id=chat_id,
        text="Введите ваш номер телефона для исправления:\n\n"
             "Пример: +79781234567"
    )

async def request_phone_number(bot_instance: Bot, chat_id: int):
    """Запрашивает номер телефона"""
    await bot_instance.send_message(
        chat_id=chat_id,
        text="Отлично!\n"
             "Теперь введите ваш номер телефона\n\n"
             "Пример: +79781234567\n\n"
    )

# --- Обработчики событий ---

@dp.bot_started()
async def bot_started(event: BotStarted):
    """Обработка запуска бота"""
    chat_id = event.chat_id
    chat_id_str = str(chat_id)

    # Проверяем, не отправляли ли уже приветствие
    if chat_id_str in greeted_users:
        return

    try:
        # Проверяем, зарегистрирован ли пользователь
        if db.is_user_registered(chat_id_str):
            # Пользователь уже зарегистрирован - показываем главное меню
            greeting_name = db.get_user_greeting(chat_id_str)
            await send_main_menu(event.bot, chat_id, greeting_name)
        else:
            # Начинаем регистрацию
            continue_button = CallbackButton(
                text="Продолжить",
                payload=CONTINUE_CALLBACK
            )

            buttons_payload = ButtonsPayload(buttons=[[continue_button]])
            keyboard_attachment = Attachment(
                type=AttachmentType.INLINE_KEYBOARD,
                payload=buttons_payload
            )

            await event.bot.send_message(
                chat_id=chat_id,
                text='Здравствуйте! 👩‍⚕️\n\n'
                     'Вы обратились в Медицинский информационно-аналитический центр города Севастополя.\n'
                     'Наша система позволяет Вам удобно и быстро решить следующие задачи:\n\n'
                     '📌 Записаться на приём к врачу;\n'
                     '📌 Вызвать врача на дом;\n'
                     '📌 Записаться на профилактический медосмотр/диспансеризацию;\n'
                     '📌 Прикрепиться к поликлинике;\n'
                     '📌 Получать уведомления о записи к врачу с возможностью её отмены;\n'
                     '📌 Найти ближайшие государственные медицинские учреждения.'
                ,
                attachments=[keyboard_attachment]
            )

        greeted_users.add(chat_id_str)
    except Exception as e:
        logging.warning(f"Не удалось отправить сообщение пользователю {chat_id}: {e}")


async def request_birth_date(bot_instance: Bot, chat_id: int):
    """Запрашивает дату рождения"""
    await bot_instance.send_message(
        chat_id=chat_id,
        text="Отлично!\n"
             "Теперь введите вашу дату рождения\n\n"
             "Формат: ДД.ММ.ГГГГ\n"
             "Пример: 13.03.2003"
    )


async def send_confirmation_message(bot_instance: Bot, chat_id: int, user_data: dict):
    """Отправляет сообщение с подтверждением данных"""
    fio = user_data.get('fio', 'Не указано')
    birth_date = user_data.get('birth_date', 'Не указано')
    phone = user_data.get('phone', 'Не указано')

    # Создаем кнопки для исправления
    correct_fio_button = CallbackButton(
        text="⚠️ Исправить ФИО",
        payload=CORRECT_FIO_CALLBACK
    )
    correct_birth_date_button = CallbackButton(
        text="⚠️ Исправить дату рождения",
        payload=CORRECT_BIRTH_DATE_CALLBACK
    )
    correct_phone_button = CallbackButton(
        text="⚠️ Исправить телефон",
        payload=CORRECT_PHONE_CALLBACK
    )
    confirm_button = CallbackButton(
        text="✅ Всё верно, подтвердить",
        payload=CONFIRM_DATA_CALLBACK
    )

    buttons_payload = ButtonsPayload(buttons=[
        [correct_fio_button],
        [correct_birth_date_button],
        [correct_phone_button],
        [confirm_button]
    ])
    keyboard_attachment = Attachment(
        type=AttachmentType.INLINE_KEYBOARD,
        payload=buttons_payload
    )

    await bot_instance.send_message(
        chat_id=chat_id,
        text="📋 Пожалуйста, проверьте введенные данные:\n\n"
             f"👤 ФИО: {fio}\n\n"
             f"🎂 Дата рождения: {birth_date}\n\n"
             f"📞 Телефон: {phone}\n\n"
             "Если всё верно - нажмите 'Подтвердить', "
             "или выберите что нужно исправить:",
        attachments=[keyboard_attachment]
    )


async def complete_registration(bot_instance: Bot, chat_id: int, user_data: dict):
    """Завершает регистрацию и показывает главное меню"""
    fio = user_data['fio']
    birth_date = user_data['birth_date']
    phone = user_data['phone']

    success = db.register_user(str(chat_id), fio, phone, birth_date)

    if success:
        # Удаляем состояние перед отправкой сообщения
        user_states.pop(str(chat_id), None)

        # Получаем приветствие по имени и отчеству
        greeting_name = db.get_user_greeting(str(chat_id))

        # Отправляем сообщение об успешной регистрации
        await bot_instance.send_message(
            chat_id=chat_id,
            text=f"✅ Успешная регистрация!\n"
                 f"Теперь вы можете пользоваться всеми функциями бота."
        )

        # Отправляем главное меню
        await send_main_menu(bot_instance, chat_id, greeting_name)

    else:
        # Ошибка при сохранении
        user_states.pop(str(chat_id), None)
        await bot_instance.send_message(
            chat_id=chat_id,
            text=f"🚨 Ошибка при регистрации. Комбинация ФИО и телефона уже существует.\n\n"
                 f"Пожалуйста, обратитесь к администратору, {ADMIN_CONTACT}."
        )


@dp.message_callback()
async def message_callback(event: MessageCallback):
    """Обработка нажатий на инлайн-кнопки"""
    chat_id = event.message.recipient.chat_id
    chat_id_str = str(chat_id)

    # Защита от дублирования
    current_time = time.time()
    if chat_id_str in last_processed:
        if current_time - last_processed[chat_id_str] < 1.0:
            return
    last_processed[chat_id_str] = current_time

    callback_id = event.callback.callback_id if hasattr(event.callback, 'callback_id') else None
    if callback_id and callback_id in processed_callbacks:
        return
    if callback_id:
        processed_callbacks.add(callback_id)
        if len(processed_callbacks) > 1000:
            processed_callbacks.clear()

    if event.callback.payload == CONTINUE_CALLBACK:
        await send_agreement_message(event.bot, chat_id)


    elif event.callback.payload == AGREEMENT_CALLBACK:

        await start_fio_request(event.bot, chat_id)


    # Обработка кнопок исправления данных
    elif event.callback.payload == CORRECT_FIO_CALLBACK:
        # Сохраняем уже введенные данные кроме ФИО
        current_data = user_states.get(chat_id_str, {}).get('data', {})
        current_data.pop('fio', None)  # Удаляем старое ФИО
        user_states[chat_id_str] = {'state': 'waiting_fio', 'data': current_data}
        await request_fio_correction(event.bot, chat_id)  # ← НОВАЯ ФУНКЦИЯ

    elif event.callback.payload == CORRECT_BIRTH_DATE_CALLBACK:
        # Сохраняем уже введенные данные кроме даты рождения
        current_data = user_states.get(chat_id_str, {}).get('data', {})
        current_data.pop('birth_date', None)  # Удаляем старую дату
        user_states[chat_id_str] = {'state': 'waiting_birth_date', 'data': current_data}
        await request_birth_date_correction(event.bot, chat_id)  # ← НОВАЯ ФУНКЦИЯ

    elif event.callback.payload == CORRECT_PHONE_CALLBACK:
        # Сохраняем уже введенные данные кроме телефона
        current_data = user_states.get(chat_id_str, {}).get('data', {})
        current_data.pop('phone', None)  # Удаляем старый телефон
        user_states[chat_id_str] = {'state': 'waiting_phone', 'data': current_data}
        await request_phone_correction(event.bot, chat_id)  # ← НОВАЯ ФУНКЦИЯ


    elif event.callback.payload == CONFIRM_DATA_CALLBACK:

        # Завершаем регистрацию

        user_data = user_states.get(chat_id_str, {}).get('data', {})

        if user_data and all(key in user_data for key in ['fio', 'birth_date', 'phone']):

            await complete_registration(event.bot, chat_id, user_data)

        else:

            # Если данных недостаточно, начинаем заново

            await event.bot.send_message(

                chat_id=chat_id,

                text="❌ Не все данные заполнены. Начинаем регистрацию заново."

            )

            await start_fio_request(event.bot, chat_id)


@dp.message_created()
async def handle_message(event: MessageCreated):
    """Обработка всех текстовых сообщений"""
    chat_id = event.message.recipient.chat_id
    chat_id_str = str(chat_id)

    # Проверяем базовые условия
    if not event.message.body or not event.message.body.text:
        return

    if not event.message.sender:
        return

    # Защита от дублирования
    message_id = event.message.body.mid if hasattr(event.message.body, 'mid') else None
    if message_id and message_id in processed_messages:
        return
    if message_id:
        processed_messages.add(message_id)
        if len(processed_messages) > 1000:
            processed_messages.clear()

    message_text = event.message.body.text.strip()

    if not message_text:
        return

    # Если пользователь не зарегистрирован и не в процессе регистрации, игнорируем
    if not db.is_user_registered(chat_id_str) and chat_id_str not in user_states:
        return

    # Проверяем состояние пользователя (процесс регистрации)
    state_info = user_states.get(chat_id_str)
    if not state_info:
        return

    state = state_info.get('state')
    user_data = state_info.get('data', {})

    # --- Ожидание ФИО ---
    if state == 'waiting_fio':
        if not message_text:
            await event.message.answer(
                "ФИО не может быть пустым. Пожалуйста, введите ваше ФИО в формате: Фамилия Имя Отчество"
            )
            return

        if not db.validate_fio(message_text):
            await event.message.answer(
                "❌ Ошибка формата!\n\n"
                "Пожалуйста, введите ваше ФИО в таком формате: Фамилия Имя Отчество\n\n"
                "Пример: Иванов Иван Иванович"
            )
            return

        # Сохраняем ФИО
        user_data['fio'] = message_text

        # Проверяем, все ли данные уже есть для подтверждения
        if all(key in user_data for key in ['fio', 'birth_date', 'phone']):
            # Все данные есть - переходим к подтверждению
            user_states[chat_id_str] = {
                'state': 'waiting_confirmation',
                'data': user_data
            }
            await send_confirmation_message(event.bot, chat_id, user_data)
        elif 'birth_date' in user_data and 'phone' not in user_data:
            # Есть ФИО и дата, но нет телефона
            user_states[chat_id_str] = {
                'state': 'waiting_phone',
                'data': user_data
            }
            await request_phone_number(event.bot, chat_id)
        elif 'birth_date' not in user_data:
            # Нет даты рождения - запрашиваем её
            user_states[chat_id_str] = {
                'state': 'waiting_birth_date',
                'data': user_data
            }
            await request_birth_date(event.bot, chat_id)
        else:
            # Во всех остальных случаях переходим к подтверждению
            user_states[chat_id_str] = {
                'state': 'waiting_confirmation',
                'data': user_data
            }
            await send_confirmation_message(event.bot, chat_id, user_data)

    # --- Ожидание даты рождения ---
    elif state == 'waiting_birth_date':
        if not message_text:
            await event.message.answer(
                "Дата рождения не может быть пустой. Пожалуйста, введите дату в формате: ДД.ММ.ГГГГ"
            )
            return

        if not db.validate_birth_date(message_text):
            await event.message.answer(
                "❌ Ошибка формата!\n\n"
                "Пожалуйста, введите дату рождения в формате: ДД.ММ.ГГГГ\n\n"
                "Пример: 13.03.2003"
            )
            return

        # Сохраняем дату рождения
        user_data['birth_date'] = message_text

        # Проверяем, все ли данные уже есть для подтверждения
        if all(key in user_data for key in ['fio', 'birth_date', 'phone']):
            # Все данные есть - переходим к подтверждению
            user_states[chat_id_str] = {
                'state': 'waiting_confirmation',
                'data': user_data
            }
            await send_confirmation_message(event.bot, chat_id, user_data)
        elif 'phone' not in user_data:
            # Нет телефона - запрашиваем его
            user_states[chat_id_str] = {
                'state': 'waiting_phone',
                'data': user_data
            }
            await request_phone_number(event.bot, chat_id)
        else:
            # Есть все данные - переходим к подтверждению
            user_states[chat_id_str] = {
                'state': 'waiting_confirmation',
                'data': user_data
            }
            await send_confirmation_message(event.bot, chat_id, user_data)

    # --- Ожидание телефона ---
    elif state == 'waiting_phone':
        if not message_text:
            await event.message.answer(
                "Номер телефона не может быть пустым. Пожалуйста, введите Ваш номер телефона в формате: +79781111111"
            )
            return

        # Нормализуем телефон
        phone_normalized = message_text.replace(' ', '').replace('-', '').replace('(', '').replace(')', '').strip()

        if not db.validate_phone(phone_normalized):
            await event.message.answer(
                "❌ Ошибка формата!\n\n"
                "Пожалуйста, введите Ваш номер телефона в таком формате:\n"
                "+79781111111\n\n"
                "Пример: +79781234567"
            )
            return

        # Сохраняем телефон
        user_data['phone'] = phone_normalized

        # Защита от дублирования
        current_time = time.time()
        if chat_id_str in last_processed:
            if current_time - last_processed[chat_id_str] < 0.5:
                return
        last_processed[chat_id_str] = current_time

        # Всегда переходим к подтверждению после ввода телефона
        user_states[chat_id_str] = {
            'state': 'waiting_confirmation',
            'data': user_data
        }
        await send_confirmation_message(event.bot, chat_id, user_data)  # ← ОДИН ВЫЗОВ


# --- Запуск вебхука ---

async def setup_webhook():
    """Настраивает вебхук через Xtunnel"""
    logging.info(f"Setting up webhook to URL: {X_TUNNEL_URL}")
    await bot.subscribe_webhook(
        url=X_TUNNEL_URL,
        update_types=[
            "message_created",
            "message_callback",
            "bot_started"
        ]
    )
    logging.info("Webhook setup complete.")


async def main():
    # Сначала настраиваем вебхук
    await setup_webhook()

    # Затем запускаем сервер
    logging.info("Starting webhook server...")
    await dp.handle_webhook(
        bot=bot,
        host='0.0.0.0',
        port=80,
        log_level='info'
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Bot stopped manually.")