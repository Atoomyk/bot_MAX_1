# visit_a_doctor/soap_parser.py
"""
Модуль для парсинга SOAP-ответов от медицинского сервиса.
"""
import xml.etree.ElementTree as ET
from typing import List, Dict, Optional

class SoapResponseParser:
    """Парсер для обработки XML ответов SOAP сервиса"""
    
    @staticmethod
    def parse_session_id(xml_content: str) -> Optional[str]:
        """Парсит Session_ID из любого ответа"""
        try:
            xml_clean = xml_content
            # Пытаемся удалить xmlns через регулярку для упрощения парсинга
            import re
            xml_clean = re.sub(r' xmlns:?[^=]*="[^"]+"', '', xml_clean) # remove xmlns="..."
            xml_clean = re.sub(r'<(\w+):', '<', xml_clean) # remove <prefix:
            xml_clean = re.sub(r'</(\w+):', '</', xml_clean) # remove </prefix:

            root = ET.fromstring(xml_clean)
            
            # Ищем Session_ID (он обычно на верхнем уровне тела ответа)
            # Примитивный поиск по всем тегам, так как неймспейсы могут мешать
            session_id = None
            if "Session_ID" in xml_content:
                # Fallback regex search if XML parsing is struggling with namespaces
                import re
                match = re.search(r'<Session_ID>([^<]+)</Session_ID>', xml_content)
                if match:
                    return match.group(1)
            
            # Попробуем через XML
            # Обычно: Body -> Response -> Session_ID
            # Но неймспейсы сложны. 
            pass 
        except Exception as e:
            print(f"Error parsing Session_ID: {e}")
        return None

    @staticmethod
    def parse_patient_id(xml_content: str) -> Optional[str]:
        """Парсит Patient_Id из GetPatientInfoResponse"""
        import re
        match = re.search(r'<Patient_Id>([^<]+)</Patient_Id>', xml_content)
        return match.group(1) if match else None

    @staticmethod
    def parse_mo_list(xml_content: str) -> List[Dict[str, str]]:
        """Парсит список МО (GetMOInfoExtendedResponse)"""
        mos = []
        try:
            # Очистка namespaces не всегда надежна, используем простой парсинг
            # Находим блок <MO_List>
            root = ET.fromstring(xml_content)
            # Для надежности используем итератор и ищем теги MO
            # Так как в примере <MO_List><MO>...</MO></MO_List>
            # А теги имеют префикс namespace, например ns2:MO
            
            # Простой вариант: найти все вхождения <MO>...</MO> с помощью split/regex
            # Но попробуем все же XML.
            
            # Удаляем namespaces из тегов перед парсингом для простоты
            import re
            xml_clean = re.sub(r' xmlns:?[^=]*="[^"]+"', '', xml_content)
            # также теги могут быть <ns:Tag>, уберем префиксы
            xml_clean = re.sub(r'<(\w+):', '<', xml_clean)
            xml_clean = re.sub(r'</(\w+):', '</', xml_clean)
            
            root = ET.fromstring(xml_clean)
            
            for mo_node in root.findall(".//MO"):
                mo_id = mo_node.find("MO_Id")
                name = mo_node.find("MO_Name")
                oid = mo_node.find("MO_OID")
                address = mo_node.find("MO_Address")
                
                if mo_id is not None and name is not None:
                    mos.append({
                        "id": mo_id.text,
                        "name": name.text,
                        "oid": oid.text if oid is not None else "",
                        "address": address.text if address is not None else ""
                    })

        except Exception as e:
            print(f"Error parsing MO list: {e}")
        return mos

    @staticmethod
    def parse_specialties(xml_content: str) -> List[Dict[str, str]]:
        """Парсит список специальностей (GetServicePostSpecsInfoResponse)"""
        specs = []
        try:
            import re
            xml_clean = re.sub(r' xmlns:?[^=]*="[^"]+"', '', xml_content)
            xml_clean = re.sub(r'<(\w+):', '<', xml_clean)
            xml_clean = re.sub(r'</(\w+):', '</', xml_clean)
            
            root = ET.fromstring(xml_clean)
            
            for post in root.findall(".//Post"):
                post_id = post.find("Post_Id")
                if post_id is not None:
                     specs.append({"id": post_id.text})
                     
        except Exception as e:
            print(f"Error parsing Specs: {e}")
        return specs

    @staticmethod
    def parse_doctors(xml_content: str) -> List[Dict[str, str]]:
        """Парсит список ресурсов (GetMOResourceInfoResponse)"""
        doctors = []
        try:
            import re
            xml_clean = re.sub(r' xmlns:?[^=]*="[^"]+"', '', xml_content)
            xml_clean = re.sub(r'<(\w+):', '<', xml_clean)
            xml_clean = re.sub(r'</(\w+):', '</', xml_clean)
            
            root = ET.fromstring(xml_clean)
            
            # Иерархия: MO_Resource_List -> MO_Available -> Resource_Available -> Resource -> Specialist
            
            for resource in root.findall(".//Resource"):
                specialist = resource.find("Specialist")
                if specialist is not None:
                    last = specialist.find("Last_Name").text
                    first = specialist.find("First_Name").text
                    middle = specialist.find("Middle_Name").text
                    snils = specialist.find("SNILS").text
                    doc_id = specialist.find("SNILS").text # Используем СНИЛС как ID, т.к. Post_Id общий
                    
                    full_name = f"{last} {first[0]}.{middle[0]}."
                    
                    # Собираем доступные даты
                    dates = []
                    avail_dates = resource.find("Available_Dates")
                    if avail_dates is not None:
                         for d in avail_dates.findall("Available_Date"):
                             # 2025-12-19T00:00:00+03:00 -> 19.12.2025
                             raw_date = d.text[:10] # 2025-12-19
                             formatted_date = f"{raw_date[8:10]}.{raw_date[5:7]}.{raw_date[0:4]}"
                             dates.append(formatted_date)
                    
                    if dates: # Добавляем только если есть даты
                        doctors.append({
                            "id": snils, # ID врача для следующих шагов
                            "name": full_name,
                            "dates": dates
                        })

        except Exception as e:
            print(f"Error parsing Doctors: {e}")
        return doctors

    @staticmethod
    def parse_slots(xml_content: str) -> List[Dict[str, str]]:
        """Парсит слоты (GetScheduleInfoResponse)"""
        slots = []
        try:
            import re
            xml_clean = re.sub(r' xmlns:?[^=]*="[^"]+"', '', xml_content)
            xml_clean = re.sub(r'<(\w+):', '<', xml_clean)
            xml_clean = re.sub(r'</(\w+):', '</', xml_clean)
            
            root = ET.fromstring(xml_clean)
            
            for slot in root.findall(".//Slots"):
                slot_id = slot.find("Slot_Id").text
                visit_time = slot.find("VisitTime").text # 2025-12-17T09:15:00+03:00
                room = slot.find("Room").text
                
                # Форматируем время: 09:15
                time_str = visit_time[11:16]
                
                slots.append({
                    "id": slot_id,
                    "time": time_str,
                    "room": room
                })

        except Exception as e:
            print(f"Error parsing Slots: {e}")
        return slots
        
    @staticmethod
    def parse_booking_status(xml_content: str) -> bool:
        """Парсит ответ создания записи (CreateAppointmentResponse)"""
        import re
        match = re.search(r'<Status_Code>([^<]+)</Status_Code>', xml_content)
        if match and match.group(1) == "SUCCESS":
            return True
        return False
