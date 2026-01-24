# API ТМК для МИС

## Endpoints

### POST `/services/telemed`
Создание телемед-консультации

**Headers:**
```
Authorization: Bearer {MIS_API_TOKEN}
Content-Type: application/json
```

**Request:**
```json
{
  "externalId": "string",
  "scheduleDate": "2026-01-25T14:00:00.000+0300",
  "doctor": {
    "firstName": "string",
    "lastName": "string",
    "middleName": "string",
    "specialization": "string",
    "position": "string",
    "SNILS": "string"
  },
  "patient": {
    "firstName": "string",
    "lastName": "string",
    "middleName": "string",
    "birthDate": "YYYY-MM-DD",
    "OMS": {"number": "string", "series": "string"},
    "SNILS": "string",
    "sex": "1|2",
    "phone": "+7XXXXXXXXXX"
  },
  "clinic": {
    "name": "string",
    "address": "string",
    "MO_OID": "string",
    "phone": "string"
  },
  "status": "APPROVED",
  "payMethod": "OMS|DMS|PAID"
}
```

**Success Response (200):**
```json
{
  "status": "success",
  "id": "uuid",
  "externalId": "string",
  "chat_invite_link": "https://max.ru/join/...",
  "message": "Консультация создана"
}
```

**Error Responses:**

| Код | Описание | Ответ |
|-----|----------|-------|
| 401 | Неверный токен | `{"status": "error", "error": "Unauthorized"}` |
| 200 | Дубликат externalId | `{"status": "error", "error": "Duplicate external_id", "message": "Чат с указанным externalId уже существует"}` |
| 200 | Ошибка MAX API | `{"status": "error", "error": "MAX API error", "message": "Не удалось создать чат после 3 попыток"}` |
| 200 | Ошибка БД | `{"status": "error", "error": "Database error", "message": "Ошибка при сохранении в БД"}` |
| 200 | Внутренняя ошибка | `{"status": "error", "error": "...", "message": "Внутренняя ошибка сервера"}` |

---

### PUT `/services/telemed/{external_id}`
Отмена/обновление консультации

**Headers:**
```
Authorization: Bearer {MIS_API_TOKEN}
Content-Type: application/json
```

**Request:**
```json
{
  "scheduleDate": "2026-01-25T14:00:00.000+0300",
  "status": "CANCELLED",
  "doctor": {
    "firstName": "string",
    "lastName": "string",
    "middleName": "string",
    "specialization": "string",
    "position": "string",
    "SNILS": "string"
  }
}
```

**Success Response (200):**
```json
{
  "status": "success",
  "id": "uuid",
  "externalId": "string",
  "message": "Статус обновлён на CANCELLED"
}
```

**Error Responses:**

| Код | Описание | Ответ |
|-----|----------|-------|
| 401 | Неверный токен | `{"status": "error", "error": "Unauthorized"}` |
| 200 | Сессия не найдена | `{"status": "error", "error": "Session not found", "message": "Консультация не найдена"}` |
| 200 | Ошибка БД | `{"status": "error", "error": "Database error", "message": "Ошибка при обновлении статуса"}` |

---

### GET `/health`
Проверка работоспособности

**Response (200):**
```json
{
  "status": "healthy",
  "service": "tmk"
}
```

---

## Форматы данных

**Дата/время:** `YYYY-MM-DDTHH:mm:ss.SSS+TZ` (ISO 8601)
- Пример: `2026-01-25T14:00:00.000+0300`

**Телефон:** `+7XXXXXXXXXX` (11 цифр с +7)

**Пол:** `"1"` - мужской, `"2"` - женский

**Статус:** `APPROVED` | `CANCELLED`

**Оплата:** `OMS` | `DMS` | `PAID`

**ОМС:** 
- Новый формат: только `number` (16 цифр)
- Старый формат: `number` + `series`

---

## Обработка ошибок

Все ошибки возвращаются с HTTP 200, проверяйте поле `status`:
- `"success"` - операция успешна
- `"error"` - произошла ошибка (см. поле `error`)

**Типы ошибок:**
- `Unauthorized` - неверный токен авторизации
- `Duplicate external_id` - консультация с таким externalId уже существует
- `MAX API error` - не удалось создать чат (3 попытки)
- `Database error` - ошибка работы с БД
- `Session not found` - консультация не найдена
- `Internal server error` - внутренняя ошибка сервера

---

## Примечания

1. `externalId` должен быть уникальным
2. При отмене (`CANCELLED`) пациент получает уведомление автоматически
3. Напоминания отправляются автоматически (за 24ч и 15м до консультации)
4. Если пациент не найден по телефону, консультация всё равно создаётся, но сообщения не отправляются
