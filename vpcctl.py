#!/usr/bin/env python3
import os
import sys
import json
import subprocess
import argparse
from datetime import datetime

LOG_DIR = "logs"
LOG_FILE = os.path.join(LOG_DIR, "vpcctl.log")


""" Utility Functions """

def log_action(action, status="success", details=""):
    """Write a structured log line."""
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
                f"ACTION={action} STATUS={status} DETAILS={details}\n")


def run_cmd(cmd):
    """Run a system command safely with error handling."""
    try:
        subprocess.run(cmd, shell=True, check=True, text=True, capture_output=True)
        log_action("cmd", "success", cmd)
    except subprocess.CalledProcessError as e:
        log_action("cmd", "error", f"{cmd} => {e.stderr.strip()}")
        print(f"Command failed: {cmd}\n{e.stderr.strip()}")
        sys.exit(1)


"""Core VPC Functions """

def create_vpc(name, base_cidr, public_iface=None):
    bridge_name = f"br-{name}"
    log_action("create-vpc", "started", f"Creating VPC {name} ({base_cidr})")

    run_cmd(f"ip link add name {bridge_name} type bridge")
    run_cmd(f"ip addr add {base_cidr.split('.')[0]}.{base_cidr.split('.')[1]}.0.1/16 dev {bridge_name}")
    run_cmd(f"ip link set {bridge_name} up")

    if public_iface:
        run_cmd(f"iptables -t nat -A POSTROUTING -o {public_iface} -j MASQUERADE")

    log_action("create-vpc", "success", f"Bridge {bridge_name} created")
    print(f"VPC '{name}' created successfully.")


def add_subnet(vpc_name, subnet_name, subnet_type, base_cidr):
    ns_name = f"{vpc_name}-{subnet_name}"
    bridge_name = f"br-{vpc_name}"

    log_action("add-subnet", "started", f"Adding {subnet_type} subnet {subnet_name}")

    # Derive subnet IP (simple incremental logic)
    subnet_id = "1" if subnet_type == "public" else "2"
    subnet_cidr = f"{base_cidr.split('.')[0]}.{base_cidr.split('.')[1]}.{subnet_id}.0/24"

    veth_host = f"veth-{vpc_name[:3]}-{subnet_name[:3]}"
    veth_ns = f"{veth_host}-ns"

    run_cmd(f"ip netns add {ns_name}")
    run_cmd(f"ip link add {veth_host} type veth peer name {veth_ns}")
    run_cmd(f"ip link set {veth_ns} netns {ns_name}")
    run_cmd(f"ip link set {veth_host} master {bridge_name}")
    run_cmd(f"ip link set {veth_host} up")
    run_cmd(f"ip netns exec {ns_name} ip addr add 10.20.{subnet_id}.2/24 dev {veth_ns}")
    run_cmd(f"ip netns exec {ns_name} ip link set {veth_ns} up")
    run_cmd(f"ip netns exec {ns_name} ip route add default via 10.20.{subnet_id}.1")

    log_action("add-subnet", "success", f"Subnet {subnet_name} ({subnet_cidr}) added")
    print(f"Subnet '{subnet_name}' added successfully ({subnet_cidr}).")


def apply_policies(vpc_name, policies_file):
    """Apply firewall rules defined in policies.json."""
    log_action("apply-policies", "started", f"Applying policies from {policies_file}")

    if not os.path.exists(policies_file):
        log_action("apply-policies", "error", f"{policies_file} not found")
        print(f"Policy file {policies_file} not found.")
        sys.exit(1)

    with open(policies_file, "r") as f:
        policies = json.load(f)

    for policy in policies:
        subnet = policy["subnet"]
        for rule in policy["ingress"]:
            port = rule["port"]
            proto = rule["protocol"]
            action = rule["action"]

            if action == "allow":
                cmd = f"iptables -A INPUT -s {subnet} -p {proto} --dport {port} -j ACCEPT"
            else:
                cmd = f"iptables -A INPUT -s {subnet} -p {proto} --dport {port} -j DROP"

            run_cmd(cmd)
            log_action("firewall", "applied", f"{subnet} {action} {proto}:{port}")

    log_action("apply-policies", "success", f"Policies applied to {vpc_name}")
    print(f"Firewall policies applied successfully for VPC '{vpc_name}'.")


def delete_vpc(vpc_name):
    bridge_name = f"br-{vpc_name}"
    log_action("delete-vpc", "started", f"Deleting {vpc_name}")

    # Delete namespaces
    ns_list = subprocess.getoutput("ip netns list").splitlines()
    for ns in ns_list:
        if vpc_name in ns:
            run_cmd(f"ip netns delete {ns.split()[0]}")

    # Delete bridge
    run_cmd(f"ip link set {bridge_name} down || true")
    run_cmd(f"ip link delete {bridge_name} type bridge || true")

    # Clean iptables rules related to vpcctl
    run_cmd("iptables -F || true")
    run_cmd("iptables -t nat -F || true")

    # Remove logs directory
    if os.path.exists(LOG_DIR):
        run_cmd(f"rm -rf {LOG_DIR}")

    log_action("delete-vpc", "success", f"{vpc_name} and all components removed")
    print(f"Cleaned up VPC '{vpc_name}' successfully.")


""" CLI Entry Point """

def main():
    parser = argparse.ArgumentParser(description="VPC Simulation CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # create-vpc
    p_create = subparsers.add_parser("create-vpc", help="Create a new VPC")
    p_create.add_argument("name")
    p_create.add_argument("base_cidr")
    p_create.add_argument("--public-interface")

    # add-subnet
    p_add = subparsers.add_parser("add-subnet", help="Add a subnet to VPC")
    p_add.add_argument("vpc_name")
    p_add.add_argument("subnet_name")
    p_add.add_argument("--type", required=True, choices=["public", "private"])
    p_add.add_argument("--base-cidr", required=True)

    # apply-policies
    p_policies = subparsers.add_parser("apply-policies", help="Apply firewall policies")
    p_policies.add_argument("vpc_name")
    p_policies.add_argument("--policies", required=True)

    # delete-vpc
    p_delete = subparsers.add_parser("delete-vpc", help="Delete a VPC and cleanup")
    p_delete.add_argument("vpc_name")

    args = parser.parse_args()

    if args.command == "create-vpc":
        create_vpc(args.name, args.base_cidr, args.public_interface)
    elif args.command == "add-subnet":
        add_subnet(args.vpc_name, args.subnet_name, args.type, args.base_cidr)
    elif args.command == "apply-policies":
        apply_policies(args.vpc_name, args.policies)
    elif args.command == "delete-vpc":
        delete_vpc(args.vpc_name)


if __name__ == "__main__":
    main()
