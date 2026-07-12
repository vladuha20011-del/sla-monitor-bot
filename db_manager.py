"""
Менеджер базы данных для бота и админки
"""

import sqlite3
import os
from typing import List, Dict, Any, Optional

DB_PATH = 'settings.db'

def get_db_connection():
    """Получить соединение с БД"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Инициализация базы данных"""
    conn = get_db_connection()
    c = conn.cursor()
    
    # Таблица сотрудников (с полем status и vacation_end_date)
    c.execute('''
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT,
            search_names TEXT,
            telegram_username TEXT,
            email TEXT,
            username TEXT,
            status TEXT DEFAULT 'active',
            vacation_end_date TEXT,
            is_active INTEGER DEFAULT 1
        )
    ''')
    
    try:
        c.execute('ALTER TABLE employees ADD COLUMN status TEXT DEFAULT "active"')
    except sqlite3.OperationalError:
        pass
    
    try:
        c.execute('ALTER TABLE employees ADD COLUMN vacation_end_date TEXT')
    except sqlite3.OperationalError:
        pass
    
    # Таблица настроек
    c.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT,
            description TEXT
        )
    ''')
    
    # Таблица статусов задач (с флагом уведомления)
    c.execute('''
        CREATE TABLE IF NOT EXISTS task_statuses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            is_active INTEGER DEFAULT 1,
            notify_enabled INTEGER DEFAULT 1
        )
    ''')
    
    # Таблица шаблонов сообщений
    c.execute('''
        CREATE TABLE IF NOT EXISTS message_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            template TEXT,
            description TEXT,
            is_active INTEGER DEFAULT 1
        )
    ''')
    
    # Таблица статистики
    c.execute('''
        CREATE TABLE IF NOT EXISTS stats (
            key TEXT PRIMARY KEY,
            value INTEGER DEFAULT 0
        )
    ''')
    
    # Таблица ошибок со статусами
    c.execute('''
        CREATE TABLE IF NOT EXISTS error_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            message TEXT,
            solution TEXT,
            status TEXT DEFAULT 'new',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    c.execute('CREATE INDEX IF NOT EXISTS idx_error_status ON error_logs(status)')
    
    # Таблица истории уведомлений (с полем status)
    c.execute('''
        CREATE TABLE IF NOT EXISTS notification_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_text TEXT NOT NULL,
            tasks_text TEXT,
            assignees_text TEXT,
            task_keys_text TEXT,
            sent_at TIMESTAMP DEFAULT (datetime('now', 'localtime')),
            is_excel INTEGER DEFAULT 0,
            excel_data TEXT,
            excel_filename TEXT,
            status TEXT DEFAULT 'sent',
            error_text TEXT,
            is_deleted INTEGER DEFAULT 0
        )
    ''')
    
    c.execute('CREATE INDEX IF NOT EXISTS idx_hist_sent ON notification_history(sent_at)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_hist_task_keys ON notification_history(task_keys_text)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_hist_assignees ON notification_history(assignees_text)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_hist_status ON notification_history(status)')
    
    # Добавляем настройки по умолчанию
    default_settings = {
        'SLA_HOURS': ('24', 'За сколько часов до дедлайна уведомлять'),
        'CHECK_INTERVAL_MINUTES': ('180', 'Интервал проверки задач (минуты)'),
        'TAG_START_HOUR': ('9', 'С какого часа тегать'),
        'TAG_END_HOUR': ('18', 'До какого часа тегать'),
        'TAG_ENABLED': ('True', 'Теги включены'),
        'TAG_WORKDAYS_ONLY': ('True', 'Только по будням'),
        'IGNORE_REPLIES': ('True', 'Игнорировать ответы'),
        'IGNORE_EDITS': ('True', 'Игнорировать редактирования'),
        'IGNORE_FORWARDS': ('True', 'Игнорировать пересылки')
    }
    
    for key, (value, desc) in default_settings.items():
        c.execute('INSERT OR IGNORE INTO settings (key, value, description) VALUES (?, ?, ?)', 
                  (key, value, desc))
    
    # Добавляем статусы по умолчанию
    default_statuses = [
        ('Ожидание поддержки', 1),
        ('В процессе', 1),
        ('Ожидание клиента', 0),
        ('Передано партнеру', 0),
        ('Эскалация (не разработка)', 0),
        ('Фин блок', 0),
        ('Согласование', 0),
        ('ЗАПРОС НА ПАУЗУ', 0),
        ('ETL', 0),
        ('РЕГ БЛОК', 0),
        ('Претензионный', 0),
        ('ЮР БЛОК', 0),
        ('ВНЕДРЕНИЕ', 0),
        ('РЕКА', 0),
        ('В разработку', 0),
        ('Пауза', 0)
    ]
    
    for status, notify in default_statuses:
        c.execute('INSERT OR IGNORE INTO task_statuses (name, notify_enabled) VALUES (?, ?)', 
                  (status, notify))
    
    # Добавляем шаблоны по умланию
    default_templates = [
        ('header', '⚠️ Внимание! Приближается SLA!', 'Заголовок уведомления'),
        ('footer', 'Коллеги, обратите внимание!', 'Финальная фраза'),
        ('task_format', '📌 Задача: {id}\n🔗 Ссылка: {url}\n📋 Название: {title}\n👤 Исполнитель: {assignee}\n📅 Создана: {created}\n⏰ Осталось на решение: {remaining}\n📈 Статус: {status}\n🎯 Приоритет: {priority}', 'Формат задачи в рассылке'),
        ('check_task_format', '📌 Задача: {id}\n📋 Название: {title}\n🔗 Ссылка: {url}\n\n👤 Исполнитель: {assignee}\n📅 Создана: {created}\n⏰ Осталось: {remaining}\n📈 Статус задачи: {status}\n🎯 Приоритет: {priority}', 'Формат задачи в /check'),
        ('reopen_format', '🔄 Переоткрыта: {reopen_date}', 'Текст для переоткрытой задачи'),
        ('alarm_header', '⚠️ Внимание! Приближается SLA!', 'Заголовок для /alarm'),
        ('alarm_footer', 'Коллеги, обратите внимание!', 'Финальная фраза для /alarm'),
        ('request_caption', '📊 ВСЕ задачи сотрудников: {employees}\n📈 Всего задач: {total}\n📋 {status_summary}', 'Подпись для /request'),
        ('checking_dep_caption', '📊 Отчёт по задачам отдела (всего: {total})', 'Подпись для /checking_dep')
    ]
    
    for name, template, desc in default_templates:
        c.execute('INSERT OR IGNORE INTO message_templates (name, template, description) VALUES (?, ?, ?)', 
                  (name, template, desc))
    
    conn.commit()
    conn.close()


