#!/usr/bin/env python3
import ipaddress
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
        result = subprocess.run(cmd, shell=True, check=True,
                                text=True, capture_output=True)
        log_action("cmd", "success", cmd)
        return result.stdout
    except subprocess.CalledProcessError as e:
        log_action("cmd", "error", f"{cmd} => {e.stderr.strip()}")
        if not ignore_error:
            print(f"Command failed: {cmd}\n{e.stderr.strip()}")
            sys.exit(1)
        return None


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

    # Check if bridge exists
    bridge_check = subprocess.getoutput(f"ip link show {bridge_name}")
    if not bridge_check or "does not exist" in bridge_check:
        print(f"Error: Bridge {bridge_name} does not exist. Create VPC first.")
        sys.exit(1)

    # Extract the first two octets from base_cidr (e.g., "10.20" from "10.20.0.0/16")
    cidr_parts = base_cidr.split('.')
    first_octet = cidr_parts[0]
    second_octet = cidr_parts[1]

    subnet_id = "1" if subnet_type == "public" else "2"
    subnet_cidr = f"{first_octet}.{second_octet}.{subnet_id}.0/24"

    # Create unique interface names using hash to avoid collisions
    import hashlib
    vpc_hash = hashlib.md5(vpc_name.encode()).hexdigest()[:3]
    subnet_hash = hashlib.md5(subnet_name.encode()).hexdigest()[:3]

    veth_host = f"v{vpc_hash}{subnet_hash}h"[:15]
    veth_ns = f"v{vpc_hash}{subnet_hash}n"[:15]

    # Clean up any leftovers
    run_cmd(f"ip link del {veth_host} 2>/dev/null || true", ignore_error=True)
    run_cmd(f"ip netns del {ns_name} 2>/dev/null || true", ignore_error=True)

    run_cmd(f"ip netns add {ns_name}")
    run_cmd(f"ip link add {veth_host} type veth peer name {veth_ns}")

    # Verify veth created
    check = subprocess.getoutput(f"ip link show {veth_ns}")
    if not check or "does not exist" in check:
        print(f"Failed to create veth pair {veth_host}/{veth_ns}")
        sys.exit(1)

    run_cmd(f"ip link set {veth_ns} netns {ns_name}")
    run_cmd(f"ip link set {veth_host} master {bridge_name}")
    run_cmd(f"ip link set {veth_host} up")

    # Assign IP to namespace veth and bring it up (using dynamic base_cidr)
    namespace_ip = f"{first_octet}.{second_octet}.{subnet_id}.2/24"
    gateway_ip = f"{first_octet}.{second_octet}.{subnet_id}.1/24"
    gateway_ip_only = f"{first_octet}.{second_octet}.{subnet_id}.1"

    run_cmd(
        f"ip netns exec {ns_name} ip addr add {namespace_ip} dev {veth_ns}")
    run_cmd(f"ip netns exec {ns_name} ip link set {veth_ns} up")
    run_cmd(f"ip netns exec {ns_name} ip link set lo up")

    # Add gateway IP for this subnet on the bridge (so namespace can reach gateway)
    run_cmd(
        f"ip addr add {gateway_ip} dev {bridge_name} || true", ignore_error=True)

    # Default route for the subnet namespace via the gateway
    run_cmd(
        f"ip netns exec {ns_name} ip route add default via {gateway_ip_only}")

    # Verify the IP was actually assigned
    verify = subprocess.getoutput(
        f"ip netns exec {ns_name} ip addr show {veth_ns}")
    if namespace_ip.split('/')[0] not in verify:
        print(f"ERROR: Failed to assign IP {namespace_ip} to {veth_ns}")
        print(f"Interface state: {verify}")
        sys.exit(1)

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
               f"Subnet {subnet_name} ({subnet_cidr}) added with IP {namespace_ip}")
    print(
        f"✓ Subnet '{subnet_name}' added successfully ({subnet_cidr}) with IP {namespace_ip.split('/')[0]}")


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

    # Create shorter veth names
    veth1 = f"p{vpc1[:3]}{vpc2[:3]}a"[:15]
    veth2 = f"p{vpc1[:3]}{vpc2[:3]}b"[:15]

    # Clean up any existing peering
    run_cmd(f"ip link del {veth1} 2>/dev/null || true", ignore_error=True)

    # Create veth pair to connect the two bridges
    run_cmd(f"ip link add {veth1} type veth peer name {veth2}")
    run_cmd(f"ip link set {veth1} master {br1}")
    run_cmd(f"ip link set {veth2} master {br2}")
    run_cmd(f"ip link set {veth1} up")
    run_cmd(f"ip link set {veth2} up")

    # Enable IP forwarding on both bridges
    run_cmd("sysctl -w net.ipv4.ip_forward=1")

    # Get all namespaces for each VPC
    all_ns = subprocess.getoutput("ip netns list").splitlines()
    ns_list1 = [ns.split()[0] for ns in all_ns if vpc1 in ns]
    ns_list2 = [ns.split()[0] for ns in all_ns if vpc2 in ns]

    if not ns_list1:
        print(f"Error: No namespaces found for VPC '{vpc1}'")
        sys.exit(1)

    if not ns_list2:
        print(f"Error: No namespaces found for VPC '{vpc2}'")
        sys.exit(1)

    def get_ns_subnets(ns):
        """Extract subnet CIDRs from a namespace."""
        subnets = []
        # Use ip -o (one line per record) for easier parsing
        output = subprocess.getoutput(f"ip netns exec {ns} ip -o -4 addr show")

        for line in output.splitlines():
            parts = line.split()
            # Format: "1: lo inet 127.0.0.1/8 ..."
            # or: "2: veth inet 10.10.1.2/24 ..."
            for i, part in enumerate(parts):
                if part == "inet" and i + 1 < len(parts):
                    ip_cidr = parts[i + 1]
                    if not ip_cidr.startswith("127."):
                        try:
                            network = ipaddress.ip_network(
                                ip_cidr, strict=False)
                            subnets.append(str(network))
                        except ValueError:
                            continue
        return subnets

    def get_bridge_gateway(bridge_name):
        """Get the primary gateway IP of a bridge."""
        output = subprocess.getoutput(f"ip addr show {bridge_name}")
        for line in output.splitlines():
            line = line.strip()
            if line.startswith("inet "):
                ip_cidr = line.split()[1]
                gateway_ip = ip_cidr.split('/')[0]
                return gateway_ip
        return None

    # Collect all subnets from both VPCs
    vpc1_subnets = set()
    for ns in ns_list1:
        subnets = get_ns_subnets(ns)
        vpc1_subnets.update(subnets)
        log_action("peer-vpc", "info",
                   f"VPC1 namespace {ns} has subnets: {subnets}")

    vpc2_subnets = set()
    for ns in ns_list2:
        subnets = get_ns_subnets(ns)
        vpc2_subnets.update(subnets)
        log_action("peer-vpc", "info",
                   f"VPC2 namespace {ns} has subnets: {subnets}")

    if not vpc1_subnets:
        log_action("peer-vpc", "error", f"No subnets found in VPC {vpc1}")
        print(
            f"Error: No subnets found in VPC '{vpc1}'. Please add subnets first.")
        sys.exit(1)

    if not vpc2_subnets:
        log_action("peer-vpc", "error", f"No subnets found in VPC {vpc2}")
        print(
            f"Error: No subnets found in VPC '{vpc2}'. Please add subnets first.")
        sys.exit(1)

    # Get bridge gateway IPs
    br1_gateway = get_bridge_gateway(br1)
    br2_gateway = get_bridge_gateway(br2)

    if not br1_gateway or not br2_gateway:
        log_action("peer-vpc", "error", "Failed to get bridge gateway IPs")
        print(f"Error: Could not determine bridge gateway IPs")
        sys.exit(1)

    log_action("peer-vpc", "info",
               f"Bridge gateways: {br1}={br1_gateway}, {br2}={br2_gateway}")

    # Add routes in namespaces to reach remote VPC subnets via their local bridge gateway
    for ns in ns_list1:
        for cidr in vpc2_subnets:
            cmd = f"ip netns exec {ns} ip route add {cidr} via {br1_gateway}"
            run_cmd(cmd, ignore_error=True)
            log_action("peer-vpc-route", "added",
                       f"{ns}: {cidr} via {br1_gateway}")

    for ns in ns_list2:
        for cidr in vpc1_subnets:
            cmd = f"ip netns exec {ns} ip route add {cidr} via {br2_gateway}"
            run_cmd(cmd, ignore_error=True)
            log_action("peer-vpc-route", "added",
                       f"{ns}: {cidr} via {br2_gateway}")

    # Add routes on the host system to route traffic between VPC bridges
    for cidr in vpc2_subnets:
        cmd = f"ip route add {cidr} dev {br1}"
        run_cmd(cmd, ignore_error=True)
        log_action("peer-vpc-host-route", "added", f"{cidr} via {br1}")

    for cidr in vpc1_subnets:
        cmd = f"ip route add {cidr} dev {br2}"
        run_cmd(cmd, ignore_error=True)
        log_action("peer-vpc-host-route", "added", f"{cidr} via {br2}")

    # Enable forwarding between the bridges using iptables
    run_cmd(
        f"iptables -A FORWARD -i {br1} -o {br2} -j ACCEPT || true", ignore_error=True)
    run_cmd(
        f"iptables -A FORWARD -i {br2} -o {br1} -j ACCEPT || true", ignore_error=True)

    log_action("peer-vpc", "success", f"{vpc1} ↔ {vpc2} peered")
    print(f"✓ Peering established between '{vpc1}' and '{vpc2}'")
    print(f"  {vpc1} subnets: {', '.join(sorted(vpc1_subnets))}")
    print(f"  {vpc2} subnets: {', '.join(sorted(vpc2_subnets))}")


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
