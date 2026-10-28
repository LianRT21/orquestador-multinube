.PHONY: help setup up down lint test test-unit test-integration smoke design run-all run metrics analyze excel dashboards

PYTHON ?= python

help:
	@echo "Comandos disponibles:"
	@echo "  make setup            - Configura entorno virtual, dependencias y pre-commit"
	@echo "  make up               - Levanta el entorno Docker y espera a que este sano"
	@echo "  make down             - Destruye contenedores y volumenes de Docker"
	@echo "  make lint             - Ejecuta ruff linter y mypy strict"
	@echo "  make test             - Ejecuta pruebas unitarias con reporte de cobertura"
	@echo "  make test-integration - Ejecuta pruebas de integracion con Docker"
	@echo "  make smoke            - Ejecuta la corrida de humo (8 corridas cortas)"
	@echo "  make design           - Genera data/design.csv (240 corridas aleatorizadas)"
	@echo "  make run-all          - Ejecuta el experimento completo reanudable (--resume)"
	@echo "  make run ID=<id>      - Ejecuta una corrida especifica"
	@echo "  make metrics          - Calcula data/processed/runs.csv desde datos crudos"
	@echo "  make analyze          - Ejecuta modelos estadisticos, figuras e informe"
	@echo "  make excel            - Exporta el libro Excel con validacion cruzada"
	@echo "  make dashboards       - Muestra URL y abre Grafana localmente"

setup:
	$(PYTHON) manage.py setup

up:
	$(PYTHON) manage.py up

down:
	$(PYTHON) manage.py down

lint:
	$(PYTHON) manage.py lint

test:
	$(PYTHON) manage.py test

test-unit:
	$(PYTHON) manage.py test-unit

test-integration:
	$(PYTHON) manage.py test-integration

smoke:
	$(PYTHON) manage.py smoke

design:
	$(PYTHON) manage.py design

run-all:
	$(PYTHON) manage.py run-all

run:
	$(PYTHON) manage.py run $(ID)

metrics:
	$(PYTHON) manage.py metrics

analyze:
	$(PYTHON) manage.py analyze

excel:
	$(PYTHON) manage.py excel

dashboards:
	$(PYTHON) manage.py dashboards
