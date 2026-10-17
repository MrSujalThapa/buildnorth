.PHONY: setup dev lint typecheck test build seed-demo evaluate check

setup:
	npm run setup

dev:
	npm run dev

lint:
	npm run lint

typecheck:
	npm run typecheck

test:
	npm run test

build:
	npm run build

seed-demo:
	npm run seed-demo

evaluate:
	npm run evaluate -- --system final

check:
	npm run lint && npm run typecheck && npm run test && npm run build && npm run check:architecture && npm run check:migrations
