# Adversarial review PLAN-PLATFORM.md

Дата 2026-11-05. Вердикт: направление "тонкий форк Postiz + Python-фабрика" совместимо с целью, но план пока нельзя считать спецификацией безопасного запуска. Ни единый admission-вызов, ни существующий delivery fence фабрики сами по себе не контролируют фактические отправки Postiz и legacy.

## Метод и границы

Прочитаны все 13 исходных Markdown-файлов в `research/2026-11-05/`, код ядра `src/content_factory`, миграции, README/ARCHITECTURE/MANIFEST/DECISIONS/DEBT и относящиеся к выводам тесты. Дополнительно прочитаны локальные исходники YourHelp, autopost WWG и steward. Прод, Docker, аккаунты и внешние API публикации не вызывались. Существующие тесты не запускались: они создают файлы, а задание разрешает запись только этого отчёта. Число 185 passing взято из прежнего исследования, здесь заново не подтверждено.

Postiz проверен непосредственно в клоне. `git describe --tags --always` = `v2.25.3`, HEAD = `a5affe62c74e39c1e7ac960d50d8418b807d532c`, рабочее дерево клона чистое. Это статическое ревью, не runtime-доказательство эксплуатации. Где описана будущая реализация, находка означает пробел спецификации, а не утверждение о уже существующей уязвимости.

Обозначения путей для всех ссылок `файл:строка` ниже:

- `PLAN` = `/Users/pavlopopravkin/www/content-factory/research/2026-11-05/PLAN-PLATFORM.md`.
- `R` = `/Users/pavlopopravkin/www/content-factory/research/2026-11-05`.
- `CF` = `/Users/pavlopopravkin/www/content-factory`.
- `PZ` = `/tmp/claude-1003/postiz-src/postiz-app`.
- `YH` = `/Users/pavlopopravkin/www/yourhelp/autopost`.
- `AP` = `/Users/pavlopopravkin/www/server-root/scripts/autopost`.
- `ST` = `/Users/pavlopopravkin/www/server-root/scripts/steward`.
- `FACTS` = `/Users/pavlopopravkin/www/wwgwow/.planning/facebook-pilot/approved-business-facts.json`.

Серьёзность: `critical` означает обход обязательного запрета либо риск повторной публичной отправки; `high` означает потерю публикаций/изоляции или обязательную незапланированную часть продукта; `medium` означает существенный пробел эксплуатации или неверное основание оценки; `low` означает локальную неточность без самостоятельного нарушения запрета.

## Critical

### C01. Guard в postSocialBody не является границей каждого внешнего действия

**severity: critical.** Утверждение, что guard ловит все пути, опережает выбранную реализацию (`PLAN:51-54`, `PLAN:339`, `PLAN:344-345`, `PLAN:487`).

**Доказательства.** `PZ/apps/orchestrator/src/activities/post.activity.ts:347-413` вызывает первичный provider, но комментарии идут отдельно через `:209-255`, финализация через `:452-462`, plugs через `:554-575`. В `PZ/apps/orchestrator/src/workflows/post-workflows/post.workflow.v1.1.2.ts:449-462` перед комментарием есть отдельный sleep; `:341-359` вызывает финализацию после опроса. Plugs исполняются после задержки в `:642-675`, а `PZ/libraries/nestjs-libraries/src/database/prisma/integrations/integration.service.ts:601-610` и `:628-639` вызывают методы provider напрямую.

Даже guard перед КАЖДЫМ вызовом метода provider недостаточен. Один `InstagramProvider.finalizePost()` публикует несколько stories в цикле (`PZ/libraries/nestjs-libraries/src/integrations/social/instagram.provider.ts:939-961`); Telegram отправляет несколько медиагрупп в одном вызове (`PZ/libraries/nestjs-libraries/src/integrations/social/telegram.provider.ts:268-289`). Первый HTTP может быть до начала окна, следующий уже внутри. Facebook загружает фото параллельно, затем отдельно отправляет `/feed` (`PZ/libraries/nestjs-libraries/src/integrations/social/facebook.provider.ts:865-925`).

**Закрытие.** До оценки P1 зафиксировать все внешние мутации и точки проверки непосредственно перед каждым HTTP/SDK-send, включая внутренние циклы. Для неиспользуемых comments/plugs/repeat установить серверный запрет. Проверить пересечение окна МЕЖДУ двумя отправками одной activity, а не только запуск activity внутри окна. Поиск T4.1 только по `PZ/apps` пропускает сами provider и HTTP-клиенты в `PZ/libraries` (`PLAN:486`).

### C02. Postiz повторяет неоднозначные POST внутри provider и workflow, а ядро принимает ERROR за доказанный отказ

**severity: critical.** Обещание "потерянный ответ = unknown без повтора" (`PLAN:349`, `PLAN:359`, `PLAN:381-382`) не выполняется одним fence фабрики.

**Доказательства.** `PZ/libraries/nestjs-libraries/src/integrations/social.abstract.ts:603-607` выполняет fetch; `:628-653` повторяет тот же запрос после 429, необъяснённого 500 и provider-retry, без различения GET/POST и без нового policy-вызова. GBP создаёт localPost именно этим клиентом (`PZ/libraries/nestjs-libraries/src/integrations/social/gmb.provider.ts:475-487`). После нескольких отказов клиент бросает `BadBody` (`social.abstract.ts:620-623`), хотя 500 не доказывает отсутствие публичного результата.

