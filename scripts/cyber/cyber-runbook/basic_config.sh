#!/usr/bin/env bash
set -e

echo "[+] Updating system..."
sudo apt update && sudo apt -y full-upgrade

echo "[+] Installing core tooling..."
sudo apt install -y \
  nmap masscan rustscan \
  netcat-traditional socat curl wget git jq unzip p7zip-full \
  python3 python3-pip python3-venv pipx \
  gobuster ffuf feroxbuster dirsearch \
  sqlmap nikto whatweb wafw00f enum4linux-ng smbclient smbmap \
  ldap-utils nfs-common snmp snmp-mibs-downloader onesixtyone \
  hydra john hashcat hashid hash-identifier \
  responder impacket-scripts evil-winrm freerdp2-x11 rdesktop \
  metasploit-framework exploitdb seclists wordlists \
  bloodhound neo4j crackmapexec \
  wireshark tshark tcpdump burpsuite zaproxy \
  openvpn tmux vim nano rlwrap xclip

echo "[+] Setup complete."