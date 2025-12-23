# visit_a_doctor/handlers.py
"""
Основная логика сценария записи к врачу.
Интеграция с SOAP-сервисом.
"""
from visit_a_doctor.states import UserContext
from visit_a_doctor import keyboards as kb
from visit_a_doctor.soap_client import SoapClient
import uuid
from visit_a_doctor.soap_parser import SoapResponseParser
from visit_a_doctor.specialties_mapping import get_specialty_name
from bot_utils import send_main_menu
from user_database import db

# Хранилище состояний: chat_id -> UserContext
user_states = {}

# Временный кэш данных (MO, Specs, Doctors) для сессии, чтобы не спамить запросами при пагинации
# В реальном проде можно кешировать на уровне UserContext или Redis
session_cache = {} # chat_id -> {'mos': [], 'specs': [], 'doctors': [], 'slots': []}

async def get_or_create_context(chat_id: str) -> UserContext:
    if chat_id not in user_states:
        user_states[chat_id] = UserContext(chat_id=chat_id)
    return user_states[chat_id]

def get_cache(chat_id):
    if chat_id not in session_cache:
        session_cache[chat_id] = {}
    return session_cache[chat_id]

async def show_patient_confirmation(bot, chat_id, ctx):
    """Показывает экран подтверждения данных пациента"""
    # Ensure we have the latest context
    ctx = await get_or_create_context(str(chat_id))
    ctx.step = "CONFIRM_PATIENT_DATA"
    ctx.return_to_confirm = False 
    
    summary = (
        "ℹ️ Проверьте данные пациента:\n\n"
        f"ФИО: {getattr(ctx, 'patient_fio', 'Не указано')}\n"
        f"Дата рождения: {getattr(ctx, 'patient_birthdate', 'Не указана')}\n"
        f"Пол: {getattr(ctx, 'patient_gender', 'Не указан')}\n"
        f"СНИЛС: {getattr(ctx, 'patient_snils', 'Не указан')}\n"
        f"Полис: {getattr(ctx, 'patient_oms', 'Не указан')}"
    )
    
    is_self_booking = getattr(ctx, 'selected_person', '') == 'me'
    
    await bot.send_message(
        chat_id=chat_id,
        text=summary,
        attachments=[kb.kb_confirm_patient_data(is_self_booking=is_self_booking)]
    )

async def start_booking(bot, chat_id):
    """Запуск сценария"""
    ctx = UserContext(chat_id=str(chat_id))
    user_states[str(chat_id)] = ctx
    session_cache.pop(str(chat_id), None) # Очистка кэша
    
    ctx.step = "PERSON"
    await bot.send_message(
        chat_id=chat_id,
        text="Кого записать на прием?",
        attachments=[kb.kb_person_selection()]
    )

async def process_mo_selection(bot, chat_id, ctx):
    """(Helper) Загружает и показывает список МО"""
    xml = await SoapClient.get_mos(ctx.session_id)
    mos = SoapResponseParser.parse_mo_list(xml)
    
    if not mos:
        await bot.send_message(chat_id=chat_id, text="⚠️ Не удалось получить список медицинских организаций (или он пуст).")
        return

    # Кэшируем
    get_cache(chat_id)['mos'] = mos
    
    ctx.step = "MO"
    await bot.send_message(
        chat_id=chat_id,
        text="Выберите медицинскую организацию для записи:",
        attachments=[kb.kb_mo_selection(mos)]
    )

