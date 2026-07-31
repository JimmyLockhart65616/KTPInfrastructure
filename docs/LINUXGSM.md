# LinuxGSM multi-instance setup + known bugs

Moved out of the stack-root `CLAUDE.md` on 2026-07-27. Consulted when building, cloning or repairing a host, not during normal work.

> ⚠️ The **"old type tmux session" detection bug** below causes random server restarts DURING MATCHES and must be patched on every host before the monitor cron is enabled. `provision/clone-ktp-stack.sh` applies it for new hosts, and it **must be re-applied after any `./dodserver update-lgsm`**.

### Directory Structure
Each port gets its own directory with LinuxGSM installation:
```
~/dod-27015/  (dodserver executable - instance 1)
~/dod-27016/  (dodserver2 executable - instance 2)
~/dod-27017/  (dodserver3 executable - instance 3)
~/dod-27018/  (dodserver4 executable - instance 4)
~/dod-27019/  (dodserver5 executable - instance 5)
```

### Config Hierarchy (Critical!)
LinuxGSM loads configs in this order (later files override earlier):
1. `lgsm/config-lgsm/dodserver/_default.cfg` - Template defaults (DO NOT MODIFY - gets reset)
2. `lgsm/config-lgsm/dodserver/common.cfg` - Common settings for all instances
3. `lgsm/config-lgsm/dodserver/dodserver.cfg` - Base server settings
4. `lgsm/config-lgsm/dodserver/dodserver2.cfg` - Instance-specific overrides

**Important**: Instance configs (dodserver2.cfg, etc.) must be in the `dodserver/` folder, NOT in a separate `dodserver2/` folder!

### Default Server Settings
When deploying new servers, use these settings in `common.cfg`:
```
defaultmap="dod_anzio"
```

### Cloning a Server
To clone from an existing server (e.g., Atlanta to Dallas):
```bash
# On source server, create tarball of full installation
cd ~ && tar -czvf dod-full.tar.gz dod-27015/

# Copy to destination
scp dod-full.tar.gz dodserver@<dest-ip>:~/

# On destination, extract and create copies for each port
tar -xzf dod-full.tar.gz
for port in 27016 27017 27018 27019; do
  cp -r dod-27015 dod-$port
done

# Update instance configs for each port
for port in 27016 27017 27018 27019; do
  n=$((port - 27014))
  mv ~/dod-$port/dodserver ~/dod-$port/dodserver$n
  # Create instance config with correct port/IP
  # CRITICAL: ip= must be set or LinuxGSM monitors 127.0.0.1 and falsely restarts servers!
  cat > ~/dod-$port/lgsm/config-lgsm/dodserver/dodserver$n.cfg << EOF
port="$port"
clientport="$((port - 10))"
ip="<SERVER_IP>"
startparameters="-game dod -strictportbind +ip \${ip} -port \${port} +clientport \${clientport} +map \${defaultmap} +servercfgfile \${servercfg} -maxplayers 13 -pingboost 2"
servercfg="dodserver.cfg"
EOF
done
```

### LinuxGSM Tmux Session Fix
LinuxGSM monitor cron can cause random server restarts if it detects "old type tmux session" format.

**Symptoms:**
- Servers randomly restart during matches
- Monitor log shows: `ERROR: Checking session: PIDS with old type tmux session are running`
- Console logs show `quit` command with no RCON source

**Diagnosis:**
```bash
grep -i 'old type\|error' ~/log/monitor.log | tail -20
```

**Fix:**
Restart all servers to recreate tmux sessions in current format:
```bash
# Dallas (74.91.126.55)
for s in dodserver dodserver2 dodserver3 dodserver4 dodserver5; do
  ~/dod-2701$((${s#dodserver} + 4 - ${s#dodserver}))/$s stop
done
sleep 5
for s in dodserver dodserver2 dodserver3 dodserver4 dodserver5; do
  ~/dod-2701$((${s#dodserver} + 4 - ${s#dodserver}))/$s start
done

# Or use the restart-all-servers.sh script:
~/restart-all-servers.sh
```

**Verify fix:**
After next monitor cycle (~1 minute), check log for all `OK` status:
```bash
tail -20 ~/log/monitor.log | grep -E 'Checking session'
# Should show [  OK  ] for all servers, no ERROR
```

### LinuxGSM "Old Type" Detection Bug - HIGH PRIORITY (Patched 2026-01-12)

**CRITICAL:** This bug causes random server restarts during matches. Must be patched on ALL servers BEFORE enabling monitor cron.

**Automation:** This fix is automatically applied by `KTPInfrastructure/provision/clone-ktp-stack.sh` during new deployments.

LinuxGSM has a bug in `command_monitor.sh` where the "old type tmux session" detection uses substring matching that incorrectly matches NEW-style sessions.

**The bug:** The detection pattern `tmux new-session -d -x ... -s sessionname` matches both:
- Old format: `tmux new-session -d -x 80 -y 23 -s dodserver`
- New format: `tmux -L dodserver-xxx new-session -d -x 80 -y 23 -s dodserver`