У workflow mutation `maximumAttempts: 1` действительно стоит (`PZ/apps/orchestrator/src/workflows/post-workflows/post.workflow.v1.1.2.ts:74-91`), но вокруг неё остаётся ручной цикл из пяти итераций (`:113`, `:433-445`). Неизвестная application failure классифицируется как `unknown` (`:281-306`), затем код после `:555-578` может перейти к следующей итерации. Это не то же самое, что запрет повтора. Кроме того, отсутствие heartbeat трактуется как доказательство "activity не стартовала" (`:271-276`), хотя `withHeartbeat` посылает первый heartbeat только по таймеру через 15 секунд (`PZ/libraries/nestjs-libraries/src/temporal/temporal.heartbeat.ts:45-76`). Сбой worker после быстрого внешнего успеха до первого heartbeat требует отдельного разбора.

`markUnconfirmed()` записывает именно `ERROR` (`post.workflow.v1.1.2.ts:312-327`). `PublishedWithError` сохраняет release ID, затем бросает `BadBody` (`PZ/apps/orchestrator/src/activities/post.activity.ts:305-324`). Однако `CF/src/content_factory/publishers/postiz.py:88-89` безусловно превращает ERROR в FAILED. Тест закрепляет этот маппинг (`CF/tests/test_postiz.py:55-60`).

**Закрытие.** Описать transport-state-machine внутри Postiz: никакого повторного mutation после 500/обрыва/неизвестной ошибки без доказанного отсутствия эффекта; каждый повтор проходит policy заново. Различать policy-denied-before-send, provider-rejected, partial и unconfirmed. Сохранять известные ID даже при ERROR. Повтор после восстановления фабрики из `PLAN:349` допустим только по отдельному доказательству, что ни один внешний шаг этой попытки не начался.

### C03. Одобрение и связь postId со слотом допускают повтор уже опубликованного поста

**severity: critical.** `/policy/admit` описан как проверка хеша, организации, времени и номера попытки, но не как атомарная выдача одноразового права на конкретную мутацию (`PLAN:343-349`).

**Доказательства.** `PZ/libraries/nestjs-libraries/src/database/prisma/posts/posts.service.ts:1384-1406` принимает `status=schedule`, меняет состояние на QUEUE и стартует workflow без проверки прежнего PUBLISHED/ERROR. Public API предоставляет этот метод (`PZ/apps/backend/src/public-api/routes/v1/public.integrations.controller.ts:636-643`). Отдельный `guardAgainstRepublish` есть в `posts.service.ts:1157-1165`, но эта status-ветка его не вызывает.

Также `intervalInDays` порождает новый child workflow с тем же postId и `postNow: true` (`PZ/apps/orchestrator/src/workflows/post-workflows/post.workflow.v1.1.2.ts:623-633`, `:706-725`); при `postNow` исходная проверка QUEUE и sleep обходятся (`:161-173`). Поле repeat приходит как top-level `inter` (`PZ/libraries/nestjs-libraries/src/dtos/posts/create.post.dto.ts:111-119`), а в хеше v2 оно не указано (`PLAN:193`).

**Сценарий.** Одобренный, известный фабрике пост повторно ставят через status API. Его текст, publishDate и хеш не меняются. Проверка "известный postId + правильный хеш" снова даёт allow. Новый workflow не проходит `Store.begin_delivery()`, поэтому UNIQUE в SQLite его не останавливает (`CF/src/content_factory/storage.py:299-311`).

**Закрытие.** Нужны durable operation/attempt IDs, проверка текущего состояния Delivery, атомарная reservation и запрет любого нового исполнения published/unknown. Для multi-step публикации разрешение привязывается к шагу/container ID, а не расходуется один раз на весь пост. Repeat по умолчанию запретить; отдельное повторение требует нового слота и апрува. Проверить два конкурентных workflow и повтор status=schedule для опубликованного postId.

### C04. План оставляет явные исключения из жёсткого owner approval

**severity: critical.** В текущем задании owner approval перед публикацией указан как hard rule. План сохраняет `none` для YourHelp/OurKids/ministry (`PLAN:34-36`, `PLAN:160`, `PLAN:258`, `PLAN:321`) и разрешает `via=grant` от Pavel для WWG (`PLAN:323`, `PLAN:416`). Старое разрешение автопостинга YourHelp действительно существует (`YH/intake/TASK-INTAKE.md:3-5`), но оно не является разрешением выключить новое требование у OurKids/ministry или заменять владельца WWG оператором платформы.

**Доказательства.** Текущее ядро принимает апрув без личности (`CF/src/content_factory/storage.py:186-204`), CLI также не знает актора (`CF/src/content_factory/cli.py:120-126`). Добавить строку actor в аудит недостаточно: сервер должен проверить, что это назначенный владелец именно этого tenant.

**Закрытие.** В ревизии плана явно разрешить конфликт нового hard rule со старым YourHelp auto-mode. Пока исключение не подтверждено в рамках нового требования, целевой режим required. WWG approval создаётся только от назначенного owner identity, не от admin/LLM/импортированного grant. Исторический grant остаётся историей и не становится разрешением на будущую отправку.

## High

### H01. Bridge и active_publisher не обеспечивают поканальный cutover legacy

**severity: high.** Флаг в БД фабрики (`PLAN:170`, `PLAN:196`) старые процессы не читают. Переключение флагом в M5/M6 и T7.2 не специфицировано на владеющем слое (`PLAN:397-398`, `PLAN:517-518`).