# ============ РАБОТА С СОТРУДНИКАМИ ============

def get_employees(active_only: bool = True) -> List[Dict]:
    """Получить всех сотрудников"""
    conn = get_db_connection()
    c = conn.cursor()
    
    query = 'SELECT * FROM employees'
    if active_only:
        query += ' WHERE is_active = 1'
    
    query += ' ORDER BY id'
    
    c.execute(query)
    rows = c.fetchall()
    conn.close()
    
    employees = []
    for row in rows:
        employees.append({
            'id': row['id'],
            'full_name': row['full_name'],
            'search_names': row['search_names'].split(',') if row['search_names'] else [],
            'telegram_username': row['telegram_username'],
            'email': row['email'],
            'username': row['username'],
            'status': row['status'] if 'status' in row.keys() else 'active',
            'vacation_end_date': row['vacation_end_date'] if 'vacation_end_date' in row.keys() else None,
            'is_active': row['is_active']
        })
    return employees

def add_employee(data: Dict) -> int:
    """Добавить сотрудника"""
    conn = get_db_connection()
    c = conn.cursor()
    
    status = data.get('status', 'active')
    vacation_end_date = data.get('vacation_end_date', None)
    
    c.execute('''
        INSERT INTO employees (full_name, search_names, telegram_username, email, username, status, vacation_end_date)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (
        data['full_name'],
        ','.join(data['search_names']),
        data['telegram_username'],
        data['email'],
        data['username'],
        status,
        vacation_end_date
    ))
    
    conn.commit()
    employee_id = c.lastrowid
    conn.close()
    return employee_id

def update_employee(employee_id: int, data: Dict):
    """Обновить сотрудника"""
    conn = get_db_connection()
    c = conn.cursor()
    
    status = data.get('status', 'active')
    vacation_end_date = data.get('vacation_end_date', None)
    
    c.execute('''
        UPDATE employees 
        SET full_name = ?, search_names = ?, telegram_username = ?, email = ?, username = ?, status = ?, vacation_end_date = ?
        WHERE id = ?
    ''', (
        data['full_name'],
        ','.join(data['search_names']),
        data['telegram_username'],
        data['email'],
        data['username'],
        status,
        vacation_end_date,
        employee_id
    ))
    
    conn.commit()
    conn.close()

def delete_employee(employee_id: int, soft: bool = True):
    """Удалить сотрудника (мягкое или жёсткое)"""
    conn = get_db_connection()
    c = conn.cursor()
    
    if soft:
        c.execute('UPDATE employees SET is_active = 0 WHERE id = ?', (employee_id,))
    else:
        c.execute('DELETE FROM employees WHERE id = ?', (employee_id,))
    
    conn.commit()
    conn.close()

def get_employee_by_name(name_text: str) -> Optional[Dict]:
    """Найти сотрудника по имени (только активных)"""
    employees = get_employees(active_only=True)
    if not name_text:
        return None
    
    name_text_lower = name_text.lower().strip()
    
    for employee in employees:
        if employee['full_name'].lower() == name_text_lower:
            return employee
        
        search_names = [s.lower() for s in employee['search_names']]
        if all(keyword in name_text_lower for keyword in search_names):
            return employee
        
        name_words = employee['full_name'].lower().split()
        search_words = name_text_lower.split()
        if all(any(word in nw for nw in name_words) for word in search_words):
            return employee
    
    return None

def get_employee_by_id(employee_id: int) -> Optional[Dict]:
    """Получить сотрудника по ID"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT * FROM employees WHERE id = ? AND is_active = 1', (employee_id,))
    row = c.fetchone()
    conn.close()
    
    if row:
        return {
            'id': row['id'],
            'full_name': row['full_name'],
            'search_names': row['search_names'].split(',') if row['search_names'] else [],
            'telegram_username': row['telegram_username'],
            'email': row['email'],
            'username': row['username'],
            'status': row['status'] if 'status' in row.keys() else 'active',
            'vacation_end_date': row['vacation_end_date'] if 'vacation_end_date' in row.keys() else None,
            'is_active': row['is_active']
        }
    return None

def get_all_telegram_mentions() -> str:
    """Получить все Telegram упоминания (только активных)"""
    employees = get_employees(active_only=True)
    return " ".join([emp['telegram_username'] for emp in employees])

def get_active_employees_for_mention() -> List[Dict]:
    """Получить сотрудников, которых можно тегать (статус 'active')"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        SELECT * FROM employees 
        WHERE is_active = 1 AND status = 'active'
    ''')
    rows = c.fetchall()
    conn.close()
    
    employees = []
    for row in rows:
        employees.append({
            'id': row['id'],
            'full_name': row['full_name'],
            'telegram_username': row['telegram_username'],
            'status': row['status'] if 'status' in row.keys() else 'active',
            'vacation_end_date': row['vacation_end_date'] if 'vacation_end_date' in row.keys() else None
        })
    return employees

