# Разметка

Настройки: `backend/app/.env`. Образец рядом — `.env.example`.
Ключ хранится только в `.env`, в Git он не попадает.

```python
from app.services.ai_agents import NewsTagger, ProfileTagger

news = NewsTagger().tag({
    "data-time": "2026-10-23T12:00:00+03:00",
    "title": "Открылась пекарня",
    "text": "В Москве начали выпекать хлеб для местных магазинов."
})
# Выход: те же поля + tags, список коротких кодов.

profile = ProfileTagger().tag({
    "city": "Москва",
    "text": "Я бухгалтер оптовой компании."
})
# Выход: city, text, tags.
```

- `news_tagger.py` — новости, Qwen.
- `profile_tagger.py` — компания или сотрудник, GLM.
- `manual_test.py` — вписать дату, заголовок, текст и нажать Run. JSON и теги выводятся в консоль. Один запуск — один платный запрос.
- `bad_news.py` — `add_bad_news(title, text, tags)`: сохранить неверные теги. Очередь хранит последние 20 записей.
- `backend/app/tags.json` — разрешённые теги.
- `backend/app/bad_news.json` — очередь ошибок; изначально 20 вымышленных учебных примеров.

Дата — ISO 8601 с часовым поясом. Классы принимают словарь или JSON-строку,
возвращают словарь. Неизвестные теги и неверные ответы вызывают ошибку.
Импорты выше работают из backend с установленными зависимостями проекта.

Бесплатные тесты из этой папки:
`PYTHONPATH=.. python -m unittest ai_agents.test_ai_agents`.
