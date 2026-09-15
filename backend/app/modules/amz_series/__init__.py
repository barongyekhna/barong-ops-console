"""A 系列(亚马逊运营,module_key ``amz.ops``)。

四家广州公司 × 五个店铺,与 K/I/M 零交集:自己的表(前缀 ``amz_``,**没有任何一列叫
``org_id``**——C18G 会按会话组织自动过滤带 org_id 的表,王创鑫在深圳组织上下文下会
看不到任何店铺数据;法人归属列叫 ``company_org_id``,数据主键是 ``store_code``)、
自己的门(``amz_store_grants``,只 owner 绕过,super_admin 不直通)、自己的机器人。
"""
