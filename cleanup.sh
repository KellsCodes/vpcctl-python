#!/bin/bash
# cleanup.sh - Remove all vpcctl-created VPCs, subnets, bridges, and iptables rules
# This script removes ALL artifacts created by vpcctl.py

set -e

echo "Starting full VPC cleanup..."

# 1. Delete all namespaces matching vpcctl naming pattern (vpc*-*)
echo ""
echo "[1/7] Cleaning up network namespaces..."
NS_COUNT=0
for ns in $(ip netns list 2>/dev/null | awk '{print $1}' | grep -E "vpc.*-.*"); do
    echo "  → Deleting namespace: $ns"
    sudo ip netns del "$ns" 2>/dev/null || true
    NS_COUNT=$((NS_COUNT + 1))
done
echo "  ✓ Removed $NS_COUNT namespaces"

# 2. Delete all veth pairs (both in host and those that might be orphaned)
echo ""
echo "[2/7] Cleaning up veth interfaces..."
VETH_COUNT=0
# Delete veth interfaces starting with 'v' (vpcctl pattern) or 'p' (peering pattern)
for veth in $(ip link show 2>/dev/null | grep -oP '(v[a-f0-9]{6}[hn]|p[a-z0-9]+[ab])(?=[@:])'| sort -u); do
    echo "  → Deleting veth: $veth"
    sudo ip link del "$veth" 2>/dev/null || true
    VETH_COUNT=$((VETH_COUNT + 1))
done
# Also clean up old naming pattern veths (vvppuh, vvpprh, etc)
for veth in $(ip link show 2>/dev/null | grep -oP 'v[vp]{2}[a-z]{2}[hn](?=[@:])' | sort -u); do
    echo "  → Deleting veth: $veth"
    sudo ip link del "$veth" 2>/dev/null || true
    VETH_COUNT=$((VETH_COUNT + 1))
done
echo "  ✓ Removed $VETH_COUNT veth interfaces"

# 3. Delete all bridges matching vpcctl naming pattern (br-*)
echo ""
echo "[3/7] Cleaning up bridges..."
BRIDGE_COUNT=0
for br in $(ip link show 2>/dev/null | grep -oP 'br-[^\s:]+' | sort -u); do
    echo "  → Deleting bridge: $br"
    sudo ip link set "$br" down 2>/dev/null || true
    sudo ip link del "$br" type bridge 2>/dev/null || true
    BRIDGE_COUNT=$((BRIDGE_COUNT + 1))
done
echo "  ✓ Removed $BRIDGE_COUNT bridges"

# 4. Clean up iptables NAT rules (MASQUERADE rules added by vpcctl)
echo ""
echo "[4/7] Cleaning up iptables NAT rules..."
NAT_COUNT=0
sudo iptables -t nat -S 2>/dev/null | grep "MASQUERADE" | grep -E "10\.(10|20|30)\." | while read -r rule; do
    # Convert -A to -D for deletion
    rule_to_delete=$(echo "$rule" | sed 's/^-A /-D /')
    echo "  → Deleting NAT rule: $rule_to_delete"
    sudo iptables -t nat $rule_to_delete 2>/dev/null || true
    NAT_COUNT=$((NAT_COUNT + 1))
done
echo "  ✓ Removed NAT rules"

# 5. Clean up iptables FORWARD rules (peering rules)
echo ""
echo "[5/7] Cleaning up iptables FORWARD rules..."
FORWARD_COUNT=0
sudo iptables -S FORWARD 2>/dev/null | grep -E "br-vpc" | while read -r rule; do
    # Convert -A to -D for deletion
    rule_to_delete=$(echo "$rule" | sed 's/^-A /-D /')
    echo "  → Deleting FORWARD rule: $rule_to_delete"
    sudo iptables $rule_to_delete 2>/dev/null || true
    FORWARD_COUNT=$((FORWARD_COUNT + 1))
done
echo "  ✓ Removed FORWARD rules"

# 6. Clean up any remaining routes for VPC subnets
echo ""
echo "[6/7] Cleaning up routing table..."
ROUTE_COUNT=0
ip route show 2>/dev/null | grep -E "10\.(10|20|30)\." | while read -r route; do
    echo "  → Deleting route: $route"
    sudo ip route del $route 2>/dev/null || true
    ROUTE_COUNT=$((ROUTE_COUNT + 1))
done
echo "  ✓ Cleaned routing table"

# 7. Remove vpcctl log directory and metadata
echo ""
echo "[7/7] Cleaning up logs and metadata..."
if [ -d "logs" ]; then
    echo "  → Removing logs directory"
    sudo rm -rf logs/
    echo "  ✓ Removed logs directory"
else
    echo "  → No logs directory found"
fi