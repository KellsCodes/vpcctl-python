# VPC CLI for Network Simulation with Namespace Isolation
This project demonstrates how to simulate Virtual Private Clouds (VPCs) using Linux network namespaces, virtual Ethernet (veth) pairs, and bridges.
Each VPC contains public and private subnets, with routing, NAT, and isolation configured to mimic cloud VPC behavior (similar to AWS VPC).

## Features
* Create multiple isolated VPCs with their own bridges and routing rules.

* Add public and private subnets to each VPC.

* Configure NAT for outbound Internet access via the host’s interface.

* Enable IP forwarding for cross-network communication.

* Automate setup and teardown using a Makefile for testing.

* Easily extend to simulate VPC peering and routing policies.

## Project Structure
```bash
├── Makefile
├── vpcctl.py
├── README.md
├── cleanup.sh
├── policies.json
└── requirements.txt  (optional, not required for system tools)
```

## Prerequisites
Make sure the following are installed on your Linux host:

* Python 3.8+

* iproute2 utilities (ip, ip netns, etc.)

* iptables

* bridge-utils

* make

* sudo privileges

## Usage
You can either run commands directly with vpcctl.py or automate everything using the Makefile.

```bash
sudo apt update
sudo apt install -y iproute2 iptables net-tools
```
**Option 1: Using the Makefile**
To create and test everything automatically:
```bash
make all
```
This will:

1. Create two VPCs (vpc1 and vpc2) with their bridges.

2. Add public and private subnets to each.

3. Enable NAT for Internet-bound traffic.

4. Test VPCs isolation

5. Peer the VPCs and test peering

6. Display the final namespace and route configurations.

To clean up everything:
```bash
make cleanup
```

**Option 2: Using Python Script Directly**
You can also run individual operations with Python:
1. Create a new VPC
```bash
sudo python3 vpcctl.py create-vpc vpc1 10.10.0.0/16 --public-interface <wlp2s0> (use your network interface here e.g eth0 )
```
2. Add a public subnet
```bash
sudo python3 vpcctl.py add-subnet vpc1 public --type public --base-cidr 10.10.0.0/16
```
3. Add a private subnet
```bash
sudo python3 vpcctl.py add-subnet vpc1 private --type private --base-cidr 10.10.0.0/16
```
4. View network namespaces
```bash
ip netns list
```
5. Check routes inside a subnet
```bash
sudo ip netns exec vpc1-public ip route
```
6. Delete a VPC
```bash
sudo python3 vpcctl.py delete-vpc vpc1
```

### Testing & Verification
After running make all, verify the following:
1. Namespace Check
```bash
ip netns list
```
You should see something like:
```bash
vpc1-public
vpc1-private
vpc2-public
vpc2-private
```
2. Routing Check
```bash
sudo ip netns exec vpc1-private ip route
```
You should see:
```bash
default via 10.10.0.1 dev veth-private
10.10.0.0/24 dev veth-private proto kernel scope link src 10.10.0.2
```
3. Ping Test (Public ↔ Private)
```bash
sudo ip netns exec vpc1-public ping -c 2 10.10.0.2
```
4. Internet Connectivity (via NAT)
```bash
sudo ip netns exec vpc1-public ping -c 2 8.8.8.8
```
*(works only if host Internet and NAT are active)*

### Makefile Commands Overview
| Command               | Description                                              |
| --------------------- | -------------------------------------------------------- |
| `make all`            | Builds and tests all VPCs with subnets.                  |
| `make create-vpcs`    | Creates VPC1 and VPC2.                                   |
| `make add-subnets`    | Adds public and private subnets to VPC1 and VPC2            |
| `make peer-vpcs`      | Peers VPC1 and VPC2 to allow communication between them. |
| `make test-peering`   | Test communication between VPC1 and VPC2                 |
| `make test-isolation` | Test communication of subnets on thesame VPC             |
| `make test-internet`  | Test NAT on public subnet and restriction on private subnet |
| `make apply-policies` | Applies firewall policies on policies.json               |
| `make test-policies`  | Test if firewall policies works on the target VPC        |
| `make verify`         | Verifies the VPCs namespaces, bridges, routes            |
| `make cleanup`        | Removes all VPC namespaces, bridges, and iptables rules. |

**Example Output (abridged)**
```bash
Creating VPC 'vpc2' with bridge 'br-vpc2'...
IP forwarding enabled.
NAT configured for outbound traffic via wlp2s0
Bridge 'br-vpc2' created and ready.
Adding public and private subnets to vpc2...
Subnet vpc2-public added with IP 10.20.0.1/24
Subnet vpc2-private added with IP 10.20.1.1/24
VPC2 setup complete.
```

### Cleanup
To delete all configurations and restore your host networking:
```bash
make cleanup
```
This removes:

* All network namespaces (ip netns delete)

* All VPC bridges

* Related veth pairs

* NAT and iptables rules

**Notes**

* The project uses hardcoded CIDRs on the Makefile (10.10.0.0/16, 10.20.0.0/16, etc.) for testing and clarity.
These can be customized in the Makefile or passed as CLI arguments.

* Works best on Ubuntu/Debian-based systems with systemd networking.

* Run all commands with sudo for full permissions.

Article link: https://dev.to/ifeanyi_nworji/building-and-testing-a-mini-vpc-with-python-and-linux-namespaces-5cg9
**Author**

**Ifeanyi Nworji**

DevOps Intern | Cloud & Infrastructure Enthusiast