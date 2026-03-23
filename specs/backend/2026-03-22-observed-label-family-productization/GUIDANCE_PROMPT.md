你负责 CalendarDIFF 的后端 productization，只做 backend，不改前端实现。

任务目标：

- 不改 semantic core
- 不动 canonical state model
- 只把现有 `raw type / family` 稳定能力投影成更直观的 product contract

你要做的事：

1. 在 `/families` 和 `/families/raw-types` 上补 additive product-facing projection
   - `observed_label`
   - `canonical_family_label`
   - impact counts
2. 增加 `POST /families/raw-types/relink-preview`
3. 扩展 `/families/raw-types/relink` response，让前端能显示产品化成功文案
4. 在 `/changes` item payload 上补：
   - `observed_label`
   - `canonical_family_label`
   - mapping explanation code / params

严格约束：

- 不改 DB 表名
- 不改 parser / apply 核心语义
- 不删除旧字段
- 新字段只做 additive contract
- preview endpoint 必须无副作用

如果字段命名、preview payload 细节、影响范围统计口径有冲突，以 `SPEC.md` 为准。

完成后把实际改动、测试结果、未完成项写进 `OUTPUT.md`。
