# visit_a_doctor/keyboards.py
"""
Генераторы клавиатур для сценария записи к врачу.
Обновлено для работы с динамическими данными (SOAP).
"""
from bot_utils import create_keyboard
from visit_a_doctor.constants import get_available_dates, get_slots_for_date
from visit_a_doctor.specialties_MO import Abbreviations_MO

def get_back_button(payload):
    return {'type': 'callback', 'text': '⬅️ Назад', 'payload': payload}

def kb_person_selection():
    """Шаг 1: Кого записать"""
    buttons = [
        [{'type': 'callback', 'text': 'Записать себя', 'payload': 'doc_person_me'}],
        [{'type': 'callback', 'text': 'Записать другого человека', 'payload': 'doc_person_other'}],
        [get_back_button('back_to_main')]
    ]
    return create_keyboard(buttons)

def kb_mo_selection(medical_organizations):
    """
    Шаг 2: Выбор МО
    :param medical_organizations: list[dict] {'id': str, 'name': str}
    """
    buttons = []
    if not medical_organizations:
        return None

    for mo in medical_organizations:
        # 1. Сначала пробуем найти сокращение в словаре
        name = Abbreviations_MO.get(mo['name'], mo['name'])
        
        # 2. Если все еще длинное (и не было в словаре или сокращение тоже длинное), режем
        if len(name) > 60:
             name = name[:60] + '..'
             
        buttons.append([
            {'type': 'callback', 'text': name, 'payload': f"doc_mo_{mo['id']}"}
        ])
    buttons.append([get_back_button('doc_back_to_person')])
    return create_keyboard(buttons)

def kb_spec_selection(specialties, page=0, page_size=6):
    """
    Шаг 3: Выбор специализации (с пагинацией)
    :param specialties: list[dict] {'id': str, 'name': str}
    """
    total_specs = len(specialties)
    start_index = page * page_size
    end_index = min(start_index + page_size, total_specs)
    
    current_specs = specialties[start_index:end_index]
    
    buttons = []
    for spec in current_specs:
        buttons.append([
            {'type': 'callback', 'text': spec['name'], 'payload': f"doc_spec_{spec['id']}"}
        ])
    
    # Кнопки пагинации
    nav_row = []
    if page > 0:
        nav_row.append({'type': 'callback', 'text': '⬅️ Пред.', 'payload': f"doc_spec_page_{page-1}"})
    if end_index < total_specs:
        nav_row.append({'type': 'callback', 'text': 'След. ➡️', 'payload': f"doc_spec_page_{page+1}"})
    
    if nav_row:
        buttons.append(nav_row)
        
    buttons.append([get_back_button('doc_back_to_mo')])
    return create_keyboard(buttons)

def kb_doctor_selection(doctors):
    """
    Шаг 4: Выбор врача
    :param doctors: list[dict] {'id': str, 'name': str}
    """
    buttons = []
    
    if not doctors:
        return None
        
    for doctor in doctors:
        buttons.append([
            {'type': 'callback', 'text': f"{doctor['name']}", 'payload': f"doc_doc_{doctor['id']}"}
        ])
    
    buttons.append([get_back_button('doc_back_to_spec')])
    return create_keyboard(buttons)

def kb_date_selection(dates, page=0, page_size=6):
    """
    Шаг 5: Выбор даты (с пагинацией)
    :param dates: list[str] "DD.MM.YYYY"
    """
    total_dates = len(dates)
    
    start_index = page * page_size
    end_index = min(start_index + page_size, total_dates)
    
    current_dates = dates[start_index:end_index]
    
    buttons = []
    if not dates:
        return None
        
    for date_str in current_dates:
        # Для SOAP кнопки могут быть просто датой
        buttons.append([
            {'type': 'callback', 'text': date_str, 'payload': f"doc_date_{date_str}"}
        ])
        
    # Кнопки пагинации
    nav_row = []
    if page > 0:
        nav_row.append({'type': 'callback', 'text': '⬅️ Пред.', 'payload': f"doc_date_page_{page-1}"})
    if end_index < total_dates:
        nav_row.append({'type': 'callback', 'text': 'След. ➡️', 'payload': f"doc_date_page_{page+1}"})
    
    if nav_row:
        buttons.append(nav_row)
        
    buttons.append([get_back_button('doc_back_to_doc')])
    return create_keyboard(buttons)

def kb_time_selection(slots, page=0, page_size=10):
    """
    Шаг 6: Выбор времени (с пагинацией)
    :param slots: list[dict] {'id': str, 'time': str, 'room': str}
    """
    total_slots = len(slots)
    
    start_index = page * page_size
    end_index = min(start_index + page_size, total_slots)
    
    current_slots = slots[start_index:end_index]
    
    buttons = []
    if not slots:
        return None
        
    for slot in current_slots:
        # payload: doc_time_SLOT_ID
        buttons.append([
            {'type': 'callback', 'text': slot['time'], 'payload': f"doc_time_{slot['id']}"}
        ])
        
    # Кнопки пагинации
    nav_row = []
    if page > 0:
        nav_row.append({'type': 'callback', 'text': '⬅️ Пред.', 'payload': f"doc_time_page_{page-1}"})
    if end_index < total_slots:
        nav_row.append({'type': 'callback', 'text': 'След. ➡️', 'payload': f"doc_time_page_{page+1}"})
    
    if nav_row:
        buttons.append(nav_row)
        
    buttons.append([get_back_button('doc_back_to_date')])
    return create_keyboard(buttons)

# Gender selection now handled via text input

def kb_confirm_patient_data(is_self_booking=False):
    """Подтверждение данных пациента
    :param is_self_booking: Если True, скрываем кнопки редактирования ФИО и ДР
    """
    buttons = [
        [{'type': 'callback', 'text': '✅ Все верно, продолжить', 'payload': 'doc_confirm_patient_data'}],
    ]
    
    # Показываем кнопки редактирования только если это не запись себя
    if not is_self_booking:
        buttons.extend([
            [{'type': 'callback', 'text': '✏️ Изменить ФИО', 'payload': 'doc_edit_fio'}],
            [{'type': 'callback', 'text': '✏️ Изменить Дату рождения', 'payload': 'doc_edit_birthdate'}],
        ])
    
    # Кнопки для СНИЛС и ОМС показываем всегда
    buttons.extend([
        [{'type': 'callback', 'text': '✏️ Изменить СНИЛС', 'payload': 'doc_edit_snils'}],
        [{'type': 'callback', 'text': '✏️ Изменить Полис', 'payload': 'doc_edit_oms'}],
    ])
    
    return create_keyboard(buttons)

def kb_confirm_appointment():
    """Финальное подтверждение записи"""
    buttons = [
        [{'type': 'callback', 'text': '✅ Подтвердить запись', 'payload': 'doc_confirm_booking'}],
        [{'type': 'callback', 'text': '🔄 Начать сначала', 'payload': 'doc_restart'}]
    ]
    return create_keyboard(buttons)

def kb_final_menu():
    """Меню после успешной записи"""
    buttons = [
        [{'type': 'callback', 'text': '🏠 Главное меню', 'payload': 'back_to_main'}]
    ]
    return create_keyboard(buttons)
