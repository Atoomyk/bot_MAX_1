# reminder_handler.py
# =======================
# Обработчик управления напоминаниями "Вкл/Откл напоминаний"

from maxapi.types import CallbackButton, ButtonsPayload, Attachment
from maxapi.utils.inline_keyboard import AttachmentType


class ReminderHandler:
    def __init__(self, db, send_other_options_menu):
        """
        db — экземпляр класса UserDatabase
        send_other_options_menu — функция из bot.py для возврата в меню "Другие возможности"
        """
        self.db = db
        self.send_other_options_menu = send_other_options_menu

    # ---------------------------------------------------------------------
    # 🔘 Клавиатура настроек напоминаний
    # ---------------------------------------------------------------------
    def _create_reminders_keyboard(self):
        buttons = [
            [CallbackButton(text="✅ Да", payload="reminders_yes")],
            [CallbackButton(text="❌ Нет", payload="reminders_no")],
            [CallbackButton(text="⬅️ Назад", payload="reminders_back")]
        ]

        payload = ButtonsPayload(buttons=buttons)
        return Attachment(type=AttachmentType.INLINE_KEYBOARD, payload=payload)

    # ---------------------------------------------------------------------
    # 📩 Показать меню управления напоминаниями
    # ---------------------------------------------------------------------
    async def send_reminder_settings(self, bot, chat_id):
        """
        Показывает состояние уведомлений и кнопки:
        Да / Нет / Назад
        """
        status = self.db.get_reminders_status(str(chat_id))
        status_text = "ВКЛЮЧЕНЫ" if status else "ОТКЛЮЧЕНЫ"

        text = (
            "Хотите получать напоминания о записях к врачу?\n"
            f"Сейчас уведомления *{status_text}*."
        )

        await bot.send_message(
            chat_id=chat_id,
            text=text,
            attachments=[self._create_reminders_keyboard()]
        )

    # ---------------------------------------------------------------------
    # ✔ Кнопка "Да" — включение напоминаний
    # ---------------------------------------------------------------------
    async def enable_reminders(self, bot, chat_id):
        self.db.set_reminders_status(str(chat_id), True)

        await bot.send_message(
            chat_id=chat_id,
            text="🔔 Уведомления включены."
        )

        # Возврат в меню "Другие возможности"
        await self.send_other_options_menu(bot, chat_id)

    # ---------------------------------------------------------------------
    # ❌ Кнопка "Нет" — отключение напоминаний
    # ---------------------------------------------------------------------
    async def disable_reminders(self, bot, chat_id):
        self.db.set_reminders_status(str(chat_id), False)

        await bot.send_message(
            chat_id=chat_id,
            text="🔕 Уведомления отключены."
        )

        # Возврат в меню "Другие возможности"
        await self.send_other_options_menu(bot, chat_id)

    # ---------------------------------------------------------------------
    # ↩ Кнопка "Назад"
    # ---------------------------------------------------------------------
    async def go_back(self, bot, chat_id):
        await self.send_other_options_menu(bot, chat_id)
