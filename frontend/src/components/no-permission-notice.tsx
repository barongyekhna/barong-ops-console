import { CircleSlash2, LockKeyhole } from "lucide-react";
import {
  MODULE_NO_PERMISSION_DESCRIPTION,
  MODULE_NO_PERMISSION_TITLE,
  MODULE_UNAVAILABLE_DESCRIPTION,
  MODULE_UNAVAILABLE_TITLE,
} from "@/lib/module-notices";

type NoPermissionNoticeProps = {
  title?: string;
  description?: string;
};

export function NoPermissionNotice({
  title = MODULE_NO_PERMISSION_TITLE,
  description = MODULE_NO_PERMISSION_DESCRIPTION,
}: NoPermissionNoticeProps) {
  return (
    <section className="permission-denied" role="alert">
      <span className="permission-denied-icon">
        <LockKeyhole aria-hidden="true" size={24} />
      </span>
      <div>
        <h2>{title}</h2>
        <p>{description}</p>
      </div>
    </section>
  );
}

export function ModuleUnavailableNotice({
  title = MODULE_UNAVAILABLE_TITLE,
  description = MODULE_UNAVAILABLE_DESCRIPTION,
}: NoPermissionNoticeProps) {
  return (
    <section className="permission-denied" role="alert">
      <span className="permission-denied-icon permission-denied-icon-muted">
        <CircleSlash2 aria-hidden="true" size={24} />
      </span>
      <div>
        <h2>{title}</h2>
        <p>{description}</p>
      </div>
    </section>
  );
}
