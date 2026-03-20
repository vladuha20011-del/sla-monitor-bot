"""
Клиент для работы с Jira API
Адаптирован для поиска задач с приближающимся SLA
Поддерживает стандартные поля и кастомные SLA поля (customfield_10611)
"""

import socket
import aiohttp
import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple

import config

logger = logging.getLogger(__name__)

class TaskAPIClient:
    """Клиент для получения задач из Jira"""
    
    def __init__(self):
        self.base_url = config.API_URL.rstrip('/')
        self.api_token = config.API_TOKEN
        self.timeout = aiohttp.ClientTimeout(total=config.API_TIMEOUT)
    
    async def get_tasks(self, max_results: int = 500) -> List[Dict[str, Any]]:
        """
        Получает список активных задач из Jira с приближающимся SLA
        Теперь получает до 500 задач и включает нужные статусы
        """
        try:
            api_endpoint = f"{self.base_url}/rest/api/2/search"
            
            # JQL запрос для поиска активных задач в проекте ZZ
            # Включаем нужные статусы: Ожидание поддержки, В процессе, Передано партнеру
            jql_query = f'''
            project = ZZ 
            AND status IN ("Ожидание поддержки", "В процессе", "Передано партнеру")
            ORDER BY created DESC
            '''
            
            params = {
                "jql": jql_query.strip(),
                "maxResults": max_results,  # Увеличиваем до 500
                "fields": [
                    "summary", 
                    "assignee", 
                    "duedate", 
                    "status", 
                    "priority", 
                    "description", 
                    "created",
                    "updated",
                    "customfield_10611",  # SLA время до решения
                    "customfield_10612",  # SLA время до первого отклика
                    "customfield_10303",  # slaTargetDate
                    "customfield_10305",  # slaEndDate
                    "customfield_10606",  # Service Desk данные
                    "customfield_11502",  # Дополнительное описание
                ]
            }
            
            headers = {
                "Authorization": f"Bearer {self.api_token}",
                "Accept": "application/json"
            }
            
            logger.info(f"📡 Запрос к Jira API: {api_endpoint}")
            logger.info(f"📋 JQL: {jql_query.strip()}")
            
            # Принудительное использование IPv6
            connector = aiohttp.TCPConnector(family=socket.AF_INET6)
            
            async with aiohttp.ClientSession(connector=connector, timeout=self.timeout) as session:
                async with session.get(
                    api_endpoint, 
                    headers=headers,
                    params=params
                ) as response:
                    
                    if response.status == 200:
                        data = await response.json()
                        tasks = self._parse_jira_response(data)
                        
                        total = data.get('total', 0)
                        logger.info(f"✅ Найдено задач в Jira: {total}")
                        logger.info(f"📦 Получено задач с SLA: {len(tasks)}")
                        
                        return tasks
                    else:
                        logger.error(f"❌ Ошибка Jira API: статус {response.status}")
                        error_text = await response.text()
                        logger.error(f"Ответ: {error_text[:500]}")
                        return []
                        
        except asyncio.TimeoutError:
            logger.error("❌ Таймаут при запросе к Jira API")
            return []
        except Exception as e:
            logger.error(f"❌ Ошибка при запросе к Jira API: {e}", exc_info=True)
            return []
    
    def _parse_jira_response(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Преобразует ответ Jira API в единый формат задач
        """
        tasks = []
        issues = data.get('issues', [])
        
        # Используем UTC время для сравнения (без часового пояса)
        now = datetime.now()
        warning_hours = getattr(config, 'SLA_HOURS', 24)
        
        for issue in issues:
            try:
                fields = issue.get('fields')
                if fields is None:
                    continue
                
                # Получаем исполнителя
                assignee_data = fields.get('assignee')
                assignee = self._extract_assignee(assignee_data)
                
                # Получаем дату SLA из всех возможных источников
                due_date, sla_source = self._extract_sla_date(fields)
                
                # Если нет SLA даты - пропускаем задачу
                if not due_date:
                    continue
                
                # Приводим due_date к naive datetime (без часового пояса) для сравнения
                if due_date.tzinfo is not None:
                    # Если дата с часовым поясом, конвертируем в naive UTC
                    due_date = due_date.replace(tzinfo=None)
                
                # Рассчитываем время до дедлайна
                time_diff = due_date - now
                hours_until_due = time_diff.total_seconds() / 3600
                
                # Проверяем, попадает ли задача в интервал предупреждения
                # Уведомляем если задача критична (менее 24ч) ИЛИ просрочена
                should_notify = False
                if hours_until_due <= warning_hours:  # Уведомляем если осталось меньше 24ч ИЛИ просрочено
                    should_notify = True
                    if hours_until_due < 0:
                        logger.info(f"⚠️ Задача {issue.get('key')}: ПРОСРОЧЕНА на {abs(hours_until_due):.1f}ч (источник: {sla_source})")
                    else:
                        logger.info(f"⚠️ Задача {issue.get('key')}: до дедлайна {hours_until_due:.1f}ч (источник: {sla_source})")
                
                # Создаем задачу в нашем формате
                task = {
                    "id": issue.get('key'),
                    "key": issue.get('key'),
                    "title": fields.get('summary', 'Без названия'),
                    "description": fields.get('description', ''),
                    "assignee": assignee,
                    "assignee_email": assignee_data.get('emailAddress') if assignee_data else None,
                    "assignee_username": assignee_data.get('name') if assignee_data else None,
                    "assignee_display": assignee_data.get('displayName') if assignee_data else None,
                    "due_date": due_date,
                    "due_date_source": sla_source,
                    "hours_until_due": hours_until_due,
                    "should_notify": should_notify,
                    "created": fields.get('created'),
                    "updated": fields.get('updated'),
                    "status": fields.get('status', {}).get('name') if fields.get('status') else 'Неизвестно',
                    "status_id": fields.get('status', {}).get('id') if fields.get('status') else None,
                    "priority": fields.get('priority', {}).get('name') if fields.get('priority') else None,
                    "url": f"{self.base_url}/browse/{issue.get('key')}",
                    "sla_raw": fields.get('customfield_10611'),  # Сырые данные SLA для отладки
                    "raw_data": issue
                }
                
                tasks.append(task)
                
                # Логируем для отладки
                logger.debug(f"📅 {task['id']}: {task['title'][:30]}... | Дедлайн: {due_date.strftime('%d.%m.%Y %H:%M')} | Осталось: {hours_until_due:.1f}ч | Исп: {task['assignee']}")
                
            except Exception as e:
                logger.warning(f"Ошибка при парсинге задачи {issue.get('key')}: {e}")
                continue
        
        return tasks
    
    def _extract_assignee(self, assignee_data: Optional[Dict]) -> str:
        """Извлекает имя исполнителя"""
        if not assignee_data:
            return "Не назначен"
        
        return assignee_data.get('displayName', 'Не назначен')
    
    def _extract_sla_date(self, fields: Dict) -> Tuple[Optional[datetime], str]:
        """
        Извлекает дату SLA из разных возможных полей Jira
        Возвращает (дата, источник)
        """
        
        # 1. Проверяем стандартное поле duedate
        due_date = fields.get('duedate')
        if due_date:
            parsed = self._parse_date(due_date)
            if parsed:
                return parsed, "duedate"
        
        # 2. Проверяем SLA поле customfield_10611 (время до решения)
        sla_data = fields.get('customfield_10611')
        if sla_data and isinstance(sla_data, dict):
            # Проверяем текущий цикл SLA
            ongoing_cycle = sla_data.get('ongoingCycle')
            if ongoing_cycle:
                breach_time = ongoing_cycle.get('breachTime', {})
                if breach_time:
                    iso_date = breach_time.get('iso8601')
                    if iso_date:
                        parsed = self._parse_date(iso_date)
                        if parsed:
                            return parsed, "customfield_10611 (SLA решение)"
            
            # Проверяем завершенные циклы (на всякий случай)
            completed_cycles = sla_data.get('completedCycles', [])
            if completed_cycles:
                for cycle in completed_cycles:
                    stop_time = cycle.get('stopTime', {})
                    if stop_time:
                        iso_date = stop_time.get('iso8601')
                        if iso_date:
                            parsed = self._parse_date(iso_date)
                            if parsed:
                                return parsed, "customfield_10611 (completed)"
        
        # 3. Проверяем SLA поле customfield_10612 (время до первого отклика)
        sla_data2 = fields.get('customfield_10612')
        if sla_data2 and isinstance(sla_data2, dict):
            ongoing_cycle = sla_data2.get('ongoingCycle')
            if ongoing_cycle:
                breach_time = ongoing_cycle.get('breachTime', {})
                if breach_time:
                    iso_date = breach_time.get('iso8601')
                    if iso_date:
                        parsed = self._parse_date(iso_date)
                        if parsed:
                            return parsed, "customfield_10612 (SLA отклик)"
        
        # 4. Проверяем другие SLA поля
        other_sla_fields = ['customfield_10303', 'customfield_10305', 'customfield_11717']
        for field in other_sla_fields:
            value = fields.get(field)
            if value:
                if isinstance(value, dict):
                    # Если словарь, ищем поле с датой
                    for key in ['iso8601', 'date', 'value', 'endDate']:
                        if key in value and value[key]:
                            parsed = self._parse_date(str(value[key]))
                            if parsed:
                                return parsed, f"{field}"
                else:
                    # Если строка, пробуем распарсить
                    parsed = self._parse_date(str(value))
                    if parsed:
                        return parsed, field
        
        return None, "не найдено"
    
    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """Парсит дату из различных форматов и возвращает naive datetime (без часового пояса)"""
        if not date_str:
            return None
        
        # Убираем лишние пробелы
        date_str = str(date_str).strip()
        
        # Форматы для парсинга
        formats = [
            "%Y-%m-%d",                          # 2024-03-14
            "%Y-%m-%dT%H:%M:%S.%f%z",            # 2026-03-14T03:19:47.639+0300
            "%Y-%m-%dT%H:%M:%S%z",                # 2026-03-14T03:19:47+0300
            "%Y-%m-%dT%H:%M:%S",                  # 2026-03-14T03:19:47
            "%Y-%m-%d %H:%M:%S",                  # 2024-03-14 15:30:00
            "%d.%m.%Y %H:%M",                     # 14.03.2024 15:30
            "%d.%m.%Y",                           # 14.03.2024
            "%Y/%m/%d %H:%M:%S",                  # 2024/03/14 15:30:00
            "%Y/%m/%d",                           # 2024/03/14
            "%d/%m/%Y %H:%M",                     # 14/03/2024 15:30
        ]
        
        # Для форматов с часовым поясом (+0300) нужно особое внимание
        for fmt in formats:
            try:
                # Пробуем стандартный парсинг
                dt = datetime.strptime(date_str, fmt)
                # Если получилось и это naive datetime (без часового пояса) - возвращаем как есть
                return dt
            except ValueError:
                continue
        
        # Специальная обработка для форматов с часовым поясом
        try:
            # Пробуем распарсить с помощью dateutil если есть, но мы сделаем вручную
            if '+0300' in date_str or '+03:00' in date_str:
                # Убираем часовой пояс для простоты (все равно нам нужно только время)
                date_str_clean = date_str.replace('+0300', '').replace('+03:00', '')
                for fmt in ["%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"]:
                    try:
                        return datetime.strptime(date_str_clean, fmt)
                    except ValueError:
                        continue
        except Exception:
            pass
        
        logger.debug(f"Не удалось распарсить дату: {date_str}")
        return None
    
    async def get_task_by_key(self, task_key: str) -> Optional[Dict]:
        """Получить задачу по ключу напрямую из API"""
        try:
            url = f"{self.base_url}/rest/api/2/issue/{task_key}"
            headers = {
                "Authorization": f"Bearer {self.api_token}",
                "Accept": "application/json"
            }
            
            logger.info(f"🔍 Прямой запрос задачи {task_key}")
            
            # Принудительное использование IPv6 и для прямых запросов
            connector = aiohttp.TCPConnector(family=socket.AF_INET6)
            
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        logger.info(f"✅ Задача {task_key} найдена")
                        return data
                    else:
                        logger.error(f"❌ Ошибка получения задачи {task_key}: статус {response.status}")
                        return None
        except Exception as e:
            logger.error(f"❌ Ошибка получения задачи {task_key}: {e}")
            return None


# Для тестирования
async def test_jira_client():
    """Тестовая функция"""
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    print("\n" + "=" * 80)
    print("🔍 ТЕСТИРОВАНИЕ ПОИСКА ЗАДАЧ С SLA")
    print("=" * 80)
    
    client = TaskAPIClient()
    
    print("\n📥 Получение задач из Jira...")
    tasks = await client.get_tasks(max_results=500)
    
    # Статистика
    total = len(tasks)
    with_sla = [t for t in tasks if t['due_date']]
    urgent = [t for t in tasks if t.get('should_notify')]
    overdue = [t for t in tasks if t.get('hours_until_due', 0) < 0]
    
    print(f"\n📊 Статистика:")
    print(f"   Всего получено задач: {total}")
    print(f"   Задач с SLA датой: {len(with_sla)}")
    print(f"   Требуют уведомления: {len(urgent)}")
    print(f"   Просрочено: {len(overdue)}")
    
    if urgent:
        print(f"\n📋 ЗАДАЧИ ДЛЯ УВЕДОМЛЕНИЯ:")
        print("-" * 80)
        
        for i, task in enumerate(urgent[:10], 1):
            hours = task['hours_until_due']
            if hours < 0:
                status = "⚠️ ПРОСРОЧЕНО"
                time_str = f"на {abs(hours):.1f}ч"
            else:
                status = "🔴 Критично" if hours < 12 else "🟡 Скоро"
                time_str = f"{hours:.1f}ч"
            
            print(f"\n{i}. {task['id']} - {task['title'][:50]}")
            print(f"   Статус: {status}")
            print(f"   Осталось: {time_str}")
            print(f"   Исполнитель: {task['assignee']}")
    
    else:
        print(f"\n❌ Задач для уведомления не найдено.")
    
    print("\n" + "=" * 80)
    
    # Проверим конкретную задачу, если передали аргумент
    import sys
    if len(sys.argv) > 1:
        task_key = sys.argv[1]
        print(f"\n🔍 Проверка задачи {task_key}...")
        task_data = await client.get_task_by_key(task_key)
        if task_data:
            print(f"✅ Задача найдена!")
            fields = task_data.get('fields', {})
            print(f"   Статус: {fields.get('status', {}).get('name')}")
            print(f"   Исполнитель: {fields.get('assignee', {}).get('displayName', 'Не назначен')}")
        else:
            print(f"❌ Задача не найдена")


if __name__ == "__main__":
    asyncio.run(test_jira_client())
