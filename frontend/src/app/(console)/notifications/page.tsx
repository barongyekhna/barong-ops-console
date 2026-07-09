import type { Metadata } from "next";

import { NotificationInbox } from "@/modules/notifications/NotificationInbox";

export const metadata: Metadata = {
  title: "通知收件箱",
};
export const dynamic = "force-dynamic";
export const revalidate = 0;

export default function NotificationsPage() {
  return <NotificationInbox />;
}
