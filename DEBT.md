# DEBT - Content Factory

## Открыто после phase 1
- Реальные staging smoke-тесты адаптеров и прав приложений не выполнялись по условиям задачи.
  Перед продом проверить нужные форматы, media limits и фактические внешние ID на отдельных тестовых каналах.
- Нужен операторский процесс сверки unknown с аудитом решения; сейчас доступны read-only hooks и журнал.
  Telegram Bot API не восстанавливает потерянные message_id, IG container ID не заменяет media ID.
- Postiz delete не удаляет опубликованный социальный объект; метод явно возвращает UnsupportedOperation.
- Pending job, принятый внешним сервисом до blackout, может завершиться позже независимо от фабрики.
  Перед продом определить допустимый запас до blackout и проверять задержки исполнителя.
- Медиа пока представлены путями/URL и метаданными. Приватный object storage, signed derivatives,
  согласия и QA относятся к следующим фазам; локальные оригиналы автоматически не раздаются.
- Авторизация операторов, AI-куратор, intake, UI, уведомления и webhook-сверка остаются вне первой фазы.

## Open from phase-1 cross-model review (2026-10-25)
Fixed in round 2: findings 1-4, 10, 12, 13, 14. Still open, P2:
- 5: interruptions that provably produced nothing public still end as failed/unknown (could be safely deferred).
- 6: Postiz adapter does not enforce documented media limits; `ERROR` with partial publication; `QUEUE` without deadline.
- 7: IG container polling sleeps inside the global lock.
- 8: `history()`/`slots()` unbounded and N+1.
- 9: reconcile rewrites state each tick, original error text lost, stuck deliveries need alerting.
- 11: tenant isolation is enforced at the database layer only; add service-layer checks with the admin/bot phases.
