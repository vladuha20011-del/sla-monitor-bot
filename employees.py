"""
Список сотрудников для SLA мониторинга
"""

EMPLOYEES = [
    {
        "id": 1,
        "full_name": "Бухвиц Владислав Александрович",
        "search_names": ["бухвиц", "владислав"],
        "telegram_username": "@armagedon1820",
        "email": "bukhvits-va@sbertroika.ru",
        "username": "bukhvits-va"
    },
    {
        "id": 2,
        "full_name": "Ягубов Сергей Фарман оглы",
        "search_names": ["ягубов", "сергей"],
        "telegram_username": "@happy_zerg",
        "email": "yagubov-sf@sbertroika.ru",
        "username": "yagubov-sf"
    },
    {
        "id": 3,
        "full_name": "Тыркова Елена Григорьевна",
        "search_names": ["тыркова", "елена"],
        "telegram_username": "@Lenin30stm",
        "email": "tirkova-eg@sbertroika.ru",
        "username": "tirkova-eg"
    },
    {
        "id": 4,
        "full_name": "Хрусталев Дмитрий Александрович",
        "search_names": ["хрусталев", "дмитрий"],
        "telegram_username": "@xrystalevdmitrii",
        "email": "hrustalev-da@sbertroika.ru",
        "username": "hrustalev-da"
    },
    {
        "id": 5,
        "full_name": "Хасанов Ильгиз Раушанович",
        "search_names": ["хасанов", "ильгиз"],
        "telegram_username": "@Don1Kor",
        "email": "hasanov-ir@sbertroika.ru",
        "username": "hasanov-ir"
    },
    {
        "id": 6,
        "full_name": "Хайрутдинов Нияз Ринурович",
        "search_names": ["хайрутдинов", "нияз"],
        "telegram_username": "@khairutdinovn",
        "email": "khayrutdinov-nr@sbertroika.ru",
        "username": "khayrutdinov-nr"
    },
    {
        "id": 7,
        "full_name": "Саттаров Имиль Ильшатович",
        "search_names": ["саттаров", "имиль"],
        "telegram_username": "@imilst",
        "email": "sattarov-ii@sbertroika.ru",
        "username": "sattarov-ii"
    },
    {
        "id": 8,
        "full_name": "Сарибекян Раффи Ашотович",
        "search_names": ["сарибекян", "раффи"],
        "telegram_username": "@raffisar",
        "email": "saribekyan-ra@sbertroika.ru",
        "username": "saribekyan-ra"
    },
    {
        "id": 9,
        "full_name": "Матовников Александр Сергеевич",
        "search_names": ["матовников", "александр"],
        "telegram_username": "@autti5",
        "email": "matovnikov-as@sbertroika.ru",
        "username": "matovnikov-as"
    },
    {
        "id": 10,
        "full_name": "Малеев Михаил Алексеевич",
        "search_names": ["малеев", "михаил"],
        "telegram_username": "@hulobvee",
        "email": "maleev-ma@sbertroika.ru",
        "username": "maleev-ma"
    },
    {
        "id": 11,
        "full_name": "Веселков Даниил Владимирович",
        "search_names": ["веселков", "даниил"],
        "telegram_username": "@veselkov_st",
        "email": "veselkov-dv@sbertroika.ru",
        "username": "veselkov-dv"
    },
    {
        "id": 12,
        "full_name": "Мифтахутдинов Даниил Рахимович",
        "search_names": ["мифтахутдинов", "даниил"],
        "telegram_username": "@speic1",
        "email": "miftakhutdinov-dr@sbertroika.ru",
        "username": "miftakhutdinov-dr"
    },
    {
        "id": 13,
        "full_name": "Папов Ильяс Бесланович",
        "search_names": ["папов", "ильяс"],
        "telegram_username": "@roiILyasik",
        "email": "papov-ib@sbertroika.ru",
        "username": "papov-ib"
    },
    {
        "id": 14,
        "full_name": "Корженков Александр Дмитриевич",
        "search_names": ["корженков", "александр"],
        "telegram_username": "@korzhenkovad",
        "email": "korzhenkov-ad@sbertroika.ru",
        "username": "korzhenkov-ad"
    }
]

