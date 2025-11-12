CLI = vpcctl.py

# User-defined
VPC1_NAME ?= vpc1
VPC2_NAME ?= vpc2
BASE1_CIDR ?= 10.10.0.0/16
BASE2_CIDR ?= 10.20.0.0/16
PUBLIC_IFACE = $(shell ip route | awk '/default/ {print $$5; exit}')

.PHONY: setup create-vpcs add-subnets peer-vpcs test-peering test-isolation apply-policies test-policies teardown all

# Make CLI executable
setup:
	@echo "Making CLI executable..."
	chmod +x $(CLI)
	@echo "CLI ready!"

# Create two VPCs
create-vpcs: setup
	@echo "Creating VPC $(VPC1_NAME) with CIDR $(BASE1_CIDR)..."
	sudo ./$(CLI) create-vpc $(VPC1_NAME) $(BASE1_CIDR) --public-interface $(PUBLIC_IFACE)
	@echo "Creating VPC $(VPC2_NAME) with CIDR $(BASE2_CIDR)..."
	sudo ./$(CLI) create-vpc $(VPC2_NAME) $(BASE2_CIDR) --public-interface $(PUBLIC_IFACE)

# Add subnets
add-subnets:
	@echo "Adding public and private subnets..."
	sudo ./$(CLI) add-subnet $(VPC1_NAME) public --type public --base-cidr $(BASE1_CIDR)
	sudo ./$(CLI) add-subnet $(VPC1_NAME) private --type private --base-cidr $(BASE1_CIDR)
	sudo ./$(CLI) add-subnet $(VPC2_NAME) public --type public --base-cidr $(BASE2_CIDR)
	sudo ./$(CLI) add-subnet $(VPC2_NAME) private --type private --base-cidr $(BASE2_CIDR)
	@echo "Subnets created."

# Peer VPCs
peer-vpcs:
	@echo "Peering $(VPC1_NAME) ↔ $(VPC2_NAME)..."
	sudo ./$(CLI) peer-vpc $(VPC1_NAME) $(VPC2_NAME)

# Test communication after peering
test-peering: peer-vpcs
	@echo "Testing peered VPC connectivity..."
	@echo "Pinging from $(VPC1_NAME)-public to $(VPC2_NAME)-public..."
	sudo ip netns exec $(VPC1_NAME)-public ping -c 3 10.20.0.2 || echo "Ping failed!"
	@echo "Curl test from $(VPC1_NAME)-public to $(VPC2_NAME)-public..."
	sudo ip netns exec $(VPC1_NAME)-public curl -s http://10.20.0.2:8080 || echo "Curl failed!"

# Test isolation for non-peered VPCs
test-isolation:
	@echo "Testing isolation between non-peered VPCs..."
	@echo "Pinging from $(VPC1_NAME)-private to $(VPC2_NAME)-private (should fail)..."
	sudo ip netns exec $(VPC1_NAME)-private ping -c 3 10.20.1.2 || echo "Ping correctly blocked!"
	@echo "Curl test (should fail)..."
	sudo ip netns exec $(VPC1_NAME)-private curl -s http://10.20.1.2:8080 || echo "Curl correctly blocked!"

# Apply firewall policies
apply-policies:
	@echo "Applying firewall policies from policies.json..."
	sudo ./$(CLI) add-subnet $(VPC1_NAME) public --type public --base-cidr $(BASE1_CIDR) --apply-policies
	sudo ./$(CLI) add-subnet $(VPC1_NAME) private --type private --base-cidr $(BASE1_CIDR) --apply-policies
	@echo "Firewall policies applied."

# Test policy enforcement
test-policies:
	@echo "Testing connectivity before applying policies..."
	@echo "Port 22 and 80 tests..."
	sudo ip netns exec $(VPC1_NAME)-public nc -zv 10.10.1.2 22 || echo "Port 22 blocked"
	sudo ip netns exec $(VPC1_NAME)-public nc -zv 10.10.1.2 80 || echo "Port 80 allowed"

	@echo "Applying policies..."
	make apply-policies

	@echo "Testing connectivity after applying policies..."
	@echo "Port 22 (should be blocked) and 80 (should be allowed)..."
	sudo ip netns exec $(VPC1_NAME)-public nc -zv 10.10.1.2 22 || echo "Port 22 correctly blocked"
	sudo ip netns exec $(VPC1_NAME)-public nc -zv 10.10.1.2 80 || echo "Port 80 correctly allowed"

# Teardown all VPCs
teardown:
	@echo "Deleting VPCs and cleaning up..."
	sudo ./$(CLI) delete-vpc $(VPC1_NAME) --cidr $(BASE1_CIDR) --public-interface $(PUBLIC_IFACE)
	sudo ./$(CLI) delete-vpc $(VPC2_NAME) --cidr $(BASE2_CIDR) --public-interface $(PUBLIC_IFACE)
	@echo "Cleanup complete."

# Full demo
all: create-vpcs add-subnets peer-vpcs test-peering test-isolation test-policies
	@echo "Full VPC demo complete with policies enforced!"
