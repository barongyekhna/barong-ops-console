import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import {
  normalizeNativeVpnEnrollment,
  normalizeNativeVpnProvisioning,
  normalizeVpnDevice,
  normalizeVpnDeviceList,
} from "../../frontend/src/modules/vpn/devices.ts";
import {
  normalizeNativeVpnIdentity,
  normalizeNativeVpnStatus,
} from "../../frontend/src/modules/vpn/native.ts";
import {
  formatBytes,
  formatRate,
  isNodeOnline,
  isVpnOnline,
  nodeStateLabel,
  nodeWarningLabel,
  normalizeVpnNodeList,
  normalizeVpnStatus,
  totalTransferBytes,
} from "../../frontend/src/modules/vpn/nodes.ts";

const DEVICE_ID = "2f6fcb65-b51f-4b29-bc65-85f71437c2ac";
const KEY = `${"E".repeat(43)}=`;
const PSK = `${"F".repeat(43)}=`;

function statusPayload(overrides = {}) {
  return {
    status: "ok",
    generated_at: "2026-07-15T00:00:00Z",
    agent_version: "0.4.0",
    private_key: "must-never-leak",
    vpn: {
      interface: "awg0",
      service: { active_state: "active", sub_state: "exited", active_since: "x", secret: "drop-me" },
      address: "10.66.66.1/24",
      listen_port: 62000,
      expected_listen_port: 62000,
      peer_count: 2,
      recently_active_peer_count: 1,
      latest_handshake_at: "2026-08-28T03:50:15Z",
      transfer: { received_bytes: 100, sent_bytes: 900, peers: ["drop-me"] },
    },
    warnings: [],
    ...overrides,
  };
}

function devicePayload(overrides = {}) {
  return {
    id: DEVICE_ID,
    name: "Windows DESKTOP",
    platform: "windows",
    address: "10.66.66.4/32",
    enabled: true,
    node_id: "us-la",
    created_at: "2026-08-28T03:49:53Z",
    updated_at: "2026-08-28T03:49:53Z",
    last_handshake_at: "2026-08-28T03:50:15Z",
    received_bytes: 10,
    sent_bytes: 20,
    owner_id: "drop-me",
    public_key: "drop-me",
    preshared_key: "drop-me",
    ...overrides,
  };
}

function provisioningPayload(overrides = {}) {
  return {
    schema_version: 2,
    node: {
      id: "us-la",
      name: "美国-洛杉矶",
      endpoint: "45.76.173.147:62000",
      public_key: KEY,
      mtu: 1280,
      obfuscation: { Jc: 0, Jmin: 0, Jmax: 0, S1: 79, S2: 121, S3: 37, S4: 0, H1: 1, H2: 2, H3: 3, H4: 4 },
      private_key: "drop-me",
    },
    device_id: DEVICE_ID,
    address: "10.66.66.4/32",
    preshared_key: PSK,
    dns: ["1.1.1.1", "1.0.0.1"],
    ...overrides,
  };
}

test("VPN status parser accepts awg0 aggregate status and drops unknown fields", () => {
  const status = normalizeVpnStatus(statusPayload());
  assert.notEqual(status, null);
  assert.equal(status.vpn.peer_count, 2);
  assert.doesNotMatch(JSON.stringify(status), /drop-me|must-never-leak/);
  assert.equal(isVpnOnline(status), true);
  assert.equal(totalTransferBytes(status), 1000);
  assert.equal(normalizeVpnStatus(statusPayload({ vpn: { interface: "wg0" } })), null);
});

