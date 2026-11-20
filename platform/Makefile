# One-command operations. `make setup && make up` gives a running two-tier platform.
PY ?= python3
.PHONY: console-check setup up down status doctor test drill tls-check board backup tenant
setup:          ## install deps, generate .env secrets, run preflight
	$(PY) -m pip install -r requirements.txt
	$(PY) tools/ctl.py init
	$(PY) tools/ctl.py doctor
up:             ## SaaS :8000 + one collector per tenant (:8001..), logs in data/
	$(PY) tools/ctl.py up
down:
	$(PY) tools/ctl.py down
status:
	$(PY) tools/ctl.py status
doctor:
	$(PY) tools/ctl.py doctor
test:
	$(PY) -m pytest -q
drill:          ## full scripted drill against a throw-away stack
	$(PY) tools/demo.py drill
console-check:  ## headless browser check of the Console; needs a running stack: make up
	$(PY) tools/consolecheck.py --user $(USER_NAME) --password $(USER_PASS)
tls-check:
	$(PY) tools/demo.py tlscheck
board:          ## headless browser check of all 9 proofs (needs playwright)
	$(PY) tools/demo.py boardcheck
backup:
	$(PY) tools/ctl.py backup
tenant:         ## make tenant NAME=gamma REGION=us TENANT_TZ=America/New_York
	$(PY) tools/ctl.py onboard $(NAME) --region $(REGION) --tz $(or $(TENANT_TZ),UTC)
