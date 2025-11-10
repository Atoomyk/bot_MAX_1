import asyncio
import logging
import os
from dotenv import load_dotenv

from maxapi import Bot, Dispatcher
from maxapi.types import (
    BotStarted,
    MessageCallback,
    Attachment,
    ButtonsPayload,
    CallbackButton
)
from maxapi.enums.attachment import AttachmentType
from maxapi.enums.intent import Intent

logging.basicConfig(level=logging.INFO)

load_dotenv()
TOKEN = os.getenv("MAXAPI_TOKEN")

X_TUNNEL_URL = "https://717ec0a7-1b1e-4142-84c1-282027d87379.tunnel4.com"

bot = Bot(TOKEN)
dp = Dispatcher()

SOGL_LINK = "https://sevmiac.ru/company/dokumenty/"
CONTINUE_CALLBACK = "start_continue"


async def send_agreement_message(bot_instance: Bot, chat_id: int):
    await bot_instance.send_message(
        chat_id=chat_id,
        text='Продолжая, Вы даёте согласие на обработку персональных данных.\n'
             f'Ознакомиться с документом вы можете по ссылке {SOGL_LINK}'
    )


@dp.bot_started()
async def bot_started(event: BotStarted):
    logging.info(f"BotStarted received: chat_id={event.chat_id}")

    continue_button = CallbackButton(
        text="Продолжить",
        payload=CONTINUE_CALLBACK,
        intent=Intent.DEFAULT
    )

    buttons_payload = ButtonsPayload(
        buttons=[[continue_button]]
    )

    keyboard_attachment = Attachment(
        type=AttachmentType.INLINE_KEYBOARD,
        payload=buttons_payload
    )

    result = await event.bot.send_message(
        chat_id=event.chat_id,
        text='Здравствуйте! 👩‍⚕️\n\n'
             'Вы обратились в Медицинский информационно-аналитический центр города Севастополя.\n'
             'Наша система позволяет Вам удобно и быстро решить следующие задачи:\n\n'
             '📌 Записаться на приём к врачу;\n'
             '📌 Пройти профилактический медосмотр или диспансеризацию.\n'
             '📌 Получать информацию по записям на приём к врачу.',
        attachments=[keyboard_attachment]
    )
    logging.info(f"Message sent: {result}")


@dp.message_callback()
async def message_callback(callback: MessageCallback):
    logging.info(f"=== CALLBACK RECEIVED ===")
    logging.info(f"Callback payload: {callback.callback.payload}")

    # Отвечаем на callback с текстом (нельзя пустой)
    await callback.message.answer('Обрабатываю...')

    if callback.callback.payload == CONTINUE_CALLBACK:
        logging.info("Processing continue button...")

        # Получаем chat_id из recipient сообщения
        chat_id = callback.message.recipient.chat_id
        await send_agreement_message(callback.bot, chat_id)
        logging.info("Agreement message sent successfully")


# Функция для настройки вебхука
async def setup_webhook():
    """Настраивает вебхук через Xtunnel"""
    logging.info(f"Setting up webhook to: {X_TUNNEL_URL}")

    result = await bot.subscribe_webhook(
        url=X_TUNNEL_URL,
        update_types=[
            "message_created",
            "message_callback",
            "bot_started"
        ]
    )
    logging.info(f"Webhook setup result: {result}")

    # Проверим текущие подписки
    subscriptions = await bot.get_subscriptions()
    logging.info(f"Current subscriptions: {subscriptions}")


# Запуск через webhook
async def main():
    # Сначала настраиваем вебхук
    await setup_webhook()

    # Затем запускаем сервер
    logging.info("Starting webhook server on port 80...")
    await dp.handle_webhook(
        bot=bot,
        host='0.0.0.0',
        port=80,
        log_level='info'
    )


if __name__ == '__main__':
    asyncio.run(main())