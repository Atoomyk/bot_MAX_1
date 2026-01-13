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
from logging_config import log_user_event, log_data_event
import re

# Хранилище состояний: chat_id -> UserContext
user_states = {}

# Временный кэш данных (MO, Specs, Doctors) для сессии, чтобы не спамить запросами при пагинации
# В реальном проде можно кешировать на уровне UserContext или Redis
session_cache = {} # chat_id -> {'mos': [], 'specs': [], 'doctors': [], 'slots': []}

async def get_or_create_context(user_id: int) -> UserContext:
    if user_id not in user_states:
        user_states[user_id] = UserContext(user_id=user_id)
    return user_states[user_id]

def get_cache(user_id: int):
    if user_id not in session_cache:
        session_cache[user_id] = {}
    return session_cache[user_id]

async def show_patient_confirmation(bot, user_id, chat_id, ctx):
    """Показывает экран подтверждения данных пациента"""
    # Ensure we have the latest context
    ctx = await get_or_create_context(user_id)
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
    is_from_rms = getattr(ctx, 'is_from_rms', False)
    
    await bot.send_message(
        chat_id=chat_id,
        text=summary,
        attachments=[kb.kb_confirm_patient_data(is_self_booking=is_self_booking, allow_edit=not is_from_rms)]
    )

async def start_booking(bot, user_id, chat_id):
    """Запуск сценария"""
    ctx = UserContext(user_id=user_id)
    user_states[user_id] = ctx
    session_cache.pop(user_id, None) # Очистка кэша
    
    ctx.step = "PERSON"
    await bot.send_message(
        chat_id=chat_id,
        text="Кого записать на прием?",
        attachments=[kb.kb_person_selection()]
    )

async def send_mo_selection_menu(bot, chat_id, mos, ctx):
    """(Helper) Отправляет меню выбора МО с нумерацией"""
    
    menu_text = "🏥 Выберите медицинскую организацию:\n\n"
    # import re - Removed, using global import
    
    for i, mo in enumerate(mos):
        mo_name = mo['name']
        mo_address = mo.get('address', '')
        
        # Очистка адреса от "г. Севастополь"
        if mo_address:
            # Убираем дублирование города (г. Севастополь, Севастополь г и т.д.)
            cleaned_address = re.sub(r'(?i)(г\.\s*)?Севастополь(\s*г)?', '', mo_address)
            # Убираем лишние запятые и пробелы, которые могли остаться
            cleaned_address = re.sub(r',+', ',', cleaned_address)
            cleaned_address = cleaned_address.strip(' ,')
            
            # Если остался индекс (6 цифр в начале), можно оставить или убрать. 
            # Часто просят просто адрес. XML пример: "299703, , г. Инкерман..." -> "299703, , г. Инкерман"
            # Оставим как есть после чистки города.
            # UPD: Убираем индекс по запросу
            cleaned_address = re.sub(r'\b\d{6}\b', '', cleaned_address)

            # Финальная зачистка
            cleaned_address = re.sub(r',+', ',', cleaned_address)
            cleaned_address = cleaned_address.strip(' ,')
            
            display_str = f"{mo_name} ({cleaned_address})"
        else:
            display_str = mo_name
                
        menu_text += f"{i + 1}. {display_str}\n\n"

    ctx.step = "MO"
    await bot.send_message(
        chat_id=chat_id,
        text=menu_text,
        attachments=[kb.kb_mo_selection(mos)]
    )

async def process_mo_selection(bot, user_id, chat_id, ctx):
    """(Helper) Загружает и показывает список МО"""
    xml = await SoapClient.get_mos(ctx.session_id)
    mos = SoapResponseParser.parse_mo_list(xml)
    
    if not mos:
        await bot.send_message(chat_id=chat_id, text="⚠️ Не удалось получить список медицинских организаций (или он пуст).")
        return

    # Кэшируем
    get_cache(user_id)['mos'] = mos
    
    await send_mo_selection_menu(bot, chat_id, mos, ctx)

