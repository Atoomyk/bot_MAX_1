import json
import os
import aiohttp
import logging
from typing import List, Dict, Optional
from dotenv import load_dotenv

load_dotenv()

PATIENT_API_URL = os.getenv("PATIENT_API_URL")
PATIENT_API_USER = os.getenv("PATIENT_API_USER")
PATIENT_API_PASSWORD = os.getenv("PATIENT_API_PASSWORD")

logger = logging.getLogger(__name__)

async def get_patients_by_phone(phone: str) -> List[Dict[str, str]]:
    """
    Запрашивает данные пациентов по номеру телефона.
    Возвращает список словарей с нормализованными данными.
    """
    if not PATIENT_API_URL or not PATIENT_API_USER or not PATIENT_API_PASSWORD:
        logger.warning("Patient API configuration missing in .env")
        return []

    # Нормализация телефона: API ожидает 10 цифр (без +7/8)
    clean_phone = ''.join(filter(str.isdigit, phone))
    if len(clean_phone) == 11 and (clean_phone.startswith('7') or clean_phone.startswith('8')):
        clean_phone = clean_phone[1:]
    elif len(clean_phone) != 10:
        logger.warning(f"Invalid phone format for API: {phone}")
        return []

    url = f"{PATIENT_API_URL}"
    params = {'phone': clean_phone}
    auth = aiohttp.BasicAuth(login=PATIENT_API_USER, password=PATIENT_API_PASSWORD)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, auth=auth, timeout=10) as response:
                if response.status != 200:
                    logger.error(f"Patient API error: status {response.status}")
                    return []
                
                try:
                    # Используем utf-8-sig для обработки BOM
                    text_data = await response.text(encoding='utf-8-sig')
                    data = json.loads(text_data)
                except Exception as e:
                     logger.error(f"Failed to parse Patient API response: {e}")
                     return []

                if not isinstance(data, list):
                    logger.warning(f"Patient API returned unexpected format: {type(data)}")
                    return []

                results = []
                for item in data:
                    try:
                        # Склеиваем ФИО
                        last_name = item.get("LastName", "").strip()
                        first_name = item.get("FirstName", "").strip()
                        father_name = item.get("FatherName", "").strip()
                        fio = f"{last_name} {first_name} {father_name}".strip()

                        # Обработка пола "1" - М, "2" - Ж
                        sex_code = item.get("Sex", "")
                        gender = None
                        if sex_code == "1":
                            gender = "Мужской"
                        elif sex_code == "2":
                            gender = "Женский"

                        patient = {
                            "fio": fio,
                            "birth_date": item.get("Birthday", ""),
                            "snils": item.get("Snils", ""),
                            "oms": item.get("PolicyOmsNumber", ""),
                            "gender": gender,
                            # Сохраняем и сырые данные на всякий случай
                            "raw_id": item.get("UniqueId", "") 
                        }
                        results.append(patient)
                    except Exception as parse_error:
                        logger.error(f"Error parsing patient item: {parse_error}")
                        continue
                
                return results

    except Exception as e:
        logger.exception(f"Patient API request failed: {e}")
        return []
