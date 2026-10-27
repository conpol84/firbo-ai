# FIRBO Production V1 — Browser kernel egress isolation

Status: **source/CI reviewed only until the owner actually installs it and
supplies both live OS negative and Browser read/frame/close receipts.**

This is the NEXT stage after owner acceptance of Browser image policy SHA-256
`a66379f52d9a265e8eb17e76ae5011c035a48876389ccdeb843b9b1741856299`
and read-only OS audit confirming `--network bridge`, Docker `iptables`
DOCKER-USER + forward hook, and no Docker-native nftables bridge table.
The main router and source Browser release must not be rebuilt, restarted
or replaced as a prerequisite.

## Scope and policy

- One **new** labelled `firbo-browser-egress-v1` user-defined Docker bridge
  whose Linux interface is `br-firbo-v1`. Docker chooses a free local IPv4
  subnet. `EnableIPv6=false`; `enable_icc=false`. No existing `docker0`,
  Compose project, DB, Docker daemon configuration, published port, other
  network, model or token is touched.
- The dedicated, root-owned `FIRBO_BROWSER_V1` iptables chain is called at
  **position 1** only when `DOCKER-USER -i br-firbo-v1` handles forwarded
  packets. Deny RFC1918/CGNAT/loopback/link-local and reserved/metadata
  destinations. Only TCP 80/443 and TCP/UDP 53 or UDP 443 can RETURN to
  Docker's normal network rules; all remaining outbound protocols DROP.
- An interface-scoped `INPUT -i br-firbo-v1 -j DROP` also denies access to
  the **host itself**, including its public and Docker gateway addresses.
  Dedicated IPv6 INPUT and FORWARD DROP hooks prevent unintended link-local
  IPv6 escape despite the bridge's IPv6-disabled configuration.
- Before **every new Browser MCP container**, the wrapper executes the
  root-owned kernel policy verifier. On every OpenJarvis startup, its new
  systemd ExecStartPre re-establishes only the expected scoped rules. Rules
  missing, out-of-order, foreign, or a switched Docker firewall backend cause
  a **fail-closed** Browser session rather than an unprotected fallback.
- Public URL/page browsing already has its separate Playwright DNS/URL guard
  inside the accepted runtime image; this second kernel layer counters
  DNS-rebinding timing windows and model/child-process bypasses.

## Cutover protocol

The source release script accepts `--check`, `--apply` and `--rollback`.
An explicit `--owner-confirms-no-active-browser-tasks` flag is mandatory
for either write operation. This confirmation means the owner checked that no
running/blocked Browser session requires preserving its current connection.

Run ONLY from the immutable reviewed GitHub runtime HEAD (pin its exact
40-character merge SHA before the shell command), as root on `srv2027143`.
Always run `--check` first.

**Preflight** refuses unknown remote/dirty source, altered old Browser image
policy, untrusted root wrapper mode, existing named network, existing chain
or release manifest, missing Docker/iptables hooks, unsupported IPv6 firewall
or active non-iptables Docker firewall. No changes at this stage.

**Apply**: save root-only original wrapper backup and release manifest, create
only the labelled bridge, install the interface-specific IPv4+IPv6 rules,
test raw bounded TCP SYN against host gateway/private range and confirm IPv6
is unroutable, install strict kernel verifier, change ONLY the existing
Browser MCP wrapper's `--network bridge` value, add the one OpenJarvis
unit drop-in, restart OpenJarvis, verify local HTTP 200 and unauthenticated
401, then perform a *real* authenticated no-model Start→public DOM read→JPEG
Frame→same-session Close. Existing Edge/Supabase production is never
modified or replayed.

**Rollback** after any failure restores the old wrapper and OpenJarvis unit,
restarts its accepted service and removes ONLY the dedicated interface
hooks/chain/network. Root-private wrapper backup is retained. A partial
installation has a manifest and blocks blind repeat apply; owner can use
the explicit rollback command after reconciling other active Browser tasks.
Never run `iptables-restore`, reset global INPUT/FORWARD policies, flush
DOCKER-USER, or delete another Docker project.

## Acceptance criteria

Required host receipts for the new scope:
- `FIRBO_BROWSER_KERNEL_PREFLIGHT_PASS`
- `FIRBO_BROWSER_KERNEL_PRIVATE_NETWORK_NEGATIVE_PASS`
- `FIRBO_BROWSER_DIRECT_READ_NO_MODEL_E2E_PASS`
- `FIRBO_BROWSER_KERNEL_EGRESS_RELEASE_PASS`
- `FIRBO_BROWSER_EGRESS_GUARD_PERSISTENT_ON_OPENJARVIS_START`

The CLI must **not** claim kernel PASS from source unit tests, mere chain
existence or a failed TCP probe. Keep the known rollback image
`firbo-browser-mcp:rollback-20261027T192726Z`, and preserve the original
VPS route acceptance.

## What this does NOT close

The owner-signed-in Cloud Browser v27 terminal `close_verified=true` receipt,
authenticated multi-site ReAct and YouTube, independently authenticated
tenant/user A/B/C test, external approved write delivery confirmations,
Mac/Debian consent and physical voice acceptance, exact invoice provider
accounting, backup restore drill, and Golden Journey 8/8 remain OPEN. This
is only the kernel egress isolation gate.

Docker references:
- https://docs.docker.com/engine/network/firewall-iptables/
- https://docs.docker.com/engine/network/firewall-nftables/
- https://docs.docker.com/engine/network/drivers/bridge/