def get_vacation_employees() -> List[Dict]:
    """Получить всех сотрудников в отпуске с датой окончания"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        SELECT * FROM employees 
        WHERE is_active = 1 AND status = 'vacation' AND vacation_end_date IS NOT NULL
    ''')
    rows = c.fetchall()
    conn.close()
    
    employees = []
    for row in rows:
        employees.append({
            'id': row['id'],
            'full_name': row['full_name'],
            'telegram_username': row['telegram_username'],
            'status': row['status'] if 'status' in row.keys() else 'vacation',
            'vacation_end_date': row['vacation_end_date'] if 'vacation_end_date' in row.keys() else None,
            'email': row['email']
        })
    return employees

def activate_employee_from_vacation(employee_id: int):
    """Перевести сотрудника из отпуска в активен (очистить дату окончания)"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        UPDATE employees 
        SET status = 'active', vacation_end_date = NULL
        WHERE id = ?
    ''', (employee_id,))
    conn.commit()
    conn.close()


# ============ РАБОТА С НАСТРОЙКАМИ ============

def get_settings() -> Dict[str, str]:
    """Получить все настройки"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT key, value FROM settings')
    rows = c.fetchall()
    conn.close()
    
    return {row['key']: row['value'] for row in rows}

def get_setting(key: str, default: str = None) -> str:
    """Получить настройку по ключу"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT value FROM settings WHERE key = ?', (key,))
    row = c.fetchone()
    conn.close()
    
    return row['value'] if row else default

def update_settings(data: Dict[str, str]):
    """Обновить настройки"""
    conn = get_db_connection()
    c = conn.cursor()
    
    for key, value in data.items():
        c.execute('UPDATE settings SET value = ? WHERE key = ?', (value, key))
    
    conn.commit()
    conn.close()


# ============ РАБОТА СО СТАТУСАМИ ============

def get_task_statuses(active_only: bool = True) -> List[Dict]:
    """Получить статусы задач с флагом уведомления"""
    conn = get_db_connection()
    c = conn.cursor()
    
    query = 'SELECT name, notify_enabled, is_active FROM task_statuses'
    if active_only:
        query += ' WHERE is_active = 1'
    
    c.execute(query)
    rows = c.fetchall()
    conn.close()
    
    return [{'name': row['name'], 'notify_enabled': bool(row['notify_enabled']), 'is_active': bool(row['is_active'])} for row in rows]

def get_notify_statuses() -> List[str]:
    """Получить статусы, для которых включены уведомления"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT name FROM task_statuses WHERE is_active = 1 AND notify_enabled = 1')
    rows = c.fetchall()
    conn.close()
    
    return [row['name'] for row in rows]

def add_task_status(name: str, notify_enabled: int = 1):
    """Добавить статус задачи"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO task_statuses (name, notify_enabled) VALUES (?, ?)', 
              (name, notify_enabled))
    conn.commit()
    conn.close()

def update_task_status(name: str, notify_enabled: int):
    """Обновить статус задачи (включить/выключить уведомления)"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('UPDATE task_statuses SET notify_enabled = ? WHERE name = ?', (notify_enabled, name))
    conn.commit()
    conn.close()

def delete_task_status(name: str, soft: bool = True):
    """Удалить статус задачи"""
    conn = get_db_connection()
    c = conn.cursor()
    
    if soft:
        c.execute('UPDATE task_statuses SET is_active = 0 WHERE name = ?', (name,))
    else:
        c.execute('DELETE FROM task_statuses WHERE name = ?', (name,))
    
    conn.commit()
    conn.close()


# ============ РАБОТА С ШАБЛОНАМИ ============

def get_template(name: str) -> Optional[str]:
    """Получить шаблон по имени"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT template FROM message_templates WHERE name = ? AND is_active = 1', (name,))
    row = c.fetchone()
    conn.close()
    
    return row['template'] if row else None

def save_template(name: str, template: str):
    """Сохранить шаблон"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        INSERT OR REPLACE INTO message_templates (name, template, is_active)
        VALUES (?, ?, 1)
    ''', (name, template))
    conn.commit()
    conn.close()

