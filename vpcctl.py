#!/usr/bin/env python3
import os
import sys
import json
import subprocess
import argparse
from datetime import datetime

LOG_DIR = "logs"
LOG_FILE = os.path.join(LOG_DIR, "vpcctl.log")


def log_action(action, status="success", details=""):
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
                f"ACTION={action} STATUS={status} DETAILS={details}\n")


def run_cmd(cmd, ignore_error=False):
    try:
        subprocess.run(cmd, shell=True, check=True,
                       text=True, capture_output=True)
        log_action("cmd", "success", cmd)
    except subprocess.CalledProcessError as e:
        log_action("cmd", "error", f"{cmd} => {e.stderr.strip()}")
        if not ignore_error:
            print(f"Command failed: {cmd}\n{e.stderr.strip()}")
            sys.exit(1)


def create_vpc(name, base_cidr, public_iface=None):
    bridge_name = f"br-{name}"
    log_action("create-vpc", "started", f"Creating VPC {name} ({base_cidr})")

    run_cmd(f"ip link add name {bridge_name} type bridge || true")
    run_cmd(f"ip addr flush dev {bridge_name} || true")
    run_cmd(
        f"ip addr add {base_cidr.split('.')[0]}.{base_cidr.split('.')[1]}.0.1/16 dev {bridge_name}")
    run_cmd(f"ip link set {bridge_name} up")

    # Save public interface metadata so add_subnet can apply NAT only for public subnets
    os.makedirs(LOG_DIR, exist_ok=True)
    meta_file = os.path.join(LOG_DIR, f"{name}.meta")
    meta = {"public_interface": public_iface} if public_iface else {}
    with open(meta_file, "w") as mf:
        json.dump(meta, mf)

    log_action("create-vpc", "success", f"Bridge {bridge_name} created")
    print(f"VPC '{name}' created successfully.")


def add_subnet(vpc_name, subnet_name, subnet_type, base_cidr):
    ns_name = f"{vpc_name}-{subnet_name}"
    bridge_name = f"br-{vpc_name}"

    log_action("add-subnet", "started",
               f"Adding {subnet_type} subnet {subnet_name}")

    subnet_id = "1" if subnet_type == "public" else "2"
    subnet_cidr = f"{base_cidr.split('.')[0]}.{base_cidr.split('.')[1]}.{subnet_id}.0/24"

    # Shorter interface names (max 15 chars)
    veth_host = f"v{vpc_name[:2]}{subnet_name[:2]}h"
    veth_ns = f"v{vpc_name[:2]}{subnet_name[:2]}n"

    # Clean up any leftovers
    run_cmd(f"ip link del {veth_host} 2>/dev/null || true", ignore_error=True)

    run_cmd(f"ip netns add {ns_name}")
    run_cmd(f"ip link add {veth_host} type veth peer name {veth_ns}")

    # Verify veth created
    check = subprocess.getoutput(f"ip link show {veth_ns}")
    if not check:
        print(f"Failed to create veth pair {veth_host}/{veth_ns}")
        sys.exit(1)

    run_cmd(f"ip link set {veth_ns} netns {ns_name}")
    run_cmd(f"ip link set {veth_host} master {bridge_name}")
    run_cmd(f"ip link set {veth_host} up")

    # Assign IP to namespace veth and bring it up
    run_cmd(
        f"ip netns exec {ns_name} ip addr add 10.10.{subnet_id}.2/24 dev {veth_ns}")
    run_cmd(f"ip netns exec {ns_name} ip link set {veth_ns} up")

    # Add gateway IP for this subnet on the bridge (so namespace can reach gateway)
    run_cmd(f"ip addr add 10.10.{subnet_id}.1/24 dev {bridge_name} || true")

    # Default route for the subnet namespace via the gateway
    run_cmd(
        f"ip netns exec {ns_name} ip route add default via 10.10.{subnet_id}.1")

    # 🔒 Apply NAT only for public subnets (read public interface from meta file)
    meta_file = os.path.join(LOG_DIR, f"{vpc_name}.meta")
    public_iface = None
    if os.path.exists(meta_file):
        try:
            with open(meta_file, "r") as mf:
                meta = json.load(mf)
                public_iface = meta.get("public_interface")
        except Exception:
            public_iface = None

    if subnet_type == "public" and public_iface:
        # Use iptables -C ... || -A ... so duplicate rules aren't added
        cmd = (
            f"iptables -t nat -C POSTROUTING -s {subnet_cidr} -o {public_iface} -j MASQUERADE "
            f"|| iptables -t nat -A POSTROUTING -s {subnet_cidr} -o {public_iface} -j MASQUERADE"
        )
        run_cmd(cmd, ignore_error=True)
        log_action("nat", "applied", f"{subnet_cidr} -> {public_iface}")
    else:
        log_action("nat", "skipped",
                   f"{subnet_name} (public_iface={public_iface})")

    log_action("add-subnet", "success",
               f"Subnet {subnet_name} ({subnet_cidr}) added")
    print(f"Subnet '{subnet_name}' added successfully ({subnet_cidr}).")


