# Cloud infrastructure and releases: Terraform (infra/) + AWS CLI. Design: docs/04 §10, docs/06 §2-5.
#
#   make bootstrap GITHUB_REPO=owner/repo OWNER=you   one-time: state bucket + GitHub OIDC deploy roles
#   make up ENV=staging                               package -> terraform apply -> promote code (+ SPA)
#   make deploy-code ENV=staging                      code-only release: Lambda versions/aliases + SPA
#   make rollback FN=api ENV=prod                     move a function's "live" alias back one version
#   make down ENV=staging                             destroy (prod also needs ALLOW_DATA_DESTROY=1)
#
# Remote state lives in the bootstrap bucket: export TF_STATE_BUCKET=<bootstrap output state_bucket_name>.
# Terraform variables come from infra/envs/<env>/terraform.tfvars locally and TF_VAR_* in CI.
# Recipes quote every path: the checkout may live in a directory with spaces.

INFRA          := $(ROOT)/infra
DIST           := $(ROOT)/dist
FRONTEND_DIST  := $(ROOT)/frontend/dist
AWS_REGION     ?= us-east-1
TF_STATE_BUCKET ?=
KEEP_VERSIONS  ?= 5
ALIAS          := live
FUNCTIONS      := api ingest-tick schedule-import daily-rollup maintenance notify lamp-validate

# Recursive (=) so they pick up ENV from the command line and only run git when actually used.
VERSION        ?= $(or $(GITHUB_SHA),$(shell git -C "$(ROOT)" rev-parse HEAD 2>/dev/null),dev)
TF_DIR          = $(INFRA)/envs/$(ENV)
TF              = terraform -chdir="$(TF_DIR)"
AWS             = aws --region $(AWS_REGION)
SNAPSHOT_FILE   = $(ROOT)/build/alias-snapshot-$(ENV).tsv
TF_AUTO         = $(if $(filter 1 true yes,$(AUTO_APPROVE)),-auto-approve,)
TF_PKG_VARS     = -var "app_version=$(VERSION)" \
                  -var "api_package_path=$(DIST)/api.zip" -var "jobs_package_path=$(DIST)/jobs.zip" \
                  -var "api_package_sha256=$$(cat "$(DIST)/api.zip.base64sha256")" \
                  -var "jobs_package_sha256=$$(cat "$(DIST)/jobs.zip.base64sha256")"

.PHONY: package bootstrap plan apply up down deploy-code deploy-functions deploy-site rollback rollback-site \
        publish-rollback migrate-cloud smoke outputs tf-check require-env guard-destroy tf-init ensure-package

# --- Build ---------------------------------------------------------------------------------------

package: ## Build dist/api.zip + dist/jobs.zip for Lambda (arm64, python3.13) with sizes and SHA-256
	"$(ROOT)/scripts/package_lambda.sh"

ensure-package:
	@test -f "$(DIST)/api.zip" -a -f "$(DIST)/jobs.zip" || "$(ROOT)/scripts/package_lambda.sh"

# --- Terraform -----------------------------------------------------------------------------------

require-env:
	@case "$(ENV)" in staging|prod) ;; *) echo "Set ENV=staging or ENV=prod" >&2; exit 1 ;; esac

tf-init: require-env
	@test -n "$(TF_STATE_BUCKET)" || { echo "Set TF_STATE_BUCKET (terraform -chdir=infra/bootstrap output -raw state_bucket_name)" >&2; exit 1; }
	@$(TF) init -input=false -reconfigure -backend-config="bucket=$(TF_STATE_BUCKET)" -backend-config="region=$(AWS_REGION)" >/dev/null
	@echo "==> terraform initialised for $(ENV) (state: s3://$(TF_STATE_BUCKET)/$(ENV)/terraform.tfstate)"

bootstrap: ## One-time account setup: state bucket + GitHub OIDC roles (GITHUB_REPO=owner/repo OWNER=you)
	terraform -chdir="$(INFRA)/bootstrap" init -input=false
	terraform -chdir="$(INFRA)/bootstrap" apply -input=false $(if $(GITHUB_REPO),-var "github_repo=$(GITHUB_REPO)") $(if $(OWNER),-var "owner=$(OWNER)")
	@echo; echo "Next: export TF_STATE_BUCKET=$$(terraform -chdir="$(INFRA)/bootstrap" output -raw state_bucket_name)"