test("node registry parser keeps every node, its live state and warnings", () => {
  const nodes = normalizeVpnNodeList({
    nodes: [
      { id: "us-la", name: "美国-洛杉矶", region: "US", enabled: true, order: 10, status: statusPayload() },
      { id: "jp-tyo", name: "日本-东京", region: "JP", enabled: true, order: 20, status: { ...statusPayload(), status: "degraded", warnings: ["vpn_status_unavailable"] } },
      { id: "parked", name: "停用", region: "", enabled: false, order: 90, status: { status: "unreachable", vpn: null, warnings: ["node_unreachable"] } },
    ],
  });
  assert.notEqual(nodes, null);
  assert.equal(nodes.length, 3);
  const [la, tokyo, parked] = nodes;
  assert.equal(isNodeOnline(la), true);
  assert.equal(nodeStateLabel(la), "在线");
  assert.equal(tokyo.state, "degraded");
  assert.equal(nodeStateLabel(tokyo), "降级");
  assert.equal(nodeWarningLabel(tokyo.warnings[0]), "专线程序无响应");
  assert.equal(parked.state, "unreachable");
  assert.equal(nodeStateLabel(parked), "已停用");
  assert.equal(normalizeVpnNodeList({ nodes: [{ id: "Bad Id", name: "x", enabled: true }] }), null);
  assert.doesNotMatch(JSON.stringify(nodes), /agent_url|drop-me|must-never-leak/);
});

test("VPN transfer values use compact human-readable units", () => {
  assert.equal(formatBytes(0), "0 B");
  assert.equal(formatBytes(1536), "1.5 KB");
  assert.equal(formatBytes(283567823), "270 MB");
  assert.equal(formatBytes(null), "—");
  assert.equal(formatRate(1536), "1.5 KB/s");
  assert.equal(formatRate(null), "—");
});

test("VPN device parser scopes output to safe member-device fields and carries node_id", () => {
  const device = normalizeVpnDevice(devicePayload());
  assert.notEqual(device, null);
  assert.equal(device.node_id, "us-la");
  assert.doesNotMatch(JSON.stringify(device), /drop-me/);
  assert.equal(normalizeVpnDevice(devicePayload({ node_id: "Nope!" })), null);
  const list = normalizeVpnDeviceList({ devices: [devicePayload()], unavailable_nodes: ["jp-tyo", "bad id"] });
  assert.deepEqual(list.unavailable_nodes, ["jp-tyo"]);
});

test("schema-2 provisioning carries the node parameters and rejects anything malformed", () => {
  const provisioning = normalizeNativeVpnProvisioning(provisioningPayload());
  assert.notEqual(provisioning, null);
  assert.equal(provisioning.schema_version, 2);
  assert.equal(provisioning.node.endpoint, "45.76.173.147:62000");
  assert.equal(provisioning.node.obfuscation.S3, 37);
  assert.deepEqual(provisioning.dns, ["1.1.1.1", "1.0.0.1"]);
  assert.doesNotMatch(JSON.stringify(provisioning), /drop-me/);
  assert.equal(normalizeNativeVpnProvisioning(provisioningPayload({ schema_version: 1 })), null);
  assert.equal(normalizeNativeVpnProvisioning({ ...provisioningPayload(), node: { ...provisioningPayload().node, endpoint: "evil" } }), null);
  assert.equal(normalizeNativeVpnProvisioning({ ...provisioningPayload(), node: { ...provisioningPayload().node, obfuscation: { Jc: 1 } } }), null);
  assert.equal(normalizeNativeVpnProvisioning(provisioningPayload({ dns: [] })), null);
});

test("native enrollment keeps the private key local and binds device to the node", () => {
  const enrollment = normalizeNativeVpnEnrollment({
    device: devicePayload(),
    provisioning: provisioningPayload(),
    one_time: true,
    private_key: "drop-me",
  });
  assert.notEqual(enrollment, null);
  assert.equal(enrollment.provisioning.node.id, enrollment.device.node_id);
  assert.doesNotMatch(JSON.stringify(enrollment), /drop-me/);
  assert.equal(
    normalizeNativeVpnEnrollment({ device: devicePayload({ node_id: "jp-tyo" }), provisioning: provisioningPayload(), one_time: true }),
    null,
  );
  const identity = normalizeNativeVpnIdentity({
    schema_version: 1, device_id: DEVICE_ID, public_key: KEY, architecture: "amd64", agent_version: "0.3.0-pilot", platform: "android",
  });
  assert.equal(identity.suggested_name, "Android 手机");
});

