# Дошка задач — org2

Канонічна дошка до переходу на GitHub Issues. Виконання S1 ще не завершене.

| ID | Власник | Статус | Залежність / вихід |
|---|---|---|---|
| ORG-01 | Інтегратор | DONE | Git baseline і docs org1 |
| ORG-02 | Baseline reviewer | DONE | Read-only звірка baseline |
| ORG-03 | Workflow reviewer | DONE | Read-only ревізія промптів v1.0 |
| ORG-04 | Інтегратор | DONE | Gemini review, PROJECT_STATE, docs/prompts org2 |
| S1-A | A | BLOCKED_QUOTA → QUEUED | Попередній запуск без результату; нова task card перед відновленням |
| S1-B | B | ATTEMPTED_UNVERIFIED | Доручення відправлено; результат не підтверджено, розділено B1/B2 |
| S1-B1 | B / root | QUEUED | Cache contract + regression, окремий diff |
| S1-B2 | B | QUEUED | Explicit create/open + callers + no-side-effects tests |
| S1-C | C | NOT_STARTED | Незалежний QA конкретного candidate, інтеграційні критерії |
| G-01 | Gemini | INPUT_RECEIVED | Концептуальна рецензія через замовника; прямого API немає |
| DEV-GH | Інтегратор/замовник | PROPOSED | Підключення, private owner/repo, prepublish audit, CI |

QUEUED не означає поточний активний агент. Наступний агент отримує точний фактичний HEAD у task card, а не старий hash із чату.
