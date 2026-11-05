# Postiz на S2: инвентаризация живой установки (только чтение)

Дата: 2026-11-05. Хост: Hetzner-S2 (`hostname`). Всё снято командами `docker inspect`, `docker ps`, `docker logs`, `ss`, `systemctl cat`, `psql` с `SET default_transaction_read_only = on` и только SELECT. Значения секретов не печатались и сюда не попали. Ничего не перезапускалось и не менялось.

## 1. Коротко

1. Postiz `v2.25.3` работает 10 дней (старт 2026-10-25 15:04 UTC). Это последний релиз upstream; все 4 critical-advisory от 02.11.2026 закрыты в 2.25.1-2.25.3.
2. **В Postiz ноль постов за всю историю.** Таблицы `Post`, `Media`, `Errors`, `Webhooks`, `AutoPost`, `Sets`, `Signatures`, `Customer`, `Tags`, `Comments`, `mastra_*` пусты. Публичный API за последние 10 дней не вызывался (0 строк `public/v1` в `docker logs --since 240h`).
3. Одна организация `Your Help UA`, один пользователь (LOCAL SUPERADMIN), три канала Facebook/Instagram. У всех трёх `tokenExpiration` в прошлом (14-15.09.2026), а у канала `Pavlo Popravkin` `inBetweenSteps=true`, то есть подключение не завершено.
4. Ни один живой процесс сейчас не публикует через этот Postiz. YourHelp autopost осознанно ушёл мимо него. Решение server-root от 2026-11-04 для WWG тоже **отвергло Postiz** в пользу `server-root/scripts/autopost/`. Это прямо противоречит новому запросу Pavel'я "всё через Postiz" (см. §8).
5. Регулярного бэкапа Postiz нет. Есть один ручной снимок `/root/backups/postiz-croscor-20261025` перед апгрейдом.
6. Перед HTML-страницами Postiz стоит самописный root-сервис `postiz-fanout.service` (`/opt/postiz/fanout_server.py`, порт 8912). Он внедряет оверлей массового добавления FB-страниц. Это первый существующий пример "расширяем Postiz снаружи, не форкая".

## 2. Контейнеры и compose

Compose: `/opt/postiz/docker-compose.yml` (метка `com.docker.compose.project.config_files`, проект `postiz`, compose 5.1.2). В каталоге лежат `docker-compose.yml.bak-pre-li-igsa`, `dynamicconfig/`, `fanout_server.py` (+4 `.bak`), `fb_fanout.py` (+2 `.bak`).

| Сервис | Образ | Restart | Порты | Тома | RAM сейчас |
|---|---|---|---|---|---|
| postiz | `ghcr.io/gitroomhq/postiz-app:v2.25.3` (compose:3) | always (:5) | `127.0.0.1:4007->5000` (:33) | `postiz_postiz-config:/config` (0 B), `postiz_postiz-uploads:/uploads` (54 kB) | 271 MiB |
| postiz-postgres | `postgres:17-alpine` (:44), PG 17.11 | always | только сеть | `postiz_postgres-volume` (70 MB, БД 13 MB) | 16 MiB |
| postiz-redis | `redis:7.2` (:62) | always | только сеть | `postiz_postiz-redis-data` (89 B) | 2.5 MiB |
| temporal | `temporalio/auto-setup:1.28.1` (:110) | always | expose 7233 | `./dynamicconfig` | 159 MiB |
| temporal-postgresql | `postgres:16` (:96) | always | expose 5432 | `postiz_temporal-pg-data` (77 MB) | 66 MiB |
| temporal-elasticsearch | `elasticsearch:7.17.27` (:77), heap 256m | always | expose 9200 | `postiz_temporal-es-data` (39 MB) | 292 MiB |

Итого стек занимает около 0.8 ГБ RAM при нулевой нагрузке. Healthcheck есть у postgres и redis, у самого `postiz` его нет (`State.Health` = nil).

