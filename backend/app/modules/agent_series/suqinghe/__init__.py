"""苏青禾:独立站运营总管(数字员工)。2026-10-22 起影子期——只出方案、发审批卡,批了只记账。"""

# 先把数据库层加载完整再导入任何子模块:子模块顶层导入 services.data_isolation,
# 如果它比 db.session 先被加载,就会 data_isolation → db → db.session → data_isolation 循环导入,
# 进程一启动就崩(2026-10-21 R-W/R-A 就是这么停了两小时)。
from ....db import session as _db_session  # noqa: F401