plan: require-env tf-init ensure-package ## terraform plan for ENV (builds dist/ first if it is empty)
	$(TF) plan -input=false $(TF_PKG_VARS)

apply: require-env tf-init ensure-package ## terraform apply for ENV using the dist/ artifact hashes (AUTO_APPROVE=1 in CI)
	$(TF) apply -input=false $(TF_AUTO) $(TF_PKG_VARS)

up: require-env package apply deploy-functions ## Create/update ENV: package -> terraform apply -> promote Lambda aliases (+ SPA if built)
	@if [ -f "$(FRONTEND_DIST)/index.html" ]; then $(MAKE) --no-print-directory deploy-site ENV=$(ENV); \
	 else echo "frontend/dist not built: skipped SPA upload (npm run build, then make deploy-code ENV=$(ENV))"; fi
	@echo "==> $(ENV) is up: $$($(TF) output -raw public_base_url)"

guard-destroy:
	@if [ "$(ENV)" = prod ] && [ "$(ALLOW_DATA_DESTROY)" != 1 ]; then \
	  echo "Refusing to destroy prod: it holds curated data and backups. Re-run with ALLOW_DATA_DESTROY=1 if you mean it." >&2; exit 1; fi

down: require-env guard-destroy tf-init ## Destroy ENV, keeping the state bucket, deploy roles and Neon (prod: ALLOW_DATA_DESTROY=1)
	@if [ "$(ALLOW_DATA_DESTROY)" = 1 ]; then \
	  echo "==> ALLOW_DATA_DESTROY=1: enabling force_destroy on $(ENV) buckets first"; \
	  $(TF) apply -input=false $(TF_AUTO) -target='module.storage.aws_s3_bucket.this' -var force_destroy=true; \
	fi
	$(TF) destroy -input=false $(TF_AUTO) $(if $(filter 1,$(ALLOW_DATA_DESTROY)),-var force_destroy=true,)

outputs: require-env tf-init ## Show Terraform outputs for ENV
	@$(TF) output

tf-check: ## terraform fmt -check + validate for every root (offline; no AWS needed)
	terraform fmt -check -recursive "$(INFRA)"
	@for d in bootstrap envs/staging envs/prod; do \
	  terraform -chdir="$(INFRA)/$$d" init -backend=false -input=false >/dev/null && \
	  printf '%-14s ' "$$d" && terraform -chdir="$(INFRA)/$$d" validate -no-color || exit 1; done
	@diff -q "$(INFRA)/envs/staging/main.tf" "$(INFRA)/envs/prod/main.tf" && echo "envs/*/main.tf identical"

# --- Releases ------------------------------------------------------------------------------------
# Terraform publishes a Lambda version when code/config changes but never moves the "live" alias
# after creation; promotion and rollback happen here, so `terraform apply` can't undo a rollback.
# SPA caching: hashed assets/* immutable for a year; index.html and sw.js no-cache (browsers only
# pick up a new service worker if sw.js is revalidated); other root files 5 minutes. Uploads never
# delete and never touch data/ (published by the rollup), and index.html goes last so it never
# references assets that are not there yet.

deploy-code: require-env tf-init deploy-functions deploy-site ## Release code to ENV: publish versions, move aliases, upload SPA, invalidate /index.html

