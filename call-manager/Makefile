VERSION=$(shell cat version)

IMAGE=ghcr.io/epoch8/rtk-call-manager:${VERSION}

build:
	cd .. && docker build -t ${IMAGE} .

upload:
	docker push ${IMAGE}
