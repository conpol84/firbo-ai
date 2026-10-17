.PHONY: bootstrap orchestrator openjarvis omniroute

bootstrap:
	bash scripts/bootstrap.sh

orchestrator:
	python -m uvicorn services.orchestrator.app:app --host 127.0.0.1 --port 8787

openjarvis:
	cd packages/openjarvis && uv sync

omniroute:
	cd packages/omniroute && npm install && npm run dev
