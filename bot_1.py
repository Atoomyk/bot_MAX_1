import asyncio
import logging
import os
from dotenv import load_dotenv

from maxapi import Bot, Dispatcher
from maxapi.types import BotStarted, Command, MessageCreated

from user_database import db

logging.basicConfig(level=logging.INFO)

# Загружаем токен из .env
load_dotenv()
TOKEN = os.getenv("MAXAPI_TOKEN")

bot = Bot(TOKEN)
dp = Dispatcher()

# Словарь для хранения состояний регистрации пользователей
user_states = {}

# Обработка события запуска бота
@dp.bot_started()
async def bot_started(event: BotStarted):
    chat_id = str(event.chat_id)

    if db.is_user_registered(chat_id):
        greeting = db.get_user_greeting(chat_id)
        await event.bot.send_message(
            chat_id=event.chat_id,
            text=f'Здравствуйте, {greeting}! Вы уже зарегистрированы. Отправьте /start для продолжения.'
        )
    else:
        user_states[chat_id] = 'waiting_fio'
        await event.bot.send_message(
            chat_id=event.chat_id,
            text='Добро пожаловать! Для начала работы необходимо пройти идентификацию.\n\n'
                 'Пожалуйста, введите ваше ФИО в формате:\n'
                 'Фамилия Имя Отчество\n\n'
                 'Например: Иванов Иван Иванович'
        )

# Команда /start
@dp.message_created(Command('start'))
async def start_command(event: MessageCreated):
    chat_id = str(event.message.recipient.chat_id)

    if db.is_user_registered(chat_id):
        greeting = db.get_user_greeting(chat_id)
        await event.message.answer(f'Здравствуйте, {greeting}! Чем могу помочь?')
    else:
        user_states[chat_id] = 'waiting_fio'
        await event.message.answer(
            'Для начала работы необходимо пройти идентификацию.\n\n'
            'Пожалуйста, введите ваше ФИО в формате:\n'
            'Фамилия Имя Отчество\n\n'
            'Например: Иванов Иван Иванович'
        )

# Обработка сообщений (регистрация)
@dp.message_created()
async def handle_message(event: MessageCreated):
    chat_id = str(event.message.recipient.chat_id)

    if not event.message.body or not event.message.body.text:
        return

    message_text = event.message.body.text.strip()

    if message_text.startswith('/'):
        return

    if db.is_user_registered(chat_id) and chat_id not in user_states:
        return

    state = user_states.get(chat_id)

    if state == 'waiting_fio':
        if not db.validate_fio(message_text):
            await event.message.answer(
                '❌ Неверный формат ФИО.\n\n'
                'Пожалуйста, введите ФИО в формате:\n'
                'Фамилия Имя Отчество\n\n'
                'Например: Иванов Иван Иванович'
            )
            return

        user_states[chat_id] = {'state': 'waiting_phone', 'fio': message_text}
        await event.message.answer(
            'Отлично! Теперь введите ваш номер телефона в формате:\n'
            '+79781111111\n\n'
            'Например: +79781234567'
        )

    elif isinstance(state, dict) and state.get('state') == 'waiting_phone':
        if not db.validate_phone(message_text):
            await event.message.answer(
                '❌ Неверный формат телефона.\n\n'
                'Пожалуйста, введите номер телефона в формате:\n'
                '+79781111111\n\n'
                'Например: +79781234567'
            )
            return

        try:
            fio = state['fio']
            phone = message_text
            success = db.register_user(chat_id, fio, phone)

            if success:
                user_states.pop(chat_id, None)
                greeting = db.get_user_greeting(chat_id)
                await event.message.answer(
                    f'✅ Регистрация успешно завершена!\n\n'
                    f'Здравствуйте, {greeting}! Теперь вы можете пользоваться ботом.\n\n'
                    f'Отправьте /start для продолжения.'
                )
            else:
                await event.message.answer(
                    '❌ Ошибка регистрации. Этот номер телефона уже зарегистрирован.\n\n'
                    'Если нужно изменить данные, обратитесь к администратору.'
                )
                user_states.pop(chat_id, None)

        except Exception as e:
            logging.error(f"Ошибка при регистрации пользователя {chat_id}: {e}")
            await event.message.answer(
                '❌ Произошла ошибка при регистрации. Попробуйте позже или обратитесь к администратору.'
            )
            user_states.pop(chat_id, None)

# Запуск через webhook
async def main():
    await dp.handle_webhook(
        bot=bot,
        host='localhost',
        port=80,
        log_level='critical'
    )

if __name__ == '__main__':
    asyncio.run(main())