**Доказательства.** `YH/slots.py:198-201` исключает выполненное по slot ID целиком; состояние записывается один раз на весь набор каналов (`:226-233`). `AP/engine.py:344-368` тоже блокирует весь slot ID, а не channel. Фактические каналы берутся из `item['channels']` (`YH/slots.py:153-165`, `AP/engine.py:314-329`). Нет обращения к active_publisher фабрики.

Если TG уже отправлен фабрикой, а FB/IG ещё legacy, единый slot-status нельзя трактовать как выполненные все каналы. Снятие канала из нового плана не останавливает процесс, уже прочитавший старый план. Rollback без переноса новых delivery ID повторит отправки.

**Закрытие.** Задачи на оба legacy consumer: экспорт только принадлежащих им каналов, остановка новых admissions, drain начатых слотов, сверка ID и атомарное переключение generation/lease. Описать обратный cutover. Проверять конкурентный tick старого движка во время переключения, а не только семь дней без наблюдённых дублей.

### H02. Bridge сохраняет слабый апрув и шабат старого транспорта

**severity: high.** Первую пользу WWG предлагают дать через bridge до форка (`PLAN:418-427`, `PLAN:470`). На этой стадии L2 Postiz не участвует вообще.

**Доказательства.** WWG fingerprint включает значения полей и пути files (`AP/engine.py:63`, `:141-147`), но не байты файлов. Публикация читает их позже (`AP/engine.py:302-329`). Шабат/approval проверяются перед слотом (`:352-368`), не перед каждым HTTP внутри каналов. В YourHelp вообще одна проверка шабата перед всем due-списком (`YH/slots.py:210-236`).

Замена функции вычисления заката T1.7 не добавляет проверки между upload и finalize, между FB и IG, или после задержки. Замена файла по прежнему пути после апрува фабрики обходит legacy fingerprint.

**Закрытие.** Мост должен переносить immutable artifacts и подписанное разрешение на точный payload либо legacy transport должен вызывать общий send_gate на каждом шаге. При невозможности этого bridge остаётся явно ограниченным переходным режимом, а обещание доказанного нового апрува/шабата до Postiz-cutover снимается.

### H03. После M4 остаются несколько писателей slots.json и несколько источников нового сырья

**severity: high.** В M4 фабрика становится владельцем плана (`PLAN:396`), но нет задачи отключить/переадресовать старых производителей плана; M7 снимает кроны лишь в конце (`PLAN:399`).

**Доказательства.** `YH/intake/run.sh:39-49` запускает старый intake-builder; `:69-91` независимо запускает archive-builder. Куратор дописывает canon и вызывает push (`YH/intake/TASK-INTAKE.md:39-49`), `YH/intake/push-slots.sh:21` копирует файл в runtime. `YH/intake/social.py:110-125` редактирует тот же canon через text/cancel. Забор лички продолжает класть материал в старый inbox (`YH/intake/run.sh:24-35`), а shadow M2 в плане описан только для team_outbox.

**Закрытие.** В M4 отдельно переключить builders, archive refill, text/cancel, push и личный intake. Перенести pending/contributors/last_in_ts/archive-used, будущие AR-слоты и правила приоритета свежего сырья. До этого нельзя объявлять фабрику единственным владельцем плана. Архивный добор и украинская автоматическая сводка должны иметь отдельный acceptance, иначе после исчерпания свежих пачек лента встанет.

### H04. Импорт "78 published" маскирует частичные ошибки и смешивает разные журналы

**severity: high.** M1 и T1.6 требуют импортировать 78 записей как published и сравнить число (`PLAN:197`, `PLAN:393`, `PLAN:458`). Это не достаточная схема миграции per-channel Delivery.

**Доказательства.** `YH/slots.py:228-233` ставит `posted`, если успешен ХОТЯ БЫ ОДИН канал, сохраняя остальные в errors. Старый `autopost.py` тоже пишет `posted.jsonl` (`YH/autopost.py:364-366`), поэтому этот журнал не равен slots-state. Исследование сообщает 78 slot-state и 126 строк posted.jsonl (`R/yourhelp-system.md:117-120`), а также отдельные queue.json и её расхождение 27/33 (`R/yourhelp-system.md:44-45`).

**Закрытие.** Импортировать источники с namespace и исходным статусом, раскладывать успешные result по каналам, учитывать message_ids и ошибки. Неизвестное/частичное не помечать published всех каналов. Сравнивать множества `(legacy_source, slot, channel, external_id)` и pending-план, а не число строк. Pending-апрувы WWG нельзя переносить в новый hash v2 как действующие без повторного owner-review.

### H05. Кнопки approval в @croscor_bot сейчас не доставляются вообще

**severity: high.** T2.1/T2.2 создают новый webhook/gateway, но WWG оставляют на существующем боте, меняя лишь team_outbox (`PLAN:149`, `PLAN:210`, `PLAN:423`, `PLAN:466-470`).

**Доказательства.** Единственный consumer бота регистрирует `bot.on('message')` (`ST/croscor-bot/index.mjs:53-70`) и ставит webhook с `allowed_updates: ['message']` (`:117-122`). `callback_query` ни подпиской, ни обработчиком не охвачен. Сохраняемая row не содержит callback ID/from.id/data (`:57-65`). `team_outbox.py:98-110` маршрутизирует текстовые команды, не Telegram callbacks.

**Закрытие.** Отдельная задача на Server 1 relay: приём callback_query без замены существующего webhook, durable forwarding, дедуп update_id, проверка Telegram user ID на policy-сервере, answerCallbackQuery и запись результата. Нужен общий интерфейс отправки клавиатур существующим bot-owner. Второй webhook на том же токене запрещён; новый `/cf/tg/{bot_id}` эту интеграцию не заменяет.

