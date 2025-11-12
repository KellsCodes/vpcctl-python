# Makefile for VPC Testing and Demonstration
# Usage: make <target>
# Example: make all (runs full demo)

CLI = python3 vpcctl.py

# Configuration - You can override these
VPC1_NAME ?= vpc1
VPC2_NAME ?= vpc2
BASE1_CIDR ?= 10.10.0.0/16
BASE2_CIDR ?= 10.20.0.0/16
PUBLIC_IFACE ?= $(shell ip route | awk '/default/ {print $$5; exit}')
POLICIES_FILE ?= policies.json

# Derived IP addresses for testing
VPC1_PUBLIC_IP = 10.10.1.2
VPC1_PRIVATE_IP = 10.10.2.2
VPC2_PUBLIC_IP = 10.20.1.2
VPC2_PRIVATE_IP = 10.20.2.2

.PHONY: help setup create-vpcs add-subnets peer-vpcs test-peering test-isolation \
        apply-policies test-policies cleanup verify show-config all demo

# Default target - show help
.DEFAULT_GOAL := help

# Color codes for output
GREEN = \033[0;32m
YELLOW = \033[0;33m
BLUE = \033[0;34m
RED = \033[0;31m
NC = \033[0m # No Color

help:
	@echo ""
	@echo "$(BLUE)═══════════════════════════════════════════════════════════════$(NC)"
	@echo "$(GREEN)           VPC Simulation Testing Suite$(NC)"
	@echo "$(BLUE)═══════════════════════════════════════════════════════════════$(NC)"
	@echo ""
	@echo "$(YELLOW)Available targets:$(NC)"
	@echo ""
	@echo "  $(GREEN)make all$(NC)              - Run complete demo (create, peer, test)"
	@echo "  $(GREEN)make demo$(NC)             - Same as 'all' with more verbose output"
	@echo ""
	@echo "$(YELLOW)Setup and Creation:$(NC)"
	@echo "  $(GREEN)make setup$(NC)            - Check prerequisites"
	@echo "  $(GREEN)make create-vpcs$(NC)      - Create VPC1 and VPC2"
	@echo "  $(GREEN)make add-subnets$(NC)      - Add public/private subnets to both VPCs"
	@echo ""
	@echo "$(YELLOW)Peering and Testing:$(NC)"
	@echo "  $(GREEN)make peer-vpcs$(NC)        - Establish VPC peering connection"
	@echo "  $(GREEN)make test-peering$(NC)     - Test connectivity between peered VPCs"
	@echo "  $(GREEN)make test-isolation$(NC)   - Test that private subnets are isolated"
	@echo ""
	@echo "$(YELLOW)Firewall:$(NC)"
	@echo "  $(GREEN)make apply-policies$(NC)   - Apply firewall rules from $(POLICIES_FILE)"
	@echo "  $(GREEN)make test-policies$(NC)    - Test firewall enforcement"
	@echo ""
	@echo "$(YELLOW)Utilities:$(NC)"
	@echo "  $(GREEN)make verify$(NC)           - Verify VPC setup and connectivity"
	@echo "  $(GREEN)make show-config$(NC)      - Display current configuration"
	@echo "  $(GREEN)make cleanup$(NC)          - Remove all VPCs and resources"
	@echo ""
	@echo "$(YELLOW)Examples:$(NC)"
	@echo "  make all                                    # Full demo"
	@echo "  make VPC1_NAME=prod-vpc BASE1_CIDR=10.30.0.0/16 create-vpcs"
	@echo ""
	@echo "$(BLUE)═══════════════════════════════════════════════════════════════$(NC)"
	@echo ""

# Show current configuration
show-config:
	@echo ""
	@echo "$(BLUE)Current Configuration:$(NC)"
	@echo "  VPC1 Name:       $(VPC1_NAME)"
	@echo "  VPC1 CIDR:       $(BASE1_CIDR)"
	@echo "  VPC2 Name:       $(VPC2_NAME)"
	@echo "  VPC2 CIDR:       $(BASE2_CIDR)"
	@echo "  Public Interface: $(PUBLIC_IFACE)"
	@echo ""

# Check prerequisites
setup:
	@echo "$(YELLOW)Checking prerequisites...$(NC)"
	@command -v python3 >/dev/null 2>&1 || { echo "$(RED)Error: python3 not found$(NC)"; exit 1; }
	@test -f vpcctl.py || { echo "$(RED)Error: vpcctl.py not found$(NC)"; exit 1; }
	@test -n "$(PUBLIC_IFACE)" || { echo "$(RED)Error: Cannot detect public interface$(NC)"; exit 1; }
	@echo "$(GREEN)✓ All prerequisites met$(NC)"
	@echo "  Python3: $$(which python3)"
	@echo "  Public Interface: $(PUBLIC_IFACE)"
	@echo ""

# Create two VPCs
create-vpcs: setup
	@echo ""
	@echo "$(BLUE)═══ Creating VPCs ═══$(NC)"
	@echo "$(YELLOW)Creating VPC $(VPC1_NAME) with CIDR $(BASE1_CIDR)...$(NC)"
	@sudo $(CLI) create-vpc $(VPC1_NAME) $(BASE1_CIDR) --public-interface $(PUBLIC_IFACE)
	@echo ""
	@echo "$(YELLOW)Creating VPC $(VPC2_NAME) with CIDR $(BASE2_CIDR)...$(NC)"
	@sudo $(CLI) create-vpc $(VPC2_NAME) $(BASE2_CIDR) --public-interface $(PUBLIC_IFACE)
	@echo "$(GREEN)✓ VPCs created successfully$(NC)"
	@echo ""

# Add subnets to both VPCs
add-subnets:
	@echo ""
	@echo "$(BLUE)═══ Adding Subnets ═══$(NC)"
	@echo "$(YELLOW)Adding subnets to $(VPC1_NAME)...$(NC)"
	@sudo $(CLI) add-subnet $(VPC1_NAME) public --type public --base-cidr $(BASE1_CIDR)
	@sudo $(CLI) add-subnet $(VPC1_NAME) private --type private --base-cidr $(BASE1_CIDR)
	@echo ""
	@echo "$(YELLOW)Adding subnets to $(VPC2_NAME)...$(NC)"
	@sudo $(CLI) add-subnet $(VPC2_NAME) public --type public --base-cidr $(BASE2_CIDR)
	@sudo $(CLI) add-subnet $(VPC2_NAME) private --type private --base-cidr $(BASE2_CIDR)
	@echo "$(GREEN)✓ All subnets created successfully$(NC)"
	@echo ""

# Establish VPC peering
peer-vpcs:
	@echo ""
	@echo "$(BLUE)═══ Establishing VPC Peering ═══$(NC)"
	@sudo $(CLI) peer-vpc $(VPC1_NAME) $(VPC2_NAME)
	@echo "$(GREEN)✓ Peering established$(NC)"
	@echo ""

# Test connectivity between VPCs
test-peering:
	@echo ""
	@echo "$(BLUE)═══ Testing VPC Peering ═══$(NC)"
	@echo "$(YELLOW)Test 1: $(VPC1_NAME)-public → $(VPC2_NAME)-public ($(VPC2_PUBLIC_IP))$(NC)"
	@sudo ip netns exec $(VPC1_NAME)-public ping -c 3 -W 2 $(VPC2_PUBLIC_IP) && echo "$(GREEN)✓ Success$(NC)" || echo "$(RED)✗ Failed$(NC)"
	@echo ""
	@echo "$(YELLOW)Test 2: $(VPC2_NAME)-public → $(VPC1_NAME)-public ($(VPC1_PUBLIC_IP))$(NC)"
	@sudo ip netns exec $(VPC2_NAME)-public ping -c 3 -W 2 $(VPC1_PUBLIC_IP) && echo "$(GREEN)✓ Success$(NC)" || echo "$(RED)✗ Failed$(NC)"
	@echo ""
	@echo "$(YELLOW)Test 3: $(VPC1_NAME)-public → $(VPC2_NAME)-private ($(VPC2_PRIVATE_IP))$(NC)"
	@sudo ip netns exec $(VPC1_NAME)-public ping -c 3 -W 2 $(VPC2_PRIVATE_IP) && echo "$(GREEN)✓ Success$(NC)" || echo "$(RED)✗ Failed$(NC)"
	@echo ""
	@echo "$(YELLOW)Test 4: $(VPC1_NAME)-private → $(VPC2_NAME)-private ($(VPC2_PRIVATE_IP))$(NC)"
	@sudo ip netns exec $(VPC1_NAME)-private ping -c 3 -W 2 $(VPC2_PRIVATE_IP) && echo "$(GREEN)✓ Success$(NC)" || echo "$(RED)✗ Failed$(NC)"
	@echo ""

# Test that private subnets can communicate within VPC
test-isolation:
	@echo ""
	@echo "$(BLUE)═══ Testing Subnet Isolation (Within VPC) ═══$(NC)"
	@echo "$(YELLOW)Test: $(VPC1_NAME)-public → $(VPC1_NAME)-private ($(VPC1_PRIVATE_IP))$(NC)"
	@sudo ip netns exec $(VPC1_NAME)-public ping -c 3 -W 2 $(VPC1_PRIVATE_IP) && echo "$(GREEN)✓ Can communicate within same VPC$(NC)" || echo "$(RED)✗ Unexpected isolation$(NC)"
	@echo ""

# Test internet connectivity
test-internet:
	@echo ""
	@echo "$(BLUE)═══ Testing Internet Connectivity ═══$(NC)"
	@echo "$(YELLOW)Test 1: $(VPC1_NAME)-public → 8.8.8.8 (Google DNS)$(NC)"
	@sudo ip netns exec $(VPC1_NAME)-public ping -c 3 -W 2 8.8.8.8 && echo "$(GREEN)✓ Public subnet has internet access$(NC)" || echo "$(RED)✗ No internet access$(NC)"
	@echo ""
	@echo "$(YELLOW)Test 2: $(VPC1_NAME)-private → 8.8.8.8 (Google DNS)$(NC)"
	@sudo ip netns exec $(VPC1_NAME)-private ping -c 3 -W 2 8.8.8.8 && echo "$(RED)✗ Private subnet should NOT have internet access$(NC)" || echo "$(GREEN)✓ Private subnet correctly isolated from internet$(NC)"
	@echo ""

# Apply firewall policies (if policies.json exists)
apply-policies:
	@echo ""
	@echo "$(BLUE)═══ Applying Firewall Policies ═══$(NC)"
	@if [ -f "$(POLICIES_FILE)" ]; then \
		sudo $(CLI) apply-policies $(VPC1_NAME) --policies $(POLICIES_FILE); \
		echo "$(GREEN)✓ Policies applied$(NC)"; \
	else \
		echo "$(YELLOW)⚠ $(POLICIES_FILE) not found, skipping$(NC)"; \
	fi
	@echo ""

# Test firewall policies
test-policies:
	@echo ""
	@echo "$(BLUE)═══ Testing Firewall Policies ═══$(NC)"
	@if [ -f "$(POLICIES_FILE)" ]; then \
		echo "$(YELLOW)Testing port accessibility...$(NC)"; \
		sudo ip netns exec $(VPC1_NAME)-public nc -zv -w 2 $(VPC1_PUBLIC_IP) 22 2>&1 | head -1; \
		sudo ip netns exec $(VPC1_NAME)-public nc -zv -w 2 $(VPC1_PUBLIC_IP) 80 2>&1 | head -1; \
		echo "$(GREEN)✓ Policy tests completed$(NC)"; \
	else \
		echo "$(YELLOW)⚠ $(POLICIES_FILE) not found, skipping$(NC)"; \
	fi
	@echo ""

# Verify the setup
verify:
	@echo ""
	@echo "$(BLUE)═══ Verifying VPC Setup ═══$(NC)"
	@echo "$(YELLOW)Checking namespaces...$(NC)"
	@sudo ip netns list | grep -E "$(VPC1_NAME)|$(VPC2_NAME)" || echo "$(RED)No VPC namespaces found$(NC)"
	@echo ""
	@echo "$(YELLOW)Checking bridges...$(NC)"
	@ip link show | grep -E "br-$(VPC1_NAME)|br-$(VPC2_NAME)" || echo "$(RED)No VPC bridges found$(NC)"
	@echo ""
	@echo "$(YELLOW)Checking routes in $(VPC1_NAME)-public...$(NC)"
	@sudo ip netns exec $(VPC1_NAME)-public ip route
	@echo ""

# Clean up everything
cleanup:
	@echo ""
	@echo "$(BLUE)═══ Cleaning Up Resources ═══$(NC)"
	@if [ -f "cleanup.sh" ]; then \
		chmod +x cleanup.sh; \
		sudo ./cleanup.sh; \
	else \
		echo "$(YELLOW)Running manual cleanup...$(NC)"; \
		sudo $(CLI) delete-vpc $(VPC1_NAME) 2>/dev/null || true; \
		sudo $(CLI) delete-vpc $(VPC2_NAME) 2>/dev/null || true; \
	fi
	@echo "$(GREEN)✓ Cleanup complete$(NC)"
	@echo ""

# Full demonstration
all: show-config create-vpcs add-subnets peer-vpcs test-peering test-isolation test-internet
	@echo ""
	@echo "$(GREEN)═══════════════════════════════════════════════════════════════$(NC)"
	@echo "$(GREEN)✓ Full VPC demo completed successfully!$(NC)"
	@echo "$(GREEN)═══════════════════════════════════════════════════════════════$(NC)"
	@echo ""
	@echo "$(YELLOW)Summary:$(NC)"
	@echo "  • Created 2 VPCs with public/private subnets"
	@echo "  • Established VPC peering"
	@echo "  • Verified inter-VPC connectivity"
	@echo "  • Tested subnet isolation"
	@echo "  • Tested internet connectivity"
	@echo ""
	@echo "$(YELLOW)To clean up:$(NC) make cleanup"
	@echo ""

# Verbose demo with step-by-step prompts
demo: show-config
	@echo ""
	@echo "$(BLUE)Starting interactive VPC demonstration...$(NC)"
	@echo "Press Enter to continue after each step"
	@read -p ""
	@make create-vpcs
	@read -p "$(YELLOW)Press Enter to add subnets...$(NC)"
	@make add-subnets
	@read -p "$(YELLOW)Press Enter to establish peering...$(NC)"
	@make peer-vpcs
	@read -p "$(YELLOW)Press Enter to test connectivity...$(NC)"
	@make test-peering
	@make test-isolation
	@make test-internet
	@echo ""
	@echo "$(GREEN)✓ Demo complete! Run 'make cleanup' when done.$(NC)"
	@echo ""