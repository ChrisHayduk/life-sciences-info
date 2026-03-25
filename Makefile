.PHONY: backend-test web-lint bootstrap-local

backend-test:
	cd backend && pytest

web-lint:
	cd web && npm run lint

bootstrap-local:
	cd backend && python -m app.bootstrap
