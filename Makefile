CLI = vpcctl.py

# User-defined
VPC1_NAME ?= vpc1
VPC2_NAME ?= vpc2
BASE1_CIDR ?= 10.10.0.0/16
BASE2_CIDR ?= 10.20.0.0/16
PUBLIC_IFACE = $(shell ip route | awk '/default/ {print $$5; exit}')
POLICIES_FILE ?= policies.json

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

# Simulate VPC peering using a veth pair
peer-vpcs:
	@echo "Creating veth pair to simulate peering..."
	sudo ip link add vpc1-peer type veth peer name vpc2-peer
	sudo ip link set vpc1-peer netns $(VPC1_NAME)-public
	sudo ip link set vpc2-peer netns $(VPC2_NAME)-public
	sudo ip netns exec $(VPC1_NAME)-public ip addr add 10.255.1.1/30 dev vpc1-peer
	sudo ip netns exec $(VPC2_NAME)-public ip addr add 10.255.1.2/30 dev vpc2-peer
	sudo ip netns exec $(VPC1_NAME)-public ip link set vpc1-peer up
	sudo ip netns exec $(VPC2_NAME)-public ip link set vpc2-peer up
	sudo ip netns exec $(VPC1_NAME)-public ip route add $(BASE2_CIDR) via 10.255.1.2
	sudo ip netns exec $(VPC2_NAME)-public ip route add $(BASE1_CIDR) via 10.255.1.1
	@echo "Peering established via veth pair."

# Test connectivity between VPCs
test-peering: peer-vpcs
	@echo "Testing connectivity between $(VPC1_NAME) and $(VPC2_NAME)..."
	sudo ip netns exec $(VPC1_NAME)-public ping -c 3 10.255.1.2 || echo "Ping failed!"
	@echo "VPC peering test completed."

# Test isolation (no peering)
test-isolation:
	@echo "Testing isolation between $(VPC1_NAME)-private and $(VPC2_NAME)-private..."
	sudo ip netns exec $(VPC1_NAME)-private ping -c 3 10.20.2.2 || echo "Ping correctly blocked!"

# Apply firewall policies
apply-policies:
	@echo "Applying firewall policies..."
	sudo ./$(CLI) apply-policies $(VPC1_NAME) --policies $(POLICIES_FILE)
	@echo "Firewall policies applied."

# Test before and after firewall enforcement
test-policies:
	@echo "Testing BEFORE firewall policy..."
	sudo ip netns exec $(VPC1_NAME)-public nc -zv 10.10.1.2 22 || echo "Port 22 open (pre-policy)"
	sudo ip netns exec $(VPC1_NAME)-public nc -zv 10.10.1.2 80 || echo "Port 80 open (pre-policy)"

	@echo "Applying firewall policies..."
	make apply-policies

	@echo "Testing AFTER firewall policy..."
	sudo ip netns exec $(VPC1_NAME)-public nc -zv 10.10.1.2 22 || echo "Port 22 correctly blocked"
	sudo ip netns exec $(VPC1_NAME)-public nc -zv 10.10.1.2 80 || echo "Port 80 correctly allowed"

# Teardown
teardown:
	@echo "Cleaning up all resources..."
	sudo ip link del vpc1-peer 2>/dev/null || true
	sudo ./$(CLI) delete-vpc $(VPC1_NAME) --cidr $(BASE1_CIDR) --public-interface $(PUBLIC_IFACE)
	sudo ./$(CLI) delete-vpc $(VPC2_NAME) --cidr $(BASE2_CIDR) --public-interface $(PUBLIC_IFACE)
	@echo "Cleanup complete."

# Full demo
all: create-vpcs add-subnets peer-vpcs test-peering test-isolation test-policies
	@echo "✅ Full VPC demo complete with peering and firewall enforcement!"