def apply_policies(vpc_name, policies_file):
    log_action("apply-policies", "started",
               f"Applying policies from {policies_file}")

    if not os.path.exists(policies_file):
        log_action("apply-policies", "error", f"{policies_file} not found")
        print(f"Policy file {policies_file} not found.")
        sys.exit(1)

    with open(policies_file, "r") as f:
        policies = json.load(f)

    for policy in policies:
        subnet = policy["subnet"]
        for rule in policy["ingress"]:
            port, proto, action = rule["port"], rule["protocol"], rule["action"]
            target = "ACCEPT" if action == "allow" else "DROP"
            cmd = f"iptables -A INPUT -s {subnet} -p {proto} --dport {port} -j {target}"
            run_cmd(cmd)
            log_action("firewall", "applied",
                       f"{subnet} {action} {proto}:{port}")

    log_action("apply-policies", "success", f"Policies applied to {vpc_name}")
    print(f"Firewall policies applied successfully for VPC '{vpc_name}'.")


def peer_vpcs(vpc1, vpc2):
    """Create a VPC peering connection between two bridges."""
    log_action("peer-vpc", "started", f"Peering {vpc1} ↔ {vpc2}")

    br1 = f"br-{vpc1}"
    br2 = f"br-{vpc2}"

    veth1 = f"peer-{vpc1[:2]}-{vpc2[:2]}a"
    veth2 = f"peer-{vpc1[:2]}-{vpc2[:2]}b"

    # Clean up any leftovers
    run_cmd(f"ip link del {veth1} 2>/dev/null || true", ignore_error=True)

    # Create the veth pair connecting both bridges
    run_cmd(f"ip link add {veth1} type veth peer name {veth2}")
    run_cmd(f"ip link set {veth1} master {br1}")
    run_cmd(f"ip link set {veth2} master {br2}")

    # Assign link-local IPs for routing between VPCs
    run_cmd(
        f"ip addr add 169.254.{hash(vpc1) % 250}.{hash(vpc2) % 250}/30 dev {veth1}")
    run_cmd(
        f"ip addr add 169.254.{hash(vpc2) % 250}.{hash(vpc1) % 250}/30 dev {veth2}")

    run_cmd(f"ip link set {veth1} up")
    run_cmd(f"ip link set {veth2} up")

    log_action("peer-vpc", "success", f"{vpc1} ↔ {vpc2} connected")
    print(f"Peering established between {vpc1} and {vpc2}.")


def delete_vpc(vpc_name):
    bridge_name = f"br-{vpc_name}"
    log_action("delete-vpc", "started", f"Deleting {vpc_name}")

    ns_list = subprocess.getoutput("ip netns list").splitlines()
    for ns in ns_list:
        if vpc_name in ns:
            run_cmd(f"ip netns delete {ns.split()[0]}")

    run_cmd(f"ip link set {bridge_name} down || true", ignore_error=True)
    run_cmd(
        f"ip link delete {bridge_name} type bridge || true", ignore_error=True)
    run_cmd("iptables -F || true", ignore_error=True)
    run_cmd("iptables -t nat -F || true", ignore_error=True)

    if os.path.exists(LOG_DIR):
        run_cmd(f"rm -rf {LOG_DIR}", ignore_error=True)

    log_action("delete-vpc", "success", f"{vpc_name} removed")
    print(f"VPC '{vpc_name}' cleaned up successfully.")


def main():
    parser = argparse.ArgumentParser(description="VPC Simulation CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_create = subparsers.add_parser("create-vpc")
    p_create.add_argument("name")
    p_create.add_argument("base_cidr")
    p_create.add_argument("--public-interface")

    p_add = subparsers.add_parser("add-subnet")
    p_add.add_argument("vpc_name")
    p_add.add_argument("subnet_name")
    p_add.add_argument("--type", required=True, choices=["public", "private"])
    p_add.add_argument("--base-cidr", required=True)

    p_policies = subparsers.add_parser("apply-policies")
    p_policies.add_argument("vpc_name")
    p_policies.add_argument("--policies", required=True)

    p_peer = subparsers.add_parser("peer-vpc")
    p_peer.add_argument("vpc1")
    p_peer.add_argument("vpc2")

    p_delete = subparsers.add_parser("delete-vpc")
    p_delete.add_argument("vpc_name")

    args = parser.parse_args()

    if args.command == "create-vpc":
        create_vpc(args.name, args.base_cidr, args.public_interface)
    elif args.command == "add-subnet":
        add_subnet(args.vpc_name, args.subnet_name, args.type, args.base_cidr)
    elif args.command == "apply-policies":
        apply_policies(args.vpc_name, args.policies)
    elif args.command == "peer-vpc":
        peer_vpcs(args.vpc1, args.vpc2)
    elif args.command == "delete-vpc":
        delete_vpc(args.vpc_name)


if __name__ == "__main__":
    main()