async def handle_callback(bot, user_id, chat_id, payload):
    ctx = await get_or_create_context(user_id)
    cache = get_cache(user_id)
    
    if payload == 'doc_restart':
        await start_booking(bot, user_id, chat_id)
        return

    # --- НАВИГАЦИЯ НАЗАД ---
    if payload == 'doc_back_to_person':
        ctx.step = "PERSON"
        await bot.send_message(chat_id=chat_id, text="Кого записать на прием?", attachments=[kb.kb_person_selection()])
        return
    elif payload == 'doc_back_to_mo':
        mos = cache.get('mos', [])
        if not mos: # Ре-фетч если кэш пропал
             await process_mo_selection(bot, user_id, chat_id, ctx)
             return
        await send_mo_selection_menu(bot, chat_id, mos, ctx)
        return
    elif payload == 'doc_back_to_spec':
        specs = cache.get('specs', [])
        ctx.step = "SPEC"
        
        # Get MO Name for display
        mos = cache.get('mos', [])
        mo_name = next((m['name'] for m in mos if m['id'] == ctx.selected_mo_id), "")
        from visit_a_doctor.specialties_MO import Abbreviations_MO
        short_mo_name = Abbreviations_MO.get(mo_name, mo_name)
        
        await bot.send_message(chat_id=chat_id, text=f"🏥 {short_mo_name}\n\nВыберите специальность:", attachments=[kb.kb_spec_selection(specs, ctx.spec_page)])
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
        ctx.step = "ENTER_GENDER"
        ctx.return_to_confirm = True
        await bot.send_message(chat_id=chat_id, text="Выберите пол:", attachments=[kb.kb_gender_selection()])
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

    if payload == "doc_incorrect_data":
        await bot.send_message(
            chat_id=chat_id,
            text="ℹ️ Если вы заметили ошибку в своих данных, обратитесь в медицинскую организацию по месту прописки — там смогут внести корректные сведения в вашу медицинскую карту.\nСейчас вы можете, нажать кнопку <<Всё верно, продолжить>>, и записаться к врачу."
        )
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
             log_data_event(user_id, "rms_auth_failed", snils=ctx.patient_snils)
             await bot.send_message(chat_id=chat_id, text="❌ Ошибка авторизации. Пациент не найден или данные некорректны.\n(Подробности в логах)")
             return
        
        ctx.session_id = session_id
        log_data_event(user_id, "rms_auth_success", session_id=session_id)
        await process_mo_selection(bot, user_id, chat_id, ctx)
        return

    if payload.startswith('doc_person_'):
        selection = payload.replace('doc_person_', '')
        ctx.selected_person = selection
        
        # Генерируем новый Session_ID для этой сессии записи
        ctx.client_session_id = str(uuid.uuid4())
        log_user_event(user_id, "booking_session_started", client_session_id=ctx.client_session_id, selection=selection)
        
        
        if selection == 'other':
            # ⚡ ЗАПРОС К API ПАЦИЕНТОВ ПО ТЕЛЕФОНУ ВЛАДЕЛЬЦА ⚡
            user_data = db.get_user_full_data(user_id)
            phone = user_data.get('phone', '') if user_data else ''

            if phone:
                await bot.send_message(chat_id=chat_id, text="🔄 Проверяем список прикрепленных пациентов...")
                from patient_api_client import get_patients_by_phone
                found_patients = await get_patients_by_phone(phone)
                
                # Фильтруем список: исключаем самого пользователя (владельца)
                filtered_patients = []
                if found_patients:
                    user_snils_clean = re.sub(r'\D', '', user_data.get('snils', ''))
                    
                    for p in found_patients:
                        # Сравнение по СНИЛС
                        p_snils_clean = re.sub(r'\D', '', p.get('snils', ''))
                        if user_snils_clean and p_snils_clean and user_snils_clean == p_snils_clean:
                            continue # Это сам юзер, пропускаем
                        
                        # Сравнение по ФИО + ДР (если нет СНИЛСа)
                        if (p.get('fio', '').lower() == user_data.get('fio', '').lower() and 
                            p.get('birth_date', '') == user_data.get('birth_date', '')):
                            continue # Это сам юзер
                            
                        filtered_patients.append(p)
                
                # Если после фильтрации остались люди — предлагаем выбор.
                if filtered_patients:
                    # Сохраняем кандидатов в контексте
                    ctx.family_candidates = filtered_patients
                    
                    keyboard_rows = []
                    for idx, p in enumerate(filtered_patients):
                        btn_text = f"{p['fio']} ({p['birth_date']})"
                        keyboard_rows.append([{'type': 'callback', 'text': btn_text, 'payload': f"doc_other_select_{idx}"}])
                    
                    keyboard_rows.append([{'type': 'callback', 'text': '➕ Ввести вручную', 'payload': "doc_other_select_manual"}])
                    keyboard = kb.create_keyboard(keyboard_rows)
                    
                    await bot.send_message(
                        chat_id=chat_id,
                        text="📋 Выберите пациента из списка или введите данные вручную:",
                        attachments=[keyboard]
                    )
                    return

            # Если не нашли или нет телефона — ручной ввод
            ctx.step = "ENTER_FIO"
            ctx.return_to_confirm = False
            await bot.send_message(chat_id=chat_id, text="Пожалуйста, введите ФИО пациента.\n\nПример: **Иванов Иван Иванович**")
        else:
            # Запись себя: берем данные из БД
            user_data = db.get_user_full_data(user_id)
            if user_data:
                # Начинаем с False
                ctx.is_from_rms = False

                # ⚡ СИНХРОНИЗАЦИЯ С РМИС (при каждом старте записи себя) ⚡
                phone = user_data.get('phone', '')
                if phone:
                    await bot.send_message(chat_id=chat_id, text="🔄 Проверяем актуальность данных...")
                    from patient_api_client import get_patients_by_phone
                    found_patients = await get_patients_by_phone(phone)
                    
                    # Пытаемся найти текущего пользователя в списке по СНИЛС или ФИО+ДР
                    my_snils = user_data.get('snils', '')
                    # Очистка СНИЛСа для сравнения
                    # import re (Removed: using global)
                    my_snils_clean = re.sub(r'[\D]', '', my_snils) if my_snils else ""

                    matched_patient = None
                    
                    if found_patients:
                        for p in found_patients:
                            p_snils_clean = re.sub(r'[\D]', '', p.get('snils', ''))
                            # Сравниваем по СНИЛС
                            if my_snils_clean and p_snils_clean and my_snils_clean == p_snils_clean:
                                matched_patient = p
                                break
                            # Сравниваем по ФИО + ДР (если нет СНИЛСа)
                            if not matched_patient:
                                if (p.get('fio', '').lower() == user_data.get('fio', '').lower() and 
                                    p.get('birth_date', '') == user_data.get('birth_date', '')):
                                    matched_patient = p
                                    break
                    
                    if matched_patient:
                        # Нашли в РМИС -> Обновляем БД если есть изменения
                        need_update = False
                        
                        # Сравниваем поля. Данные из РМИС считаем эталоном.
                        # Сравниваем поля. Данные из РМИС считаем эталоном.
                        if matched_patient.get('fio') != user_data.get('fio'): need_update = True
                        if matched_patient.get('birth_date') != user_data.get('birth_date'): need_update = True
                        if matched_patient.get('snils') != user_data.get('snils'): need_update = True
                        if matched_patient.get('oms') != user_data.get('oms'): need_update = True
                        # Если пол пришел из РМИС и отличается - обновляем
                        if matched_patient.get('gender') and matched_patient.get('gender') != user_data.get('gender'): need_update = True
                        
                        if need_update:
                            db.update_user_data(
                                user_id,
                                matched_patient['fio'],
                                matched_patient['birth_date'],
                                matched_patient.get('snils'),
                                matched_patient.get('oms'),
                                matched_patient.get('gender') or user_data.get('gender')
                            )
                            # Обновляем локальные user_data
                            user_data['fio'] = matched_patient['fio']
                            user_data['birth_date'] = matched_patient['birth_date']
                            user_data['snils'] = matched_patient.get('snils')
                            user_data['oms'] = matched_patient.get('oms')
                            if matched_patient.get('gender'):
                                user_data['gender'] = matched_patient.get('gender')
                        
                        ctx.is_from_rms = True
                        await bot.send_message(chat_id=chat_id, text="✅ Ваши данные синхронизированы с Региональной системой.")

                ctx.patient_fio = user_data.get('fio', '')
                ctx.patient_birthdate = user_data.get('birth_date', '')
                ctx.patient_snils = user_data.get('snils', '')
                ctx.patient_oms = user_data.get('oms', '')
                ctx.patient_gender = user_data.get('gender', '')

                # Проверяем, чего не хватает
                if not ctx.patient_gender:
                    ctx.step = "ENTER_GENDER"
                    ctx.return_to_confirm = False
                    await bot.send_message(chat_id=chat_id, text="Выберите пол:", attachments=[kb.kb_gender_selection()])
                elif not ctx.patient_snils:
                    ctx.step = "ENTER_SNILS"
                    ctx.return_to_confirm = False
                    await bot.send_message(chat_id=chat_id, text="Введите СНИЛС пациента (11 цифр).")
                elif not ctx.patient_oms:
                    ctx.step = "ENTER_OMS"
                    ctx.return_to_confirm = False
                    await bot.send_message(chat_id=chat_id, text="Введите номер полиса ОМС.")
                else:
                    # Все есть, переходим к подтверждению
                    await show_patient_confirmation(bot, user_id, chat_id, ctx)
            else:
                 await bot.send_message(chat_id=chat_id, text="❌ Ошибка: не удалось получить данные профиля. Попробуйте записать 'другого человека'.")
                 return
        return

    # 1.1 Выбор пациента (Other) из списка
    if payload.startswith('doc_other_select_'):
        selection_idx = payload.replace('doc_other_select_', '')
        
        if selection_idx == 'manual':
            ctx.step = "ENTER_FIO"
            ctx.return_to_confirm = False
            ctx.is_from_rms = False
            await bot.send_message(chat_id=chat_id, text="Пожалуйста, введите ФИО пациента.\n\nПример: **Иванов Иван Иванович**")
            return

        try:
            params = getattr(ctx, 'family_candidates', [])
            idx = int(selection_idx)
            selected_p = params[idx]
            
            ctx.patient_fio = selected_p['fio']
            ctx.patient_birthdate = selected_p['birth_date']
            ctx.patient_snils = selected_p['snils']
            ctx.patient_oms = selected_p['oms']
            ctx.patient_gender = selected_p.get('gender')
            ctx.is_from_rms = True

            log_data_event(user_id, "booking_patient_selected", patient_snils=ctx.patient_snils, gender_autofilled=bool(ctx.patient_gender))
            
            if ctx.patient_gender:
                    # Если пол есть - идем дальше
                    # Пропускаем ENTER_GENDER
                    if getattr(ctx, 'patient_snils', None):
                        if getattr(ctx, 'patient_oms', None):
                                await show_patient_confirmation(bot, user_id, chat_id, ctx)
                        else:
                                ctx.step = "ENTER_OMS"
                                await bot.send_message(chat_id=chat_id, text="Введите номер полиса ОМС.")
                    else:
                        ctx.step = "ENTER_SNILS"
                        await bot.send_message(chat_id=chat_id, text="Введите СНИЛС пациента (11 цифр).")
            else:
                ctx.step = "ENTER_GENDER"
                ctx.return_to_confirm = False
                await bot.send_message(chat_id=chat_id, text="Выберите пол:", attachments=[kb.kb_gender_selection()])
            
        except (ValueError, IndexError):
                await bot.send_message(chat_id=chat_id, text="⚠ Ошибка выбора. Введите данные вручную.")
                ctx.step = "ENTER_FIO"
                ctx.return_to_confirm = False
                await bot.send_message(chat_id=chat_id, text="Пожалуйста, введите ФИО пациента.")
        return

    # 1.5 Пол (Other) - Обработка кнопок
    if payload in ['doc_gender_male', 'doc_gender_female']:
        ctx.patient_gender = "Мужской" if payload == 'doc_gender_male' else "Женский"
        
        if getattr(ctx, 'return_to_confirm', False):
            await show_patient_confirmation(bot, user_id, chat_id, ctx)
            return True

        # Если СНИЛС уже есть (из РМИС), переходим к следующему шагу
        if getattr(ctx, 'patient_snils', None):
            if getattr(ctx, 'patient_oms', None):
                # И полис есть - сразу к подтверждению
                await show_patient_confirmation(bot, user_id, chat_id, ctx)
            else:
                # Полиса нет - просим полис
                ctx.step = "ENTER_OMS"
                await bot.send_message(chat_id=chat_id, text="Введите номер полиса ОМС.")
            return True
            
        ctx.step = "ENTER_SNILS"
        await bot.send_message(
            chat_id=chat_id, 
            text="Введите СНИЛС пациента (11 цифр).\n\nПример: **12300012300**"
        )
        return True

    # 1.5 Пол (Other) - Текст (оставим как фоллбек, но кнопки приоритетнее)
    if ctx.step == "ENTER_GENDER":
        # Если пришел странный payload не являющийся текстом (хотя сюда payload попадает)
        # Логика обработки текста в handlers_text_input.py, здесь только колбэки
        pass

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
        
        # Get MO Name for display
        # selected_mo already retrieved above
        mo_name = selected_mo['name']
        from visit_a_doctor.specialties_MO import Abbreviations_MO
        short_mo_name = Abbreviations_MO.get(mo_name, mo_name)
        
        await bot.send_message(chat_id=chat_id, text=f"🏥 {short_mo_name}\n\nВыберите специальность:", attachments=[kb.kb_spec_selection(specs_ui, ctx.spec_page)])
        return

    # 3. Выбор специальности
    if payload.startswith('doc_spec_page_'):
        page = int(payload.split('_')[-1])
        ctx.spec_page = page
        specs = cache.get('specs', [])
        
        # Get MO Name for display
        mos = cache.get('mos', [])
        mo_name = next((m['name'] for m in mos if m['id'] == ctx.selected_mo_id), "")
        from visit_a_doctor.specialties_MO import Abbreviations_MO
        short_mo_name = Abbreviations_MO.get(mo_name, mo_name)
        
        await bot.send_message(chat_id=chat_id, text=f"🏥 {short_mo_name}\n\nВыберите специальность (стр. {page+1}):", attachments=[kb.kb_spec_selection(specs, page)])
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
        # Определяем текст в зависимости от типа ресурсов (врачи или кабинеты)
        selection_text = f"Выберите врача ({ctx.selected_spec}):"
        # Проверяем, есть ли среди ресурсов кабинеты
        has_rooms = any(d.get('type') == 'room' for d in doctors)
        if has_rooms:
            selection_text = f"Выберите врача или кабинет ({ctx.selected_spec}):"
        
        await bot.send_message(chat_id=chat_id, text=selection_text, attachments=[kb.kb_doctor_selection(doctors)])
        return

    # 4. Выбор врача
    if payload.startswith('doc_doc_'):
        doc_id = payload.replace('doc_doc_', '') # Это SNILS врача или ROOM_XXX для кабинета
        
        doctors = cache.get('doctors', [])
        found_doc = next((d for d in doctors if d['id'] == doc_id), None)
        
        if found_doc:
            ctx.selected_doctor_id = doc_id
            ctx.selected_doctor_name = found_doc['name']
            ctx.available_dates_cache = found_doc['dates'] # Сохраняем даты из объекта врача
            
            # Сохраняем тип ресурса и room_id если это кабинет
            resource_type = found_doc.get('type', 'specialist')
            ctx.selected_resource_type = resource_type
            if resource_type == 'room':
                ctx.selected_room_id = found_doc.get('room_id', '')
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
        
        # Определяем SNILS для запроса: для кабинетов используем пустую строку
        resource_type = getattr(ctx, 'selected_resource_type', 'specialist')
        specialist_snils = ctx.selected_doctor_id
        
        # Если это кабинет (ROOM_XXX), используем пустой SNILS
        room_id = None
        if resource_type == 'room' and ctx.selected_doctor_id.startswith('ROOM_'):
            # Для кабинетов используем пустой SNILS
            specialist_snils = ''
            room_id = getattr(ctx, 'selected_room_id', '')
        
        xml = await SoapClient.get_slots(ctx.session_id, specialist_snils, ctx.selected_mo_oid, ctx.selected_post_id, date_str, room_id)
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
            
            # --- Сохранение в БД (New Logic) ---
            try:
                # Определяем источник записи
                booking_src = "self_bot" if ctx.selected_person == "me" else "other_bot"
                
                visit_dt = f"{ctx.selected_date} {ctx.selected_time}"
                
                appointment_data = {
                    "mo_name": mo_name,
                    "doctor_name": ctx.selected_doctor_name,
                    "specialty": ctx.selected_spec,
                    "room_number": ctx.selected_room,
                    "visit_date": ctx.selected_date,
                    "visit_time": ctx.selected_time,
                    "start_time": visit_dt, # Используется db.add_appointment для external_visit_time
                    "patient_fio": getattr(ctx, 'patient_fio', ''),
                    "patient_birthdate": getattr(ctx, 'patient_birthdate', ''),
                    "patient_snils": getattr(ctx, 'patient_snils', ''),
                    "patient_oms": getattr(ctx, 'patient_oms', ''),
                    "patient_gender": getattr(ctx, 'patient_gender', ''),
                    "slot_id": slot_id
                }
                db.add_appointment(user_id, appointment_data, booking_source=booking_src)
            except Exception as e:
                print(f"DB SAVE ERROR: {e}") # Non-blocking error logging

            await bot.send_message(chat_id=chat_id, text=summary, attachments=[kb.kb_final_menu()])
        else:
            await bot.send_message(chat_id=chat_id, text="❌ Ошибка при создании записи. Возможно слот уже занят.", attachments=[kb.kb_final_menu()])
            
        if user_id in user_states:
             del user_states[user_id]
        return
        

