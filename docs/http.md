# 本地接口

服务只用于本地教研复核，不连接真实人员目录或外部数据源。数据以 UTF-8 JSON 传输；未找到对象返回 404，无效业务输入返回 400，正文超出 8MB 返回 413。

- `GET /health` 返回就绪状态。
- `GET /api/context` 返回产品配置、默认版本、已导入版本与保存记录目录。
- `GET /api/data?revision=版本` 返回该版本完整原始数据；省略版本使用演示材料。
- `POST /api/datasets` 接收 `label` 和完整 `data`，返回新建或复用的 `revision`。
- `POST /api/explore` 接收可选 `revision`、`selection` 和 `tolerance`。`tolerance` 形如 `{"absolute": 2, "relative": 0.04}`，缺省时回退到数据自带 `limits`；返回数据指纹、实际选择（含冻结回传的 tolerance）和领域描述。
- `POST /api/notebooks` 使用相同选择参数、`tolerance` 和 `title`，服务端重新计算后保存，不能由客户端伪造结果。保存的 selection 内含 tolerance，重开记录时误差约定与数据版本同时还原。
- `GET /api/notebooks` 返回材料目录，`GET /api/notebooks/编号` 返回冻结描述、选择条件（含误差约定）和所用数据。

容许误差校验：absolute、relative 必须为有限非负数，relative 不超过 1；非法值返回 400。两者均为 0 时结果只含描述统计，不输出合格/超限判定。

领域描述保留 `summary`、`rows`、`series`、`notes`，并新增 `comparison`：

- `policy`：当次生效的容许误差约定与判定开关；
- `coverage`：可定量配对、含检出限复测配对、双侧检出限、单侧可定量、单方法样品计数与观测量程；
- `samples`：样品级明细，含两方法复测值、检出限复测编号、均值/标准差、实验室、批次、差值与逐对容许误差判定；
- `repeatability`：两方法合并复测方差与自由度；
- `deming`：lambda、斜率、截距与低/中/高锚点偏差，无法拟合时给出 note 且数值为 null；
- `bland_altman`：平均偏差、差值标准差与一致性界限；
- `profile`：6 个量程箱的判定、支持样品、适用范围、超限区间、证据不足区间与观测量程；
- `lab_groups`、`lot_groups`：实验室/批次层面的配对覆盖与偏差，单方法分组带 `only_one_method`；
- `fully_censored_samples`、`one_sided_censored_samples`、`single_method_samples`：检出限与单方法限制清单。

增添业务能力时需保持现有原始记录和保存材料可读取。
