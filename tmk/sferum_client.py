"""
Клиент для работы с MAX API (Sferum)
"""
import os
import asyncio
import aiohttp
import json
from typing import Optional, Dict
from dotenv import load_dotenv

from logging_config import log_system_event
from tmk.utils import normalize_phone

load_dotenv()

SFERUM_ACCESS_TOKEN = os.getenv("SFERUM_ACCESS_TOKEN")
SFERUM_CREATE_CHAT_URL = "https://ejd-api.sferum-dev.ru/method/educationSchool.createChat"
SFERUM_ADD_CHAT_USERS_URL = "https://ejd-api.sferum-dev.ru/method/educationSchool.addChatUsers"
SFERUM_CALL_START_URL = "https://ejd-api.sferum-dev.ru/method/educationSchool.callStart"

MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 60


class SferumClient:
    """Клиент для взаимодействия с MAX API"""
    
    @staticmethod
    async def create_telemedicine_chat(
        doctor_fio: str,
        patient_fio: str
    ) -> Optional[Dict[str, any]]:
        """
        Создание чата телемедицинской консультации
        
        Args:
            doctor_fio: ФИО врача
            patient_fio: ФИО пациента
            
        Returns:
            Словарь с chat_id и invite_link или None при ошибке
        """
        chat_title = f"Телемедконсультация: врач {doctor_fio} – пациент {patient_fio}"
        
        data = {
            "access_token": SFERUM_ACCESS_TOKEN,
            "type": "telemedicine",
            "chat_title": chat_title
        }
        
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                log_system_event(
                    "sferum_client", 
                    "create_chat_attempt",
                    attempt=attempt,
                    chat_title=chat_title
                )
                
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        SFERUM_CREATE_CHAT_URL,
                        data=data,
                        headers={"Content-Type": "application/x-www-form-urlencoded"}
                    ) as response:
                        result = await response.json()
                        
                        # Проверка на успешный ответ
                        if "response" in result:
                            chat_data = {
                                "chat_id": result["response"]["chat_id"],
                                "invite_link": result["response"]["invite_link"],
                                "all_can_post": result["response"].get("all_can_post", True)
                            }
                            
                            log_system_event(
                                "sferum_client",
                                "chat_created_successfully",
                                chat_id=chat_data["chat_id"],
                                invite_link=chat_data["invite_link"]
                            )
                            
                            return chat_data
                        
                        # Ошибка от API
                        elif "error" in result:
                            error_code = result["error"].get("error_code", "unknown")
                            error_msg = result["error"].get("error_msg", "Unknown error")
                            
                            log_system_event(
                                "sferum_client",
                                "api_error",
                                attempt=attempt,
                                error_code=error_code,
                                error_msg=error_msg
                            )
                            
                            # Если последняя попытка - возвращаем None
                            if attempt == MAX_RETRIES:
                                return None
                            
                            # Ждём перед следующей попыткой
                            await asyncio.sleep(RETRY_DELAY_SECONDS)
                        
                        else:
                            log_system_event(
                                "sferum_client",
                                "unexpected_response",
                                attempt=attempt,
                                response=str(result)
                            )
                            
                            if attempt == MAX_RETRIES:
                                return None
                            
                            await asyncio.sleep(RETRY_DELAY_SECONDS)
            
            except aiohttp.ClientError as e:
                log_system_event(
                    "sferum_client",
                    "network_error",
                    attempt=attempt,
                    error=str(e)
                )
                
                if attempt == MAX_RETRIES:
                    return None
                
                await asyncio.sleep(RETRY_DELAY_SECONDS)
            
            except Exception as e:
                log_system_event(
                    "sferum_client",
                    "unexpected_error",
                    attempt=attempt,
                    error=str(e)
                )
                
                if attempt == MAX_RETRIES:
                    return None
                
                await asyncio.sleep(RETRY_DELAY_SECONDS)
        
        return None

    @staticmethod
    async def add_doctor_as_admin(
        chat_id: int,
        doctor_phone: str
    ) -> bool:
        """
        Добавление врача в чат как администратора
        
        Args:
            chat_id: ID чата телемедицины
            doctor_phone: Телефон врача (как приходит из МИС)
        
        Returns:
            True если добавление прошло успешно, False при ошибке
        """
        if not doctor_phone:
            log_system_event(
                "sferum_client",
                "add_doctor_missing_phone",
                chat_id=chat_id
            )
            return False

        # Приводим телефон к формату, ожидаемому Sferum: число без плюса
        normalized = normalize_phone(doctor_phone)  # +7XXXXXXXXXX
        phone_digits = "".join(filter(str.isdigit, normalized))

        users_payload = [
            {
                "phone": phone_digits,
                "chat_role": "teacher",
                "member_role": "admin",
            }
        ]

        data = {
            "access_token": SFERUM_ACCESS_TOKEN,
            "chat_id": chat_id,
            "users": json.dumps(users_payload, ensure_ascii=False),
        }

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                log_system_event(
                    "sferum_client",
                    "add_doctor_as_admin_attempt",
                    attempt=attempt,
                    chat_id=chat_id,
                    phone=phone_digits,
                )

                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        SFERUM_ADD_CHAT_USERS_URL,
                        data=data,
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                    ) as response:
                        result = await response.json()

                        if "response" in result:
                            failed = result["response"].get("failed_users", [])
                            queued = result["response"].get("queued_users", [])

                            log_system_event(
                                "sferum_client",
                                "add_doctor_as_admin_response",
                                chat_id=chat_id,
                                failed_users=str(failed),
                                queued_users=str(queued),
                            )

                            # Считаем успехом даже queued_users (врач будет добавлен, когда появится в MAX)
                            if not failed:
                                return True

                            # Если есть failed_users, повторять смысла нет
                            return False

                        elif "error" in result:
                            error_code = result["error"].get("error_code", "unknown")
                            error_msg = result["error"].get("error_msg", "Unknown error")

                            log_system_event(
                                "sferum_client",
                                "add_doctor_as_admin_api_error",
                                attempt=attempt,
                                chat_id=chat_id,
                                error_code=error_code,
                                error_msg=error_msg,
                            )

                            if attempt == MAX_RETRIES:
                                return False

                            await asyncio.sleep(RETRY_DELAY_SECONDS)
                        else:
                            log_system_event(
                                "sferum_client",
                                "add_doctor_as_admin_unexpected_response",
                                attempt=attempt,
                                chat_id=chat_id,
                                response=str(result),
                            )

                            if attempt == MAX_RETRIES:
                                return False

                            await asyncio.sleep(RETRY_DELAY_SECONDS)

            except aiohttp.ClientError as e:
                log_system_event(
                    "sferum_client",
                    "add_doctor_as_admin_network_error",
                    attempt=attempt,
                    chat_id=chat_id,
                    error=str(e),
                )

                if attempt == MAX_RETRIES:
                    return False

                await asyncio.sleep(RETRY_DELAY_SECONDS)

            except Exception as e:
                log_system_event(
                    "sferum_client",
                    "add_doctor_as_admin_unexpected_error",
                    attempt=attempt,
                    chat_id=chat_id,
                    error=str(e),
                )

                if attempt == MAX_RETRIES:
                    return False

                await asyncio.sleep(RETRY_DELAY_SECONDS)

        return False

    @staticmethod
    async def start_call(chat_id: int) -> Optional[Dict[str, any]]:
        """
        Создание звонка в чате телемедицины (educationSchool.callStart).

        Args:
            chat_id: ID чата телемедицины

        Returns:
            Словарь с join_link, call_id, chat_id или None при ошибке
        """
        data = {
            "access_token": SFERUM_ACCESS_TOKEN,
            "chat_id": chat_id,
        }

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                log_system_event(
                    "sferum_client",
                    "call_start_attempt",
                    attempt=attempt,
                    chat_id=chat_id,
                )

                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        SFERUM_CALL_START_URL,
                        data=data,
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                    ) as response:
                        result = await response.json()

                        if "response" in result:
                            call_data = {
                                "join_link": result["response"].get("join_link"),
                                "call_id": result["response"].get("call_id"),
                                "chat_id": result["response"].get("chat_id"),
                            }
                            log_system_event(
                                "sferum_client",
                                "call_started_successfully",
                                chat_id=chat_id,
                                call_id=call_data.get("call_id"),
                            )
                            return call_data

                        elif "error" in result:
                            error_code = result["error"].get("error_code", "unknown")
                            error_msg = result["error"].get("error_msg", "Unknown error")
                            log_system_event(
                                "sferum_client",
                                "call_start_api_error",
                                attempt=attempt,
                                chat_id=chat_id,
                                error_code=error_code,
                                error_msg=error_msg,
                            )
                            if attempt == MAX_RETRIES:
                                return None
                            await asyncio.sleep(RETRY_DELAY_SECONDS)
                        else:
                            log_system_event(
                                "sferum_client",
                                "call_start_unexpected_response",
                                attempt=attempt,
                                chat_id=chat_id,
                                response=str(result),
                            )
                            if attempt == MAX_RETRIES:
                                return None
                            await asyncio.sleep(RETRY_DELAY_SECONDS)

            except aiohttp.ClientError as e:
                log_system_event(
                    "sferum_client",
                    "call_start_network_error",
                    attempt=attempt,
                    chat_id=chat_id,
                    error=str(e),
                )
                if attempt == MAX_RETRIES:
                    return None
                await asyncio.sleep(RETRY_DELAY_SECONDS)
            except Exception as e:
                log_system_event(
                    "sferum_client",
                    "call_start_unexpected_error",
                    attempt=attempt,
                    chat_id=chat_id,
                    error=str(e),
                )
                if attempt == MAX_RETRIES:
                    return None
                await asyncio.sleep(RETRY_DELAY_SECONDS)

        return None
