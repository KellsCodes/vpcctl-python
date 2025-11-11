#!/usr/bin/env python3

import argparse

def create_vpc(args):
    print(f"Creating VPC '{args.name}' with CIDR '{args.cidr}'...")

def delete_vpc(args):
    print(f"Deleting VPC '{args.name}'...")

def add_subnet(args):
    print(f"Adding subnet '{args.subnet_name}' to VPC '{args.vpc_name}' with CIDR '{args.cidr}'...")

def main():
    parser = argparse.ArgumentParser(description="vpcctl - Virtual Private Cloud CLI")

    subparsers = parser.add_subparsers(title="Commands", dest="command")

    # create-vpc
    parser_create = subparsers.add_parser("create-vpc", help="Create a new VPC")
    parser_create.add_argument("name", help="VPC name")
    parser_create.add_argument("cidr", help="VPC CIDR block")
    parser_create.set_defaults(func=create_vpc)

    # delete-vpc
    parser_delete = subparsers.add_parser("delete-vpc", help="Delete a VPC")
    parser_delete.add_argument("name", help="VPC name")
    parser_delete.set_defaults(func=delete_vpc)

    # add-subnet
    parser_subnet = subparsers.add_parser("add-subnet", help="Add a subnet to a VPC")
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
