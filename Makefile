# Default variables
CLI=vpcctl.py
VPC_NAME ?= myvpc
BASE_CIDR ?= 10.10.0.0/16
PUBLIC_IFACE=$(shell ip route | awk '/default/ {print $$5; exit}')

# Dynamic subnet calculation (default offsets)
PUBLIC_SUBNET_IP=$(shell python3 -c "import ipaddress; print(list(ipaddress.IPv4Network('$(BASE_CIDR)').subnets(new_prefix=24))[0])")
PRIVATE_SUBNET_IP=$(shell python3 -c "import ipaddress; print(list(ipaddress.IPv4Network('$(BASE_CIDR)').subnets(new_prefix=24))[1])")

.PHONY: setup create-vpc add-subnets all

setup:
	@echo "Making CLI executable..."
	chmod +x $(CLI)
	@echo "CLI ready"

create-vpc:
	sudo ./$(CLI) create-vpc $(VPC_NAME) $(BASE_CIDR) --public-interface $(PUBLIC_IFACE)

add-subnets:
	sudo ./$(CLI) add-subnet $(VPC_NAME) public $(PUBLIC_SUBNET_IP)/24 --type public
	sudo ./$(CLI) add-subnet $(VPC_NAME) private $(PRIVATE_SUBNET_IP)/24 --type private

all: setup create-vpc add-subnets
	@echo "VPC $(VPC_NAME) ready with dynamic subnet IPs"
