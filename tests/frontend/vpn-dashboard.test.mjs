import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  formatBytes,
  isVpnOnline,
  normalizeVpnStatus,
  totalTransferBytes,
} from "../../frontend/src/modules/vpn/status.ts";

function statusPayload(overrides = {}) {
  return {
    status: "ok",
    generated_at: "2026-07-15T00:00:00Z",
    agent_version: "0.1.0",
    private_key: "must-not-reach-the-ui",
    vpn: {
      interface: "awg0",
      service: {
        active_state: "active",
        sub_state: "exited",
        active_since: "Tue 2026-07-14 12:45:01 UTC",
      },
      address: "10.66.66.1/24",
      listen_port: 443,
      expected_listen_port: 443,
      peer_count: 2,
      recently_active_peer_count: 1,
      latest_handshake_at: null,
      transfer: {
        received_bytes: 1024,
        sent_bytes: 512,
      },
      peers: [{ public_key: "must-not-reach-the-ui" }],
      ...overrides,
    },
    warnings: [],
  };
}

test("VPN status parser accepts awg0 aggregate status and drops unknown fields", () => {
  const status = normalizeVpnStatus(statusPayload());
  assert.notEqual(status, null);
  assert.equal(status.vpn.interface, "awg0");
  assert.equal(status.vpn.peer_count, 2);
  assert.equal(totalTransferBytes(status), 1536);
  assert.doesNotMatch(JSON.stringify(status), /private_key|public_key|peers/);
});

test("VPN online state requires the active service and expected listening port", () => {
  const online = normalizeVpnStatus(statusPayload());
  const wrongPort = normalizeVpnStatus(
    statusPayload({ listen_port: 8443, expected_listen_port: 443 }),
  );
  const wrongInterface = normalizeVpnStatus(
    statusPayload({ interface: "wg0" }),
  );

  assert.equal(isVpnOnline(online), true);
  assert.equal(isVpnOnline(wrongPort), false);
  assert.equal(wrongInterface, null);
});

test("VPN transfer values use compact human-readable units", () => {
  assert.equal(formatBytes(null), "—");
  assert.equal(formatBytes(0), "0 B");
  assert.equal(formatBytes(1024), "1.0 KB");
  assert.equal(formatBytes(1536), "1.5 KB");
});

test("VPN page keeps the Fire Phoenix cockpit classes without adding CSS", () => {
  const dashboard = readFileSync(
    "frontend/src/modules/vpn/VpnDashboard.tsx",
    "utf8",
  );
  const api = readFileSync("frontend/src/modules/vpn/api.ts", "utf8");
  const nginx = readFileSync(
    "deploy/nginx/vpn-status-location.conf",
    "utf8",
  );

  assert.match(dashboard, /<DashboardScene \/>/);
  assert.match(dashboard, /className="dashboard-page cc-dash"/);
  assert.match(dashboard, /className="cc-head"/);
  assert.match(dashboard, /className="cc-grid"/);
  assert.match(dashboard, /className="cc-card wide"/);
  assert.doesNotMatch(dashboard, /\.module\.css|globals\.css/);
  assert.match(api, /apiRequest<unknown>\("\/vpn\/status"/);
  assert.match(api, /method: "GET"/);
  assert.match(nginx, /location = \/api\/backend\/vpn\/status/);
  assert.match(nginx, /limit_except GET HEAD \{ deny all; \}/);
});