# Функция для поиска сотрудника по тексту (имени из задачи)
def find_employee_by_name(name_text):
    """
    Ищет сотрудника по тексту (например, "Бухвиц Владислав" или "Бухвиц Владислав Александрович")
    Возвращает сотрудника и его Telegram username
    """
    if not name_text:
        return None
    
    name_text_lower = name_text.lower().strip()
    
    for employee in EMPLOYEES:
        # Проверяем полное совпадение
        if employee["full_name"].lower() == name_text_lower:
            print(f"✅ Найдено по полному имени: {employee['full_name']} -> {employee['telegram_username']}")
            return employee
        
        # Проверяем по ключевым словам (фамилия + имя)
        all_keywords_found = all(
            keyword in name_text_lower 
            for keyword in employee["search_names"]
        )
        
        if all_keywords_found:
            print(f"✅ Найдено по ключевым словам: {employee['full_name']} -> {employee['telegram_username']}")
            return employee
        
        # Проверяем частичное совпадение (например, ищут без отчества)
        name_words = employee["full_name"].lower().split()
        search_words = name_text_lower.split()
        
        # Проверяем, что каждое слово из поиска есть в полном имени
        words_match = all(
            any(search_word in name_word for name_word in name_words)
            for search_word in search_words
        )
        
        if words_match and len(search_words) > 0:
            print(f"✅ Найдено по частичному совпадению: {employee['full_name']} -> {employee['telegram_username']}")
            return employee
    
    print(f"❌ Сотрудник не найден: '{name_text}'")
    return None

# Функция для поиска сотрудника по email (если в API есть email)
def find_employee_by_email(email):
    """Ищет сотрудника по email"""
    if not email:
        return None
    
    email_lower = email.lower()
    for employee in EMPLOYEES:
        if employee.get("email") and employee["email"].lower() == email_lower:
            return employee
    return None

# Функция для поиска сотрудников по фамилии (для команды /request)
def find_employees_by_lastname(lastname: str) -> list:
    """
    Ищет сотрудников по фамилии (частичное совпадение)
    Возвращает список найденных сотрудников
    """
    lastname_lower = lastname.lower().strip()
    found = []
    
    for employee in EMPLOYEES:
        # Проверяем, содержится ли фамилия в full_name
        if lastname_lower in employee['full_name'].lower():
            found.append(employee)
        # Также проверяем по search_names
        elif any(lastname_lower in name for name in employee['search_names']):
            if employee not in found:
                found.append(employee)
    
    return found

# Функция для получения всех Telegram username
def get_all_telegram_mentions():
    """Возвращает строку со всеми @username через пробел"""
    return " ".join([emp["telegram_username"] for emp in EMPLOYEES])

# Для тестирования
if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("🔍 ТЕСТИРОВАНИЕ ПОИСКА СОТРУДНИКОВ")
    print("=" * 60)
    
    test_names = [
        "Бухвиц Владислав",
        "Бухвиц Владислав Александрович",
        "Владислав Бухвиц",
        "Ягубов Сергей",
        "Тыркова Елена",
        "Хрусталев Дмитрий",
        "Хасанов Ильгиз",
        "Хайрутдинов Нияз",
        "Саттаров Имиль",
        "Сарибекян Раффи",
        "Матовников Александр",
        "Малеев Михаил",
        "Веселков Даниил",
        "Мифтахутдинов Даниил",
        "Папов Ильяс",
        "Корженков Александр",
        "Неизвестный Автор"
    ]
    
    print("\n📋 Результаты поиска:")
    print("-" * 60)
    
    for name in test_names:
        print(f"\n🔎 Поиск: '{name}'")
        employee = find_employee_by_name(name)
        if employee:
            print(f"   👤 Найден: {employee['full_name']}")
            print(f"   📱 Telegram: {employee['telegram_username']}")
        else:
            print(f"   ❌ Не найден")
    
    print("\n" + "=" * 60)
    print(f"📱 Все Telegram упоминания:")
    print(get_all_telegram_mentions())
    print("=" * 60)