Because `pgrep -f` does substring matching, new-style sessions are falsely detected as "old type" and killed.

**Fix applied:** Comment out lines 203-212 in `~/dod-*/lgsm/modules/command_monitor.sh`:
```bash
# Apply to all server instances:
for dir in dod-27015 dod-27016 dod-27017 dod-27018 dod-27019; do
  sed -i '203,212s/^/# KTP-DISABLED: /' ~/$dir/lgsm/modules/command_monitor.sh
done
```

**IMPORTANT:** This patch must be reapplied after any `./dodserver update-lgsm` command, as LinuxGSM overwrites the modules. Always verify the patch is in place before enabling monitor cron on a new or updated server.

> 🔴 **The line range above is version-specific and WILL break a newer LinuxGSM. Never apply it without the `bash -n` gate below.**
>
> `203,212` was correct for the LinuxGSM shipped in January 2026. On **v26.2.0** the same range lands one block earlier and swallows the opening `if` of the duplicate-PID check, orphaning the `elif` that follows it. The result is a `command_monitor.sh` that **fails to parse**:
>
> ```
> command_monitor.sh: line 214: syntax error near unexpected token `elif'
> MONITOR: ERROR: Command did not exit correctly: monitor
> MONITOR: ERROR: core_exit.sh exiting with code: 2
> ```
>
> Monitor then does nothing at all — every minute, forever. It does not restart a dead server, and because the cron redirects to `/dev/null` it is **completely silent**. The only outward symptom is a crashed instance that stays down.
>
> **This happened.** The Philly LAN box was provisioned 2026-07-22 on v26.2.0 and ran with a dead monitor for nine days. On 2026-07-31 instance 27016 segfaulted mid-event and sat down for ~3 hours; monitor had fired ~180 times in that window and never once acted. The 24-instance production fleet was patched against the older LinuxGSM and is **unaffected** — verified `bash -n` clean on all 24 the same day.
>
> Note the range also disables the *wrong* block on v26.2.0: it hits the duplicate-PID check, while the "old type tmux" check this patch exists to neutralise sits further down and is left live. (It happens not to fire, because our sockets carry a hash — `tmux -L dodserver3-4c129d63` — which defeats its `pgrep` pattern.)

**Mandatory verification — a patched monitor that cannot parse is worse than an unpatched one.** Always run this after patching, after `update-lgsm`, and on any new host before enabling the monitor cron:

```bash
# 1. Does it still parse?  ANY failure here means the patch landed wrong.
for d in ~/dod-2701*; do
  f="$d/lgsm/modules/command_monitor.sh"
  bash -n "$f" 2>/dev/null && echo "OK      $(basename $d)" || echo "BROKEN  $(basename $d)"
done

# 2. Does monitor actually run?  Expect "Checking session ... OK", not an error.
~/dod-27015/dodserver monitor
```

If step 1 reports `BROKEN`, find the orphaned `elif` and restore it to `if` (do **not** re-comment more lines):

```bash
grep -n 'KTP-DISABLED' ~/dod-27015/lgsm/modules/command_monitor.sh | tail -1   # last disabled line
# the first live `elif` AFTER that line must be an `if` -- fix just that token:
sed -i '<N>s/^\([[:space:]]*\)elif /\1if /' ~/dod-27015/lgsm/modules/command_monitor.sh
bash -n ~/dod-27015/lgsm/modules/command_monitor.sh && echo repaired
```

The line is tab-indented — anchoring `elif` to column 0 matches nothing and the `sed` silently no-ops.

**Servers patched:** Atlanta Baremetal (74.91.121.9), Dallas (74.91.126.55), Denver (66.163.114.109), New York (74.91.123.64), Chicago (172.238.176.101) - All 5 instances each.

### LinuxGSM Lockfile Fix (After Cloning/Migration)
When cloning a server or migrating to new hardware, LinuxGSM may report "No lockfile found" errors if the `-monitoring.lock` files don't exist.

**Symptoms:**
- Monitor log shows: `ERROR: Checking lockfile: No lockfile found`
- Intermittent errors even though servers are running

**Root cause:**
LinuxGSM v23.5.0+ uses `${selfname}-monitoring.lock` files. When servers are cloned or migrated, these files may not be created properly by the initial start.

**Quick fix:**
Create the old-style lockfiles - LinuxGSM will automatically migrate them:
```bash
# Run this on the affected server
for i in 1 2 3 4 5; do
  port=$((27014 + i))
  name="dodserver"
  [ $i -gt 1 ] && name="dodserver$i"

  # Get the running PID
  pid=$(pgrep -f "hlds_linux.*-port $port")

  if [ -n "$pid" ]; then
    # Create old-style lockfile (LinuxGSM auto-migrates to -monitoring.lock)
    echo "$pid" > ~/dod-$port/lgsm/lock/$name.lock
    echo "Created $name.lock with PID $pid"
  fi
done
```

**Verify fix:**
```bash
# Check lockfiles exist
ls -la ~/dod-*/lgsm/lock/*-monitoring.lock

# Check monitor log for errors
tail -20 ~/log/monitor.log | grep -E 'lockfile|ERROR'
```

---