### H06. Postiz Telegram не сохраняет текущий контракт YourCamp

**severity: high.** T6.4 ограничивается одним тестовым message_id (`PLAN:510`), хотя миграция должна сохранить поведение фонда.

**Доказательства.** `YH/slots.py:115-130` отделяет длинный текст и возвращает ВСЕ message_ids альбома. `CF/src/content_factory/publishers/telegram.py:29-37`, `:50-59` это сохраняет. В Postiz `PZ/libraries/nestjs-libraries/src/integrations/social/telegram.provider.ts:238-250` кладёт весь текст в caption и не передаёт video width/height/duration/thumbnail. При альбоме `:277-288` сохраняется только `response[0].message_id` первой группы; остальные ID теряются. Stories Instagram тоже возвращают один последний ID (`PZ/libraries/nestjs-libraries/src/integrations/social/instagram.provider.ts:939-974`).

**Закрытие.** Добавить обязательный provider-patch и промежуточный журнал каждого публичного ID до M5, поддержать длинные подписи и размеры видео. Acceptance: длинный украинский текст + 10 фото, mixed album и видео, сбой после первого успешного send, возможность найти/удалить каждый отправленный объект. Один сохранённый releaseId недостаточен.

### H07. В задачах нет реализации центрального DRAFT → publish адаптера

**severity: high.** В архитектуре это основной путь (`PLAN:51`, `PLAN:129`), но F1-F7 не назначают изменение `publishers/postiz.py` для создания зеркала, promotion и корреляции. Есть policy API, legacy bridge, guard и webhook; самого связующего протокола нет (`PLAN:453-510`).

**Доказательства.** `CF/src/content_factory/publishers/postiz.py:35-66` загружает медиа и сразу делает новый `type: now`; DRAFT, mapping, promote существующего ID отсутствуют. FB Reel явно отклоняется (`:37-38`), `PROVIDERS` не содержит gmb (`:14-15`). `PZ/libraries/nestjs-libraries/src/database/prisma/posts/posts.service.ts:1384-1406` меняет status на том же ID и НЕ меняет publishDate; `:1190-1192` для `type: now` перезаписывает дату текущим временем. Эти пути не взаимозаменяемы при включённом в hash when_utc.

**Закрытие.** До F4 определить и реализовать draft-upsert/map-before-start/promote/reconcile; выбрать один путь. Mapping обязан быть durable ДО запуска workflow, иначе guard отвергнет ещё неизвестный фабрике пост. У status-promotion повторить provider-validity, поскольку DRAFT-create пропускает часть валидации (`PZ/apps/backend/src/public-api/routes/v1/public.integrations.controller.ts:209-220`). Добавить gmb capabilities/settings и снять Reel-reject после P5. Сохранять один preview ID либо явно перевыпускать карточку с новым.

### H08. Hash v2 не описывает фактический payload после преобразований Postiz

**severity: high.** `PLAN:193`, `PLAN:347` обещают одобренные байты, но перечисляют текст, paths и settings до provider-преобразований. Проблема шире перезаписи файла по тому же пути.

**Доказательства.** `PZ/apps/orchestrator/src/activities/post.activity.ts:371-396` заменяет tags, преобразует HTML и разрешает media перед provider. `PZ/libraries/nestjs-libraries/src/database/prisma/posts/posts.service.ts:522-527` заменяет path на новый ready-normalized media, `:557-583` перекодирует PNG в JPEG. `:789-819` подставляет динамический releaseURL в content/settings. Обложка и alt находятся в MediaDto, не в provider-settings (`PZ/libraries/nestjs-libraries/src/dtos/media/media.dto.ts:15-21`); IG использует thumbnail в реальном запросе (`PZ/libraries/nestjs-libraries/src/integrations/social/instagram.provider.ts:759-765`). В описании hash отсутствуют отдельные thumbnail bytes, alt, thread/comments, delays, repeat и явный format.

**Закрытие.** Заморозить канонический per-channel execution payload после всех преобразований, включая обложку и каждый публичный текст; его и показывать владельцу. Нормализацию завершать до approval. Finalize проверяет связь подготовленного container с этой версией, не только текущий текст в БД. Запретить unsupported mutable/dynamic поля. Проверить изменение cover/alt/normalized media после approval и правку текста во время pending upload.

### H09. Пример WWG уже использует отсутствующий факт; видео и свободная проза не закрыты

**severity: high.** Карточка в `PLAN:218-219` называет Naperville и `family_owned` разрешёнными данными. В FACTS нет `family_owned` и нет происхождения конкретного кейса ванной в Naperville (`FACTS:13-34`). Это пример обхода собственной политики, а не допустимый fact_id.

Правила "неизвестное число/гарантия" и OCR derivative (`PLAN:326-328`, `PLAN:456`, `PLAN:478`) не определяют полный запрет неподтверждённых утверждений. "We use eco-safe products" не содержит числа или слова guarantee; разрешённые $175 и deep при неправильном сочетании всё равно дадут ложный оффер. Из старых видео могут прийти речь, субтитры, CTA/баннеры и текст на отдельных кадрах, которые OCR одной картинки не проверит. FACTS отдельно требует неизменённые правильно спаренные before/after и точные разрешённые файлы лиц (`FACTS:43-48`), а импорт всего архива не означает их допуск.