def get_all_templates() -> Dict[str, Dict]:
    """Получить все шаблоны с описаниями"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT name, template, description FROM message_templates WHERE is_active = 1')
    rows = c.fetchall()
    conn.close()
    
    return {row['name']: {'template': row['template'], 'description': row['description']} for row in rows}

def get_all_templates_dict() -> Dict[str, str]:
    """Получить все шаблоны как словарь {name: template}"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT name, template FROM message_templates WHERE is_active = 1')
    rows = c.fetchall()
    conn.close()
    
    return {row['name']: row['template'] for row in rows}

def save_templates(data: Dict[str, str]):
    """Сохранить несколько шаблонов"""
    conn = get_db_connection()
    c = conn.cursor()
    
    for name, template in data.items():
        c.execute('''
            INSERT OR REPLACE INTO message_templates (name, template, is_active)
            VALUES (?, ?, 1)
        ''', (name, template))
    
    conn.commit()
    conn.close()


# ============ СТАТИСТИКА ============

def increment_stats(key: str):
    """Увеличить статистику"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        INSERT INTO stats (key, value) VALUES (?, 1)
        ON CONFLICT(key) DO UPDATE SET value = value + 1
    ''', (key,))
    conn.commit()
    conn.close()

def get_stats() -> Dict[str, int]:
    """Получить статистику"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT key, value FROM stats')
    rows = c.fetchall()
    conn.close()
    
    return {row['key']: row['value'] for row in rows}


