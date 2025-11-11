CLI = vpcctl.py

# User-defined (can be overridden when running `make`)
VPC_NAME ?= myvpc
BASE_CIDR ?= 10.10.0.0/16

# Automatically detect host's internet interface
PUBLIC_IFACE = $(shell ip route | awk '/default/ {print $$5; exit}')

.PHONY: setup create-vpc add-subnets delete-vpc all

# Make CLI executable
setup:
	@echo "🔧 Making CLI executable..."
	chmod +x $(CLI)
	@echo "CLI ready!"

# Create a new VPC
create-vpc:
	@echo "Creating VPC $(VPC_NAME) with CIDR $(BASE_CIDR)..."
	sudo ./$(CLI) create-vpc $(VPC_NAME) $(BASE_CIDR) --public-interface $(PUBLIC_IFACE)

# Add subnets to the VPC (public and private)
add-subnets:
	@echo "Adding public and private subnets to $(VPC_NAME)..."
	sudo ./$(CLI) add-subnet $(VPC_NAME) public --type public --base-cidr $(BASE_CIDR)
	sudo ./$(CLI) add-subnet $(VPC_NAME) private --type private --base-cidr $(BASE_CIDR)
	@echo "Subnets created successfully!"

# Delete the VPC and all its resources
delete-vpc:
	@echo "Cleaning up VPC $(VPC_NAME)..."
	sudo ./$(CLI) delete-vpc $(VPC_NAME)
	@echo "VPC $(VPC_NAME) deleted successfully!"

# Complete setup (for quick demo)
all: setup create-vpc add-subnets
	@echo "VPC $(VPC_NAME) setup complete and ready!"