Имена env у контейнера `postiz` (значения не читались): `API_LIMIT BACKEND_INTERNAL_URL DATABASE_URL DISABLE_REGISTRATION FACEBOOK_APP_ID FACEBOOK_APP_SECRET FRONTEND_URL INSTAGRAM_APP_ID INSTAGRAM_APP_SECRET IS_GENERAL JWT_SECRET MAIN_URL NEXT_PUBLIC_BACKEND_URL NEXT_PUBLIC_UPLOAD_DIRECTORY NEXT_PUBLIC_VERSION NODE_VERSION NX_ADD_PLUGINS PATH REDIS_URL RUN_CRON STORAGE_PROVIDER TEMPORAL_ADDRESS UPLOAD_DIRECTORY YARN_VERSION YOUTUBE_CLIENT_ID YOUTUBE_CLIENT_SECRET`.

Несекретные настройки из compose: `IS_GENERAL=true` (:15), `RUN_CRON=true` (:16), `DISABLE_REGISTRATION=true` (:17), `STORAGE_PROVIDER=local` (:18), `API_LIMIT=30` (:27), `TEMPORAL_ADDRESS=temporal:7233` (:14). Публичный адрес `MAIN_URL`/`FRONTEND_URL`/`NEXT_PUBLIC_BACKEND_URL` = `https://postiz.croscor.com`, внутренний backend `http://localhost:3000`.

Провайдеры, для которых заданы ключи: только Facebook, Instagram (через Facebook-app) и YouTube. **Нет** ключей LinkedIn, TikTok, X, Google Business Profile, Telegram-бота. Значит для WWG (Google Business) и для Telegram-канала нужно добавлять env и пересоздавать контейнер. По vault (`/secure/inventory/croscor-postiz.md`) FB/IG здесь = Meta-app Pavel'я "Marketing"; чужие креды Сереги сюда подключали 21.07 и откатили по слову Pavel'я.

Замечания по безопасности compose (без значений):
- `temporal` получает пароль своей БД открытым текстом прямо в compose (:119), и он дефолтный. Сеть внутренняя, наружу порт не проброшен, но при выносе стека на другой хост это надо править.
- Все секреты Postiz лежат в самом `docker-compose.yml` (0644 root), отдельного `.env` нет. На cc-mailer сделано лучше: `/opt/postiz/.env` chmod 600 (vault `carolina-connect-postiz.md`).

## 3. Домен и прокси

- Caddy общий, контейнер `alivespaceorg-caddy-1`. Хостовый `caddy.service` = inactive, файлы в `/etc/caddy/` только архивные.
- vhost: `/home/claude/caddy-sites/croscor-infra.caddy:34-43`. `/_next/* /api/* /uploads/* /favicon*` идут напрямую на `localhost:4007`, всё остальное (HTML) идёт на `localhost:8912`, это fanout-прокси. Стоит `import cc_bot_block`.
- Резерв: `croscor-infra.caddy.bak-pre-postiz-unmaint-20261025` (это версия с 503-заглушкой на время апгрейда).
- `curl` на `127.0.0.1:4007/` и на `https://postiz.croscor.com/` даёт 307 (редирект на логин), сервис жив.
- Vault-заметка устарела: она указывает vhost в `/home/claude/projects/alivespace.org/Caddyfile`, фактически он в `caddy-sites/croscor-infra.caddy`.

### fanout-оверлей
- `/etc/systemd/system/postiz-fanout.service`: `ExecStart=/usr/bin/python3 /opt/postiz/fanout_server.py 4007 --proxy`, `User=root`, `Restart=always`. Слушает `127.0.0.1:8912`, работает 11+ дней.
- Назначение по vault: внедряет `inject.js` в нативный попап "Add Channel → Facebook", даёт галочки и кнопку "добавить выбранные" для массового подключения страниц, авторизация через cookie сессии Postiz. CLI-двойник `fb_fanout.py`.
- Код я не читал: файлы `0700 root`. Содержимое не проверено.
- Вывод для архитектуры. Мы уже расширяем Postiz без форка, через reverse-proxy, который внедряет JS. Тот же приём годится для админки фабрики "внутри Postiz" (вкладка или iframe), но он хрупкий. Ошибки `Failed to find Server Action` в логах (24 шт. за 10 дней) показывают, что Next.js-фронт чувствителен к версиям. Источник этих ошибок я не подтвердил, это могут быть сканеры.