# ============ РАБОТА С ОШИБКАМИ ============

def save_error_log(timestamp: str, message: str, solution: str):
    """Сохранить ошибку в БД"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        INSERT INTO error_logs (timestamp, message, solution, status)
        VALUES (?, ?, ?, 'new')
    ''', (timestamp, message, solution))
    conn.commit()
    conn.close()

def get_error_logs(status_filter: str = 'active') -> List[Dict]:
    """Получить ошибки с фильтром по статусу"""
    conn = get_db_connection()
    c = conn.cursor()
    
    if status_filter == 'active':
        c.execute('SELECT * FROM error_logs WHERE status != "done" ORDER BY id DESC LIMIT 100')
    elif status_filter == 'all':
        c.execute('SELECT * FROM error_logs ORDER BY id DESC LIMIT 100')
    else:
        c.execute('SELECT * FROM error_logs WHERE status = ? ORDER BY id DESC LIMIT 100', (status_filter,))
    
    rows = c.fetchall()
    conn.close()
    
    return [{'id': row['id'], 'timestamp': row['timestamp'], 'message': row['message'], 'solution': row['solution'], 'status': row['status']} for row in rows]

def update_error_status(error_id: int, status: str):
    """Обновить статус ошибки"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('UPDATE error_logs SET status = ? WHERE id = ?', (status, error_id))
    conn.commit()
    conn.close()

def delete_done_errors() -> int:
    """Удалить выполненные ошибки"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('DELETE FROM error_logs WHERE status = "done"')
    deleted = c.rowcount
    conn.commit()
    conn.close()
    return deleted


# ============ РАБОТА С ИСТОРИЕЙ УВЕДОМЛЕНИЙ ============

def save_notification_history(message_text: str, tasks: List[Dict] = None, is_excel: bool = False, 
                              excel_data: str = None, excel_filename: str = None, 
                              status: str = 'sent', error_text: str = None):
    """Сохранить отправленное уведомление в историю"""
    conn = get_db_connection()
    c = conn.cursor()
    
    tasks_text = ""
    assignees_text = ""
    task_keys_text = ""
    
    if tasks:
        task_keys = [t.get('id', '') for t in tasks if t.get('id')]
        task_keys_text = ", ".join(task_keys)
        
        assignees = []
        for t in tasks:
            assignee = t.get('assignee', '')
            if assignee and assignee not in assignees:
                assignees.append(assignee)
        assignees_text = ", ".join(assignees)
        
        tasks_text = "\n".join([f"{t.get('id', '')}|{t.get('title', '')[:50]}|{t.get('assignee', '')}" for t in tasks if t.get('id')])
    
    c.execute('''
        INSERT INTO notification_history 
        (message_text, tasks_text, assignees_text, task_keys_text, is_excel, excel_data, excel_filename, status, error_text)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (message_text, tasks_text, assignees_text, task_keys_text, 1 if is_excel else 0, excel_data, excel_filename, status, error_text))
    
    conn.commit()
    conn.close()
    return c.lastrowid


def get_notification_history(limit: int = 100, search: str = None, status_filter: str = 'all') -> List[Dict]:
    """Получить историю уведомлений с поиском и фильтром по статусу"""
    conn = get_db_connection()
    c = conn.cursor()
    
    query = '''
        SELECT * FROM notification_history 
        WHERE is_deleted = 0
    '''
    params = []
    
    if status_filter and status_filter != 'all':
        query += ' AND status = ?'
        params.append(status_filter)
    
    if search and search.strip():
        search_term = f"%{search.strip()}%"
        query += ''' AND (
            message_text LIKE ? OR 
            tasks_text LIKE ? OR 
            assignees_text LIKE ? OR 
            task_keys_text LIKE ?
        )'''
        params.extend([search_term, search_term, search_term, search_term])
    
    query += ' ORDER BY sent_at DESC LIMIT ?'
    params.append(limit)
    
    c.execute(query, params)
    rows = c.fetchall()
    conn.close()
    
    history = []
    for row in rows:
        history.append({
            'id': row['id'],
            'message_text': row['message_text'],
            'tasks_text': row['tasks_text'],
            'assignees_text': row['assignees_text'],
            'task_keys_text': row['task_keys_text'],
            'sent_at': row['sent_at'],
            'is_excel': bool(row['is_excel']),
            'excel_data': row['excel_data'],
            'excel_filename': row['excel_filename'],
            'status': row['status'] if 'status' in row.keys() else 'sent',
            'error_text': row['error_text'] if 'error_text' in row.keys() else None
        })
    
    return history


def get_notification_by_id(notification_id: int) -> Optional[Dict]:
    """Получить уведомление по ID"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT * FROM notification_history WHERE id = ? AND is_deleted = 0', (notification_id,))
    row = c.fetchone()
    conn.close()
    
    if row:
        return {
            'id': row['id'],
            'message_text': row['message_text'],
            'tasks_text': row['tasks_text'],
            'assignees_text': row['assignees_text'],
            'task_keys_text': row['task_keys_text'],
            'sent_at': row['sent_at'],
            'is_excel': bool(row['is_excel']),
            'excel_data': row['excel_data'],
            'excel_filename': row['excel_filename'],
            'status': row['status'] if 'status' in row.keys() else 'sent',
            'error_text': row['error_text'] if 'error_text' in row.keys() else None
        }
    return None


