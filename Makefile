.PHONY: bootstrap up down doctor orchestrator openjarvis omniroute

bootstrap:
	bash scripts/bootstrap.sh

up:
	bash scripts/dev-up.sh

down:
	bash scripts/dev-down.sh

doctor:
	bash scripts/doctor.sh

orchestrator:
	python -m uvicorn services.orchestrator.app:app --host 127.0.0.1 --port 8787

openjarvis:
	cd packages/openjarvis && uv run jarvis serve --port 8000

omniroute:
	cd packages/omniroute && node bin/omniroute.mjs serve --headless --port 20128
