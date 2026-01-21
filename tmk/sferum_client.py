"""
Клиент для работы с MAX API (Sferum)
"""
import os
import asyncio
import aiohttp
from typing import Optional, Dict
from dotenv import load_dotenv

from logging_config import log_system_event

load_dotenv()

SFERUM_ACCESS_TOKEN = os.getenv("SFERUM_ACCESS_TOKEN")
SFERUM_API_URL = "https://ejd-api.sferum-dev.ru/method/educationSchool.createChat"

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
                        SFERUM_API_URL,
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
