# Оцінка пропозиції Gemini та наступні кроки

Дата: 2026-10-07. Це концептуальна рецензія наданого тексту; функціонального коду Gemini для перевірки не надано. Перевірено локальний Git стан та офіційні джерела нижче.

## Рекомендації
| Теза Gemini | Рішення | Обґрунтування |
|---|---|---|
| Компактні контракти та атомарні задачі | ACCEPT | Зменшують зайвий контекст і задають критерії сумісності |
| PROJECT_STATE.md | ACCEPT | Короткий versioned індекс з commit та доказами; не дублювання журналу |
| Замовник переносить код, запускає все, робить merge | REJECT для нашої роботи | Диспетчеризацію/Git/інтеграцію виконує головний агент; замовнику лише його локальний acceptance |
| Окремий постійний чат-архітектор | DEFER | Архітектор і інтегратор зараз одна роль; незалежна думка через checkpoint review |
| Три постійні виконавці | ADAPT | Ролі збережено; за замовчуванням один виконавець і послідовний QA |
| B працює лише після A | ADAPT | Root володіє контрактами; B1/store та A validator можуть бути незалежними |
| Нульовий cross-context | ADAPT | Чернетки не потрібні; прийняті рішення, unresolved risks та залежності потрібні |
| Новий чат після 15 повідомлень | REJECT як жорстке правило | Межа задачі, обсяг контексту та якість результату важливіші за кількість повідомлень |
| Три однакові невдалі спроби → аудитор | ADAPT | Раніше збирати minimal reproduction; критичні ризики ескалувати одразу |
| Pydantic або dataclasses для всіх контрактів | DEFER | Спершу typed API/contract та tests; не додаємо обов'язкову залежність заради форми |
| QA пише unit/mocks | ADAPT | Плюс інваріанти, integration/recovery/Windows acceptance; автор також перевіряє свою реалізацію |
| GitHub критично необхідний | ADAPT | Корисний для спільної роботи, але Git/worktree вже працюють локально |
| CI гарантовано безкоштовний | ADAPT | Private hosted runners мають plan-dependent квоту; не обіцяємо необмежені запуски |
| .gitignore блокує витік | REJECT як гарантію | Не діє на вже tracked файли; force add/інші формати/історія потребують перевірки |
| Drive непотрібний крім 1–2 WAV | ADAPT | Корисний також для дозволених довідкових матеріалів, release ZIP/bundle і великих fixtures |
| Синхронізація SQLite неминуче зіпсує БД | REJECT як твердження неминучості | Ризик залежить від доступу/FS/копіювання; live sync все одно виключаємо з нашого workflow |
| Docs/Sheets як окреме джерело плану | ADAPT | Чернетки/проєкції; затверджені contracts/ADR у Git, одна канонічна дошка задач |
| Локальний test run = 0 токенів | ADAPT | Сам Python не викликає LLM; підготовка, tool interaction та інтерпретація теж можуть споживати бюджет |
| 2–3K/5–8K токенів і підключення за 5 хв | DEFER як оцінку | Це не замір; довжина вхідних даних, retries, доступи й аудит історії невідомі |

## Рекомендований мінімальний стек
| Інструмент | Тепер | Роль / межа |
|---|---|---|
| Локальний Git | Уже є | Код, історія, теги, ізоляція задач, bundle |
| GitHub private | Перший кандидат на підключення | PR, CI, remote backup історії; без аудіо/реальних transcripts/реєстрів |
| Google Drive | За потреби | Довідкові файли, готові випуски, heavy synthetic fixtures; не sync робочої Git/DB папки |
| Google Docs | За потреби для спільних обговорень | Чернетки ТЗ/коментарі; freeze в Git ADR/contract |
| Google Sheets | Відкласти дублюючий tracker | Необов'язкова проєкція, якщо команда справді її використовує |
| Окремий Google Workspace tenant | Не потрібен лише заради цього етапу | Повернутися при потребі admin/identity/domain controls; Google Docs доступний з Google Account |

## Перед GitHub publish
Погодити account/owner, назву private repo та права. Перевірити всі tracked файли та історію, включно з docs/logs/JSON, на дані реальних справ і secrets; .gitignore не є security boundary. Перевірити vendor/license склад, а не автоматично push всього bundle. Нічого не вилучати/переписувати в історії мовчки. При знахідці — окреме рішення про дозволений clean snapshot чи очищення історії.
Після перевірки: погоджений remote, одна гілка на task, PR, review, merge gate. Наявність плагіна не дорівнює permission на довільний push; фактичні read/write/CLI можливості перевірити після підключення.
CI: короткий synthetic/headless suite (поточна команда python -m unittest discover -s tests -v); Windows runner для відповідних системних перевірок, Linux — де корисно. Не завантажувати WhisperX/models у базовий suite. Не запускати real cases в hosted CI. Перший workflow перевірити на конкретному HEAD; поточні 58 історичних tests не гарантують green на іншому OS. Бюджет/retention/branch restrictions перевірити на фактичному account plan. Автоматичне production deployment не потрібне.

## Фактичний стан
До цього етапу HEAD org1 і чиста копія, remote немає. Після org2 лише docs/prompts; програма 0.2.4, схему БД не змінено. S1-A quota failure підтверджений; B завершення не підтверджено, C не запускався. GitHub запропоновано до підключення, але не підключено. Drive tools доступні; конкретну папку не читали/не створювали. Gemini звіт отримано від замовника, не автоматичним викликом.

## Наступна хвиля
Спершу S1-B1 (cache contract), потім S1-A і S1-B2 з окремими criteria, далі C на candidate та інтеграція. GitHub не блокує локальні виправлення. Сирі JSON потрібні для доведення причини хвостів, але не для розробки валідатора. Чеклист для Windows та дані на погодження входять у цілісний release candidate.

## Офіційні джерела (перевірено 2026-10-07)
- GitHub Actions quota/billing: https://docs.github.com/en/actions/concepts/billing-and-usage
- Семантика gitignore: https://git-scm.com/docs/gitignore
- SQLite locking/copying hazards: https://www.sqlite.org/howtocorrupt.html
- Google Docs та Google Account: https://workspace.google.com/products/docs/
