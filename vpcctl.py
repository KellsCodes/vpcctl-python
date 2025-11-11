#!/usr/bin/env python3
import argparse
import subprocess
import json
import ipaddress


def run(cmd):
    """Run shell commands safely."""
    print(f"> {cmd}")
    subprocess.run(cmd, shell=True, check=False)


def create_vpc(args):
    br = f"br-{args.name}"
    print(f"Setting up VPC '{args.name}'...")

    # Idempotent bridge setup
    run(f"sudo ip link show {br} || sudo ip link add name {br} type bridge")
    run(f"sudo ip link set dev {br} up")
    run("sudo sysctl -w net.ipv4.ip_forward=1")

    # NAT (avoid duplicates)
    if args.public_interface:
        run(f"sudo iptables -C POSTROUTING -t nat -s {args.cidr} -o {args.public_interface} -j MASQUERADE || "
            f"sudo iptables -t nat -A POSTROUTING -s {args.cidr} -o {args.public_interface} -j MASQUERADE")
    print(f"VPC '{args.name}' ready.")


def calculate_subnet(base, typ):
    net = ipaddress.IPv4Network(base, strict=False)
    subs = list(net.subnets(new_prefix=24))
    return str(subs[0] if typ == "public" else subs[1])


def add_subnet(args):
    ns, br = f"{args.vpc_name}-{args.subnet_name}", f"br-{args.vpc_name}"
    veth_h, veth_n = f"veth-{args.vpc_name[:3]}-{args.subnet_name[:2]}-h", f"veth-{args.vpc_name[:3]}-{args.subnet_name[:2]}-n"
    cidr = args.cidr or calculate_subnet(args.base_cidr, args.type)

    print(f"Adding {args.type} subnet '{ns}'...")
    run(f"sudo ip netns add {ns} 2>/dev/null || true")
    run(f"sudo ip link del {veth_h} 2>/dev/null || true")
    run(f"sudo ip link add {veth_h} type veth peer name {veth_n}")
    run(f"sudo ip link set {veth_h} master {br} && sudo ip link set {veth_h} up")
    run(f"sudo ip link set {veth_n} netns {ns} && sudo ip netns exec {ns} ip link set {veth_n} up")
    run(f"sudo ip netns exec {ns} ip addr add {cidr} dev {veth_n} || true")

    gw = str(ipaddress.IPv4Network(cidr, strict=False)[1])
    prefix = ipaddress.IPv4Network(cidr, strict=False).prefixlen
    run(f"sudo ip addr add {gw}/{prefix} dev {br} 2>/dev/null || true")
    if args.type == "public":
        run(f"sudo ip netns exec {ns} ip route add default via {gw} || true")
    print(f"Subnet '{ns}' ready with gateway {gw}")


def peer_vpc(args):
    br_a, br_b = f"br-{args.vpc_a}", f"br-{args.vpc_b}"
    veth_a, veth_b = f"veth-{args.vpc_a[:3]}-{args.vpc_b[:3]}", f"veth-{args.vpc_b[:3]}-{args.vpc_a[:3]}"
    print(f"Peering {args.vpc_a} ↔ {args.vpc_b}...")
    run(f"sudo ip link del {veth_a} 2>/dev/null || true")
    run(f"sudo ip link add {veth_a} type veth peer name {veth_b}")
    run(f"sudo ip link set {veth_a} master {br_a} && sudo ip link set {veth_b} master {br_b}")
    run(f"sudo ip link set {veth_a} up && sudo ip link set {veth_b} up")
    print("Peering complete.")


def delete_vpc(args):
    br = f"br-{args.name}"
    print(f"Deleting VPC '{args.name}'...")
    subprocess.run(f"ip netns list | grep {args.name}", shell=True,
                   text=True, capture_output=True).stdout.splitlines()
    run(f"sudo ip link set {br} down || true && sudo ip link del {br} || true")
    if args.public_interface and args.cidr:
        run(
            f"sudo iptables -t nat -D POSTROUTING -s {args.cidr} -o {args.public_interface} -j MASQUERADE || true")
    print(f"Deleted VPC '{args.name}'.")


def main():
    p = argparse.ArgumentParser(description="vpcctl - Mini VPC CLI")
    sp = p.add_subparsers(dest="cmd")

    c = sp.add_parser("create-vpc")
    c.add_argument("name")
    c.add_argument("cidr")
    c.add_argument("--public-interface")
    c.set_defaults(func=create_vpc)
    s = sp.add_parser("add-subnet")
    s.add_argument("vpc_name")
    s.add_argument("subnet_name")
    s.add_argument("--cidr")
    s.add_argument("--base-cidr")
    s.add_argument("--type", choices=["public", "private"], default="private")
    s.set_defaults(func=add_subnet)
    d = sp.add_parser("delete-vpc")
    d.add_argument("name")
    d.add_argument("--public-interface")
    d.add_argument("--cidr")
    d.set_defaults(func=delete_vpc)
    pr = sp.add_parser("peer-vpc")
    pr.add_argument("vpc_a")
    pr.add_argument("vpc_b")
    pr.set_defaults(func=peer_vpc)

    args = p.parse_args()
    if hasattr(args, "func"):
        args.func(args)
    else:
        p.print_help()


if __name__ == "__main__":
    main()
