"use client";

import { LoaderCircle, RotateCcw } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { UserPermissionsPanel } from "@/components/user-permissions-panel";
import {
  listPermissionRegistry,
  type PermissionRegistryItem,
} from "@/lib/permission-management-api";
import {
  formatUsersApiError,
  listUsers,
  type ManagedUser,
} from "@/lib/users-api";

export function PermissionsProductView() {
  const [users, setUsers] = useState<ManagedUser[]>([]);
  const [registry, setRegistry] = useState<PermissionRegistryItem[]>([]);
  const [selectedUserId, setSelectedUserId] = useState<number | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");

  const selectedUser = useMemo(
    () => users.find((user) => user.id === selectedUserId) ?? users[0] ?? null,
    [selectedUserId, users],
  );

  const load = useCallback(async () => {
    setIsLoading(true);
    setError("");
    try {
      const [userResult, registryResult] = await Promise.all([
        listUsers(),
        listPermissionRegistry(),
      ]);
      setUsers(userResult.items);
      setRegistry(registryResult);
      setSelectedUserId((current) => {
        if (current && userResult.items.some((user) => user.id === current)) {
          return current;
        }
        return userResult.items[0]?.id ?? null;
      });
    } catch (loadError) {
      setUsers([]);
      setRegistry([]);
      setSelectedUserId(null);
      setError(
        formatUsersApiError(
          loadError,
          "Permission center data could not be loaded.",
        ),
      );
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <section className="product-console" aria-label="Permissions">
      <div className="registry-command-bar">
        <div>
          <span className="eyebrow">Users & Organizations</span>
          <h2>Permissions</h2>
          <p>
            Permission registry, user assignment list, grants, updates, and
            revocations from the existing permission APIs.
          </p>
        </div>
        <button
          className="secondary-button"
          disabled={isLoading}
          onClick={() => void load()}
          type="button"
        >
          {isLoading ? (
            <LoaderCircle aria-hidden="true" className="spin" size={17} />
          ) : (
            <RotateCcw aria-hidden="true" size={17} />
          )}
          Refresh
        </button>
      </div>

      <div className="capability-summary-grid">
        <div>
          <span>Users</span>
          <strong>{users.length}</strong>
        </div>
        <div>
          <span>Permissions</span>
          <strong>{registry.length}</strong>
        </div>
        <div>
          <span>Selected</span>
          <strong>{selectedUser?.username ?? "Not set"}</strong>
        </div>
        <div>
          <span>API</span>
          <strong>/permissions</strong>
        </div>
      </div>

      {isLoading ? (
        <section className="list-state">
          <LoaderCircle className="spin" aria-hidden="true" size={22} />
          <span>Loading permission center</span>
        </section>
      ) : error ? (
        <section className="list-state list-error" role="alert">
          <div>
            <h2>Permissions are unavailable</h2>
            <p>{error}</p>
          </div>
          <button className="primary-button" onClick={() => void load()} type="button">
            <RotateCcw aria-hidden="true" size={17} />
            Retry
          </button>
        </section>
      ) : (
        <div className="product-console-grid">
          <article className="ops-panel">
            <div className="ops-panel-heading">
              <div>
                <h3>User list</h3>
                <p>/users and /permissions/users/:user_id/assignments</p>
              </div>
              <span className="ops-source">{users.length} users</span>
            </div>
            {users.length > 0 ? (
              <ol className="ops-record-list">
                {users.map((user) => (
                  <li key={user.id}>
                    <span>{user.role}</span>
                    <strong>{user.username}</strong>
                    <small>{user.is_active ? "active" : "disabled"}</small>
                    <button
                      className="secondary-button"
                      onClick={() => setSelectedUserId(user.id)}
                      type="button"
                    >
                      Select
                    </button>
                  </li>
                ))}
              </ol>
            ) : (
              <div className="ops-empty-state">
                <strong>No users returned.</strong>
                <span>/users</span>
              </div>
            )}
          </article>

          <article className="ops-panel">
            <div className="ops-panel-heading">
              <div>
                <h3>Registry</h3>
                <p>/permissions/registry</p>
              </div>
              <span className="ops-source">{registry.length} permissions</span>
            </div>
            {registry.length > 0 ? (
              <ol className="ops-record-list">
                {registry.slice(0, 12).map((permission) => (
                  <li key={permission.permission_key}>
                    <span>{permission.risk_level}</span>
                    <strong>{permission.permission_key}</strong>
                    <small>{permission.description}</small>
                  </li>
                ))}
              </ol>
            ) : (
              <div className="ops-empty-state">
                <strong>No registry entries returned.</strong>
                <span>/permissions/registry</span>
              </div>
            )}
          </article>
        </div>
      )}

      {selectedUser ? <UserPermissionsPanel targetUser={selectedUser} /> : null}
    </section>
  );
}