## 4. База данных Postiz (только SELECT)

Схема Prisma, 43 основные таблицы плюс около 40 `mastra_*` (встроенный AI-агент Postiz, все пусты). Размер БД 13 MB.

**Organization** (1 строка):
| id | name | apiKey | created | trial |
|---|---|---|---|---|
| b19b9fb2-4f4b-46db-b59f-9afe4b91a3a9 | Your Help UA | задан (ротирован 25.10 по vault) | 2026-07-17 | allowTrial=t, isTrailing=t |

**User** (1): LOCAL, домен почты gmail.com, `isSuperAdmin=f` на уровне User, роль `SUPERADMIN` в `UserOrganization`, активирован, `lastOnline` 2026-07-17. Имя пустое. Вход в UI с 17.07 не отмечался. Поле `lastOnline` может обновляться не при каждом входе, это не проверено.

**Integration** (3, все `social`, `disabled=f`, `refreshNeeded=f`, не удалены, `customerId` пуст):
| provider | name | inBetweenSteps | tokenExpiration | created |
|---|---|---|---|---|
| facebook | Pavlo Popravkin | **t** | 2026-09-15 | 2026-07-18 |
| facebook | Our Kids Ua | f | 2026-09-14 | 2026-07-17 |
| instagram | Our Kids UA | f | 2026-09-14 | 2026-07-17 |

Здесь нет ни одного канала YourCamp, YourHelp-страниц, WWG, Telegram или Google Business. Есть только страница Our Kids UA. Срок токенов истёк 50 дней назад. Postiz при этом не выставил `refreshNeeded`, потому что флаг ставится только на ошибке публикации, а публикаций не было. Жив ли page-токен, не проверено: page-токены, полученные из long-lived user token, у Meta часто бессрочные, и поле Postiz может это не отражать. Проверка возможна только реальным вызовом Graph API, я его не делал.

**Post**: 0 строк всего, значит 0 за 90 дней по любому `state`. `Errors` 0, `Media` 0.

Для сравнения, второй инстанс `smm.dispatchandservices.com` на cc-mailer (клиент Carolina Connect, не в scope, по vault) держит 85 integrations. Там Postiz реально используется. Здесь он только стоит.

## 5. Кто пользуется

Поиск по `~/www/{server-root,yourhelp,content-factory,croscor,carolinaconnect}` в коде (py/js/ts/sh/json/yaml) по `POSTIZ_CROSCOR_API_KEY|postiz.croscor.com/api|api/public/v1`:
- `content-factory/src/content_factory/publishers/postiz.py` и тесты `tests/test_postiz.py`, `test_scheduler.py`, `test_review_round2.py`. Это единственный клиентский код. Боевых вызовов нет: в логах 0 запросов `public/v1`.
- `server-root/.env` содержит имена `POSTIZ_CROSCOR_API_KEY` (:866), `YT_YOURHELP_POSTIZ_CLIENT_ID/SECRET` (:581-582). Это хранение, не потребитель.
- `server-root/registry/generated/vault.json` только каталожит ключ.
- **YourHelp autopost (`~/www/yourhelp/autopost/`) Postiz не вызывает**: в его коде нет ни одного упоминания. Причина записана в `yourhelp/DECISIONS.md:431-433` (2026-08-12): "Postiz на `postiz.croscor.com` - планировщик стоит с 17.07 и до сих пор ждёт трёх кликов Pavel в Meta и Google Console".
- Новый движок клиентов `server-root/scripts/autopost/` (engine.py, meta.py, gbp.py, tenant `wwg`) ходит в Graph API и GBP напрямую, мимо Postiz (`server-root/scripts/autopost/README.md`).
- `server-root/scripts/tg-purge/_send-serega-postiz.mjs` разово отправил Сереге сообщение про продукты Meta-app. Это про инстанс cc-mailer.

