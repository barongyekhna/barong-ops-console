export type CsNotificationTarget = {
  channel: "retail" | "wholesale";
  messageId: string;
  href: string;
};

type NotificationRouteInput = {
  source?: string | null;
  event_type?: string | null;
  external_refs?: Record<string, unknown> | null;
  payload?: Record<string, unknown> | null;
};

const MESSAGE_ID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function stringValue(value: unknown) {
  return typeof value === "string" ? value.trim() : "";
}

function channelValue(value: unknown): "retail" | "wholesale" | null {
  return value === "retail" || value === "wholesale" ? value : null;
}

function targetHref(channel: "retail" | "wholesale", messageId: string) {
  const params = new URLSearchParams({ channel, message: messageId });
  return `/cs/customer-service?${params.toString()}`;
}

function targetFromRoute(value: unknown): CsNotificationTarget | null {
  const route = stringValue(value);
  if (!route.startsWith("/") || route.startsWith("//")) return null;
  try {
    const parsed = new URL(route, "https://console.local");
    if (parsed.pathname !== "/cs/customer-service") return null;
    const channel = channelValue(parsed.searchParams.get("channel"));
    const messageId = parsed.searchParams.get("message") ?? "";
    if (!channel || !MESSAGE_ID_PATTERN.test(messageId)) return null;
    return { channel, href: targetHref(channel, messageId), messageId };
  } catch {
    return null;
  }
}

export function getCsNotificationTarget(
  notification: NotificationRouteInput,
): CsNotificationTarget | null {
  const payload = notification.payload ?? {};
  const externalRefs = notification.external_refs ?? {};
  const routed = targetFromRoute(
    payload.route ?? externalRefs.route ?? externalRefs.console_path,
  );
  if (routed) return routed;

  const source = stringValue(notification.source).toLowerCase();
  const eventType = stringValue(notification.event_type).toLowerCase();
  const isCustomerService =
    source === "cs" ||
    source.startsWith("cs_") ||
    source.startsWith("cs.") ||
    eventType === "cs" ||
    eventType.startsWith("cs.") ||
    eventType.startsWith("cs_");
  if (!isCustomerService) return null;

  const channel = channelValue(payload.channel ?? externalRefs.channel);
  const messageId = stringValue(
    payload.message_id ?? externalRefs.message_id ?? externalRefs.message,
  );
  if (!channel || !MESSAGE_ID_PATTERN.test(messageId)) return null;
  return { channel, href: targetHref(channel, messageId), messageId };
}
