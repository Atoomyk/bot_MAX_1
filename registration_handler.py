# registration_handler.py
import re
import asyncio
from typing import Dict, Any, Callable, Optional
from maxapi import Bot
from maxapi.types import Attachment, ButtonsPayload, CallbackButton, LinkButton, RequestContactButton
from maxapi.utils.inline_keyboard import AttachmentType

from user_database import db
from logging_config import log_user_event, log_data_event, log_system_event

# Callback-константы для регистрации
SOGL_LINK = "https://sevmiac.ru/upload/iblock/d73/sttjnvlhg3j2df943ve0fv3husrlm8oj.pdf"
CONTINUE_CALLBACK = "start_continue"
AGREEMENT_CALLBACK = "agreement_accepted"
ADMIN_CONTACT = "@admin_MIAC"

CORRECT_FIO_CALLBACK = "correct_fio"
CORRECT_BIRTH_DATE_CALLBACK = "correct_birth_date"
CORRECT_PHONE_CALLBACK = "correct_phone"
CONFIRM_DATA_CALLBACK = "confirm_data"
CONFIRM_PHONE_CALLBACK = "confirm_phone"
REJECT_PHONE_CALLBACK = "reject_phone"


class RegistrationHandler:
    """Обработчик процесса регистрации пользователя"""

    def __init__(self, user_states: Dict[str, Any]):
        self.user_states = user_states

    def create_keyboard(self, buttons_config):
        """Универсальная функция создания клавиатуры для регистрации"""
        if not buttons_config:
            return None

        formatted_buttons = []
        for row in buttons_config:
            button_row = []
            for button in row:
                if isinstance(button, dict):
                    if button.get('type') == 'callback':
                        btn = CallbackButton(text=button['text'], payload=button['payload'])
                    elif button.get('type') == 'link':
                        btn = LinkButton(text=button['text'], url=button['url'])
                    elif button.get('type') == 'contact':
                        btn = RequestContactButton(text=button['text'])
                    else:
                        continue
                    button_row.append(btn)
                else:
                    button_row.append(button)
            if button_row:
                formatted_buttons.append(button_row)

        if not formatted_buttons:
            return None

        buttons_payload = ButtonsPayload(buttons=formatted_buttons)
        return Attachment(
            type=AttachmentType.INLINE_KEYBOARD,
            payload=buttons_payload
        )

    async def send_agreement_message(self, bot_instance: Bot, chat_id: int):
        """Отправляет сообщение с соглашением"""
        keyboard = self.create_keyboard([[
            {'type': 'callback', 'text': 'Согласие на обработку персональных данных', 'payload': AGREEMENT_CALLBACK}
        ]])

        await bot_instance.send_message(
            chat_id=chat_id,
            text=f'Продолжая, Вы даёте согласие на обработку персональных данных.\nОзнакомиться с документом вы можете по ссылке {SOGL_LINK}',
            attachments=[keyboard] if keyboard else []
        )

    async def start_registration_process(self, bot_instance: Bot, chat_id: int):
        """Начинает процесс регистрации - подтверждение телефона"""
        self.user_states[str(chat_id)] = {'state': 'waiting_phone_confirmation', 'data': {}}
        log_user_event(str(chat_id), "registration_started")

        await bot_instance.send_message(
            chat_id=chat_id,
            text='Для начала работы необходимо подтвердить номер и пройти регистрацию.'
        )
        await self.request_contact(bot_instance, chat_id)

    async def request_contact(self, bot_instance: Bot, chat_id: int):
        """Запрашивает контакт пользователя"""
        keyboard = self.create_keyboard([[
            {'type': 'contact', 'text': '📇 Отправить контакт'}
        ]])

        await bot_instance.send_message(
            chat_id=chat_id,
            text="Нажмите кнопку ниже чтобы поделиться контактом:",
            attachments=[keyboard] if keyboard else []
        )

    async def send_phone_confirmation(self, bot_instance: Bot, chat_id: int, phone: str):
        """Отправляет сообщение с подтверждением номера телефона"""
        keyboard = self.create_keyboard([[
            {'type': 'callback', 'text': '✅ Да, номер верный', 'payload': CONFIRM_PHONE_CALLBACK},
            {'type': 'callback', 'text': '❌ Нет, неверный номер', 'payload': REJECT_PHONE_CALLBACK}
        ]])

        await bot_instance.send_message(
            chat_id=chat_id,
            text=f"📞 Ваш номер телефона определён:\n\n📱 {phone}\n\nПожалуйста, проверьте актуальность номера:",
            attachments=[keyboard] if keyboard else []
        )

    async def handle_incorrect_phone(self, bot_instance: Bot, chat_id: int):
        """Обработка неверного номера телефона"""
        log_user_event(str(chat_id), "phone_rejected")
        await bot_instance.send_message(
            chat_id=chat_id,
            text="❌ Пожалуйста, отправьте контакт с правильным номером телефона."
        )
        await self.request_contact(bot_instance, chat_id)

    async def start_fio_request(self, bot_instance: Bot, chat_id: int, user_data: dict):
        """Начинает процесс ввода ФИО"""
        self.user_states[str(chat_id)] = {'state': 'waiting_fio', 'data': user_data}
        log_user_event(str(chat_id), "fio_input_started")

        await bot_instance.send_message(
            chat_id=chat_id,
            text='Пожалуйста, введите ваше ФИО в формате:\nФамилия Имя Отчество\n\nПример: Иванов Иван Иванович'
        )

    async def request_birth_date(self, bot_instance: Bot, chat_id: int, user_data: dict):
        """Запрашивает дату рождения"""
        self.user_states[str(chat_id)] = {'state': 'waiting_birth_date', 'data': user_data}

        await bot_instance.send_message(
            chat_id=chat_id,
            text="Отлично!\nТеперь введите вашу дату рождения\n\nФормат: ДД.ММ.ГГГГ\nПример: 13.03.2003"
        )

    async def send_confirmation_message(self, bot_instance: Bot, chat_id: int, user_data: dict):
        """Отправляет сообщение с подтверждением данных"""
        fio = user_data.get('fio', 'Не указано')
        birth_date = user_data.get('birth_date', 'Не указано')
        phone = user_data.get('phone', 'Не указано')

        log_data_event(str(chat_id), "confirmation_prepared", fio=fio, birth_date=birth_date, phone=phone)

        keyboard = self.create_keyboard([
            [{'type': 'callback', 'text': '⚠️ Исправить ФИО', 'payload': CORRECT_FIO_CALLBACK}],
            [{'type': 'callback', 'text': '⚠️ Исправить дату рождения', 'payload': CORRECT_BIRTH_DATE_CALLBACK}],
            [{'type': 'callback', 'text': '✅ Всё верно, подтвердить', 'payload': CONFIRM_DATA_CALLBACK}]
        ])

        await bot_instance.send_message(
            chat_id=chat_id,
            text=f"📋 Пожалуйста, проверьте введенные данные:\n\n👤 ФИО: {fio}\n🎂 Дата рождения: {birth_date}\n📞 Телефон: {phone}\n\nЕсли всё верно - нажмите 'Подтвердить', или выберите что нужно исправить:",
            attachments=[keyboard] if keyboard else []
        )

    async def complete_registration(self, bot_instance: Bot, chat_id: int, user_data: dict):
        """Завершает регистрацию и показывает главное меню"""
        fio = user_data['fio']
        birth_date = user_data['birth_date']
        phone = user_data['phone']

        try:
            async with asyncio.timeout(10):
                success = db.register_user(str(chat_id), fio, phone, birth_date)
        except asyncio.TimeoutError:
            log_system_event("db_timeout", chat_id=str(chat_id))
            await bot_instance.send_message(
                chat_id=chat_id,
                text="⏳ Сервер перегружен, попробуйте позже"
            )
            return

        if success:
            self.user_states.pop(str(chat_id), None)
            greeting_name = db.get_user_greeting(str(chat_id))
            log_data_event(str(chat_id), "registration_completed", fio=fio, phone=phone, status="success")

            await bot_instance.send_message(
                chat_id=chat_id,
                text="✅ Успешная регистрация!\nТеперь вы можете пользоваться всеми функциями бота."
            )
            return greeting_name
        else:
            self.user_states.pop(str(chat_id), None)
            log_data_event(str(chat_id), "registration_failed", fio=fio, phone=phone, status="duplicate")
            await bot_instance.send_message(
                chat_id=chat_id,
                text=f"🚨 Ошибка при регистрации. Комбинация ФИО и телефона уже существует.\n\nПожалуйста, обратитесь к администратору, {ADMIN_CONTACT}."
            )
            return None

    async def validate_and_process_input(self, chat_id_str: str, input_text: str, input_type: str,
                                         bot_instance: Bot, chat_id: int, user_data: dict):
        """Универсальная функция валидации и обработки ввода для регистрации"""
        validator_map = {
            'fio': db.validate_fio,
            'birth_date': db.validate_birth_date,
            'phone': db.validate_phone
        }

        error_messages = {
            'fio': "❌ Ошибка формата!\n\nПожалуйста, введите ваше ФИО в формате: Фамилия Имя Отчество\n\nПример: Иванов Иван Иванович",
            'birth_date': "❌ Ошибка формата!\n\nПожалуйста, введите дату рождения в формате: ДД.ММ.ГГГГ\n\nПример: 13.03.2003",
            'phone': "❌ Неверный формат номера телефона."
        }

        if input_type not in validator_map:
            return False

        if not validator_map[input_type](input_text):
            log_user_event(chat_id_str, f"invalid_{input_type}_format", input=input_text)
            await bot_instance.send_message(chat_id=chat_id, text=error_messages[input_type])
            return False

        # Сохраняем данные
        user_data[input_type] = input_text
        log_data_event(chat_id_str, f"{input_type}_entered", **{input_type: input_text})
        return True

    async def request_data_correction(self, bot_instance: Bot, chat_id: int, user_data: dict, data_type: str):
        """Универсальная функция запроса исправления данных"""
        correction_configs = {
            'fio': {
                'state': 'waiting_fio_correction',
                'log_event': 'fio_correction_requested',
                'message': "Введите ваше ФИО для исправления:\n\nФормат: Фамилия Имя Отчество\nПример: Иванов Иван Иванович"
            },
            'birth_date': {
                'state': 'waiting_birth_date_correction',
                'log_event': 'birth_date_correction_requested',
                'message': "Введите вашу дату рождения для исправления:\n\nФормат: ДД.ММ.ГГГГ\nПример: 13.03.2003"
            }
        }

        if data_type not in correction_configs:
            return

        config = correction_configs[data_type]
        self.user_states[str(chat_id)] = {'state': config['state'], 'data': user_data}
        log_user_event(str(chat_id), config['log_event'])

        await bot_instance.send_message(chat_id=chat_id, text=config['message'])

    async def handle_phone_confirmation(self, bot_instance: Bot, chat_id_str: str, chat_id: int):
        """Обработка подтверждения телефона"""
        log_user_event(chat_id_str, "phone_confirmed")
        current_state = self.user_states.get(chat_id_str, {})
        user_data = current_state.get('data', {})

        if 'phone' not in user_data:
            log_data_event(chat_id_str, "phone_missing_on_confirmation")
            await bot_instance.send_message(chat_id=chat_id,
                                            text="❌ Ошибка: номер телефона не найден. Начинаем регистрацию заново.")
            await self.start_registration_process(bot_instance, chat_id)
            return

        await self.start_fio_request(bot_instance, chat_id, user_data)

    async def handle_data_correction(self, bot_instance: Bot, chat_id_str: str, chat_id: int, data_type: str):
        """Обработка исправления данных"""
        current_data = self.user_states.get(chat_id_str, {}).get('data', {})
        current_data.pop(data_type, None)
        await self.request_data_correction(bot_instance, chat_id, current_data, data_type)

    async def handle_data_confirmation(self, bot_instance: Bot, chat_id_str: str, chat_id: int):
        """Обработка подтверждения данных"""
        log_user_event(chat_id_str, "user_confirmed_registration")
        user_data = self.user_states.get(chat_id_str, {}).get('data', {})

        if user_data and all(key in user_data for key in ['fio', 'birth_date', 'phone']):
            return await self.complete_registration(bot_instance, chat_id, user_data)
        else:
            missing_fields = [key for key in ['fio', 'birth_date', 'phone'] if key not in user_data]
            log_data_event(chat_id_str, "incomplete_data_on_confirmation", missing=missing_fields)
            await bot_instance.send_message(chat_id=chat_id,
                                            text="❌ Не все данные заполнены. Начинаем регистрацию заново.")
            await self.start_registration_process(bot_instance, chat_id)
            return None

    async def process_contact_message(self, event, chat_id_str: str, chat_id: int):
        """Обработка сообщений с контактами для регистрации"""
        state_info = self.user_states.get(chat_id_str)
        if not state_info or state_info.get('state') != 'waiting_phone_confirmation':
            return False

        contact_attachments = [attr for attr in event.message.body.attachments if attr.type == "contact"]
        if not contact_attachments:
            return False

        for contact in contact_attachments:
            try:
                payload = contact.payload
                vcf_info = payload.vcf_info
                phone_match = re.search(r'TEL[^:]*:([^\r\n]+)', vcf_info)

                if phone_match:
                    phone = phone_match.group(1).strip()
                    clean_phone = re.sub(r'[^\d+]', '', phone)
                    if not clean_phone.startswith('+'):
                        clean_phone = '+' + clean_phone
                    if not db.validate_phone(clean_phone):
                        log_user_event(chat_id_str, "invalid_phone_format", phone=clean_phone)
                        await event.bot.send_message(chat_id=chat_id, text="❌ Неверный формат номера телефона.")
                        return True

                    user_data = state_info.get('data', {})
                    user_data['phone'] = clean_phone
                    self.user_states[chat_id_str] = {'state': 'waiting_phone_confirmation', 'data': user_data}

                    log_data_event(chat_id_str, "phone_extracted", phone=clean_phone)
                    await self.send_phone_confirmation(event.bot, chat_id, clean_phone)
                    return True
                else:
                    log_user_event(chat_id_str, "phone_extraction_failed")
                    await event.bot.send_message(chat_id=chat_id, text="❌ Не удалось определить номер телефона.")
                    return True

            except Exception as e:
                log_system_event("contact_handler", "processing_failed", error=str(e), chat_id=chat_id_str)
                await event.bot.send_message(chat_id=chat_id, text="❌ Произошла ошибка при обработке контакта.")
                return True

        return False

    async def process_text_input(self, chat_id_str: str, message_text: str, bot_instance: Bot, chat_id: int):
        """Обработка текстового ввода в процессе регистрации"""
        state_info = self.user_states.get(chat_id_str)
        if not state_info:
            return False

        state = state_info.get('state')
        user_data = state_info.get('data', {})

        # Обработка разных состояний регистрации
        state_handlers = {
            'waiting_fio': lambda: self._handle_fio_input(chat_id_str, message_text, bot_instance, chat_id, user_data),
            'waiting_birth_date': lambda: self._handle_birth_date_input(chat_id_str, message_text, bot_instance,
                                                                        chat_id, user_data),
            'waiting_fio_correction': lambda: self._handle_fio_correction(chat_id_str, message_text, bot_instance,
                                                                          chat_id, user_data),
            'waiting_birth_date_correction': lambda: self._handle_birth_date_correction(chat_id_str, message_text,
                                                                                        bot_instance, chat_id,
                                                                                        user_data),
        }

        if state in state_handlers:
            result = await state_handlers[state]()
            return result is not False  # Возвращаем True если состояние обработано

        return False

    async def _handle_fio_input(self, chat_id_str: str, message_text: str, bot_instance: Bot, chat_id: int,
                                user_data: dict):
        """Обработка ввода ФИО"""
        success = await self.validate_and_process_input(chat_id_str, message_text, 'fio', bot_instance, chat_id,
                                                        user_data)
        if success:
            await self.request_birth_date(bot_instance, chat_id, user_data)
        return success

    async def _handle_birth_date_input(self, chat_id_str: str, message_text: str, bot_instance: Bot, chat_id: int,
                                       user_data: dict):
        """Обработка ввода даты рождения"""
        success = await self.validate_and_process_input(chat_id_str, message_text, 'birth_date', bot_instance, chat_id,
                                                        user_data)
        if success:
            self.user_states[chat_id_str] = {'state': 'waiting_confirmation', 'data': user_data}
            await self.send_confirmation_message(bot_instance, chat_id, user_data)
        return success

    async def _handle_fio_correction(self, chat_id_str: str, message_text: str, bot_instance: Bot, chat_id: int,
                                     user_data: dict):
        """Обработка исправления ФИО"""
        success = await self.validate_and_process_input(chat_id_str, message_text, 'fio', bot_instance, chat_id,
                                                        user_data)
        if success:
            self.user_states[chat_id_str] = {'state': 'waiting_confirmation', 'data': user_data}
            await self.send_confirmation_message(bot_instance, chat_id, user_data)
        return success

    async def _handle_birth_date_correction(self, chat_id_str: str, message_text: str, bot_instance: Bot, chat_id: int,
                                            user_data: dict):
        """Обработка исправления даты рождения"""
        success = await self.validate_and_process_input(chat_id_str, message_text, 'birth_date', bot_instance, chat_id,
                                                        user_data)
        if success:
            self.user_states[chat_id_str] = {'state': 'waiting_confirmation', 'data': user_data}
            await self.send_confirmation_message(bot_instance, chat_id, user_data)
        return success