Вывод: живых потребителей у S2-Postiz нет. Его API-ключ и OAuth-каналы готовы, но не используются.

## 6. Бэкапы

- Регулярного бэкапа нет. В crontab root, crontab claude, `/etc/cron.d/*` и systemd timers нет ничего про postiz, pg_dump его БД или его тома. Общий `db-backup` Postiz не покрывает.
- Единственный снимок: `/root/backups/postiz-croscor-20261025/` (0700 root): `postiz.dump` 173 KB (pg_dump), `postgres-volume.tgz` 9.2 MB, `temporal-pg-data.tgz` 14.3 MB, `postiz-uploads.tgz`, `postiz-config.tgz`, `postiz-redis-data.tgz`, `docker-compose.yml.pre-2.25.3`. По vault и `server-root/DEBT.md:537` восстановление проверено на копии.
- `/run/postiz-recovery` (0700 root, пусто, создан 09.09) и `/run/lock/postiz-recovery.lock` остались от инцидента восстановления пароля 09.09 (`server-root/DECISIONS.md:1663`, `DEBT.md:518`).
- Пока постов ноль, потеря данных = потеря трёх OAuth-подключений и API-ключа. Как только Postiz станет системой записи для клиентов, ежедневный pg_dump плюс том uploads (на S3, где уже лежат архивы S2) становится обязательным.

## 7. История в server-root

- `DEBT.md:535-537`: P0 "Postiz v2.21.10 уязвим" (открыт 09.09) **закрыт 25.10**. Обе установки (S2 и cc-mailer) закреплены на `v2.25.3`; перед апгрейдом сделаны pg_dump и архив томов, восстановление проверено. Prisma требовала `--accept-data-loss` из-за нового unique на пустой `mastra_experiment_results`, это применили разово. Maintenance снят, API-ключи организаций ротированы, `JWT_SECRET` не менялся.
- `DEBT.md:538-540` содержит устаревший хвост ("App всё ещё на v2.21.10... maintenance остаётся ON") внутри закрытого пункта. Это противоречит факту (живой образ v2.25.3), строку стоит вычистить. `DEBT.md:3` отмечает, что реестр продолжает показывать этот P0 из старых `-wt-*` копий.
- `DECISIONS.md:1663-1665` (09.09): пароль admin Postiz закрыт, PG17 восстановлен из physical+logical backup.
- `DECISIONS.md:1171`: 02.10 Hetzner закрыл IPv4 cc-mailer, вместе с ним лёг второй Postiz.
- `.planning/security-swarm-20261103/host-network.md:10`: Postiz публичен со своим логином, `DISABLE_REGISTRATION=true`, v2.25.3.
- **`DECISIONS.md:18-22` (2026-11-04)**: посты клиентов в FB/IG/Google ведёт `scripts/autopost`, WWG первым, одобрение владельца в @croscor_bot. **Postiz отвергнут**: "больше 20 advisories с 03.2026, около 10 critical, токены всех клиентов в одной веб-системе".
- `content-factory/DECISIONS.md:20-23` (2026-10-25): противоположное решение. Postiz = исполнитель за адаптером `Publisher`, план и одобрение держит фабрика.
- `NEXT.md:368` (06.10): Postiz упомянут в списке кандидатов на освобождение памяти S2.