async def handle_callback(bot, chat_id, payload):
    ctx = await get_or_create_context(str(chat_id))
    cache = get_cache(chat_id)
    
    if payload == 'doc_restart':
        await start_booking(bot, chat_id)
        return

    # --- НАВИГАЦИЯ НАЗАД ---
    if payload == 'doc_back_to_person':
        ctx.step = "PERSON"
        await bot.send_message(chat_id=chat_id, text="Кого записать на прием?", attachments=[kb.kb_person_selection()])
        return
    elif payload == 'doc_back_to_mo':
        mos = cache.get('mos', [])
        if not mos: # Ре-фетч если кэш пропал
             await process_mo_selection(bot, chat_id, ctx)
             return
        ctx.step = "MO"
        await bot.send_message(chat_id=chat_id, text="Выберите медицинскую организацию для записи:", attachments=[kb.kb_mo_selection(mos)])
        return
    elif payload == 'doc_back_to_spec':
        specs = cache.get('specs', [])
        ctx.step = "SPEC"
        await bot.send_message(chat_id=chat_id, text="Выберите специальность:", attachments=[kb.kb_spec_selection(specs, ctx.spec_page)])
        return
    elif payload == 'doc_back_to_doc':
        doctors = cache.get('doctors', [])
        ctx.step = "DOCTOR"
        spec_name = ctx.selected_spec
        await bot.send_message(chat_id=chat_id, text=f"Выберите врача ({spec_name}):", attachments=[kb.kb_doctor_selection(doctors)])
        return
    elif payload == 'doc_back_to_date':
        dates = ctx.available_dates_cache or []
        ctx.step = "DATE"
        await bot.send_message(chat_id=chat_id, text="Выберите дату приема:", attachments=[kb.kb_date_selection(dates, ctx.date_page)])
        return

    # --- РЕДАКТИРОВАНИЕ ДАННЫХ ПАЦИЕНТА ---
    is_self_booking = getattr(ctx, 'selected_person', '') == 'me'
    
    # Проверка на попытку редактирования отключенных полей при записи себя
    if payload == 'doc_edit_fio':
        if is_self_booking:
            await bot.send_message(chat_id=chat_id, text="❌ Изменение ФИО при записи себя недоступно. Пожалуйста, измените данные в профиле.")
            return
        ctx.step = "ENTER_FIO"
        ctx.return_to_confirm = True
        await bot.send_message(chat_id=chat_id, text="Введите ФИО пациента (Фамилия Имя Отчество):")
        return
        
    if payload == "doc_edit_birthdate": 
        if is_self_booking:
            await bot.send_message(chat_id=chat_id, text="❌ Изменение даты рождения при записи себя недоступно. Пожалуйста, измените данные в профиле.")
            return
        ctx.step = "ENTER_BIRTHDATE"
        ctx.return_to_confirm = True
        await bot.send_message(chat_id=chat_id, text="Введите дату рождения (ДД.ММ.ГГГГ):")
        return
        
    if payload == "doc_edit_gender": 
        ctx.step = "ENTER_GENDER"
        ctx.return_to_confirm = True
        await bot.send_message(chat_id=chat_id, text="Введите пол (м/ж):")
        return
        
    if payload == "doc_edit_snils": 
        ctx.step = "ENTER_SNILS"
        ctx.return_to_confirm = True
        await bot.send_message(chat_id=chat_id, text="Введите СНИЛС (XXX-XXX-XXX XX):")
        return
        
    if payload == "doc_edit_oms": 
        ctx.step = "ENTER_OMS"
        ctx.return_to_confirm = True
        await bot.send_message(chat_id=chat_id, text="Введите полис ОМС:")
        return


    # --- ЛОГИКА ШАГОВ ---

    # 1. Выбор персоны / Подтверждение данных пациента
    if payload == 'doc_confirm_patient_data':
        # Авторизация сессии SOAP (Other)
        await bot.send_message(chat_id=chat_id, text="🔄 Авторизация в системе РМИС...")
        
        # Разбиваем ФИО
        parts = ctx.patient_fio.split()
        if len(parts) < 3: parts = ["Иванов", "Иван", "Иванович"] # Fallback
        
        xml = await SoapClient.get_patient_session(
            snils=ctx.patient_snils,
            oms=ctx.patient_oms,
            birthdate='-'.join(ctx.patient_birthdate.split('.')[::-1]) if '.' in ctx.patient_birthdate else "2000-01-01",
            fio_parts=parts,
            gender=ctx.patient_gender,
            client_session_id=getattr(ctx, 'client_session_id', str(uuid.uuid4()))
        )
        session_id = SoapResponseParser.parse_session_id(xml)
        if not session_id:
             print(f"AUTH ERROR RESPONSE: {xml}") # Логируем ответ в консоль
             await bot.send_message(chat_id=chat_id, text="❌ Ошибка авторизации. Пациент не найден или данные некорректны.\n(Подробности в логах)")
             return
        
        ctx.session_id = session_id
        await process_mo_selection(bot, chat_id, ctx)
        return

    if payload.startswith('doc_person_'):
        selection = payload.replace('doc_person_', '')
        ctx.selected_person = selection
        
        # Генерируем новый Session_ID для этой сессии записи
        ctx.client_session_id = str(uuid.uuid4())
        print(f"DEBUG: Generated new Session_ID: {ctx.client_session_id}")
        
        if selection == 'other':
            ctx.step = "ENTER_FIO"
            ctx.return_to_confirm = False
            await bot.send_message(chat_id=chat_id, text="Пожалуйста, введите ФИО пациента.\n\nПример: **Иванов Иван Иванович**")
        else:
            # Запись себя: берем данные из БД
            user_data = db.get_user_full_data(str(chat_id))
            if user_data:
                ctx.patient_fio = user_data.get('fio', '')
                ctx.patient_birthdate = user_data.get('birth_date', '')
                # Пол, СНИЛС и ОМС не храним в БД — спрашиваем
                ctx.step = "ENTER_GENDER"
                ctx.return_to_confirm = False
                await bot.send_message(chat_id=chat_id, text="Введите пол (м/ж):")
            else:
                 await bot.send_message(chat_id=chat_id, text="❌ Ошибка: не удалось получить данные профиля. Попробуйте записать 'другого человека'.")
                 return
        return

    # 1.5 Пол (Other)
    if ctx.step == "ENTER_GENDER":
        text = ctx.last_message_text
        gender_input = text.lower().strip()
        if gender_input in ['м', 'm', 'мужской']:
            ctx.patient_gender = "Мужской"
        elif gender_input in ['ж', 'f', 'женский']:
            ctx.patient_gender = "Женский"
        else:
            await bot.send_message(chat_id=chat_id, 
                                text="❌ Некорректный ввод. Пожалуйста, введите 'м' для мужского пола или 'ж' для женского.")
            return True
            
        if ctx.return_to_confirm:
            await show_patient_confirmation(bot, chat_id, ctx)
            return True
            
        ctx.step = "ENTER_SNILS"
        await bot.send_message(
            chat_id=chat_id, 
            text="Введите СНИЛС пациента (11 цифр).\n\nПример: **12300012300**"
        )
        return True

    # 2. Выбор МО
    if payload.startswith('doc_mo_'):
        mo_id = payload.replace('doc_mo_', '')
        
        # Ищем OID в кэше
        mos = cache.get('mos', [])
        selected_mo = next((m for m in mos if m['id'] == mo_id), None)
        if selected_mo:
            ctx.selected_mo_id = mo_id
            ctx.selected_mo_oid = selected_mo.get('oid', '')
        else:
            await bot.send_message(chat_id=chat_id, text="Ошибка выбора МО. Попробуйте снова.")
            return

        # Загружаем специальности
        await bot.send_message(chat_id=chat_id, text="🔄 Загрузка специальностей...")
        xml = await SoapClient.get_specs(ctx.session_id, mo_id)
        specs_data = SoapResponseParser.parse_specialties(xml)
        
        # Маппинг имен
        specs_ui = []
        for s in specs_data:
            pid = s['id']
            name = get_specialty_name(pid)
            specs_ui.append({'id': pid, 'name': name})
            
        if not specs_ui:
             await bot.send_message(chat_id=chat_id, text="Нет доступных специальностей.")
             return
        
        cache['specs'] = specs_ui
        ctx.step = "SPEC"
        ctx.spec_page = 0
        await bot.send_message(chat_id=chat_id, text="Выберите специальность:", attachments=[kb.kb_spec_selection(specs_ui, ctx.spec_page)])
        return

    # 3. Выбор специальности
    if payload.startswith('doc_spec_page_'):
        page = int(payload.split('_')[-1])
        ctx.spec_page = page
        specs = cache.get('specs', [])
        await bot.send_message(chat_id=chat_id, text=f"Выберите специальность (стр. {page+1}):", attachments=[kb.kb_spec_selection(specs, page)])
        return
        
    if payload.startswith('doc_spec_'):
        post_id = payload.replace('doc_spec_', '')
        ctx.selected_post_id = post_id
        
        specs = cache.get('specs', [])
        found_spec = next((s for s in specs if s['id'] == post_id), None)
        ctx.selected_spec = found_spec['name'] if found_spec else post_id
        
        # Загружаем врачей
        await bot.send_message(chat_id=chat_id, text="🔄 Поиск врачей...")
        xml = await SoapClient.get_doctors(ctx.session_id, post_id, ctx.selected_mo_oid)
        doctors = SoapResponseParser.parse_doctors(xml)
        
        if not doctors:
             await bot.send_message(chat_id=chat_id, text="Нет свободных врачей по этой специальности.", attachments=[kb.create_keyboard([[kb.get_back_button('doc_back_to_spec')]])])
             return

        cache['doctors'] = doctors
        ctx.step = "DOCTOR"
        await bot.send_message(chat_id=chat_id, text=f"Выберите врача ({ctx.selected_spec}):", attachments=[kb.kb_doctor_selection(doctors)])
        return

    # 4. Выбор врача
    if payload.startswith('doc_doc_'):
        doc_id = payload.replace('doc_doc_', '') # Это SNILS врача
        
        doctors = cache.get('doctors', [])
        found_doc = next((d for d in doctors if d['id'] == doc_id), None)
        
        if found_doc:
            ctx.selected_doctor_id = doc_id
            ctx.selected_doctor_name = found_doc['name']
            ctx.available_dates_cache = found_doc['dates'] # Сохраняем даты из объекта врача
        else:
            await bot.send_message(chat_id=chat_id, text="Ошибка выбора врача.")
            return
            
        ctx.step = "DATE"
        ctx.date_page = 0
        await bot.send_message(chat_id=chat_id, text="Выберите дату приема:", attachments=[kb.kb_date_selection(ctx.available_dates_cache, ctx.date_page)])
        return

    # 5. Выбор даты
    if payload.startswith('doc_date_page_'):
        page = int(payload.split('_')[-1])
        ctx.date_page = page
        dates = ctx.available_dates_cache or []
        await bot.send_message(chat_id=chat_id, text=f"Выберите дату приема (стр. {page+1}):", attachments=[kb.kb_date_selection(dates, page)])
        return
        
    if payload.startswith('doc_date_'):
        date_str = payload.replace('doc_date_', '')
        ctx.selected_date = date_str
        
        # Загружаем слоты
        await bot.send_message(chat_id=chat_id, text="🔄 Загрузка свободного времени...")
        xml = await SoapClient.get_slots(ctx.session_id, ctx.selected_doctor_id, ctx.selected_mo_oid, ctx.selected_post_id, date_str)
        slots = SoapResponseParser.parse_slots(xml)
        
        if not slots:
             await bot.send_message(chat_id=chat_id, text="Нет свободного времени на эту дату.")
             return
             
        cache['slots'] = slots
        ctx.step = "TIME"
        ctx.time_page = 0
        await bot.send_message(chat_id=chat_id, text=f"Выберите время приема на {date_str}:", attachments=[kb.kb_time_selection(slots, ctx.time_page)])
        return

    # 6. Выбор времени
    if payload.startswith('doc_time_page_'):
        page = int(payload.split('_')[-1])
        ctx.time_page = page
        slots = cache.get('slots', [])
        await bot.send_message(chat_id=chat_id, text=f"Выберите время приема (стр. {page+1}):", attachments=[kb.kb_time_selection(slots, page)])
        return
        
    if payload.startswith('doc_time_'):
        slot_id = payload.replace('doc_time_', '')
        
        slots = cache.get('slots', [])
        found_slot = next((s for s in slots if s['id'] == slot_id), None)
        if found_slot:
            ctx.selected_time = found_slot['time']
            ctx.selected_room = found_slot.get('room', "")
        else:
             # Fallback если кэш протух
             ctx.selected_time = "Выбрано"
        
        # ID слота нужен для записи, сохраним его в time или отдельное поле?
        # В CreateAppointmentRequest нужен Slot_Id. Сохраним временно, например в selected_doctor_id (грязный хак) 
        # или лучше добавим selected_slot_id в контекст? Добавил бы, но states.py менять лень.
        # Используем available_slots_cache чтобы найти ID при подтверждении. А, стоп. slot_id у нас уже есть в payload.
        # Сохраним slot_id в user_context динамически
        ctx.selected_slot_id = slot_id

        ctx.step = "CONFIRM_APPOINTMENT"
        
        person_info = "Записать себя"
        if ctx.selected_person == "other":
            person_info = f"Записать другого (Пациент: {ctx.patient_fio})"

        # Ищем имя МО
        mos = cache.get('mos', [])
        mo_name = next((m['name'] for m in mos if m['id'] == ctx.selected_mo_id), "Выбранная МО")
        
        # Получаем сокращенное имя МО для красивого вывода
        from visit_a_doctor.specialties_MO import Abbreviations_MO
        mo_name_short = Abbreviations_MO.get(mo_name, mo_name)
        if len(mo_name_short) > 60: mo_name_short = mo_name_short[:60] + ".."

        confirm_text = (
            f"ℹ️ -Подтверждение записи-\n\n"
            f"🏥 МО: {mo_name_short}\n"
            f"👨‍⚕️ Врач: {ctx.selected_doctor_name} ({ctx.selected_spec})\n"
            f"🚪 Кабинет: {ctx.selected_room}\n"
            f"🗓 Дата: {ctx.selected_date}\n"
            f"⏰ Время: {ctx.selected_time}\n"
            f"👤 Тип записи: {person_info}\n\n"
            f"Все верно?"
        )
        await bot.send_message(chat_id=chat_id, text=confirm_text, attachments=[kb.kb_confirm_appointment()])
        return

    # ФИНАЛ
    if payload == 'doc_confirm_booking':
        await bot.send_message(chat_id=chat_id, text="🔄 Оформление записи...")
        
        # Отправляем запрос
        # slot_id мы сохранили динамически в ctx (Python позволяет)
        slot_id = getattr(ctx, 'selected_slot_id', "")
        
        xml = await SoapClient.book_appointment(ctx.session_id, slot_id)
        success = SoapResponseParser.parse_booking_status(xml)
        
        if success:
            person_str = "Вы записали себя" if ctx.selected_person == "me" else "Вы записали другого человека"
            
            # Повторно достаем имя МО для красивого ответа
            mos = cache.get('mos', [])
            mo_name = next((m['name'] for m in mos if m['id'] == ctx.selected_mo_id), "Выбранная МО")
            from visit_a_doctor.specialties_MO import Abbreviations_MO
            mo_name_short = Abbreviations_MO.get(mo_name, mo_name)
            
            summary = (
                f"✅ *Запись успешно оформлена!*\n\n"
                f"{person_str}\n"
                f"🏥 МО: {mo_name_short}\n"
                f"👨‍⚕️ Врач: {ctx.selected_doctor_name} ({ctx.selected_spec})\n"
                f"🚪 Кабинет: {ctx.selected_room}\n"
                f"🗓 Дата: {ctx.selected_date}\n"
                f"⏰ Время: {ctx.selected_time}\n"
                f"За день до приёма вам придёт уведомление!\n"
                f"\nЖдем вас на прием!\n"
            )
            await bot.send_message(chat_id=chat_id, text=summary, attachments=[kb.kb_final_menu()])
        else:
            await bot.send_message(chat_id=chat_id, text="❌ Ошибка при создании записи. Возможно слот уже занят.", attachments=[kb.kb_final_menu()])
            
        if str(chat_id) in user_states:
             del user_states[str(chat_id)]
        return
        