**Закрытие.** Каждое утверждение выводится из закрытого набора типизированных шаблонов с привязкой к пути/значению FACTS; свободные вставки не могут добавлять факты. Версия = digest канонического файла, не вручную присвоенный номер. Нужны задачи на video-frame/text/audio QA и visualRules, ручной quarantine для сомнительных материалов. Коррекция facts инвалидирует уже подготовленные pending executions, а approval владельца не повышает данные из заметки/истории до business-fact.

### H10. Обещание полной шабат-паузы не охватывает всю автоматизацию и уже работающие jobs

**severity: high.** `PLAN:317` запрещает даже обработку медиа, карточки и сводки, но задачи закрывают в основном factory и publication guard. Нет общего lifecycle-stop с inventory остальных workers.

**Доказательства.** Postiz digest ждёт час и отправляет email (`PZ/apps/orchestrator/src/workflows/digest.email.workflow.ts:33-63`), email activity сразу вызывает sender (`PZ/apps/orchestrator/src/activities/email.activity.ts:14-21`). Media activity вызывает processing независимо от policy (`PZ/apps/orchestrator/src/activities/media.activity.ts:10-19`). Telegram connect сам отправляет/удаляет сообщения вне post workflow (`PZ/libraries/nestjs-libraries/src/integrations/social/telegram.provider.ts:112-130`). У native-агента P4 меняет только draft-type, но не запуск LLM, генерации картинок, clipping и уведомлений (`PZ/libraries/nestjs-libraries/src/chat/tools/tool.list.ts:24-46`). `RUN_CRON` управляет запуском missing-post workflow (`PZ/libraries/nestjs-libraries/src/temporal/infinite.workflow.register.ts:8-18`), не общей паузой всего стека.

Старый `YH/intake/run.sh:22` проверяет окно до запуска 90-минутного куратора (`:45-49`), но не до сводок после его окончания (`:51-64`); alert при закрытом томе идёт вообще до guard (`:15-22`). Новый общий солнечный модуль этого порядка не исправляет.

**Закрытие.** Inventory каждой automation с владельцем и стоп-контрактом: запущенные curator/ffmpeg, notification queues, retry timers, email, media normalization, intake-analysis, backups/CI. Планирование старта не заменяет остановку работы на границе. Отдельно указать допустимое passive-inbox исключение и какие read-only диагностические действия разрешены. Оповещение из самого guard тоже проходит паузу, иначе запрет публикации вызовет уведомление в запрещённое время.

### H11. Подключение общего shabbat.py к legacy может превратить ошибку импорта в разрешение работы

**severity: high.** T1.7 предлагает импорт общего модуля в рабочие копии (`PLAN:312`, `PLAN:459`), но не описывает установку пакета у root/pavel и работу при закрытом vault.

**Доказательства.** В `YH/intake/run.sh:22` команда внутри `if` выходит из скрипта только при exit 0. Любая ошибка Python/import/env даёт ненулевой exit и трактуется как "не шабат". Рантайм publisher находится в `/root/compute`, а куратор/исходники могут быть недоступны (`YH/intake/run.sh:8`, `:15-22`; `R/yourhelp-system.md:123`). Импорт из расположенного в vault проекта не сохраняет доказанный режим работы без `/secure`.

**Закрытие.** Версионированный установленный policy-package в каждом runtime с fail-fast/fail-closed. Ошибку вычисления/импорта отличать от явного allow. Тестировать закрытый том, отсутствие пакета, несовместимый Python и invalid tz. Одно место исходника плюс воспроизводимая доставка пакета, а не runtime sys.path на соседний checkout.

### H12. SSO по orgId не задаёт прав approver, владельца и администратора платформы

**severity: high.** JWT описан только через текущего пользователя/org и сессию по orgId (`PLAN:285-287`, `PLAN:499`). Карта экранов содержит approver и superadmin (`PLAN:294-302`), но нет привязки Postiz user к Member/owner и правил изменения ролей.

**Доказательства.** Postiz имеет USER/ADMIN/SUPERADMIN, а не требуемые factory-роли. Menu role всего лишь фильтр отображения (`PZ/apps/frontend/src/components/layout/top.menu.tsx:250-253`). Endpoint без `@CheckPolicies` пропускается PoliciesGuard (`PZ/apps/backend/src/services/auth/permissions/permissions.guard.ts:33-40`). Поэтому P3 в PermissionsService не защитит автоматически новый `/factory/token` и все factory handlers. Удаление Stripe-shortcut также не равно готовой RBAC-модели: оставшийся код содержит тарифные лимиты и отдельную ADMIN-ветку (`PZ/apps/backend/src/services/auth/permissions/permissions.service.ts:65-135`).

**Закрытие.** JWT должен иметь проверяемые sub/org/aud/iss/exp и одноразовый exchange; factory membership проверяется сервером на каждом sensitive action. Определить platform-admin отдельно от org-SUPERADMIN, отзыв доступа/смену организации, CSRF и cookie path. Owner assignment не доступен tenant-editor. Deny-матрица должна включать USER своей org, org-admin соседнего tenant, отозванного пользователя и прямой заход на скрытую страницу.

### H13. Native calendar/edit в Postiz не имеет определённой связи с единственным планом фабрики

**severity: high.** Одновременно обещаны родные calendar/editor и единственный план фабрики (`PLAN:25`, `PLAN:76`, `PLAN:304`, `PLAN:322`). Guard отловит несовпадение в момент отправки, но это не переносит правку в Slot и не создаёт новый approval.

