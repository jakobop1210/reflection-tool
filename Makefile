export SHELL:=/bin/sh
export SHELLOPTS:=$(if $(SHELLOPTS),$(SHELLOPTS):)pipefail:errexit

.ONESHELL:

dev:
	echo "Starting development environment..."
	docker-compose up --no-deps backend

test-backend:
	echo "Running tests..."
	rm -f ./api/test.db
	docker build -f api/Dockerfile.test -t reflect_test .
	docker run --rm -e TEST=true -e isAdmin=false -e production=false -v $(PWD)/api:/api reflect_test

# for windows, the third command should be:
# docker run --rm -e TEST=true -e isAdmin=false -e production=false -v %cd%/api:/api reflect_test