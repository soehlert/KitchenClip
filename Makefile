.DEFAULT_GOAL := help

# This automatically builds the help target based on commands prepended with a double hashbang
## help: print this help output
.PHONY: help
help: Makefile
	@sed -n 's/^##//p' $<

## build: Build the docker containers
.PHONY: build
build:
	docker compose build

## run: Run the docker containers in detached mode
.PHONY: run
run:
	docker compose up -d

## stop: Stop the docker containers
.PHONY: stop
stop:
	docker compose stop

## down: Down the docker containers (removes networks/volumes)
.PHONY: down
down:
	docker compose down

## restart: Restart the docker containers
.PHONY: restart
restart:
	docker compose restart

## test: Run all tests in the test container environment
.PHONY: test
test:
	docker compose -f docker-compose.test.yml run --rm test

## parser-tests: Run only the recipe parser tests
.PHONY: parser-tests
parser-tests:
	docker compose -f docker-compose.test.yml run --rm test pytest recipes/parsers/tests

## view-tests: Run only the Django view tests
.PHONY: view-tests
view-tests:
	docker compose -f docker-compose.test.yml run --rm test pytest recipes/tests/test_views.py

## e2e-tests: Run only the Playwright end-to-end tests
.PHONY: e2e-tests
e2e-tests:
	docker compose -f docker-compose.test.yml run --rm test pytest tests/e2e

## open: Open the web application in the browser
.PHONY: open
open:
	open http://localhost:8888