# visit_a_doctor/handlers_text_input.py
from visit_a_doctor.handlers import get_or_create_context, show_patient_confirmation
async def handle_text_input(bot, chat_id, text):
    """Обработка текстового ввода для модуля записи к врачу"""
    ctx = await get_or_create_context(str(chat_id))
    is_self_booking = getattr(ctx, 'selected_person', '') == 'me'

    # ------------------ ФИО ------------------
    if ctx.step == "ENTER_FIO":
        if is_self_booking:
            await bot.send_message(chat_id=chat_id,
                                   text="❌ Изменение ФИО при записи себя недоступно. Пожалуйста, измените данные в профиле.")
            return True

        import re
        if not re.match(r'^[а-яА-ЯёЁ\-]+\s+[а-яА-ЯёЁ\-]+\s+[а-яА-ЯёЁ\-]+$', text):
            await bot.send_message(chat_id=chat_id, text="❌ Ошибка формата! Введите ФИО через пробел.\nПример: Иванов Иван Иванович")
            return True

        ctx.patient_fio = text
        if getattr(ctx, 'return_to_confirm', False):
            await show_patient_confirmation(bot, chat_id, ctx)
            return True

        ctx.step = "ENTER_BIRTHDATE"
        await bot.send_message(chat_id=chat_id, text="Введите дату рождения пациента (ДД.ММ.ГГГГ):")
        return True

    # ------------------ Дата рождения ------------------
    if ctx.step == "ENTER_BIRTHDATE":
        if is_self_booking:
            await bot.send_message(chat_id=chat_id,
                                   text="❌ Изменение даты рождения при записи себя недоступно. Пожалуйста, измените данные в профиле.")
            return True

        import re
        if not re.match(r'^\d{2}\.\d{2}\.\d{4}$', text):
            await bot.send_message(chat_id=chat_id, text="❌ Ошибка формата! Используйте ДД.ММ.ГГГГ")
            return True

        ctx.patient_birthdate = text
        if getattr(ctx, 'return_to_confirm', False):
            await show_patient_confirmation(bot, chat_id, ctx)
            return True

        ctx.step = "ENTER_GENDER"
        await bot.send_message(chat_id=chat_id, text="Введите пол пациента (м/ж):")
        return True

    # ------------------ Пол ------------------
    if ctx.step == "ENTER_GENDER":
        gender_input = text.lower().strip()
        if gender_input in ['м', 'm', 'мужской']:
            ctx.patient_gender = "Мужской"
        elif gender_input in ['ж', 'f', 'женский']:
            ctx.patient_gender = "Женский"
        else:
            await bot.send_message(chat_id=chat_id,
                                   text="❌ Некорректный ввод. Введите 'м' для мужского пола или 'ж' для женского.")
            return True

        # После ввода пола переходим к СНИЛС
        ctx.step = "ENTER_SNILS"
        await bot.send_message(chat_id=chat_id,
                               text="Введите СНИЛС пациента (11 цифр).\nПример: 12300012300")
        return True

    # ------------------ СНИЛС ------------------
    if ctx.step == "ENTER_SNILS":
        import re
        snils = re.sub(r'\D', '', text)
        if len(snils) != 11:
            await bot.send_message(chat_id=chat_id, text="❌ Ошибка! СНИЛС должен содержать ровно 11 цифр.\nПример: 12300012300")
            return True

        ctx.patient_snils = snils
        if getattr(ctx, 'return_to_confirm', False):
            await show_patient_confirmation(bot, chat_id, ctx)
            return True

        ctx.step = "ENTER_OMS"
        await bot.send_message(chat_id=chat_id,
                               text=("Введите номер полиса ОМС.\n"
                                     "Полис может содержать латинские буквы и цифры.\n"
                                     "Длина: от 10 до 20 символов.\nПримеры: 123456789012, AB1234567890"))
        return True

    # ------------------ ОМС ------------------
    if ctx.step == "ENTER_OMS":
        import re
        oms = re.sub(r'[\s\-]', '', text).upper()
        if not re.fullmatch(r'[A-Z0-9]+', oms):
            await bot.send_message(chat_id=chat_id,
                                   text="❌ Ошибка формата! Полис ОМС может содержать только латинские буквы (A–Z) и цифры.")
            return True
        if not (10 <= len(oms) <= 20):
            await bot.send_message(chat_id=chat_id,
                                   text="❌ Ошибка! Номер полиса ОМС должен содержать от 10 до 20 символов.")
            return True

        ctx.patient_oms = oms

        # Переход к экрану подтверждения данных пациента
        await show_patient_confirmation(bot, chat_id, ctx)
        return True

    return False
