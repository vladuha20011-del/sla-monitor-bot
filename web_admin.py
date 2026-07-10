"""
Веб-интерфейс для управления SLA ботом
"""

from flask import Flask, render_template, request, jsonify
from datetime import datetime
import os
import time
import logging

import db_manager

app = Flask(__name__)

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============ ИНИЦИАЛИЗАЦИЯ ============

db_manager.init_db()

# Переносим сотрудников из employees.py если они есть
try:
    from employees import EMPLOYEES
    existing = db_manager.get_employees(active_only=False)
    if len(existing) == 0:
        for emp in EMPLOYEES:
            db_manager.add_employee({
                'full_name': emp['full_name'],
                'search_names': emp['search_names'],
                'telegram_username': emp['telegram_username'],
                'email': emp['email'],
                'username': emp.get('username', emp['email'].split('@')[0]),
                'status': 'active'
            })
        print("✅ Сотрудники перенесены из employees.py")
except ImportError:
    pass

# ============ СТРАНИЦЫ ============

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login')
def login():
    return render_template('index.html')

# ============ API: СОТРУДНИКИ ============

@app.route('/api/employees')
def api_get_employees():
    employees = db_manager.get_employees(active_only=True)
    return jsonify(employees)

@app.route('/api/employees/<int:employee_id>')
def api_get_employee(employee_id):
    employee = db_manager.get_employee_by_id(employee_id)
    if employee:
        return jsonify(employee)
    return jsonify({'error': 'Сотрудник не найден'}), 404

@app.route('/api/employees', methods=['POST'])
def api_add_employee():
    data = request.json
    
    if 'username' not in data or not data['username']:
        data['username'] = data['email'].split('@')[0] if data.get('email') else ''
    
    if 'search_names' not in data or not data['search_names']:
        name_parts = data['full_name'].split()
        data['search_names'] = [name_parts[0], name_parts[1]] if len(name_parts) >= 2 else [name_parts[0]]
    
    if 'status' not in data:
        data['status'] = 'active'
    
    db_manager.add_employee(data)
    return jsonify({'status': 'ok', 'message': 'Сотрудник добавлен'})

@app.route('/api/employees/<int:employee_id>', methods=['PUT'])
def api_update_employee(employee_id):
    data = request.json
    
    if 'search_names' not in data or not data['search_names']:
        name_parts = data['full_name'].split()
        data['search_names'] = [name_parts[0], name_parts[1]] if len(name_parts) >= 2 else [name_parts[0]]
    
    if 'status' not in data:
        data['status'] = 'active'
    
    db_manager.update_employee(employee_id, data)
    return jsonify({'status': 'ok', 'message': 'Сотрудник обновлён'})

@app.route('/api/employees/<int:employee_id>', methods=['DELETE'])
def api_delete_employee(employee_id):
    db_manager.delete_employee(employee_id, soft=True)
    return jsonify({'status': 'ok', 'message': 'Сотрудник удалён'})

# ============ API: НАСТРОЙКИ ============

@app.route('/api/settings')
def api_get_settings():
    settings = db_manager.get_settings()
    return jsonify(settings)

@app.route('/api/settings', methods=['POST'])
def api_update_settings():
    data = request.json
    db_manager.update_settings(data)
    return jsonify({'status': 'ok', 'message': 'Настройки сохранены'})

# ============ API: СТАТУСЫ ============

@app.route('/api/statuses')
def api_get_statuses():
    statuses = db_manager.get_task_statuses(active_only=True)
    return jsonify(statuses)

@app.route('/api/statuses', methods=['POST'])
def api_add_status():
    data = request.json
    db_manager.add_task_status(data['name'], data.get('notify_enabled', 1))
    return jsonify({'status': 'ok', 'message': 'Статус добавлен'})

@app.route('/api/statuses/<name>', methods=['PUT'])
def api_update_status(name):
    data = request.json
    db_manager.update_task_status(name, data.get('notify_enabled', 1))
    return jsonify({'status': 'ok', 'message': 'Статус обновлён'})

@app.route('/api/statuses/<name>', methods=['DELETE'])
def api_delete_status(name):
    db_manager.delete_task_status(name, soft=True)
    return jsonify({'status': 'ok', 'message': 'Статус удалён'})

# ============ API: ШАБЛОНЫ ============

@app.route('/api/templates')
def api_get_templates():
    templates = db_manager.get_all_templates_dict()
    return jsonify(templates)

@app.route('/api/templates', methods=['POST'])
def api_save_templates():
    data = request.json
    db_manager.save_templates(data)
    return jsonify({'status': 'ok', 'message': 'Шаблоны сохранены'})

# ============ API: ЛОГИ ============

