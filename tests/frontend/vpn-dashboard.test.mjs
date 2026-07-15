import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  normalizeCreatedVpnDevice,
  normalizeNativeVpnEnrollment,
  normalizeVpnDeviceList,
} from "../../frontend/src/modules/vpn/devices.ts";
import {
  normalizeNativeVpnIdentity,
  normalizeNativeVpnStatus,
} from "../../frontend/src/modules/vpn/native.ts";
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

function devicePayload(overrides = {}) {
  return {
    id: "2f6fcb65-b51f-4b29-bc65-85f71437c2ac",
    owner_id: "must-not-reach-the-ui",
    name: "办公电脑",
    platform: "windows",
    address: "10.66.66.2/32",
    enabled: true,
    created_at: "2026-07-15T01:00:00Z",
    updated_at: "2026-07-15T01:00:00Z",
    last_handshake_at: null,
    received_bytes: 0,
    sent_bytes: 0,
    public_key: "must-not-reach-the-ui",
    preshared_key: "must-not-reach-the-ui",
    ...overrides,
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

test("VPN device parser scopes output to safe member-device fields", () => {
  const devices = normalizeVpnDeviceList({ devices: [devicePayload()] });
  assert.notEqual(devices, null);
  assert.equal(devices.length, 1);
  assert.equal(devices[0].name, "办公电脑");
  assert.doesNotMatch(
    JSON.stringify(devices),
    /owner_id|public_key|preshared_key/,
  );
});

test("one-time configuration is accepted only with a valid safe device", () => {
  const created = normalizeCreatedVpnDevice({
    device: devicePayload(),
    configuration: "[Interface]\nPrivateKey = one-time-only\n",
    one_time: true,
    unknown: "drop-me",
  });
  assert.notEqual(created, null);
  assert.match(created.configuration, /PrivateKey/);
  assert.doesNotMatch(JSON.stringify(created.device), /owner_id|public_key/);
});

test("native enrollment keeps the private key local and accepts only bounded provisioning", () => {
  const publicKey = `${"E".repeat(43)}=`;
  const presharedKey = `${"F".repeat(43)}=`;
  const identity = normalizeNativeVpnIdentity({
    schema_version: 1,
    device_id: "2f6fcb65-b51f-4b29-bc65-85f71437c2ac",
    public_key: publicKey,
    platform: "windows",
    architecture: "amd64",
    agent_version: "0.2.0-pilot",
    suggested_name: "Windows 办公电脑",
    private_key: "must-not-cross-the-bridge",
  });
  assert.notEqual(identity, null);
  assert.doesNotMatch(JSON.stringify(identity), /private_key/);

  const enrollment = normalizeNativeVpnEnrollment({
    device: devicePayload(),
    provisioning: {
      schema_version: 1,
      device_id: "2f6fcb65-b51f-4b29-bc65-85f71437c2ac",
      address: "10.66.66.2/32",
      preshared_key: presharedKey,
      private_key: "must-not-arrive-from-server",
    },
    one_time: true,
  });
  assert.notEqual(enrollment, null);
  assert.equal(enrollment.provisioning.preshared_key, presharedKey);
  assert.doesNotMatch(JSON.stringify(enrollment), /private_key/);
});

test("native enrollment accepts the integrated Android console app", () => {
  const identity = normalizeNativeVpnIdentity({
    schema_version: 1,
    device_id: "2f6fcb65-b51f-4b29-bc65-85f71437c2ac",
    public_key: `${"E".repeat(43)}=`,
    platform: "android",
    architecture: "arm64-v8a",
    agent_version: "0.2.0-pilot",
    suggested_name: "Android Pixel",
    private_key: "must-not-cross-the-bridge",
  });
  assert.notEqual(identity, null);
  assert.equal(identity.platform, "android");
  assert.equal(identity.suggested_name, "Android Pixel");
  assert.doesNotMatch(JSON.stringify(identity), /private_key/);
});

test("native status accepts only safe local tunnel state", () => {
  const status = normalizeNativeVpnStatus({
    available: true,
    installed: true,
    agent_version: "0.2.0-pilot",
    device_id: "2f6fcb65-b51f-4b29-bc65-85f71437c2ac",
    provisioned: true,
    address: "10.66.66.2/32",
    desired_connected: true,
    connected: true,
    tunnel_service_state: "running",
    platform: "android",
    private_key: "drop-me",
  });
  assert.notEqual(status, null);
  assert.equal(status.connected, true);
  assert.equal(status.platform, "android");
  assert.doesNotMatch(JSON.stringify(status), /private_key|drop-me/);
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
  assert.match(dashboard, /className="cc-drawer"/);
  assert.match(dashboard, /我的 VPN 设备/);
  assert.match(dashboard, /controlNativeVpn/);
  assert.match(dashboard, /关闭控制台不会断开/);
  assert.match(dashboard, /ANDROID APP/);
  assert.match(dashboard, /barong-vpn-ready/);
  assert.doesNotMatch(dashboard, /ActivityFeed|活动记录/);
  assert.doesNotMatch(dashboard, /\.module\.css|globals\.css/);
  assert.match(api, /apiRequest<unknown>\("\/vpn\/status"/);
  assert.match(api, /method: "GET"/);
  assert.match(api, /apiRequest<unknown>\("\/vpn\/devices"/);
  assert.match(api, /method: "POST"/);
  assert.match(api, /method: "PATCH"/);
  assert.match(api, /"\/vpn\/devices\/enroll"/);
  assert.match(nginx, /location = \/api\/backend\/vpn\/status/);
  assert.match(nginx, /limit_except GET HEAD \{ deny all; \}/);
  assert.match(nginx, /location = \/api\/backend\/vpn\/devices/);
  assert.match(nginx, /limit_except GET POST \{ deny all; \}/);
  assert.match(nginx, /limit_except PATCH \{ deny all; \}/);
  assert.match(nginx, /location = \/api\/backend\/vpn\/devices\/enroll/);
  assert.match(nginx, /limit_except POST \{ deny all; \}/);
});