deploy-functions: require-env tf-init ensure-package
	@set -euo pipefail; \
	bucket=$$($(TF) output -raw artifacts_bucket_name); \
	mkdir -p "$(ROOT)/build"; : > "$(SNAPSHOT_FILE)"; \
	for pkg in api jobs; do \
	  sha=$$(cat "$(DIST)/$$pkg.zip.base64sha256"); \
	  key="lambda/$$pkg/$$(printf '%s' "$$sha" | tr '+/' '-_' | tr -d '=').zip"; \
	  if $(AWS) s3api head-object --bucket "$$bucket" --key "$$key" >/dev/null 2>&1; then \
	    echo "==> $$pkg.zip already at s3://$$bucket/$$key"; \
	  else \
	    echo "==> uploading $$pkg.zip -> s3://$$bucket/$$key"; \
	    $(AWS) s3 cp "$(DIST)/$$pkg.zip" "s3://$$bucket/$$key" --only-show-errors; \
	  fi; \
	  if [ "$$pkg" = api ]; then api_key="$$key"; else jobs_key="$$key"; fi; \
	done; \
	for fn in $(FUNCTIONS); do \
	  name="stopwatch-$(ENV)-$$fn"; \
	  if [ "$$fn" = api ]; then key="$$api_key"; else key="$$jobs_key"; fi; \
	  prev=$$($(AWS) lambda get-alias --function-name "$$name" --name $(ALIAS) --query FunctionVersion --output text); \
	  printf '%s\t%s\n' "$$name" "$$prev" >> "$(SNAPSHOT_FILE)"; \
	  $(AWS) lambda update-function-code --function-name "$$name" --s3-bucket "$$bucket" --s3-key "$$key" --query CodeSha256 --output text >/dev/null; \
	  $(AWS) lambda wait function-updated-v2 --function-name "$$name"; \
	  ver=$$($(AWS) lambda publish-version --function-name "$$name" --description "$(VERSION)" --query Version --output text); \
	  $(AWS) lambda update-alias --function-name "$$name" --name $(ALIAS) --function-version "$$ver" >/dev/null; \
	  echo "    $$name: $(ALIAS) $$prev -> $$ver"; \
	  old=$$($(AWS) lambda list-versions-by-function --function-name "$$name" --query 'Versions[?Version!=`$$LATEST`].Version' --output text \
	        | tr '\t' '\n' | sort -n | awk -v keep=$(KEEP_VERSIONS) '{v[NR]=$$0} END {for (i = 1; i <= NR - keep; i++) print v[i]}'); \
	  for v in $$old; do \
	    if [ "$$v" != "$$ver" ] && [ "$$v" != "$$prev" ]; then \
	      $(AWS) lambda delete-function --function-name "$$name" --qualifier "$$v" 2>/dev/null || echo "    (kept $$name:$$v)"; \
	    fi; \
	  done; \
	done; \
	echo "==> previous aliases saved to $(SNAPSHOT_FILE) (make rollback FN=all ENV=$(ENV) SNAPSHOT=...)"

deploy-site: require-env tf-init
	@set -euo pipefail; \
	test -f "$(FRONTEND_DIST)/index.html" || { echo "frontend/dist/index.html missing: run npm run build in frontend/" >&2; exit 1; }; \
	site=$$($(TF) output -raw site_bucket_name); \
	dist_id=$$($(TF) output -raw cloudfront_distribution_id); \
	echo "==> uploading SPA to s3://$$site (data/ untouched)"; \
	if [ -d "$(FRONTEND_DIST)/assets" ]; then \
	  $(AWS) s3 sync "$(FRONTEND_DIST)/assets" "s3://$$site/assets" --cache-control "public, max-age=31536000, immutable" --only-show-errors; \
	fi; \
	$(AWS) s3 sync "$(FRONTEND_DIST)" "s3://$$site" --exclude "assets/*" --exclude "data/*" --exclude "index.html" \
	  --exclude "sw.js" --cache-control "public, max-age=300" --only-show-errors; \
	if [ -f "$(FRONTEND_DIST)/sw.js" ]; then \
	  $(AWS) s3 cp "$(FRONTEND_DIST)/sw.js" "s3://$$site/sw.js" --cache-control "no-cache" \
	    --content-type "text/javascript; charset=utf-8" --only-show-errors; \
	fi; \
	$(AWS) s3 cp "$(FRONTEND_DIST)/index.html" "s3://$$site/index.html" --cache-control "no-cache" \
	  --content-type "text/html; charset=utf-8" --only-show-errors; \
	inv=$$($(AWS) cloudfront create-invalidation --distribution-id "$$dist_id" --paths "/index.html" "/sw.js" --query Invalidation.Id --output text); \
	echo "    CloudFront invalidation $$inv (/index.html, /sw.js)"

