# Makefile for vpcctl setup

CLI=vpcctl.py

.PHONY: setup

setup:
	@echo "Making vpcctl CLI executable..."
	chmod +x $(CLI)
	@echo "vpcctl is ready to use"
