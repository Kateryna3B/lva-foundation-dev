# Дошка задач

| ID | Власник | Статус | Залежність / вихід |
|---|---|---|---|
| ORG-01 | Інтегратор | DONE | Git baseline і документація |
| ORG-02 | Read-only baseline agent | DONE | Звірка 0.2.4 і відомих дефектів, без ASR |
| ORG-03 | Read-only workflow agent | DONE | Схема 5 ролей, промпти, інтеграційний gate |
| S1-A | A | PLANNED | Діагностика хвостів; raw JSON доступність перевірити до початку |
| S1-B | B | PLANNED | reused contract, create/open; точний allowlist призначити |
| S1-C | C | PLANNED | Незалежні негативні тести S1-A/B |
| G-01 | Gemini | NOT_STARTED | Зовнішня рецензія org1 або S1 snapshot через користувача |

DONE тут означає завершення організаційного доручення, не приймання всього продукту. Base commit S1 береться з RELEASE_MANIFEST.json організаційного пакета; виконавець перевіряє його перед початком. Не розподіляти production-файли на основі одного лише цього списку без TASK_CARD.
