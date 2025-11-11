#!/usr/bin/env python3

import argparse
import subprocess
import json
import ipaddress


def run_cmd(cmd):
    """Helper to run shell commands"""
    print(f"> {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error: {result.stderr.strip()}")
    return result


def create_vpc(args):
    bridge_name = f"br-{args.name}"
    print(f"Creating VPC '{args.name}' with bridge '{bridge_name}'...")

    # Create the Linux bridge
    run_cmd(f"sudo ip link add name {bridge_name} type bridge")
    run_cmd(f"sudo ip link set dev {bridge_name} up")

    # Enable IP forwarding
    run_cmd("sudo sysctl -w net.ipv4.ip_forward=1")
    print("IP forwarding enabled.")

    # Set up NAT if public interface provided
    if getattr(args, "public_interface", None):
        # use provided CIDR for masquerade if available else skip
        cidr = getattr(args, "cidr", None) or getattr(args, "base_cidr", None)
        if cidr:
            run_cmd(
                f"sudo iptables -t nat -A POSTROUTING -s {cidr} -o {args.public_interface} -j MASQUERADE")
            print(
                f"NAT configured for outbound traffic via {args.public_interface}")
        else:
            print("No VPC CIDR provided; skipping NAT rule.")
    print(f"Bridge '{bridge_name}' created and ready.")


def add_subnet(args):
    ns_name = f"{args.vpc_name}-{args.subnet_name}"
    # short veth names to meet linux limits
    veth_host = f"veth-{args.vpc_name[:3]}-{args.subnet_name[:2]}-h"
    veth_ns = f"veth-{args.vpc_name[:3]}-{args.subnet_name[:2]}-n"
    bridge_name = f"br-{args.vpc_name}"

    print(f"Creating {args.type} subnet namespace '{ns_name}'...")

    # Determine subnet IP (automatic if not provided)
    if args.cidr:
        subnet_ip = args.cidr
    elif getattr(args, "base_cidr", None):
        subnet_ip = calculate_subnet_ip(args.base_cidr, args.type)
    else:
        raise SystemExit("Error: either --cidr or --base-cidr must be provided for add-subnet")

    # Create network namespace (idempotent-ish)
    run_cmd(f"sudo ip netns add {ns_name}")

    # Create veth pair (delete any stale before creating to avoid conflicts)
    run_cmd(f"sudo ip link del {veth_host} 2>/dev/null || true")
    run_cmd(f"sudo ip link add {veth_host} type veth peer name {veth_ns}")

    # Attach host side to bridge
    run_cmd(f"sudo ip link set {veth_host} master {bridge_name}")
    run_cmd(f"sudo ip link set {veth_host} up")

    # Attach namespace side to namespace
    run_cmd(f"sudo ip link set {veth_ns} netns {ns_name}")
    run_cmd(f"sudo ip netns exec {ns_name} ip link set {veth_ns} up")

    # Assign IP to namespace interface
    run_cmd(f"sudo ip netns exec {ns_name} ip addr add {subnet_ip} dev {veth_ns}")

    # Calculate gateway (first usable IP in subnet)
    net = ipaddress.IPv4Network(subnet_ip, strict=False)
    gateway = str(net.network_address + 1)

    # Ensure bridge has gateway IP so namespace can reach it (idempotent)
    # add with /prefixlen derived from subnet
    prefix = net.prefixlen
    run_cmd(f"sudo ip addr add {gateway}/{prefix} dev {bridge_name} || true")

    # Add default route for public subnets to bridge/gateway
    if args.type == "public":
        run_cmd(f"sudo ip netns exec {ns_name} ip route add default via {gateway}")

    print(f"{args.type.capitalize()} subnet '{ns_name}' connected to bridge '{bridge_name}' with IP {subnet_ip}.")


def calculate_subnet_ip(base_cidr, subnet_type):
    net = ipaddress.IPv4Network(base_cidr, strict=False)
    # pick first /24 for public, second /24 for private
    subnets = list(net.subnets(new_prefix=24))
    if len(subnets) < 2:
        raise SystemExit("Error: base CIDR too small to create /24 subnets")
    if subnet_type == "public":
        subnet = subnets[0]
    else:  # private
        subnet = subnets[1]
    # return subnet network in form "10.20.1.0/24"
    return str(subnet)


def peer_vpc(args):
    """Peer two VPCs via bridge-to-bridge veth pair"""
    bridge_a = f"br-{args.vpc_a}"
    bridge_b = f"br-{args.vpc_b}"
    # short veth names
    veth_a = f"veth-{args.vpc_a[:3]}-{args.vpc_b[:3]}-a"
    veth_b = f"veth-{args.vpc_b[:3]}-{args.vpc_a[:3]}-b"

    print(f"Peering VPC '{args.vpc_a}' and VPC '{args.vpc_b}'...")

    # cleanup stale
    run_cmd(f"sudo ip link del {veth_a} 2>/dev/null || true")
    run_cmd(f"sudo ip link del {veth_b} 2>/dev/null || true")

    # Create veth pair between bridges
    run_cmd(f"sudo ip link add {veth_a} type veth peer name {veth_b}")
    run_cmd(f"sudo ip link set {veth_a} master {bridge_a}")
    run_cmd(f"sudo ip link set {veth_b} master {bridge_b}")
    run_cmd(f"sudo ip link set {veth_a} up")
    run_cmd(f"sudo ip link set {veth_b} up")

    print(f"VPCs '{args.vpc_a}' and '{args.vpc_b}' successfully peered via bridges.")