rollback: require-env ## Move FN's live alias back one version (FN=<function>|all; optional TO=<version> or SNAPSHOT=<file>)
	@set -euo pipefail; \
	test -n "$(FN)" || { echo "Set FN=<function> ($(FUNCTIONS)) or FN=all" >&2; exit 1; }; \
	for fn in $(if $(filter all,$(FN)),$(FUNCTIONS),$(FN)); do \
	  name="stopwatch-$(ENV)-$$fn"; \
	  cur=$$($(AWS) lambda get-alias --function-name "$$name" --name $(ALIAS) --query FunctionVersion --output text); \
	  if [ -n "$(SNAPSHOT)" ]; then \
	    target=$$(awk -F '\t' -v n="$$name" '$$1 == n {print $$2}' "$(SNAPSHOT)"); \
	  elif [ -n "$(TO)" ]; then \
	    target="$(TO)"; \
	  else \
	    target=$$($(AWS) lambda list-versions-by-function --function-name "$$name" --query 'Versions[?Version!=`$$LATEST`].Version' --output text \
	             | tr '\t' '\n' | awk -v cur="$$cur" '$$1 + 0 < cur + 0' | sort -n | tail -n 1); \
	  fi; \
	  if [ -z "$$target" ]; then echo "$$name: no earlier version to roll back to" >&2; exit 1; fi; \
	  if [ "$$target" = "$$cur" ]; then echo "$$name: already at $$cur"; continue; fi; \
	  $(AWS) lambda update-alias --function-name "$$name" --name $(ALIAS) --function-version "$$target" >/dev/null; \
	  echo "$$name: $(ALIAS) $$cur -> $$target"; \
	done

rollback-site: require-env tf-init ## Restore the previous index.html object version and invalidate it
	@set -euo pipefail; \
	site=$$($(TF) output -raw site_bucket_name); \
	dist_id=$$($(TF) output -raw cloudfront_distribution_id); \
	prev=$$($(AWS) s3api list-object-versions --bucket "$$site" --prefix index.html \
	        --query 'sort_by(Versions[?Key==`index.html`], &LastModified)[-2].VersionId' --output text); \
	if [ -z "$$prev" ] || [ "$$prev" = None ]; then echo "No previous index.html version in $$site" >&2; exit 1; fi; \
	$(AWS) s3api copy-object --bucket "$$site" --key index.html --copy-source "$$site/index.html?versionId=$$prev" \
	  --metadata-directive COPY >/dev/null; \
	$(AWS) cloudfront create-invalidation --distribution-id "$$dist_id" --paths "/index.html" >/dev/null; \
	echo "index.html restored to version $$prev"

publish-rollback: require-env tf-init ## Point data/v1/manifest.json back at BUILD=<build_id> (live within ~60 s)
	@test -n "$(BUILD)" || { echo "Set BUILD=<build_id> (see data/v1/builds/ in the site bucket)" >&2; exit 1; }
	@set -euo pipefail; \
	site=$$($(TF) output -raw site_bucket_name); \
	lake=$$($(TF) output -raw lake_bucket_name); \
	cd "$(BACKEND)" && STOPWATCH_ENV=$(ENV) SITE_URL="s3://$$site" LAKE_URL="s3://$$lake" AWS_REGION=$(AWS_REGION) \
	  uv run python -m stopwatch.rollups.publish --rollback "$(BUILD)"

migrate-cloud: require-env ## Alembic upgrade head on ENV's Neon DB (owner URL from SSM; MIGRATE_DATABASE_URL overrides)
	@set -euo pipefail; \
	url="$${MIGRATE_DATABASE_URL:-}"; \
	if [ -z "$$url" ]; then \
	  url=$$($(AWS) ssm get-parameter --name "/stopwatch/$(ENV)/database_owner_url" --with-decryption --query Parameter.Value --output text); \
	fi; \
	if [ -n "$${GITHUB_ACTIONS:-}" ]; then echo "::add-mask::$$url"; fi; \
	if [ -z "$$url" ] || [ "$$url" = unset ]; then echo "/stopwatch/$(ENV)/database_owner_url is not set (aws ssm put-parameter --overwrite ...)" >&2; exit 1; fi; \
	echo "==> alembic upgrade head ($(ENV))"; \
	cd "$(BACKEND)"; \
	export PGSSLROOTCERT="$${PGSSLROOTCERT:-$$(uv run python -c 'import certifi; print(certifi.where())')}"; \
	DATABASE_OWNER_URL="$$url" uv run alembic upgrade head

