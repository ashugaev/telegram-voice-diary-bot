APP_DIR=/home/alek/projects/diary-bot
PYTHON ?= .venv/bin/python
SERVICE=diary-bot.service

.PHONY: deploy dev stop-dev logs test

deploy:
	git push
	$(APP_DIR)/scripts/bot-update.sh

dev:
	systemctl --user stop $(SERVICE)
	$(PYTHON) bot.py

stop-dev:
	systemctl --user start $(SERVICE)

logs:
	journalctl --user -u $(SERVICE) -f

test:
	$(PYTHON) -m py_compile bot.py config.py services/*.py tests/*.py
	$(PYTHON) -m unittest discover -s tests -v