def update_notification_status(notification_id: int, status: str):
    """Обновить статус уведомления"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('UPDATE notification_history SET status = ? WHERE id = ?', (status, notification_id))
    conn.commit()
    conn.close()


def delete_notification_history(notification_id: int):
    """Удалить запись из истории (мягкое удаление)"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('UPDATE notification_history SET is_deleted = 1 WHERE id = ?', (notification_id,))
    conn.commit()
    conn.close()


def clear_old_notifications(days: int = 30):
    """Очистить уведомления старше N дней (только отправленные)"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        UPDATE notification_history 
        SET is_deleted = 1 
        WHERE sent_at < datetime("now", ?) 
        AND is_deleted = 0
        AND status IN ('sent', 'manual', 'resent')
    ''', (f"-{days} days",))
    deleted = c.rowcount
    conn.commit()
    conn.close()
    return deleted


def get_notification_stats() -> Dict:
    """Получить статистику по истории"""
    conn = get_db_connection()
    c = conn.cursor()
    
    c.execute('SELECT COUNT(*) as total FROM notification_history WHERE is_deleted = 0')
    total = c.fetchone()['total']
    
    c.execute('SELECT COUNT(*) as excel FROM notification_history WHERE is_deleted = 0 AND is_excel = 1')
    excel = c.fetchone()['excel']
    
    c.execute('SELECT COUNT(*) as pending FROM notification_history WHERE is_deleted = 0 AND status = "pending"')
    pending = c.fetchone()['pending']
    
    conn.close()
    return {'total': total, 'excel': excel, 'text': total - excel, 'pending': pending}


def get_sent_task_keys_from_history() -> set:
    """Получить все ID задач, которые уже были отправлены (из истории)"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        SELECT task_keys_text FROM notification_history 
        WHERE is_deleted = 0 
        AND status IN ('sent', 'manual', 'resent')
        AND task_keys_text IS NOT NULL
        AND task_keys_text != ''
    ''')
    rows = c.fetchall()
    conn.close()
    
    sent_keys = set()
    for row in rows:
        keys = row['task_keys_text'].split(', ')
        for key in keys:
            if key.strip():
                sent_keys.add(key.strip())
    
    return sent_keys
