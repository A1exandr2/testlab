.DEFAULT_GOAL := up
PROJECT ?= testlab
RUNTIME ?= cpython
PORT ?= 8765
MEMORY_LIMIT ?= 512m
CPU_LIMIT ?= 1.0
# На Linux сборка видит локальный HTTP-прокси так же, как обычный pip.
BUILD_NETWORK ?= $(if $(filter Linux,$(shell uname -s)),host,default)
export PROJECT RUNTIME PORT MEMORY_LIMIT CPU_LIMIT BUILD_NETWORK SQL FILE
DC = docker compose -f compose.yaml

.PHONY: up start run stop down restart build graal status ps health logs follow stats size docker-size db tables query backup import-db shell test test-py test-js compare help
up start run:
	$(DC) up -d --build --wait app
	@echo "ТестЛаб: http://127.0.0.1:$(PORT) ($(RUNTIME))"
stop:
	$(DC) stop app
down:
	$(DC) down --remove-orphans
restart:
	$(DC) up -d --build --wait --force-recreate app
build:
	$(DC) build app
graal:
	$(MAKE) RUNTIME=graalpy up
status ps:
	$(DC) ps -a
	@echo "Адрес: http://127.0.0.1:$(PORT); выбранная среда: $(RUNTIME)"
health:
	@id=$$($(DC) ps -q app); test -n "$$id" || { echo 'Проект остановлен'; exit 1; }; \
	docker inspect --format '{{.State.Status}} / {{.State.Health.Status}}' "$$id"; \
	test "$$(docker inspect --format '{{.State.Health.Status}}' "$$id")" = healthy
logs:
	$(DC) logs --tail=100 app
follow:
	$(DC) logs -f --tail=100 app
stats:
	@id=$$($(DC) ps -q app); test -n "$$id" || { echo 'Проект остановлен'; exit 1; }; docker stats --no-stream "$$id"
size:
	docker image ls --filter 'reference=$(PROJECT):*'
	$(DC) ps -a
	$(DC) run --rm --no-deps -T app python ops/manage.py disk
docker-size:
	docker system df
db tables:
	$(DC) run --rm --no-deps -T app python ops/manage.py $@
query:
	$(DC) run --rm --no-deps -T -e SQL app python ops/manage.py query
backup:
	@mkdir -p backups; partial=$$(mktemp backups/.backup-XXXXXX); \
	trap 'rm -f "$$partial"' EXIT INT TERM; \
	$(DC) run --rm --no-deps -T app python ops/manage.py backup > "$$partial" && \
	{ file="backups/$(PROJECT)-$$(date +%Y%m%d-%H%M%S)-$$(basename "$$partial").sqlite3"; mv "$$partial" "$$file"; echo "Копия: $$file"; }
import-db:
	@test -n "$$FILE" && test -f "$$FILE" || { echo 'Укажите существующий файл: make import-db FILE=путь.sqlite3'; exit 1; }
	@test -z "$$($(DC) ps -q app)" || { echo 'Сначала выполните make stop'; exit 1; }
	$(DC) run --rm --no-deps -T app python ops/manage.py import < "$$FILE"
shell:
	$(DC) exec app sh
test: test-py test-js
test-py:
	$(DC) build tests
	$(DC) run --rm --no-deps -T tests
test-js:
	$(DC) build tests-js
	$(DC) run --rm --no-deps -T tests-js
compare:
	$(MAKE) RUNTIME=cpython build
	$(MAKE) RUNTIME=graalpy build
	docker image ls --filter 'reference=$(PROJECT):cpython' --filter 'reference=$(PROJECT):graalpy'
help:
	@printf '%s\n' \
	'make / make up   сборка и запуск, ожидание готовности' \
	'make stop        остановка с сохранением базы' \
	'make down        удаление контейнеров, база сохраняется' \
	'make restart     пересборка и перезапуск' \
	'make graal       запуск на GraalPy (GraalVM)' \
	'make status      контейнер, состояние, адрес' \
	'make health      проверка HTTP и доступа к базе' \
	'make logs/follow последние логи / наблюдение за логами' \
	'make stats       CPU, память, сеть, ввод-вывод' \
	'make size        размер образа и файлов базы' \
	'make docker-size место всех образов и кэша Docker' \
	'make db/tables   количество строк / структура таблиц' \
	'make query SQL="SELECT id,name FROM users"  чтение данных' \
	'make backup      согласованная копия SQLite в backups/' \
	'make import-db FILE=путь.sqlite3  импорт в пустой том' \
	'make test        Python- и JavaScript-тесты в Docker' \
	'make compare     сборка и сравнение размеров двух сред' \
	'make shell       оболочка работающего контейнера' \
	'Параметры: PORT=18765 RUNTIME=graalpy PROJECT=testlab MEMORY_LIMIT=512m'
