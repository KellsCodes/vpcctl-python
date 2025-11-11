#!/bin/bash
# cleanup.sh - Remove all vpcctl-created VPCs, subnets, bridges, and iptables NAT rules

echo "Starting full VPC cleanup..."

# Delete all namespaces matching vpcctl naming pattern
for ns in $(ip netns list | grep -E ".*-.*"); do
    echo "Deleting namespace: $ns"
    sudo ip netns del $ns
done

# Delete all bridges matching vpcctl naming pattern
for br in $(ip link show | grep -oP 'br-[^\s:]+' | sort -u); do
    echo "Deleting bridge: $br"
    sudo ip link set $br down || true
    sudo ip link del $br type bridge || true
done

# Remove all NAT rules added by vpcctl (basic assumption: MASQUERADE rules)
sudo iptables -t nat -S | grep MASQUERADE | while read rule; do
    rule_to_delete=$(echo $rule | sed 's/^-A /-D /')
    echo "Deleting iptables NAT rule: $rule_to_delete"
    sudo iptables -t nat $rule_to_delete
done

echo "Full cleanup completed."
