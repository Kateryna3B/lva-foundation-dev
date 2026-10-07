# LVA Foundation: актуальна точка входу

Програма 0.2.4; організаційна редакція org2 від 2026-10-07. Функціональний код не змінено. Це пілот, не завершена система LVA/XLSX.

- Оператор: [інструкція](docs/OPERATOR_GUIDE_UA.md).
- Встановлення й оновлення: [розгортання](docs/DEPLOYMENT_UA.md).
- Резервування, відновлення, діагностика: [експлуатація](docs/OPERATIONS_UA.md).
- Поточний стан і обмеження: [матриця вимог](docs/REQUIREMENTS_MATRIX.md), [відомі проблеми](docs/KNOWN_ISSUES.md).
- Короткий стан: [PROJECT_STATE](PROJECT_STATE.md); [оцінка Gemini і сервісів](docs/agents/GEMINI_REVIEW_ORG2_UA.md).
- План: [ROADMAP](docs/ROADMAP.md), [рішення](docs/DECISIONS/001-approved-plan.md).
- Розробка та Git: [DEVELOPMENT](docs/DEVELOPMENT_UA.md), [журнал](docs/DEVELOPMENT_LOG.md), [CHANGELOG](CHANGELOG.md).
- Агенти: [схема роботи](docs/agents/WORKFLOW_UA.md), окремі промпти в docs/agents/prompts.
- Приймання: [контрольна точка](docs/ACCEPTANCE/BASELINE_0_2_4.md).

Для звичайного запуску Git не потрібний. Розпакуйте весь пакет, запускайте source/Start_Foundation.bat, виберіть існуючий основний робочий каталог. Заголовок 0.2.4 у пакеті org2 правильний. Інструкції START_0_2_3_UA.md, START_0_2_4_UA.md і WHISPERX_* залишено як історичні; актуальними є документи вище.

Git bundle та START_HERE_UA.md лежать у корені організаційного ZIP, на рівень вище папки source. Історичний README збережено в docs/archive. Сирі записи, реєстри справ, venv та ваги моделей не входять у репозиторій.