**Доказательства.** `PZ/libraries/nestjs-libraries/src/database/prisma/posts/posts.service.ts:1409-1445` меняет дату только в Postiz. `updatePostSettings` меняет только settings в native post (`:1234-1241`, `:1278-1297`). Отдельный MCP PostSettingsTool также пишет сюда (`PZ/libraries/nestjs-libraries/src/chat/tools/post.settings.tool.ts:74-80`), независимо от P4 force-draft для создания. В плане нет обработчика native edit/cancel/reschedule → новая factory version. Sweeper L3 описан для QUEUE без слота, а не для DRAFT drift (`PLAN:340`).

**Закрытие.** Выбрать явный контракт: factory-managed posts в native UI только чтение с переходом в factory editor, либо все native mutations проходят владельца factory-slot до сохранения. Не вводить второй независимый план. Acceptance: изменение времени, текста, настройки и удаление DRAFT сразу видны в Telegram и plan, старая карточка не действует; корректная правка не теряется молча при следующем mirror-upsert.

### H14. Ingress не имеет контракта durable update/batch, а голосовые и заметки легко потерять

**severity: high.** Модель BotSession использует tg_chat_id (`PLAN:188`), текст задаёт ключ по tg_user_id (`PLAN:205`); таблицы IntakeItem/Batch/update journal и source message IDs отсутствуют в модели (`PLAN:155-190`). T2.1 перечисляет сессию и webhook secret, но не дедуп/порядок событий.

**Доказательства.** Существующий приём сохраняет `text/near_text/from`, pending/contributors и last_in_ts (`YH/intake/social.py:69-100`). Заметки "тільки сторіс/тільки в канал" являются инструкциями текущего контракта (`YH/intake/TASK-INTAKE.md:8-11`). Старый bridge сохраняет только message и не media_group_id/update_id (`ST/croscor-bot/index.mjs:57-65`); транскрипция происходит раньше social send (`ST/inbox.py:204-226`). Простая замена маршрута social не создаст повторяемую связь текста после альбома с его batch.

**Закрытие.** Durable raw update до ACK, уникальный `(bot_id, update_id)`, source message/media_group IDs, tenant/member scope, восстановление после перезапуска, поздние файлы и связь voice/text с пачкой. Повтор webhook и повтор вызова team-tool не должны создать новый Asset/Slot. Проверить альбом + позднюю заметку + голосовое + смену tenant во время загрузки. Не подменять отправителя service-token'ом steward.

## Medium

### M01. Forward-auth allowlist написан не для фактических HTTP-путей и может закрыть preview/media

**severity: medium.** В allowlist указан `/public/v1`, но реальный внешний путь через комплектный nginx = `/api/public/v1` (`PLAN:71`, `PLAN:447`; `PZ/var/docker/nginx.conf:20-22`; `CF/src/content_factory/publishers/postiz.py:24`). Preview-комментарии используют `/public/posts/:id/comments` через backend fetch (`PZ/apps/frontend/src/components/preview/preview.comments.context.tsx:42-49`; backend `PZ/apps/backend/src/api/routes/public.controller.ts:54-87`), это не тот же `/public/v1`.

Медиа обслуживаются отдельным `/uploads/` (`PZ/var/docker/nginx.conf:36-50`). Если этот путь закрыть общим forward_auth, внешний Meta/GBP fetch не сможет скачать медиа и владелец без операционного доступа не увидит preview. Если оставить uploads полностью публичным, это не private tenant-library: URL обходит membership. Это нужно решить для derivatives отдельно от оригиналов.

**Закрытие.** Явная таблица внешних и upstream-путей с доступом для browser/client, social fetcher и S2 API, включая static assets, preview API и OAuth. Проверять сеть внешним browser и реальным media fetch, не только `curl /launches` 401. Оригиналы приватны; выдача derivatives ограничена временем и конкретным объектом, либо документирован осознанный публичный staging.

### M02. Временные расчёты плана противоречат собственным локациям

**severity: medium.** `PLAN:417` утверждает, что Испанское окно начинается "ещё раньше, около 11:00 Chicago", сравнивая с 10:28 Chicago. 11:00 позже 10:28. При этом обязательный Киев в union уже запрещает слот 10:00 независимо от video-lead.

**Проверка.** Чистый вызов имеющегося `CF/src/content_factory/solar.py:7-26` без файлов/сети для 06.11.2026 дал начало окна с margin 30: Kyiv `13:57:29Z`, Girona `16:08:25Z`, Chicago `22:10:26Z`. Слот 10:00 Chicago = `16:00Z`, уже после начала киевского окна. Это расчёт существующего приближённого модуля, не религиозный календарь и не определение местоположения Pavel.

"Испания-конверт" из четырёх материковых точек (`PLAN:314`) не обоснован как покрытие всей Испании: например, Tenerife даёт конец окна 07.11 `19:26:53Z`, позже Cádiz `18:34:08Z`. Обязательно либо ограничить область материком подтверждённым местом, либо покрыть острова; географические примеры не являются доказательством extrema на 52 недели.

**Закрытие.** Общий модуль считает локальную пятницу КАЖДОЙ локации, а не одну tenant timezone, как нынешний `CF/src/content_factory/planner.py:20-34`. Векторы должны включать реальные UTC instants, DST США/Европы в разные недели, границы дат и независимые ожидаемые значения. Минимум одна произвольная локация в конфиге ещё не обеспечивает неотключаемый платформенный профиль.

