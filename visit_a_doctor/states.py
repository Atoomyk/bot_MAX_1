# visit_a_doctor/states.py
"""
Управление состоянием пользователя для сценария записи к врачу
"""
from dataclasses import dataclass
from typing import Optional

@dataclass
class UserContext:
    user_id: int
    step: str = "INIT"  # INIT, PERSON, MO, SPEC, DOCTOR, DATE, TIME, CONFIRM
    return_to_confirm: bool = False # Флаг режима редактирования
    
    # Данные выбора
    selected_person: str = "" # "me" or "other"
    selected_mo_id: str = ""
    selected_spec: str = ""
    selected_doctor_id: str = ""
    selected_doctor_name: str = "" # Сохраняем ФИО врача
    selected_date: str = ""
    selected_time: str = ""
    
    # SOAP Context
    session_id: str = ""
    selected_mo_oid: str = ""
    selected_post_id: str = ""
    selected_slot_id: str = "" # ID слота для записи
    selected_room: str = "" # Кабинет
    available_dates_cache: list = None # Кэш дат для врача
    available_slots_cache: list = None # Кэш слотов (id, time)
    
    # Данные пациента (если selected_person == "other")
    patient_fio: str = ""
    patient_birthdate: str = ""
    patient_gender: str = ""
    patient_snils: str = ""
    patient_oms: str = ""
    
    # Пагинация
    spec_page: int = 0
    date_page: int = 0
    time_page: int = 0
