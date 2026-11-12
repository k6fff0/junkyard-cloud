# Step 2: the machine

## 1. Ubuntu Server (the owner does this part, you guide)

Use the current Ubuntu Server LTS. Give the owner these steps in their language:

1. On another computer, download Ubuntu Server LTS from ubuntu.com and write it to a USB stick (8 GB+) with
   balenaEtcher or Rufus.
2. In the old PC's BIOS: boot from USB; if offered, set "Restore on AC power loss" to "Power On" (the server
   comes back after a power cut). Turn off Secure Boot only if the stick will not boot.
3. Install: language English (logs and help are easier to find), the whole **system** disk, "Use LVM" on
   (default), the OpenSSH server **on**, no extra snaps. Note the username and password.
4. Keep it on a cable (not Wi-Fi). In the home router, reserve its IP address (DHCP reservation by MAC) so it
   never changes. Tell you the address.

Then you connect with `ssh user@address`.

## 2. Keys, not passwords

From the computer you work on: `ssh-copy-id user@address` (or append your public key to `~/.ssh/authorized_keys`).
Check you can log in with the key **before** turning passwords off.

Every SSH or firewall change is made with an undo timer, and the timer is stopped only after a new login works:

```
sudo cp /etc/ssh/sshd_config.d/00-junkyard.conf /root/00-junkyard.conf.bak 2>/dev/null || true
sudo systemd-run --on-active=180 --unit=jc-undo /bin/sh -c \
  'rm -f /etc/ssh/sshd_config.d/00-junkyard.conf; cp /root/00-junkyard.conf.bak /etc/ssh/sshd_config.d/ 2>/dev/null; ufw disable; systemctl restart ssh'
printf 'PasswordAuthentication no\nKbdInteractiveAuthentication no\nPermitRootLogin prohibit-password\n' | \
  sudo tee /etc/ssh/sshd_config.d/00-junkyard.conf
sudo sshd -t && sudo systemctl restart ssh
sudo sshd -T | grep -Ei '^(passwordauthentication|kbdinteractiveauthentication|permitrootlogin) '
# must print: passwordauthentication no / kbdinteractiveauthentication no / permitrootlogin without-password
# now, from a NEW terminal: ssh user@address  -> works?  then:
sudo systemctl stop jc-undo.timer; sudo rm -f /root/00-junkyard.conf.bak
```

The file is named `00-...` on purpose: sshd keeps the **first** value it reads, and Ubuntu often ships
`50-cloud-init.conf` with `PasswordAuthentication yes`, which would win over a later name (it did: the hardening
looked done and passwords still worked). Never report this step done without the `sshd -T` lines above.

If the new login fails, wait three minutes: the old settings come back by themselves.

## 3. Firewall

```
sudo systemd-run --on-active=180 --unit=jc-undo /usr/sbin/ufw disable
sudo ufw default deny incoming && sudo ufw default allow outgoing
sudo ufw allow from <LAN subnet, e.g. 192.168.1.0/24> to any port 22 proto tcp
sudo ufw allow from 172.16.0.0/12 to any port 22 proto tcp     # the assistant's locked SSH key (jc-ops)
sudo ufw --force enable
# new login works?  sudo systemctl stop jc-undo.timer
```

No port is opened to the internet: the tunnel connects outwards. Remember that Docker's published ports skip
`ufw`, which is why every compose file here binds to `127.0.0.1` or `172.17.0.1` only.

## 4. Updates, time, basics

```
sudo apt-get update && sudo apt-get -y full-upgrade
sudo apt-get -y install unattended-upgrades rsync restic sqlite3 jq curl gnupg python3 htop
sudo dpkg-reconfigure -f noninteractive unattended-upgrades
sudo timedatectl set-timezone <tz from the config>
[ -f /var/run/reboot-required ] && echo "REBOOT NEEDED"    # a new kernel: reboot now, before Docker
```

If it printed `REBOOT NEEDED`, `sudo reboot`, wait, log in again, then go on.

## 5. Docker (official repository)

The commands of the official guide (docs.docker.com/engine/install/ubuntu, "apt repository"); if they fail,
for example on a Ubuntu release newer than the repository, read the current guide:

```
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list
sudo apt-get update
sudo apt-get -y install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker <user>
echo '{"log-driver":"json-file","log-opts":{"max-size":"10m","max-file":"3"}}' | sudo tee /etc/docker/daemon.json
sudo systemctl restart docker
docker version && docker compose version
```

Docker must wait for the LAN address after a reboot, or containers that bind to an address fail to start (it
happened: see `lessons.md`):

```
sudo mkdir -p /etc/systemd/system/docker.service.d
printf '[Unit]\nAfter=network-online.target\nWants=network-online.target\n[Service]\nExecStartPre=/bin/sh -c "for i in $(seq 1 90); do ip -4 addr show scope global | grep -q inet && exit 0; sleep 1; done; exit 0"\n' \
  | sudo tee /etc/systemd/system/docker.service.d/wait-lan.conf
sudo systemctl daemon-reload
```

## 6. The data disk

Data (photos, documents, downloads, backups) lives on the big disk, mounted at `/mnt/storage`. If the second
disk is empty, format it ext4 **after the owner says yes** and you showed them the disk's size and model:

```
lsblk -o NAME,SIZE,MODEL,FSTYPE,MOUNTPOINT     # show this to the owner first
# an empty disk (no partition under it) gets one partition first; sdX = the disk the owner said yes to
sudo wipefs -n /dev/sdX                        # must list nothing: anything listed means data, stop and ask
printf 'label: gpt\n,,L\n' | sudo sfdisk /dev/sdX
sudo mkfs.ext4 -L storage /dev/sdX1            # on NVMe the partition is /dev/nvme1n1p1
sudo mkdir -p /mnt/storage
echo "UUID=$(sudo blkid -s UUID -o value /dev/sdX1) /mnt/storage ext4 defaults,noatime,nofail 0 2" | sudo tee -a /etc/fstab
sudo systemctl daemon-reload && sudo mount -a && df -h /mnt/storage
```

If it already has data, mount it as it is and never format it. With a single disk, use `/srv/storage` on the
system disk and tell the owner plainly that a disk failure would take everything except the off-site copy.

The data disk must hold the data, the nightly copies and the system image of `backups.md` (about as much as the
system disk uses without Docker's images). Show the owner the sum before the services go in.

## 6b. Swap (always)

Ubuntu cloud and minimal installs have no swap. Without it, a machine near its memory limit does not slow down,
it falls over: in a test on 4.8 GB, a link being read pushed n8n off its database and the owner's message got no
answer at all. Make a swap file of 4 GB (2 GB on machines with 16 GB and more), named `/swap.img` like
Ubuntu's own (the system image skips every active swap file anyway):

```
swapon --show                                   # already has swap? skip this
sudo fallocate -l 4G /swap.img && sudo chmod 600 /swap.img
sudo mkswap /swap.img && sudo swapon /swap.img
echo '/swap.img none swap sw 0 0' | sudo tee -a /etc/fstab
free -h
```

Swap keeps a short peak alive; it does not replace memory. If the chosen services need more than the machine
has (the table in `interview.md`), say so before installing them, and offer fewer services.

## 7. Folders

```
sudo install -d -m 755 /opt/junkyard           # one folder per service: /opt/junkyard/<service>
sudo install -d -m 700 /etc/junkyard           # config.json, secrets.json, notify-secret
sudo install -d -m 755 /mnt/storage/backups /mnt/storage/backups/status
```

Clone this repository to `/opt/junkyard/src` (read only for the services; you copy templates out of it).