# visit_a_doctor/handlers_text_input.py
from visit_a_doctor.handlers import get_or_create_context, show_patient_confirmation
async def handle_text_input(bot, user_id, chat_id, text):
    """Обработка текстового ввода для модуля записи к врачу"""
    ctx = await get_or_create_context(user_id)
    is_self_booking = getattr(ctx, 'selected_person', '') == 'me'

    # Список шагов, где разрешен текстовый ввод
    text_input_steps = ['ENTER_FIO', 'ENTER_BIRTHDATE', 'ENTER_GENDER', 'ENTER_SNILS', 'ENTER_OMS']

    if ctx.step not in text_input_steps:
        await bot.send_message(
            chat_id=chat_id,
            text="⚠️ Вы находитесь в сценарии записи. Нажмите «Назад», пока не выйдете в главное меню, или используйте кнопки на экране."
        )
        return True

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
            await show_patient_confirmation(bot, user_id, chat_id, ctx)
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
            await show_patient_confirmation(bot, user_id, chat_id, ctx)
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

        # После ввода пола проверяем СНИЛС
        if getattr(ctx, 'patient_snils', None):
             # СНИЛС есть, проверяем ОМС
             if getattr(ctx, 'patient_oms', None):
                 # Все есть
                 await show_patient_confirmation(bot, user_id, chat_id, ctx)
                 return True
             else:
                 ctx.step = "ENTER_OMS"
                 await bot.send_message(chat_id=chat_id, text="Введите номер полиса ОМС.")
                 return True

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
            await show_patient_confirmation(bot, user_id, chat_id, ctx)
            return True

        # После ввода СНИЛС проверяем ОМС
        if getattr(ctx, 'patient_oms', None):
             # ОМС есть, все ок
             await show_patient_confirmation(bot, user_id, chat_id, ctx)
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
        await show_patient_confirmation(bot, user_id, chat_id, ctx)
        return True

    return False