Upstream на 2026-11-05 (GitHub API): последние релизы `v2.25.3` (24.10), `v2.25.2` (23.10), `v2.25.1` (11.10), `v2.25.0` (02.10). Advisories от 02.11.2026: GHSA-fw23-6gv6-pr5p (critical, поддельные подписанные токены, захват орг; patched 2.25.3), GHSA-q6r4-5ph8-gr45 (critical, path traversal в медиа; 2.25.3), GHSA-jwv2-hpxf-9gwr (critical, чтение файлов через вызов методов провайдера; 2.25.2), GHSA-jhfm-m4vp-jcpc (medium, токены каналов и API-ключ в ответах API; 2.25.1). Наш образ закрывает все четыре. Темп остаётся высоким: 4 advisory за один день. Для коммерческого multi-tenant это главный риск, и его уже назвало решение 04.11.

## 8. Что это значит для "одной большой системы через Postiz"

1. **Конфликт решений.** Три документа тянут в разные стороны: `content-factory/DECISIONS.md` 25.10 (Postiz-исполнитель), `server-root/DECISIONS.md` 04.11 (Postiz отвергнут, свой `scripts/autopost`) и новый запрос Pavel'я 05.11 (Postiz как ядро, плюс TG-бот и админка внутри). Новое направление надо записать решением, которое явно отменяет 04.11, иначе агенты продолжат строить `scripts/autopost`.
2. **Postiz чистый, переносить нечего.** Ноль постов означает, что схему организаций и каналов можно спроектировать с нуля под тенанты (служение, фонды, коммерция) без миграции. Рекомендация к проверке: одна Organization на тенанта (Postiz изолирует каналы и API-ключ по организации), а фабрика хранит соответствие `tenant -> orgId + apiKey`.
3. **Каналы надо подключать заново.** Для YourCamp, YourHelp и WWG в Postiz нет ни одного канала, а существующие три с просроченным `tokenExpiration`. Нужны OAuth-клики Pavel'я или Жени. Это ровно тот блокер, из-за которого YourHelp в августе ушёл мимо Postiz.
4. **Google Business Profile и Telegram здесь не настроены** (нет env). Для WWG и для TG-каналов понадобится правка compose и пересоздание контейнера. Это прод-действие, только с апрувом.
5. **TG-бот "как у YourHelp" в самом Postiz** ядром не поддерживается. Postiz публикует в Telegram-каналы, а диалогового бота для приёма материалов у него нет. Таблицы `mastra_*` (встроенный агент) пусты, их возможности не проверены, это отдельный вопрос для исследования. Реалистичный путь: бот и админка = сервис фабрики, встроенный в домен Postiz через тот же приём, что fanout (Caddy-маршрут плюс внедрённый JS или iframe), а публикация идёт через публичный API Postiz.
6. **Эксплуатационный минимум до первого клиента**: ежедневный бэкап (pg_dump + uploads); healthcheck у `postiz`; секреты из compose в `.env` 600; пароль temporal не дефолтный; `API_LIMIT=30` надо сверить с планом публикаций (по docs это лимит запросов публичного API в час на организацию; по коду не проверено); шабат-стоп снаружи Postiz, потому что у самого Postiz шабат-окна нет и `RUN_CRON=true` опубликует запланированное в субботу (это надо проверить в research/postiz-backend.md или коде).

## Открытые вопросы

1. Отменяет ли новый запрос решение `server-root/DECISIONS.md` 2026-11-04 (свой `scripts/autopost` для WWG)? Его тенант `wwg` и крон `*/10` уже существуют.
2. Один Postiz на всё (служение, фонды, коммерция) или отдельный инстанс для коммерции? Учитываем риск "токены всех клиентов в одной веб-системе" и темп critical-advisory.
3. Чей Meta-app и Google-клиент использовать для WWG: Pavel'я "Marketing" или отдельный? Нужны ли App Review и Advanced Access для чужой бизнес-страницы?
4. Живы ли page-токены Our Kids UA при истёкшем `tokenExpiration`? Проверить можно только вызовом Graph API.
5. Что делает `fanout_server.py` сверх массового добавления FB-страниц? Код root-only, я его не читал.
6. Можно ли построить диалоговый бот и одобрение на встроенном агенте Postiz (`mastra_*`, MCP)? Это не исследовано.
