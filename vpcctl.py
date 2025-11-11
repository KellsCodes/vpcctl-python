#!/usr/bin/env python3

import argparse
import subprocess


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
    print(f"Bridge '{bridge_name}' created and brought up.")


def delete_vpc(args):
    print(f"Deleting VPC '{args.name}'...")


def add_subnet(args):
    ns_name = f"{args.vpc_name}-{args.subnet_name}"
    veth_host = f"veth-{args.subnet_name}-host"
    veth_ns = f"veth-{args.subnet_name}-ns"
    bridge_name = f"br-{args.vpc_name}"

    print(f"Creating subnet namespace '{ns_name}'...")

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
        f"sudo ip netns exec {ns_name} ip addr add {args.cidr} dev {veth_ns}")

    print(
        f"Subnet '{ns_name}' connected to bridge '{bridge_name}' with IP {args.cidr}.")


def main():
    parser = argparse.ArgumentParser(
        description="vpcctl - Virtual Private Cloud CLI")

    subparsers = parser.add_subparsers(title="Commands", dest="command")

    # create-vpc
    parser_create = subparsers.add_parser(
        "create-vpc", help="Create a new VPC")
    parser_create.add_argument("name", help="VPC name")
    parser_create.add_argument("cidr", help="VPC CIDR block")
    parser_create.set_defaults(func=create_vpc)

    # delete-vpc
    parser_delete = subparsers.add_parser("delete-vpc", help="Delete a VPC")
    parser_delete.add_argument("name", help="VPC name")
    parser_delete.set_defaults(func=delete_vpc)

    # add-subnet
    parser_subnet = subparsers.add_parser(
        "add-subnet", help="Add a subnet to a VPC")
    parser_subnet.add_argument("vpc_name", help="VPC name")
    parser_subnet.add_argument("subnet_name", help="Subnet name")
    parser_subnet.add_argument("cidr", help="Subnet CIDR block")
    parser_subnet.set_defaults(func=add_subnet)

    args = parser.parse_args()

    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