### M03. 2.1 GB проповедь через бота не имеет транспортного пути

**severity: medium.** Сценарий `PLAN:263-274` обещает файл 2.1 GB и обработку около часа, но задачи T2.1/T3.5 не включают local Bot API или web-upload, объёмные лимиты, resumable storage и rate/CPU budget.

**Доказательства.** Текущий steward скачивает через hosted `getFile` и hardcoded `api.telegram.org/file` (`ST/inbox.py:208-229`), где download ограничен 20 MB. [Telegram Bot API, File](https://core.telegram.org/bots/api#file) подтверждает этот предел. [Local Bot API server](https://core.telegram.org/bots/api#using-a-local-bot-api-server) снимает download limit, но это отдельный runtime с другой настройкой путей; предел upload там 2000 MB. Старый `CF/ARCHITECTURE.md:61-63` уже называл local API, новый task list этот шаг потерял. Сам Postiz nginx ограничивает body `2G` (`PZ/var/docker/nginx.conf:13`).

**Закрытие.** Отдельный транспорт больших файлов/ссылок с проверкой доступа и SSRF, размером до начала обработки и проверенным CPU-бенчмарком. Не обещать час до реального прогона 48-минутного файла на S2; критерия "3-5 таймкодов" T3.5 недостаточно для обещанных смонтированных субтитрованных роликов.

### M04. AGPL учтена декларативно, но источник релиза и сроки выдачи не поставлены задачами

**severity: medium.** `PLAN:50` правильно выбирает AGPL-форк, а `PLAN:544` честно отмечает неопределённость iframe-границы. Однако Source-link/Corresponding Source не имеют отдельного acceptance до F7. F9 и ребрендинг идут после первого сетевого использования форка (`PLAN:516-523`).

**Доказательства.** `PZ/LICENSE:542-548` требует заметного предложения Corresponding Source пользователям модифицированной сетевой версии. Это действует при её предоставлении, а не только после первой коммерческой продажи. `PZ/LICENSE:122-133` включает необходимые исходники и scripts для generation/install/run; одной пачки `FACTORY-PATCH` без исходников точного образа и сборки недостаточно. Modified notices/date и legal notices описаны в `PZ/LICENSE:196-221`. Продажа разрешена (`PZ/LICENSE:193-194`); обязательная всемирная публичность репозитория из §13 не следует, это добровольно выбранный удобный способ исполнения.

HTTP/iframe сам по себе не даёт юридической гарантии независимости. [GNU FAQ, aggregation](https://www.gnu.org/licenses/gpl-faq.en.html#MereAggregation) рассматривает характер связи программ, включая семантику обмена. MIT-код можно включить в AGPL-совместимую поставку, поэтому это не причина отказаться от архитектуры, но вывод "отдельный процесс автоматически вне объёма" делать нельзя.

**Закрытие.** До F7 source offer доступен пользователям UI/API/бота, применительно к их способу доступа; точный commit соответствует image digest, доступны fork source, contracts и build/install scripts, сохранены notices. Решить объём исходников совместной поставки. Polotno не считать решённым отсутствием env-key: он импортируется в frontend (`PZ/apps/frontend/src/components/launches/polonto.tsx:12-18`) и присутствует в dependencies (`PZ/package.json:202`); нужен проверенный build-time disable/лицензия. Это чтение условий и технический список проверки, не юридическое заключение о sidecar.

### M05. Бэкап Postiz не является восстановлением единой платформы

**severity: medium.** T0.2 требует pg_dump + uploads и доказывает restore только количеством Integration (`PLAN:446`). Между тем единственный delivery fence/апрувы лежат в отдельной SQLite, workflow-state в Temporal, бот nonce/inbox ещё в отдельном сервисе (`PLAN:95-114`, `PLAN:155-190`).

**Доказательства.** `CF/migrations/002_recovery.sql:8-23` хранит защиту от повтора в factory DB. `PZ/libraries/nestjs-libraries/src/database/prisma/posts/posts.service.ts:972-993` запускает workflow в Temporal; незавершённое выполнение не выводится из count Integration. После несогласованного restore старый approval/nonce может ожить, а уже опубликованная попытка отсутствовать в restored factory journal.

**Закрытие.** Backup/restore runbook для factory DB с WAL-consistent snapshot, Postiz, Temporal и media mapping, с точкой согласования и restore quarantine. До возобновления отправок сверять неоднозначные попытки снаружи. Primary signal восстановления: не повторился существующий социальный объект и сохранился неопубликованный owner-approved слот, а не SELECT count.

### M06. Оценка сроков не включает несколько обязательных подсистем и недооценивает зависимости

**severity: medium.** Общие 30-34 инженерных дня (`PLAN:525`) не сходятся даже с суммой обозначенных фаз F0-F9: 31.5-36.5 дня без ожиданий и наблюдения. Параллельность сокращает календарь, но не engineering effort. Это арифметическая проверка, не новая точная оценка реализации.

**Доказательства.** F2 заявлена "на немодифицированном Postiz" (`PLAN:462`), но её основные callbacks требуют нового транспорта steward (H05). P1 5-6 дней F4 включает ещё SSO, permission fix, образ, CI и matrix (`PLAN:482-493`), не оценивая provider HTTP/SDK barriers, durable mutation journal и transport semantics из C01-C03. Dev-стенд T4.7 гасится после F4 (`PLAN:492`), хотя F6 ещё требует публикационных smoke и последующие upstream-релизы требуют той же поведенческой матрицы (`PLAN:353-360`).

Нет назначенных работ на draft/promote adapter, shared attempt-journal Postiz, callback relay, private storage/TTL, восстановление платформы, daemon/timer/restart policy фабрики, curator-runner/очередь/leases/recovery, перенос legacy producers и эксплуатационные процедуры token reconnect. T3.3 даёт prompts/JSON-contract, но не реализацию runner. T5.2 обещает девять экранов за три дня, включая неизвестные ещё auth/state контракты. F8 "3 дня кода" не покрывает перечисленные изменения трёх legacy-процессов и их откат.

**Закрытие.** Сначала ограниченный доказательный срез: один owner-approved WWG slot с FB/IG/GBP через Postiz, встроенные approvals+journal, все негативные transport-тесты. После него оценить фактическую patch surface и трудозатраты. OAuth/GBP feasibility запустить в начале, не после дорогой разработки; полноценный стенд сохранить для F6 и security upgrades. Цифры 14-15 дней до Postiz и 6-8 до безопасного bridge пока не имеют достаточной декомпозиции.

## Low

### L01. Несколько утверждений о текущем коде неверны или точнее своего источника

**severity: low.** Эти ошибки не создают обход сами по себе, но искажают объём работы и уверенность плана.

- `PLAN:193` говорит, что текущий hash не содержит settings. На самом деле `CF/src/content_factory/storage.py:165-168` включает ВЕСЬ channel config, а `CF/src/content_factory/config.py:91-92` уже содержит settings. Время в hash действительно отсутствует.
- `PLAN:198` и исследование `R/cf-core-fit.md:56` называют пример `blackout: []`. Фактический `CF/examples/tenants/demo/tenant.yaml:21-29` содержит weekly и sunset blackout с 30/70. Пустоту разрешает схема (`CF/src/content_factory/config.py:59`), а README намеренно отключает окно только в dry-copy (`CF/README.md:20-28`). Нужно исправить ссылку, сохранив задачу обязательности политики в schema.
- `PLAN:60` говорит о четырёх critical. Сам источник перечисляет три critical и один medium (`R/postiz-live.md:107`). Закрытие этих четырёх advisories не доказывает закрытие всех historical advisories, ставших основанием отказа 04.11. Это основание надо проверять отдельно, а не считать снятым по четырём записям.
- `PLAN:54` приводит "81, 81, 78". Реальный delivery-judge даёт 81 (`R/judge-delivery-risk.md:11`), cross-family итог 78 (`R/judge-cross-family.md:10`), отдельный Codex вердикт 75 (`R/codex-judge-verdict.md:3`). Повтор агрегированного голоса не является третьим независимым результатом 81.
- OAuth GBP не является неразрешённым противоречием исходников (`PLAN:374`): в `PZ/libraries/nestjs-libraries/src/integrations/social/gmb.provider.ts:22-27` прямо указаны `GOOGLE_GMB_CLIENT_ID/SECRET || YOUTUBE_CLIENT_ID/SECRET`. Видео отвергается `checkValidity` (`:59-74`), хотя тело post допускает mediaFormat VIDEO (`:439-445`). Следовательно, нормальный create-post не поддерживает видео; прямое наличие ветки VIDEO не доказывает поддержку.

## Что следует добавить в критерии готовности

Порядок ниже вытекает из находок; это не просьба менять прод во время ревью.

1. Зафиксировать owner-policy для каждого tenant и закрыть возможность operator-grant для будущих постов WWG.
2. Доказать mutation barrier на первичной отправке, finalize, каждом элементе последовательности, provider retry и восстановлении worker. Проверить policy-outage после частичного успеха.
3. Протестировать повтор status=schedule уже опубликованного postId, два конкурентных workflow и перезапуск до первого heartbeat. Итог каждого неоднозначного сценария сохраняет ID/unknown и не создаёт второй объект.
4. Сделать DRAFT/mapping/promote протокол и проверку реального замороженного payload, включая cover и prepared containers; запретить unsupported repeat/plugs/comments до их отдельного допуска.
5. Закрыть Server 1 callback relay и паритет TG-альбомов/длинных подписей до переключения YourCamp.
6. Проверить cutover с работающим legacy tick, двух писателей плана, partial ledger и rollback. Для shadow-curator сравнивать заранее определённые инварианты и согласованный редакторский результат, а не требовать побайтово ноль расхождений от двух независимых LLM-планов (`PLAN:395`).
7. Сохранить стенд, восстановить весь state graph, выдавать исходники точного fork-релиза с первого сетевого использования и только затем расширять библиотеку/девять экранов/коммерческий онбординг.

## Что не является находкой

Postiz v2.25.3 действительно содержит gmb, Telegram publisher, DRAFT без старта нового workflow и shared activity, в которую можно добавить policy-hook. Сам выбор Python-sidecar не противоречит админке внутри Postiz. AGPL допускает коммерческую продажу. Azure-вызовов в проверенных `PZ/apps`, `PZ/libraries`, `.env.example`, `package.json` не обнаружено: совпадения только в справочнике тегов Hashnode. Запрет Azure надо сохранить в будущем runtime-конфиге, но выдавать его текущим нарушением оснований нет.

Считалось на Mac. Работа состояла из чтения локальных файлов и зависимых проверок по их результатам; перенос на S2 не давал преимущества. Единственные вычисления были чистым вызовом solar.py и сложением фаз, без файлов состояния и сетевых публикаций. Записан только этот отчёт; commit/push не выполнялись по явному read-only ограничению задания.