test("native status accepts only safe local tunnel state and optional node identity", () => {
  const status = normalizeNativeVpnStatus({
    available: true, installed: true, provisioned: true, desired_connected: true, connected: true,
    device_id: DEVICE_ID, address: "10.66.66.4/32", agent_version: "0.3.0-pilot", platform: "android",
    node_id: "us-la", node_name: "美国-洛杉矶", tunnel_service_state: "running", private_key: "drop-me",
  });
  assert.notEqual(status, null);
  assert.equal(status.node_id, "us-la");
  assert.doesNotMatch(JSON.stringify(status), /drop-me/);
  assert.equal(normalizeNativeVpnStatus({ available: true, installed: true, provisioned: true, desired_connected: false, connected: false, node_id: "Bad" }), null);
  const legacy = normalizeNativeVpnStatus({ available: true, installed: true, provisioned: false, desired_connected: false, connected: false });
  assert.equal(legacy.node_id, null);
  assert.equal(legacy.platform, "windows");
});

test("VPN page: one node component, no manual device creation, cookie-scoped downloads", () => {
  const dashboard = readFileSync("frontend/src/modules/vpn/VpnDashboard.tsx", "utf8");
  const bar = readFileSync("frontend/src/modules/vpn/ConnectionBar.tsx", "utf8");
  const nodePanel = readFileSync("frontend/src/modules/vpn/NodePanel.tsx", "utf8");
  const api = readFileSync("frontend/src/modules/vpn/api.ts", "utf8");
  const nginx = readFileSync("deploy/nginx/vpn-status-location.conf", "utf8");
  const css = readFileSync("frontend/src/app/globals.css", "utf8");

  // Fire Phoenix cockpit shell stays; VPN styling lives in its own appended layer.
  assert.match(dashboard, /<DashboardScene \/>/);
  assert.match(dashboard, /className="dashboard-page cc-dash cc-vpn"/);
  assert.doesNotMatch(dashboard, /\.module\.css/);
  assert.match(css, /\.cc-vpn-bar \{/);
  assert.match(css, /@keyframes ccVpnBreathe/);
  assert.match(css, /prefers-reduced-motion/);

  // Always-visible connection strip with a live lamp and rates.
  assert.match(dashboard, /<ConnectionBar/);
  assert.match(bar, /cc-vpn-lamp/);
  assert.match(bar, /formatRate\(rates\.down_bytes_per_second\)/);
  assert.match(dashboard, /POLL_INTERVAL_MS = 5_000/);
  assert.match(dashboard, /settleNative\(true\)/);

  // Every node goes through the same component fed by the registry.
  assert.match(dashboard, /<NodePanel/);
  assert.match(nodePanel, /sorted\.map\(\(node\)/);
  assert.match(api, /apiRequest<unknown>\("\/vpn\/nodes"/);
  assert.match(nginx, /location = \/api\/backend\/vpn\/nodes/);

  // Devices are only ever the signed-in client enrolling itself.
  assert.doesNotMatch(dashboard, /createVpnDevice|添加设备|cc-drawer|configuration/);
  assert.doesNotMatch(api, /createVpnDevice/);
  assert.match(api, /"\/vpn\/devices\/enroll"/);
  assert.match(api, /node_id: nodeId/);
  assert.match(nginx, /location = \/api\/backend\/vpn\/devices \{\n\s+limit_except GET HEAD \{ deny all; \}/);
  assert.match(nginx, /location = \/api\/backend\/vpn\/devices\/enroll/);

  // Installers must live under /api/backend: the session cookie path is
  // /api/backend, so any other prefix never reaches auth_request with a cookie.
  assert.match(api, /"\/api\/backend\/vpn\/downloads\/windows"/);
  assert.match(api, /"\/api\/backend\/vpn\/downloads\/android"/);
  assert.match(dashboard, /window\.location\.assign\(VPN_DOWNLOADS\.windows\)/);
  assert.match(nginx, /location = \/api\/backend\/vpn\/downloads\/windows/);
  assert.match(nginx, /location = \/api\/backend\/vpn\/downloads\/android/);
  assert.match(nginx, /auth_request \/_barong_vpn_release_auth;/);
  assert.doesNotMatch(dashboard, /"\/downloads\//);
});