@app.route('/api/logs')
def api_get_logs():
    log_file = 'sla_bot.log'
    if not os.path.exists(log_file):
        return 'Лог-файл не найден'
    
    try:
        with open(log_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            last_lines = lines[-1000:] if len(lines) > 1000 else lines
            return ''.join(last_lines)
    except Exception as e:
        return f'Ошибка чтения логов: {e}'

@app.route('/api/logs', methods=['DELETE'])
def api_clear_logs():
    log_file = 'sla_bot.log'
    if os.path.exists(log_file):
        with open(log_file, 'w', encoding='utf-8') as f:
            f.write('')
    return jsonify({'status': 'ok', 'message': 'Логи очищены'})

# ============ API: СТАТИСТИКА ============

@app.route('/api/stats')
def api_get_stats():
    stats = db_manager.get_stats()
    
    employees = db_manager.get_employees(active_only=True)
    stats['employees_count'] = len(employees)
    
    try:
        result = os.popen('pgrep -f "sla_bot.py"').read().strip()
        stats['bot_running'] = bool(result)
        stats['bot_pid'] = result if result else None
    except:
        stats['bot_running'] = False
        stats['bot_pid'] = None
    
    try:
        import asyncio
        from api_client import TaskAPIClient
        
        async def get_jira_stats():
            client = TaskAPIClient()
            tasks = await client.get_tasks()
            return {
                'total_tasks': len(tasks),
                'urgent_tasks': len([t for t in tasks if t.get('should_notify', False)])
            }
        
        jira_stats = asyncio.run(get_jira_stats())
        stats.update(jira_stats)
    except Exception as e:
        stats['total_tasks'] = 0
        stats['urgent_tasks'] = 0
    
    return jsonify(stats)

# ============ API: УПРАВЛЕНИЕ БОТОМ ============

@app.route('/api/restart', methods=['POST'])
def api_restart_bot():
    try:
        logger.info("🔄 Перезапуск бота...")
        
        os.system('pkill -f "sla_bot.py"')
        time.sleep(2)
        
        command = 'cd /root/sla-monitor-bot && source venv/bin/activate && nohup python3 sla_bot.py >> bot.log 2>&1 &'
        os.system(f'bash -c "{command}"')
        
        time.sleep(2)
        
        result = os.popen('pgrep -f "sla_bot.py"').read().strip()
        if result:
            logger.info(f"✅ Бот перезапущен (PID: {result})")
            return jsonify({'status': 'ok', 'message': f'🔄 Бот перезапущен (PID: {result})'})
        else:
            logger.error("❌ Бот не запустился")
            return jsonify({'status': 'error', 'message': '❌ Бот не запустился'}), 500
            
    except Exception as e:
        logger.error(f"❌ Ошибка перезапуска: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/stop', methods=['POST'])
def api_stop_bot():
    try:
        os.system('pkill -f "sla_bot.py"')
        logger.info("⏹ Бот остановлен")
        return jsonify({'status': 'ok', 'message': '⏹ Бот остановлен'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# ============ API: ПИНГ БОТА ============

@app.route('/api/bot-ping')
def api_bot_ping():
    """Проверяет, отвечает ли бот через Telegram API"""
    try:
        import requests
        import config
        
        # Простой запрос к Telegram API
        url = f"https://api.telegram.org/bot{config.BOT_TOKEN}/getMe"
        response = requests.get(url, timeout=3)
        
        if response.status_code == 200:
            data = response.json()
            if data.get('ok'):
                return jsonify({
                    'status': 'ok',
                    'message': '✅ OK',
                    'bot_name': data['result']['username'],
                    'timestamp': datetime.now().isoformat()
                })
        
        return jsonify({
            'status': 'error',
            'message': '❌ Недоступен'
        }), 503
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'❌ Ошибка: {str(e)[:60]}'
        }), 503

# ============ API: ЛОГ ОШИБОК ============

@app.route('/api/error-logs')
def api_error_logs():
    """Возвращает логи ошибок с расшифровкой"""
    log_file = 'sla_bot.log'
    errors = []
    
    if not os.path.exists(log_file):
        return jsonify([])
    
    # Словарь расшифровок ошибок
    error_map = {
        "KeyError": {
            'solution': 'В шаблоне используется переменная, которой нет в данных. Уберите её из шаблона в админке или добавьте в код.'
        },
        "ConnectionError": {
            'solution': 'Проверьте доступность Jira и настройки подключения в config.py'
        },
        "TelegramError": {
            'solution': 'Проверьте CHAT_ID и BOT_TOKEN в config.py. Бот должен быть добавлен в чат.'
        },
        "sqlite3.OperationalError": {
            'solution': 'Ошибка в структуре БД. Удалите settings.db и перезапустите бота (данные будут созданы заново).'
        },
        "ModuleNotFoundError": {
            'solution': 'Не установлен модуль. Установите: pip install <module>'
        },
        "TimeoutError": {
            'solution': 'Таймаут подключения. Проверьте интернет-соединение, увеличьте таймаут в api_client.py.'
        },
        "JSONDecodeError": {
            'solution': 'Jira вернул невалидный JSON. Проверьте ответ Jira, возможно ошибка авторизации.'
        },
        "PermissionError": {
            'solution': 'Нет прав на запись в файл. Проверьте права на папку ~/sla-monitor-bot'
        },
        "FileNotFoundError": {
            'solution': 'Файл не найден. Проверьте пути в коде.'
        },
        "TypeError": {
            'solution': 'Ошибка типа данных. Проверьте формат данных, передаваемых в функцию.'
        },
        "ValueError": {
            'solution': 'Неверное значение. Проверьте данные в БД или настройках.'
        }
    }
    
    try:
        with open(log_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            # Берём последние 1000 строк
            for line in lines[-1000:]:
                if 'ERROR' in line or 'Exception' in line or 'Traceback' in line:
                    error_entry = {
                        'timestamp': line[:19] if len(line) > 19 else '',
                        'message': line.strip(),
                        'solution': 'Обратитесь к администратору для анализа логов'
                    }
                    # Ищем расшифровку
                    for key, info in error_map.items():
                        if key in line:
                            error_entry['solution'] = info['solution']
                            break
                    errors.append(error_entry)
    except Exception as e:
        return jsonify([{'timestamp': '', 'message': f'Ошибка чтения логов: {str(e)}', 'solution': 'Проверьте права на файл'}] )
    
    return jsonify(errors[-50:])  # последние 50 ошибок

# ============ ЗАПУСК ============

if __name__ == '__main__':
    print("=" * 60)
    print("🌐 Веб-интерфейс для управления SLA ботом")
    print("📍 http://vladuha20011.fvds.ru:5000")
    print("=" * 60)
    
    app.run(host='0.0.0.0', port=5000, debug=False)
