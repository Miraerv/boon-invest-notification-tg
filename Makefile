init: docker-down docker-pull docker-build-pull docker-up
down: docker-down
down-clear: docker-down-clear

docker-up:
	docker compose up -d

docker-down:
	docker compose down --remove-orphans

docker-down-clear:
	docker compose down -v --remove-orphans

docker-pull:
	docker compose pull

docker-build-pull:
	docker compose build --pull

