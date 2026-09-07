# Helper commands for the Ansible dev environment (Linux / macOS / WSL)
SHELL := /bin/bash
PY := .venv/bin
ANSIBLE := $(PY)/ansible
ANSIBLE_GALAXY := $(PY)/ansible-galaxy
ANSIBLE_LINT := $(PY)/ansible-lint

.PHONY: help setup lint test check ping run clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

setup: ## Install venv + dependencies + collections
	python3 -m venv .venv
	$(PY)/pip install --upgrade pip
	$(PY)/pip install -r requirements.txt
	$(ANSIBLE_GALAXY) collection install -r requirements.yml -p collections

lint: ## Run ansible-lint
	$(ANSIBLE_LINT)

check: ## Syntax check
	$(ANSIBLE) playbook --syntax-check playbooks/site.yml

ping: ## Ping dev hosts
	$(ANSIBLE) platypus -i inventory/dev -m ping

run: ## Run site.yml against the dev environment
	$(ANSIBLE) playbook playbooks/site.yml -i inventory/dev

test: ## Run role tests with Molecule
	cd roles/common && ../../$(PY)/molecule test

clean: ## Remove Molecule artifacts and cache
	rm -rf .cache .molecule roles/common/.molecule
