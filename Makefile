# SeatLock developer and operator shortcuts. Run `make help` for the list.
SHELL := /bin/bash
TEST_DB := postgresql+psycopg://seatlock_test:test_only@localhost:55433/seatlock_test
TRIVY := aquasec/trivy:0.75.0
VENV := backend/.venv

.DEFAULT_GOAL := help
.PHONY: help up down logs monitoring test lint format e2e scan k8s-local tf-plan eks-up eks-down

help: ## Show this help
	@grep -hE '^[a-z0-9-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

up: ## Build and start the full stack on http://localhost:3000
	python3 scripts/configure.py
	docker compose up -d --build --wait

down: ## Stop the stack (keeps the database volume)
	docker compose down

logs: ## Tail backend logs
	docker compose logs -f backend

monitoring: ## Add Prometheus (:9090) and Grafana (:3002) to the local stack
	docker compose -f docker-compose.yml -f docker-compose.monitoring.yml up -d --wait

$(VENV):
	python3.11 -m venv $(VENV)
	$(VENV)/bin/pip install -q -r backend/requirements-dev.txt

test: $(VENV) ## Run pytest against a disposable PostgreSQL
	docker compose --profile test up -d --wait postgres-test
	cd backend && TEST_DATABASE_URL=$(TEST_DB) .venv/bin/pytest -v --cov=app

lint: $(VENV) ## Ruff, Bandit, Prettier, Terraform fmt, Helm lint
	cd backend && .venv/bin/ruff check app tests && .venv/bin/ruff format --check app tests alembic && .venv/bin/bandit -qr app -ll
	cd frontend && npm run format:check
	terraform -chdir=terraform fmt -check -recursive
	helm lint helm/seatlock

format: $(VENV) ## Auto-format Python and TypeScript
	cd backend && .venv/bin/ruff format app tests alembic
	cd frontend && npm run format

e2e: ## Playwright browser tests against the running stack
	cd frontend && npm ci && npm run test:e2e

scan: ## Trivy: image vulnerabilities and IaC misconfigurations
	# --no-cache: a cached `apk upgrade` layer would hide newly fixed CVEs
	docker compose build --no-cache backend frontend
	for c in backend frontend; do \
	  docker run --rm -v /var/run/docker.sock:/var/run/docker.sock $(TRIVY) image --severity HIGH,CRITICAL --exit-code 1 seatlock-$$c:local || exit 1; \
	done
	docker run --rm -v "$$PWD:/src:ro" $(TRIVY) config --severity HIGH,CRITICAL --exit-code 1 \
	  --ignorefile /src/.trivyignore --skip-dirs /src/terraform/.terraform --skip-dirs /src/frontend/node_modules /src

k8s-local: ## Deploy to minikube with the locally built images
	docker compose build
	minikube image load seatlock-backend:local --overwrite=true
	minikube image load seatlock-frontend:local --overwrite=true
	kubectl --context=minikube apply -f k8s/namespace.yaml
	python3 scripts/kube-secret.py
	helm upgrade --install seatlock helm/seatlock --kube-context minikube -n seatlock --wait --wait-for-jobs --timeout 5m
	kubectl --context=minikube -n seatlock get pods,svc,hpa

tf-plan: ## terraform init + plan (needs terraform/terraform.tfvars)
	terraform -chdir=terraform init -input=false
	terraform -chdir=terraform plan -out=tfplan

eks-up: ## terraform apply the saved plan, then bootstrap the cluster platform
	terraform -chdir=terraform apply tfplan
	bash scripts/eks-bootstrap.sh

eks-down: ## Remove load balancer and volumes, then terraform destroy
	bash scripts/eks-teardown.sh
