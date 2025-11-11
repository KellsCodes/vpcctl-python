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
    if args.public_interface:
        run_cmd(
            f"sudo iptables -t nat -A POSTROUTING -s {args.cidr} -o {args.public_interface} -j MASQUERADE")
        print(
            f"NAT configured for outbound traffic via {args.public_interface}")

    print(f"Bridge '{bridge_name}' created and ready.")


def add_subnet(args):
    ns_name = f"{args.vpc_name}-{args.subnet_name}"
    veth_host = f"veth-{args.subnet_name}-host"
    veth_ns = f"veth-{args.subnet_name}-ns"
    bridge_name = f"br-{args.vpc_name}"

    print(f"Creating {args.type} subnet namespace '{ns_name}'...")

    # Determine subnet IP (automatic if not provided)
    subnet_cidr = args.cidr or calculate_subnet_ip(args.base_cidr, args.type)

    # Create network namespace
    run_cmd(f"sudo ip netns add {ns_name}")

    # Create veth pair
    run_cmd(f"sudo ip link add {veth_host} type veth peer name {veth_ns}")

    # Attach host side to bridge
    run_cmd(f"sudo ip link set {veth_host} master {bridge_name}")
    run_cmd(f"sudo ip link set {veth_host} up")

    # Attach namespace side to namespace
    run_cmd(f"sudo ip link set {veth_ns} netns {ns_name}")
    run_cmd(f"sudo ip netns exec {ns_name} ip link set {veth_ns} up")
    run_cmd(
        f"sudo ip netns exec {ns_name} ip addr add {subnet_cidr} dev {veth_ns}")

    # Add default route for public subnets to bridge
    if args.type == "public":
        # use first host IP in subnet as gateway (x.x.1.1)
        first_octets = ".".join(subnet_cidr.split(".")[:2])
        run_cmd(
            f"sudo ip netns exec {ns_name} ip route add default via {first_octets}.1.1"
        )

    print(f"{args.type.capitalize()} subnet '{ns_name}' connected to bridge '{bridge_name}' with IP {subnet_cidr}.")


def calculate_subnet_ip(base_cidr, subnet_type):
    net = ipaddress.IPv4Network(base_cidr)
    # pick first /24 for public, second /24 for private
    if subnet_type == "public":
        subnet = list(net.subnets(new_prefix=24))[0]
    else:  # private
        subnet = list(net.subnets(new_prefix=24))[1]
    return str(subnet)


def peer_vpc(args):
    """Peer two VPCs via bridge-to-bridge veth pair"""
    bridge_a = f"br-{args.vpc_a}"
    bridge_b = f"br-{args.vpc_b}"
    veth_a = f"veth-{args.vpc_a}-to-{args.vpc_b}"
    veth_b = f"veth-{args.vpc_b}-to-{args.vpc_a}"

    print(f"Peering VPC '{args.vpc_a}' and VPC '{args.vpc_b}'...")

    # Create veth pair between bridges
    run_cmd(f"sudo ip link add {veth_a} type veth peer name {veth_b}")
    run_cmd(f"sudo ip link set {veth_a} master {bridge_a}")
    run_cmd(f"sudo ip link set {veth_b} master {bridge_b}")
    run_cmd(f"sudo ip link set {veth_a} up")
    run_cmd(f"sudo ip link set {veth_b} up")

    print(
        f"VPCs '{args.vpc_a}' and '{args.vpc_b}' successfully peered via bridges.")


def apply_policy(args):
    """Apply firewall rules to a subnet namespace"""
    with open(args.file) as f:
        policies = json.load(f)

    for policy in policies:
        ns_name = f"{args.vpc}-{policy['subnet'].split('.')[2]}-{args.subnet_type}"
        print(f"Applying policy to {ns_name}...")

        for rule in policy.get("ingress", []):
            if rule["action"] == "allow":
                cmd = f"sudo ip netns exec {ns_name} iptables -A INPUT -p {rule['protocol']} --dport {rule['port']} -j ACCEPT"
            else:
                cmd = f"sudo ip netns exec {ns_name} iptables -A INPUT -p {rule['protocol']} --dport {rule['port']} -j DROP"
            run_cmd(cmd)
    print("Policies applied successfully.")


def delete_subnet(args):
    ns_name = f"{args.vpc_name}-{args.subnet_name}"
    veth_host = f"veth-{args.subnet_name}-host"
    print(f"Deleting subnet namespace '{ns_name}'...")

    # Delete namespace
    run_cmd(f"sudo ip netns del {ns_name}")

    # Delete host veth if exists
    run_cmd(f"sudo ip link del {veth_host} || true")

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

    # Remove NAT rules
    if args.public_interface:
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

    # delete-vpc
    parser_delete = subparsers.add_parser("delete-vpc", help="Delete a VPC")
    parser_delete.add_argument("name", help="VPC name")
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

    # Add Peer VPC
    parser_peer = subparsers.add_parser("peer-vpc", help="Peer two VPCs")
    parser_peer.add_argument("vpc_a", help="First VPC name")
    parser_peer.add_argument("vpc_b", help="Second VPC name")
    parser_peer.set_defaults(func=peer_vpc)

    # Add Parser policy
    parser_policy = subparsers.add_parser(
        "apply-policy", help="Apply firewall policies to a subnet")
    parser_policy.add_argument("vpc", help="VPC name")
    parser_policy.add_argument("subnet_type", choices=[
                               "public", "private"], help="Subnet type")
    parser_policy.add_argument("file", help="Path to JSON policy file")
    parser_policy.set_defaults(func=apply_policy)

    # Delete vpc
    parser_delete = subparsers.add_parser("delete-vpc", help="Delete a VPC")
    parser_delete.add_argument("name", help="VPC name")
    parser_delete.add_argument(
        "--public-interface", help="Host interface used for NAT")
    parser_delete.add_argument("--cidr", help="VPC CIDR block")
    parser_delete.set_defaults(func=delete_vpc)

    # Delete subnet
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
