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
        """
        try:
            api_endpoint = f"{self.base_url}/rest/api/2/search"
            
            jql_query = f'''
            project = ZZ 
            AND status IN ("Ожидание поддержки", "В процессе", "Передано партнеру")
            ORDER BY created DESC
            '''
            
            params = {
                "jql": jql_query.strip(),
                "maxResults": max_results,
                "fields": [
                    "summary", 
                    "assignee", 
                    "duedate", 
                    "status", 
                    "priority", 
                    "description", 
                    "created",
                    "updated",
                    "customfield_10611",
                    "customfield_10612",
                    "customfield_10303",
                    "customfield_10305",
                    "customfield_10606",
                    "customfield_11502",
                ]
            }
            
            headers = {
                "Authorization": f"Bearer {self.api_token}",
                "Accept": "application/json",
                "Host": "support.sbertroika.ru"
            }
            
            logger.info(f"📡 Запрос к Jira API: {api_endpoint}")
            logger.info(f"📋 JQL: {jql_query.strip()}")
            
            connector = aiohttp.TCPConnector(family=socket.AF_INET)
            
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
    
    async def get_all_tasks_by_user(self, username: str, max_results: int = 500) -> List[Dict[str, Any]]:
        """
        Получает ВСЕ задачи (только активные статусы) по username исполнителя
        """
        try:
            api_endpoint = f"{self.base_url}/rest/api/2/search"
            
            # Список активных статусов
            active_statuses = [
                "Ожидание поддержки",
                "Ожидание клиента",
                "Передано партнеру",
                "В процессе",
                "Эскалация (не разработка)",
                "Фин блок",
                "Согласование",
                "ЗАПРОС НА ПАУЗУ",
                "ETL",
                "РЕГ БЛОК",
                "Претензионный",
                "ЮР БЛОК",
                "ВНЕДРЕНИЕ",
                "РЕКА",
                "В разработку",
                "Пауза"
            ]
            
            # Формируем строку статусов для JQL
            statuses_str = ', '.join([f'"{s}"' for s in active_statuses])
            
            # JQL запрос для поиска задач по исполнителю и статусам
            jql_query = f'''
            project = ZZ 
            AND assignee = "{username}"
            AND status IN ({statuses_str})
            ORDER BY created DESC
            '''
            
            params = {
                "jql": jql_query.strip(),
                "maxResults": max_results,
                "fields": [
                    "summary", 
                    "assignee", 
                    "duedate", 
                    "status", 
                    "priority", 
                    "description", 
                    "created",
                    "updated",
                    "issuetype",
                    "customfield_10611",
                    "customfield_10612",
                    "customfield_10303",
                    "customfield_10305",
                    "customfield_10606",
                    "customfield_11502",
                ]
            }
            
            headers = {
                "Authorization": f"Bearer {self.api_token}",
                "Accept": "application/json",
                "Host": "support.sbertroika.ru"
            }
            
            logger.info(f"📡 Запрос к Jira API для пользователя {username}")
            logger.info(f"📋 JQL: {jql_query.strip()}")
            
            connector = aiohttp.TCPConnector(family=socket.AF_INET)
            
            async with aiohttp.ClientSession(connector=connector, timeout=self.timeout) as session:
                async with session.get(
                    api_endpoint, 
                    headers=headers,
                    params=params
                ) as response:
                    
                    if response.status == 200:
                        data = await response.json()
                        tasks = self._parse_jira_response(data)
                        logger.info(f"✅ Найдено задач для {username}: {len(tasks)}")
                        return tasks
                    else:
                        logger.error(f"❌ Ошибка Jira API: статус {response.status}")
                        error_text = await response.text()
                        logger.error(f"Ответ: {error_text[:500]}")
                        return []
                        
        except Exception as e:
            logger.error(f"❌ Ошибка при запросе к Jira API: {e}", exc_info=True)
            return []
    
    def _parse_jira_response(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Преобразует ответ Jira API в единый формат задач"""
        tasks = []
        issues = data.get('issues', [])
        
        now = datetime.now()
        warning_hours = getattr(config, 'SLA_HOURS', 24)
        
        for issue in issues:
            try:
                fields = issue.get('fields')
                if fields is None:
                    continue
                
                assignee_data = fields.get('assignee')
                assignee = self._extract_assignee(assignee_data)
                
                due_date, sla_source, remaining_text = self._extract_sla_date(fields)
                
                if not due_date:
                    continue
                
                if due_date.tzinfo is not None:
                    due_date = due_date.replace(tzinfo=None)
                
                time_diff = due_date - now
                hours_until_due = time_diff.total_seconds() / 3600
                
                should_notify = False
                if hours_until_due <= warning_hours:
                    should_notify = True
                    if hours_until_due < 0:
                        logger.info(f"⚠️ Задача {issue.get('key')}: ПРОСРОЧЕНА на {abs(hours_until_due):.1f}ч (источник: {sla_source})")
                    else:
                        logger.info(f"⚠️ Задача {issue.get('key')}: до дедлайна {hours_until_due:.1f}ч (источник: {sla_source})")
                
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
                    "remaining_text": remaining_text,
                    "hours_until_due": hours_until_due,
                    "should_notify": should_notify,
                    "created": fields.get('created'),
                    "updated": fields.get('updated'),
                    "status": fields.get('status', {}).get('name') if fields.get('status') else 'Неизвестно',
                    "status_id": fields.get('status', {}).get('id') if fields.get('status') else None,
                    "priority": fields.get('priority', {}).get('name') if fields.get('priority') else None,
                    "url": f"{self.base_url}/browse/{issue.get('key')}",
                    "sla_raw": fields.get('customfield_10611'),
                    "raw_data": issue
                }
                
                tasks.append(task)
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
    
    def _extract_sla_date(self, fields: Dict) -> Tuple[Optional[datetime], str, Optional[str]]:
        """
        Извлекает дату SLA и оставшееся время из разных возможных полей Jira
        Возвращает (дата, источник, оставшееся_время_текст)
        """
        
        # 1. Проверяем стандартное поле duedate
        due_date = fields.get('duedate')
        if due_date:
            parsed = self._parse_date(due_date)
            if parsed:
                return parsed, "duedate", None
        
        # 2. Проверяем SLA поле customfield_10611 (время до решения)
        sla_data = fields.get('customfield_10611')
        if sla_data and isinstance(sla_data, dict):
            ongoing_cycle = sla_data.get('ongoingCycle')
            if ongoing_cycle:
                # Берём REMAINING TIME вместо BREACH TIME!
                remaining_time = ongoing_cycle.get('remainingTime', {})
                remaining_text = remaining_time.get('friendly')
                remaining_ms = remaining_time.get('millis', 0)
                
                if remaining_ms > 0:
                    due_date = datetime.now() + timedelta(milliseconds=remaining_ms)
                    return due_date, "customfield_10611 (SLA решение)", remaining_text
                
                # Если нет remainingTime, используем breachTime
                breach_time = ongoing_cycle.get('breachTime', {})
                if breach_time:
                    iso_date = breach_time.get('iso8601')
                    if iso_date:
                        parsed = self._parse_date(iso_date)
                        if parsed:
                            return parsed, "customfield_10611 (breachTime)", remaining_text
            
            completed_cycles = sla_data.get('completedCycles', [])
            if completed_cycles:
                for cycle in completed_cycles:
                    stop_time = cycle.get('stopTime', {})
                    if stop_time:
                        iso_date = stop_time.get('iso8601')
                        if iso_date:
                            parsed = self._parse_date(iso_date)
                            if parsed:
                                return parsed, "customfield_10611 (completed)", None
        
        # 3. Проверяем SLA поле customfield_10612 (время до первого отклика)
        sla_data2 = fields.get('customfield_10612')
        if sla_data2 and isinstance(sla_data2, dict):
            ongoing_cycle = sla_data2.get('ongoingCycle')
            if ongoing_cycle:
                remaining_time = ongoing_cycle.get('remainingTime', {})
                remaining_text = remaining_time.get('friendly')
                remaining_ms = remaining_time.get('millis', 0)
                
                if remaining_ms > 0:
                    due_date = datetime.now() + timedelta(milliseconds=remaining_ms)
                    return due_date, "customfield_10612 (SLA отклик)", remaining_text
        
        # 4. Проверяем другие SLA поля
        other_sla_fields = ['customfield_10303', 'customfield_10305', 'customfield_11717']
        for field in other_sla_fields:
            value = fields.get(field)
            if value:
                if isinstance(value, dict):
                    for key in ['iso8601', 'date', 'value', 'endDate']:
                        if key in value and value[key]:
                            parsed = self._parse_date(str(value[key]))
                            if parsed:
                                return parsed, f"{field}", None
                else:
                    parsed = self._parse_date(str(value))
                    if parsed:
                        return parsed, field, None
        
        return None, "не найдено", None
    
    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """Парсит дату из различных форматов"""
        if not date_str:
            return None
        
        date_str = str(date_str).strip()
        
        formats = [
            "%Y-%m-%d",
            "%Y-%m-%dT%H:%M:%S.%f%z",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%d.%m.%Y %H:%M",
            "%d.%m.%Y",
            "%Y/%m/%d %H:%M:%S",
            "%Y/%m/%d",
            "%d/%m/%Y %H:%M",
        ]
        
        for fmt in formats:
            try:
                dt = datetime.strptime(date_str, fmt)
                return dt
            except ValueError:
                continue
        
        try:
            if '+0300' in date_str or '+03:00' in date_str:
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
    
    async def get_reopen_info(self, issue_key: str) -> tuple:
        """
        Проверяет, была ли задача переоткрыта после статуса "Решен"
        Возвращает (was_reopened, reopen_date)
        """
        url = f"{self.base_url}/rest/api/2/issue/{issue_key}/changelog"
        headers = {"Authorization": f"Bearer {self.api_token}"}
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    for change in data.get('values', []):
                        for item in change.get('items', []):
                            if item.get('field') == 'status':
                                if item.get('fromString') == 'Решен' and item.get('toString') != 'Решен':
                                    reopen_date = change.get('created')
                                    return True, reopen_date
        return False, None
    
    async def get_task_by_key(self, task_key: str) -> Optional[Dict]:
        """Получить задачу по ключу напрямую из API"""
        try:
            url = f"{self.base_url}/rest/api/2/issue/{task_key}"
            headers = {
                "Authorization": f"Bearer {self.api_token}",
                "Accept": "application/json",
                "Host": "support.sbertroika.ru"
            }
            
            logger.info(f"🔍 Прямой запрос задачи {task_key}")
            
            connector = aiohttp.TCPConnector(family=socket.AF_INET)
            
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
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    print("\n" + "=" * 80)
    print("🔍 ТЕСТИРОВАНИЕ ПОИСКА ЗАДАЧ С SLA")
    print("=" * 80)
    
    client = TaskAPIClient()
    
    print("\n📥 Получение задач из Jira...")
    tasks = await client.get_tasks(max_results=500)
    
    total = len(tasks)
    with_sla = [t for t in tasks if t['due_date']]
    urgent = [t for t in tasks if t.get('should_notify')]
    
    print(f"\n📊 Статистика:")
    print(f"   Всего получено задач: {total}")
    print(f"   Задач с SLA датой: {len(with_sla)}")
    print(f"   Требуют уведомления: {len(urgent)}")
    
    if urgent:
        print(f"\n📋 ЗАДАЧИ ДЛЯ УВЕДОМЛЕНИЯ:")
        print("-" * 80)
        for i, task in enumerate(urgent[:10], 1):
            hours = task['hours_until_due']
            status = "🔴 Критично" if hours < 12 else "🟡 Скоро"
            print(f"\n{i}. {task['id']} - {task['title'][:50]}")
            print(f"   Статус: {status}")
            print(f"   Осталось: {hours:.1f}ч")
            print(f"   Исполнитель: {task['assignee']}")
    else:
        print(f"\n❌ Задач для уведомления не найдено.")
    
    print("\n" + "=" * 80)


if __name__ == "__main__":
    asyncio.run(test_jira_client())
