# Game server setup + tuning

Moved out of the stack-root `CLAUDE.md` on 2026-07-27 to keep the always-loaded context small. **Required settings for any new or rebuilt game host.** The fleet facts needed mid-task stayed in `CLAUDE.md`: CPU core placement, the server/IP table, the paramiko SSH pattern, `.new` auto-swap, and the crash-core location.

### UDP Buffer Configuration (Required)
Game servers generate heavy UDP traffic. Default Linux buffer sizes cause packet drops, resulting in lag and hit registration issues.

**Check for UDP errors:**
```bash
cat /proc/net/snmp | grep "Udp:" | tail -1
# Look at column 5 (RcvbufErrors; column 6 is SndbufErrors) - should be 0 or not climbing
```

**Check current buffer sizes:**
```bash
sysctl net.core.rmem_max net.core.rmem_default net.core.wmem_max net.core.wmem_default
# Default 212992 (208KB) is too small for multiple game servers
```

**Apply fix:**
```bash
# Edit sysctl.conf
sudo nano /etc/sysctl.conf

# Add these lines:
# KTP Game Server UDP buffers
net.core.rmem_max=26214400
net.core.rmem_default=26214400
net.core.wmem_max=26214400
net.core.wmem_default=26214400

# Apply changes
sudo sysctl -p

# Verify
sysctl net.core.rmem_max  # Should show 26214400 (25MB)
```

### Game Server Performance Tuning (Required)
Critical kernel and network settings for competitive game server performance. Applied to all servers 2026-04-13.

```bash
# Add to /etc/sysctl.conf:

# Disable RT throttling — SCHED_FIFO servers must never be descheduled
kernel.sched_rt_runtime_us = -1
# Prevent timer migration to isolated game CPUs
kernel.timer_migration = 0
# Disable scheduler autogroup
kernel.sched_autogroup_enabled = 0
# Only swap under extreme memory pressure
vm.swappiness = 1
# Reduce vmstat IPI frequency on isolated CPUs
vm.stat_interval = 120
# Increase NAPI budget for faster packet drain
net.core.netdev_budget = 1200
net.core.netdev_budget_usecs = 8000
# Disable unnecessary per-packet timestamping
net.core.netdev_tstamp_prequeue = 0
# No soft-lockup watchdog timers on isolated game cores (added 2026-07-02)
kernel.watchdog = 0
```

```bash
# Disable transparent hugepages (khugepaged compaction stalls; HLDS gets no THP benefit).
# Applied 2026-07-02 fleet-wide; persisted via tmpfiles.d:
echo 'w /sys/kernel/mm/transparent_hugepage/enabled - - - - never' > /etc/tmpfiles.d/ktp-thp.conf
echo never > /sys/kernel/mm/transparent_hugepage/enabled
```

**SMI check (2026-07-02):** MSR 0x34 via msr-tools (now installed fleet-wide as root). Baremetal SMI rates are benign — ATL/DAL/NYC ~0.4/hr, Denver ~0.9/hr, no active storms. SMIs ruled out as a hitreg/hiccup source on baremetals. Chicago (KVM) reports ~29/hr lifetime — guest-visible only, not actionable on a VPS. Re-check after any BIOS/firmware change: `rdmsr -p 0 0x34` twice, 60s apart.

```bash
# Disable thermald (conflicts with performance governor)
sudo systemctl disable --now thermald

# Bypass conntrack for game traffic — add to /etc/ufw/before.rules (before *filter):
# *raw
# :PREROUTING ACCEPT [0:0]
# :OUTPUT ACCEPT [0:0]
# -A PREROUTING -p udp --dport 27015:27019 -j NOTRACK
# -A OUTPUT -p udp --sport 27015:27019 -j NOTRACK
# COMMIT
```

### NTP Time Sync (Required)
Use chrony instead of systemd-timesyncd. Chrony properly sets the kernel synchronization flag that Netdata monitors, preventing false clock sync alerts.

```bash
# Install chrony (removes systemd-timesyncd automatically)
sudo apt install -y chrony

# Verify running and synchronized
systemctl status chrony
chronyc tracking  # "Leap status: Normal" = good
```

### RTC Timezone Configuration (Required)
The hardware clock (RTC) must use UTC, not local time. Local RTC causes Netdata clock sync warnings.

```bash
# Check current setting
timedatectl | grep "RTC in local TZ"
# Should show: RTC in local TZ: no

# Fix if needed
sudo timedatectl set-local-rtc 0

# Verify
timedatectl status
```

### Swap Configuration (Recommended)
Servers without swap risk OOM kills under memory pressure. Add a small swap file as safety net:
```bash
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

### Firewall Configuration (UFW)
Enable UFW with rules for game servers:
```bash
sudo ufw allow 22/tcp comment "SSH"
sudo ufw allow 27015:27019/udp comment "DoD Game Servers"
sudo ufw allow 27015:27019/tcp comment "DoD RCON"
sudo ufw allow 19999/tcp comment "Netdata"
sudo ufw allow 8087/tcp comment "HLTV API"
sudo ufw --force enable
sudo ufw status
```

### Netdata Monitoring (DISABLED fleet-wide 2026-07-02)
Netdata is stopped + disabled on all five game hosts and the data server. Operator preference: query Claude directly for performance checks instead. Reason: on Atlanta, `go.d.plugin` was burning ~48% of housekeeping cpu1 (HT sibling of instance 27016's core) re-enumerating ~2,900 leaked logind sessions — jitter source for 27016/27017.

- Nodes are still claimed in Netdata Cloud (https://app.netdata.cloud) and will show as unreachable there; a one-time "node unreachable" Discord alert per node may fire.
- Re-enable on any host with `systemctl enable --now netdata` (as root).
- Data server Netdata was already stopped/unclaimed 2026-02-17.
