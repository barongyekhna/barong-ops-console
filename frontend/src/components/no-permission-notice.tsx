import { LockKeyhole } from "lucide-react";

type NoPermissionNoticeProps = {
  title?: string;
  description?: string;
};

export function NoPermissionNotice({
  title = "无权访问此板块",
  description = "当前账号没有访问该板块所需权限。如需开通，请联系 Owner。",
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
