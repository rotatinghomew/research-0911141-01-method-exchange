# 数据口径

样品编号标识物理样品，replicate 是独立复测编号。value 为统一浓度单位；status=below_limit 时只知低于 limit，value=null；缺记录不代表零。laboratory、lot 是测量环境而非独立样品。old 只是沿用方法，不是真值。limits 中 absolute、relative 表示可调整的容许误差系数，边界为 absolute + relative × 浓度绝对值。样品只在一种方法出现时仍保留在原始记录中。

## 数据版本

`fixtures/data.json` 是可直接导入的一份完整材料，`product.json` 保存页面默认范围。导入必须提交完整对象，不把省略字段解释为删除补丁；以规范化 JSON 的 SHA-256 标识内容，同内容多次导入复用版本。原始记录只追加版本，保存的分析材料始终指向原来版本。

页面中的范围影响当前描述，不回写源数据。`null`、缺记录与实际零不能合并；数据格式问题应在导入时明确报错，而不是生成看似成功的空结果。涉及单位、时间或关系的解释以本文件为准，统计方法和业务决策没有预设结果。

## 目录

`method_exchange/domain.py` 提供现行领域校验和描述，`validation.py` 处理基础引用与数值校验，`service.py` 连接领域操作和材料存档，`storage.py` 负责内容寻址数据与历史记录，`server.py` 提供本地接口。`web/app.js` 使用接口构建交互页面，不自行推导独立口径。