smoke: require-env tf-init ## Smoke-test ENV through CloudFront (EXPECT_VERSION=<sha>, REQUIRE_MANIFEST=1 for prod)
	@set -uo pipefail; \
	base=$$($(TF) output -raw public_base_url); origin=$$($(TF) output -raw api_endpoint); \
	tmp=$$(mktemp -d); fail=0; \
	check() { if [ "$$2" = ok ]; then echo "  ok    $$1"; else echo "  FAIL  $$1 ($$2)"; fail=1; fi; }; \
	echo "==> smoke $$base"; \
	code=000; for i in 1 2 3 4 5 6 7 8 9 10; do \
	  code=$$(curl -sS -o "$$tmp/healthz" -w '%{http_code}' "$$base/api/v1/healthz" || echo 000); \
	  [ "$$code" = 200 ] && break; sleep 6; done; \
	if [ "$$code" = 200 ] && grep -q '"status" *: *"ok"' "$$tmp/healthz"; then check "GET /api/v1/healthz" ok; else check "GET /api/v1/healthz" "HTTP $$code"; fi; \
	if [ -n "$(EXPECT_VERSION)" ]; then \
	  if grep -q "$(EXPECT_VERSION)" "$$tmp/healthz"; then check "healthz reports version $(EXPECT_VERSION)" ok; \
	  else check "healthz reports version $(EXPECT_VERSION)" "got $$(cat "$$tmp/healthz")"; fi; fi; \
	code=$$(curl -sS -o /dev/null -w '%{http_code}' "$$origin/api/v1/healthz" || echo 000); \
	if [ "$$code" = 403 ]; then check "direct execute-api call rejected (X-Origin-Verify)" ok; else check "direct execute-api call rejected (X-Origin-Verify)" "HTTP $$code"; fi; \
	code=$$(curl -sS -o /dev/null -w '%{http_code}' "$$base/data/v1/manifest.json" || echo 000); \
	if [ "$$code" = 200 ]; then check "GET /data/v1/manifest.json" ok; \
	elif [ "$$code" = 404 ] && [ "$(REQUIRE_MANIFEST)" != 1 ]; then echo "  warn  /data/v1/manifest.json not published yet (404; OAC works)"; \
	else check "GET /data/v1/manifest.json" "HTTP $$code"; fi; \
	curl -sS -D "$$tmp/headers" -o /dev/null "$$base/" || true; \
	grep -qi "^HTTP/[0-9.]* 200" "$$tmp/headers" && check "GET / (index.html)" ok || check "GET / (index.html)" "not 200"; \
	grep -qi "^content-security-policy: default-src 'self'; connect-src 'self' https://api-v3.mbta.com;" "$$tmp/headers" && check "CSP header" ok || check "CSP header" missing; \
	grep -qi "^strict-transport-security: max-age=63072000; includesubdomains" "$$tmp/headers" && check "HSTS header" ok || check "HSTS header" missing; \
	grep -qi "^x-content-type-options: nosniff" "$$tmp/headers" && check "nosniff header" ok || check "nosniff header" missing; \
	grep -qi "^cache-control: no-cache" "$$tmp/headers" && check "index.html Cache-Control: no-cache" ok || check "index.html Cache-Control: no-cache" missing; \
	code=$$(curl -sS -o /dev/null -w '%{http_code}' "$$base/about/methodology" || echo 000); \
	[ "$$code" = 200 ] && check "SPA deep link served index.html" ok || check "SPA deep link served index.html" "HTTP $$code"; \
	rm -rf "$$tmp"; exit $$fail
