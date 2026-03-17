async def _send_bulk_notification(self, tasks: list, is_manual: bool = False):
    """
    Отправляет одно общее уведомление со всеми задачами
    """
    if not tasks:
        return
    
    # Проверяем текущее время (МСК)
    now = datetime.now()
    current_hour = now.hour
    current_weekday = now.weekday()  # 0-6 (пн-вс)
    
    # Проверяем, можно ли тегать
    should_mention = config.TAG_ENABLED
    
    if should_mention:
        # Проверка по времени суток
        time_ok = current_hour >= config.TAG_START_HOUR and current_hour < config.TAG_END_HOUR
        
        # Проверка по дням недели (если включено)
        day_ok = True
        if config.TAG_WORKDAYS_ONLY:
            day_ok = current_weekday < 5  # пн-пт = 0-4
        
        should_mention = time_ok and day_ok
        
        if not time_ok:
            logger.info(f"⏰ Теги отключены по времени: {current_hour}ч (рабочие часы {config.TAG_START_HOUR}-{config.TAG_END_HOUR})")
        elif not day_ok:
            logger.info(f"📅 Теги отключены по дню недели: {current_weekday} (рабочие дни пн-пт)")
    
    # Формируем заголовок (всегда одинаковый)
    message = "⚠️ Внимание! Приближается SLA!\n\n"
    
    for i, task in enumerate(tasks):
        # Находим сотрудника по имени
        employee = find_employee_by_name(task['assignee'])
        
        # Формируем упоминание исполнителя
        if employee and should_mention:
            mention = f"{task['assignee']} {employee['telegram_username']}"
        else:
            mention = f"{task['assignee']}"
        
        # Формируем время и статус
        hours_left = task['hours_until_due']
        time_str = self._format_time(hours_left)
        sla_status = self._get_sla_status(hours_left)
        
        # Добавляем задачу в общее сообщение
        message += (
            f"📌 Задача: {task['id']}\n"
            f"🔗 Ссылка: {task['url']}\n"
            f"📋 Название: {task['title']}\n"
            f"👤 Исполнитель: {mention}\n"
            f"⏰ Дедлайн: {task['due_date'].strftime('%d.%m.%Y %H:%M')}\n"
            f"⌛ Осталось: {time_str}\n"
            f"📊 {sla_status}\n"
            f"📈 Статус: {task['status']}\n"
            f"🎯 Приоритет: {task['priority'] or 'Не указан'}\n\n"
        )
        
        # Добавляем разделитель между задачами (кроме последней)
        if i < len(tasks) - 1:
            message += f"{'—' * 45}\n\n"
        
        # Если это не ручной вызов, добавляем задачу в список уведомлённых
        if not is_manual:
            self.notified_tasks.add(task['id'])
        
        # Telegram имеет лимит на длину сообщения (4096 символов)
        if len(message) > 3500:
            # Добавляем финальное обращение перед отправкой
            if not message.endswith("Коллеги, обратите внимание на задачи!"):
                message += "Коллеги, обратите внимание на задачи!"
            
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                disable_web_page_preview=True
            )
            # Начинаем новое сообщение
            message = "⚠️ Внимание! Приближается SLA! (продолжение)\n\n"
    
    # Добавляем финальное обращение, если его ещё нет
    if message and not message.endswith("Коллеги, обратите внимание на задачи!"):
        message += "Коллеги, обратите внимание на задачи!"
    
    # Отправляем остаток сообщения
    if message and len(message) > 0:
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                disable_web_page_preview=True
            )
            logger.info(f"✅ Отправлено общее уведомление с {len(tasks)} задачами")
        except TelegramError as e:
            logger.error(f"❌ Ошибка отправки общего уведомления: {e}")
