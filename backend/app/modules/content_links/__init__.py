"""站内内链网——**聚合器,不是底座**。

和 ``content_core`` 的方向正好相反:
- ``content_core`` 在**下面**,被 geo/seo 依赖(守卫、事实门禁、定界块…)
- ``content_links`` 在**上面**,依赖 geo/seo/p/b2b,把它们的产出连成一张图

把它放进 content_core 会让底座反过来依赖上层——那就不是底座了
(2026-07-31 被自己的依赖方向测试当场抓住)。

各系列在自己的发布/上架回报里**函数内**惰性导入这里的
``refresh_link_map_safely``,和 ``p_series`` 惰性导入 ``geo_series`` 是同一手法。
"""