def apply_policy(args):
    """Apply firewall rules to a subnet namespace"""
    # target namespace based on provided vpc and subnet_type
    ns_name = f"{args.vpc}-{args.subnet_type}"
    print(f"Applying policies from {args.file} to namespace {ns_name}...")

    with open(args.file) as f:
        policies = json.load(f)

    for policy in policies:
        for rule in policy.get("ingress", []):
            if rule["action"] == "allow":
                cmd = f"sudo ip netns exec {ns_name} iptables -A INPUT -p {rule['protocol']} --dport {rule['port']} -j ACCEPT"
            else:
                cmd = f"sudo ip netns exec {ns_name} iptables -A INPUT -p {rule['protocol']} --dport {rule['port']} -j DROP"
            run_cmd(cmd)
    print("Policies applied successfully.")


def delete_subnet(args):
    ns_name = f"{args.vpc_name}-{args.subnet_name}"
    # compute veth host name with same pattern used in add_subnet
    veth_host = f"veth-{args.vpc_name[:3]}-{args.subnet_name[:2]}-h"
    print(f"Deleting subnet namespace '{ns_name}'...")

    # Delete namespace
    run_cmd(f"sudo ip netns del {ns_name} || true")

    # Delete host veth if exists
    run_cmd(f"sudo ip link del {veth_host} 2>/dev/null || true")

    print(f"Subnet '{ns_name}' cleaned up.")


def delete_vpc(args):
    bridge_name = f"br-{args.name}"
    print(f"Deleting VPC '{args.name}' and all subnets...")

    # Delete all namespaces matching the VPC
    result = subprocess.run(
        f"ip netns list | grep {args.name}", shell=True, capture_output=True, text=True)
    for ns in result.stdout.splitlines():
        run_cmd(f"sudo ip netns del {ns.strip()}")

    # Delete bridge
    run_cmd(f"sudo ip link set {bridge_name} down || true")
    run_cmd(f"sudo ip link del {bridge_name} type bridge || true")

    # Remove NAT rules if provided
    if getattr(args, "public_interface", None) and getattr(args, "cidr", None):
        run_cmd(
            f"sudo iptables -t nat -D POSTROUTING -s {args.cidr} -o {args.public_interface} -j MASQUERADE || true")

    print(f"VPC '{args.name}' deleted successfully.")


def main():
    parser = argparse.ArgumentParser(
        description="vpcctl - Virtual Private Cloud CLI")

    subparsers = parser.add_subparsers(title="Commands", dest="command")

    # create-vpc
    parser_create = subparsers.add_parser(
        "create-vpc", help="Create a new VPC")
    parser_create.add_argument("name", help="VPC name")
    parser_create.add_argument("cidr", help="VPC CIDR block")
    parser_create.add_argument(
        "--public-interface",
        help="Host network interface for outbound NAT (e.g., eth0, wlp20)"
    )
    parser_create.set_defaults(func=create_vpc)

    # delete-vpc (single parser is enough)
    parser_delete = subparsers.add_parser("delete-vpc", help="Delete a VPC")
    parser_delete.add_argument("name", help="VPC name")
    parser_delete.add_argument(
        "--public-interface", help="Host interface used for NAT")
    parser_delete.add_argument("--cidr", help="VPC CIDR block")
    parser_delete.set_defaults(func=delete_vpc)

    # add-subnet
    parser_subnet = subparsers.add_parser(
        "add-subnet", help="Add a subnet to a VPC"
    )
    parser_subnet.add_argument("vpc_name", help="VPC name")
    parser_subnet.add_argument("subnet_name", help="Subnet name")
    parser_subnet.add_argument(
        "--cidr",
        help="Optional CIDR block for the subnet (e.g. 10.0.1.0/24). If omitted, it will be calculated from --base-cidr."
    )
    parser_subnet.add_argument(
        "--base-cidr",
        help="Base CIDR of the VPC for automatic subnet IP calculation (e.g. 10.20.0.0/16)"
    )
    parser_subnet.add_argument(
        "--type",
        choices=["public", "private"],
        default="private",
        help="Subnet type: public or private"
    )
    parser_subnet.set_defaults(func=add_subnet)

    # peer-vpc
    parser_peer = subparsers.add_parser("peer-vpc", help="Peer two VPCs")
    parser_peer.add_argument("vpc_a", help="First VPC name")
    parser_peer.add_argument("vpc_b", help="Second VPC name")
    parser_peer.set_defaults(func=peer_vpc)

    # apply-policy
    parser_policy = subparsers.add_parser(
        "apply-policy", help="Apply firewall policies to a subnet")
    parser_policy.add_argument("vpc", help="VPC name")
    parser_policy.add_argument("subnet_type", choices=[
                               "public", "private"], help="Subnet type")
    parser_policy.add_argument("file", help="Path to JSON policy file")
    parser_policy.set_defaults(func=apply_policy)

    # delete-subnet
    parser_delete_subnet = subparsers.add_parser(
        "delete-subnet", help="Delete a subnet")
    parser_delete_subnet.add_argument("vpc_name", help="VPC name")
    parser_delete_subnet.add_argument("subnet_name", help="Subnet name")
    parser_delete_subnet.set_defaults(func=delete_subnet)

    args = parser.parse_args()

    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
