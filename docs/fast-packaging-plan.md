# Быстрая упаковка и обновление watchdog

Одобрено пользователем: быстрый IPK и install.sh; проверка/установка обновлений в этом проекте, панель и Web Push — параллельным агентом в Xkeen-UI PWA. Работа локально, без commit/push/deploy новых изменений и без worktree. Релиз v1.0.10 остаётся на ранее слитом коммите; следующая реализация готовится как 1.0.11.

## 1. Быстрый пакет и feed

- [x] Написать тесты упаковки без toolchain, payload/permissions/hooks/config ownership, feed/checksum/manifest.
- [x] scripts/build_package.py: Python stdlib, читать текущий Makefile как источник имени/версии/зависимостей/install mapping/hooks. Только PKGARCH all и скриптовый пакет без компиляции. Сохранить обычный payload seed JSON 0600, defaults.json и preinst/postinst/prerm без conffiles-регистрации. Сформировать совместимый с Entware gzip-tar IPK и feed.
- [x] Workflow строит пакет/индекс напрямую без Docker/toolchain; reuse готовой main-сборки по SHA для тега сохраняется. Републикация существующего пакета поддерживается.
- [x] feed/update.json: schema_version=1, latest_version=X.Y.Z-N, package_url (фиксированный Pages feed /all/), sha256, size, release_url (GitHub tag vX.Y.Z), release_notes строка. Manifest появляется только при публикации feed.

## 2. Установка и CLI обновлений

- [x] install.sh проверяет Entware, идемпотентно подключает фиксированный feed, вызывает штатный opkg для установки/обновления и зависимостей. Не заменяет package ownership и механизмы сохранения конфигурации.
- [x] Отдельный stdlib-модуль update_service.py. --check-update: installed_version (строка/null), latest_version, update_available, release_url, checked_at UTC, release_notes. Версии в формате X.Y.Z-N. Работает без config/controller.
- [x] --install-update --expected-version X.Y.Z-N: сверить актуальный manifest, не допустить downgrade/stale version, скачать только пакет фиксированного feed, проверить hash/size/control metadata, вызвать opkg и подтвердить установленную версию. JSON: installed_version, updated.
- [x] Отдельный update-lock: общий watchdog-lock нельзя держать через opkg postinst, который вызывает --sync-cron. Ошибки JSON, без секретов. Тайм-аут операции ограничен; отмена не обещает rollback.

## 3. Проверка и интеграция

- [x] Unit/integration fixtures с подставным opkg и HTTP, shell-проверки installer, быстрая реальная локальная упаковка и время выполнения, полная suite и review.
- [x] Согласовать контракт с Xkeen-UI агентом; UI/Web Push код остаётся только в другом репозитории.
- [x] Обновить README/project-map/graphify. Реальную установку на роутере и новую публикацию выполнять только отдельно по разрешению.

## Результат локальной проверки

Все 138 тестов прошли. Реальная упаковка IPK+feed после финальных исправлений заняла 0,0459с; пакет 18 246 байт прошёл hash/size/control-проверку updater-модулем. Это время локальной упаковки, а не всего GitHub CI. Python/shell/YAML и действующие CI-проверки пройдены. Замечание review про HTTPS downloader исправлено: wget-ssl в Depends и Entware-first PATH для обоих вызовов opkg. Граф обновлён.

В Xkeen-UI PWA реализованы интерфейс обновлений и opt-in Web Push; агент сообщил 203 portable backend tests passed (2 ignored, 2 Linux-only filtered), 3 SW tests passed, production frontend build и мобильный browser smoke прошли. Исправление блокировки отписки при недоступном push-провайдере подтверждено регрессионным тестом и scoped review. Реальная доставка на телефон, MIPS cross-build и установка на роутере не проверялись. Новые изменения обоих проектов не коммитились и не публиковались.

Отдельный ранее согласованный релиз v1.0.10 опубликован на коммите 78cd1bc; tag workflow успешно использовал готовые артефакты, build был skipped, release и Pages завершились успешно. Новые изменения 1.0.11 в этот тег не входят.

## Подготовка публикации

27 октября 2026 пользователь разрешил commit, push feature-веток и создание PR в обоих проектах. Последний успешный прогон watchdog: 138 тестов; повтор перед коммитом не выполнялся после отказа в разрешении. Исходники после успешного прогона не менялись. Текущий diff проверен; локальные IPK/cache не включаются.
