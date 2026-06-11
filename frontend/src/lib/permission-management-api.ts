import { apiRequest } from "@/lib/api";
import { readAccessToken } from "@/lib/auth";
import {
  createGrantRequestBody,
  getPermissionRegistryPath,
  getUserPermissionAssignmentPath,
  getUserPermissionAssignmentsPath,
  normalizeActionResponse,
  normalizePermissionAssignmentListResponse,
  normalizePermissionRegistryResponse,
  type PermissionAssignmentCreateInput,
  type PermissionAssignmentRevokeInput,
  type PermissionAssignmentUpdateInput,
} from "@/lib/permission-management";

export * from "@/lib/permission-management";

export async function listPermissionRegistry() {
  const response = await apiRequest<unknown>(getPermissionRegistryPath(), {
    accessToken: readAccessToken(),
    method: "GET",
  });

  return normalizePermissionRegistryResponse(response);
}

export async function listUserPermissionAssignments(userId: number) {
  const response = await apiRequest<unknown>(
    getUserPermissionAssignmentsPath(userId),
    {
      accessToken: readAccessToken(),
      method: "GET",
    },
  );

  return normalizePermissionAssignmentListResponse(response, userId);
}

export async function grantUserPermissionAssignment(
  userId: number,
  payload: PermissionAssignmentCreateInput,
) {
  const response = await apiRequest<unknown>(
    getUserPermissionAssignmentsPath(userId),
    {
      accessToken: readAccessToken(),
      body: createGrantRequestBody(payload),
      method: "POST",
    },
  );

  return normalizeActionResponse(response);
}

export async function updateUserPermissionAssignment(
  userId: number,
  assignmentId: string,
  payload: PermissionAssignmentUpdateInput,
) {
  const response = await apiRequest<unknown>(
    getUserPermissionAssignmentPath(userId, assignmentId),
    {
      accessToken: readAccessToken(),
      body: payload,
      method: "PATCH",
    },
  );

  return normalizeActionResponse(response);
}

export async function revokeUserPermissionAssignment(
  userId: number,
  assignmentId: string,
  payload: PermissionAssignmentRevokeInput = {},
) {
  const response = await apiRequest<unknown>(
    getUserPermissionAssignmentPath(userId, assignmentId),
    {
      accessToken: readAccessToken(),
      body: payload,
      method: "DELETE",
    },
  );

  return normalizeActionResponse(response);
}
