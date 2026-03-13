# Future Architecture Optimization Spec

## 1. 目的

这份文档定义 CalendarDIFF 在完成 entity-first semantic cleanup 之后，下一轮应该进行的架构优化。

它不是用来继续清旧词，而是用来减少未来开发成本、降低模型漂移、让后续功能开发更快更稳。

这份文档建立在以下前提之上：

- `/Users/lishehao/Desktop/Project/CalendarDIFF/ENTITY_FIRST_SEMANTIC_SPEC.md` 已经成立。
- 当前 canonical approved state 已经只落在 `event_entities`。
- `changes` 已经只表示 semantic proposals / audit。
- `change_source_refs` 已经替代旧的 source JSON 双存。
- source 侧 payload 已经统一成 `source_facts`。

如果历史代码、旧测试、旧 migration、旧命名与本文件冲突，以本文件为准。

## 2. 当前基线

当前状态里，以下收敛已经完成：

- `event_entities` 是纯 approved state，不再承载 registry/cache 字段。
- approve 与 canonical edit 已经共用 approved-state 写入口。
- `changes` 的 source refs 已经正规化为 `change_source_refs`。
- ingest payload 的 source 层已经统一叫 `source_facts`。

因此，下一轮工作的目标不再是“删旧 canonical 层”，而是做下面四类结构优化：

1. migration baseline 压平
2. payload / evidence / refs 强类型化
3. review 读路径投影化
4. family label authority 明确化

## 3. 优化目标

### 3.1 单一基线

- 仓库应该只保留一个真正反映当前模型的 clean migration baseline。
- 不再保留仅用于过渡的 backfill、compat、downgrade 恢复旧字段逻辑。

### 3.2 强类型边界

- runtime 内部不应该长期用裸 `dict` 传递关键 semantic/source/evidence payload。
- semantic payload、source facts、change source refs、frozen evidence 都应该有稳定类型模型。

### 3.3 便宜的读路径

- review 列表、summary、通知展示不应该靠多次即时拼接或 N+1 查询来生成。
- 常见 UI 读路径应该能稳定、便宜、可预测地返回展示数据。

### 3.4 清晰的标签 authority

- `family_id`、`family_name`、raw type family、用户可编辑 label 之间必须有明确 authority 规则。
- 不允许未来开发继续靠“感觉”决定某处该读冻结值还是最新值。

## 4. 必须实施的改动

## 4.1 Migration baseline 压平

### 目标

把当前 migration 体系收敛成与现行 schema 一致的单一 fresh baseline。

### 现状

- `20260311_0001_semantic_core.py` 是初始 baseline。
- `20260312_0002_entity_approved_state_change_source_refs.py` 仍然包含：
  - 从旧 JSON source ref 回填到 `change_source_refs`
  - downgrade 时恢复旧列
  - 删除旧 `event_entities` 过渡字段

这类迁移逻辑对“已有线上数据迁移”有意义，但对当前 one-cut/reset 策略已经是额外复杂度。

### 具体要求

- 用当前最终 schema 重新生成或手写一个真正的 clean baseline。
- 删除仅用于兼容中间状态的 backfill 逻辑。
- 删除仅用于恢复已废弃字段的 downgrade 逻辑。
- 最终 migration 链应尽量只有：
  - 一个当前 schema baseline
  - 后续真正新增功能所需的增量 migration

### 非目标

- 不做旧数据库内容保留
- 不为旧 JSON source ref 再维持双向兼容

## 4.2 强类型 payload / evidence / refs

### 目标

把关键 runtime payload 从松散 `dict` 升级成有稳定 schema 的 typed model。

### 必须类型化的对象

- `ApprovedSemanticPayload`
- `SemanticEventDraft`
- `SourceFacts`
- `FrozenReviewEvidence`
- `ChangeSourceRefPayload`
- `ReviewChangeSummary`

### 具体要求

- 在 `app/modules/common` 或合适的 shared location 建立统一 schema 模块。
- schema 应优先使用 Pydantic model、TypedDict，或 repo 一致的强类型方式。
- 所有关键 helper 不再接受“任意 dict”，而是接受明确类型对象或经过验证的 dict。
- `review_evidence.py`、`pending_proposal_rebuild.py`、`payload_extractors.py`、`change_listing_service.py` 等关键模块应优先切到 typed payload。

### 最低要求

- 所有创建和消费 `source_facts` 的路径必须共用同一个 schema。
- 所有创建和消费 frozen evidence 的路径必须共用同一个 schema。
- 所有 change source refs 的规范化与序列化必须共用同一个 schema。

### 非目标

- 不要求一次性把 repo 所有普通配置 dict 都强类型化。
- 只要求把 semantic/source/evidence/review 主链路先类型化。

## 4.3 Review 读路径投影化

### 目标

把 review 列表与相关摘要读路径从“临时拼接”升级成稳定 projection/read model。

### 现状问题

当前 `change_listing_service` 虽然已经比之前干净，但仍然会在行级：

- 解析 source refs
- 取 `InputSource`
- 回查 observation 时间
- 临时拼 `primary_source`
- 临时拼 `change_summary`

这会带来：

- 容易出现 N+1
- 不同读路径重复实现展示拼接
- 未来一旦 UI 需求增加，读性能和代码复杂度都会恶化

### 具体要求

至少选下面一种方式实现：

1. SQL 层 batched projection
2. 显式的 review read model / projection table

### 最低交付

- review change list 不再逐条回查 source / observation
- `primary_source`、`proposal_sources`、source label、source observed_at 的生成有单一实现
- summary / notification / review list 尽量复用同一个 projection 逻辑

### 非目标

- 不要求现在就上缓存系统
- 不要求为了 projection 引入新基础设施

## 4.4 明确 family label authority

### 目标

明确 `family_id`、`family_name`、`canonical_label` 之间的 authority 规则，避免后续开发混乱。

### 建议规则

- `event_entities`
  - 保留 `family_id`
  - 可选保留 `family_name`，但如果保留，必须定义为 approved snapshot，而不是实时权威名称
- `changes`
  - 保留冻结的 `family_name`
  - 它代表 proposal 当时的用户可见语义，不随之后 label rename 自动变化
- `course_work_item_label_families.canonical_label`
  - 是最新权威标签名

### 推荐方向

推荐进一步收敛为：

- `event_entities` 以 `family_id` 为主
- 用户当前展示优先按 `family_id -> canonical_label` 解析最新 family label
- `changes` 继续保留冻结 `family_name` 作为历史展示

### 必须回答的问题

做这轮优化时，必须在代码和文档中明确回答：

1. 用户重命名 family 后，历史 approved entity 是否显示新名字？
2. 历史 changes 是否保持旧名字？
3. 通知 digest 展示是按最新 label 还是按检测时冻结 label？

如果没有明确回答，后续开发会在不同页面写出不一致行为。

## 4.5 剩余命名修整

这部分优先级低于上面四项，但应顺手收掉：

- 把 `apply_change_to_canonical_event` 更名为体现真实语义的名字，例如：
  - `apply_change_to_approved_entity_state`
- 继续减少 runtime 里把 approved semantic state 叫成 canonical event 的地方

这不是主架构改造，但它能减少团队心智负担。

## 5. 实施顺序

建议按下面顺序推进：

1. migration baseline 压平
2. typed payload/schema 抽象
3. review read projection
4. family label authority 决策并落库/落读路径
5. 剩余命名修整

原因：

- 先压 migration，避免后面每次动模型都踩中历史兼容逻辑。
- 先抽 typed schema，后面的 projection 和 family authority 才容易稳定实现。
- family authority 最好在 projection 改造时一起落，不然 UI 展示规则会反复改。

## 6. 验收标准

本轮优化完成，至少要满足：

1. migration 目录不再保留仅用于过渡兼容的 backfill/downgrade 逻辑
2. semantic/source/evidence/change source refs 主链路拥有统一 schema 类型
3. review list 的 source summary 与 primary/proposal source 展示不再依赖逐条回查
4. family label authority 在代码与文档里都有明确规则
5. runtime 命名不再把 approved entity state 混叫成 canonical event

## 7. 建议验证

至少运行：

```bash
PYTHONPATH=. python -m pytest -q \
  tests/test_course_work_item_family_migration.py \
  tests/test_core_ingest_pending_proposal_rebuild.py \
  tests/test_review_change_source_summary_api.py \
  tests/test_review_items_summary_api.py \
  tests/test_review_changes_batch_api.py \
  tests/test_review_label_learning_api.py \
  tests/test_notify_jsonl_sink.py \
  tests/test_openapi_contract_snapshots.py \
  tests/test_no_legacy_semantic_cleanup_strings.py
```

如动到 payload schema 或 runtime：

```bash
python -m compileall app services
```

如动到前端 DTO / review 展示：

```bash
cd frontend
npm run typecheck
npm run lint
NEXT_DIST_DIR=.next-prod npm run build
```

## 8. 另一个 agent 的输出要求

如果另一个 agent 根据本文件执行优化，最终响应应明确说明：

1. 哪些结构被真正简化了
2. 哪些 payload 被强类型化了
3. review 读路径是否已经 projection 化
4. family label authority 最终采用了什么规则
5. 实际运行了哪些验证
6. 还有哪些优化被有意留到下一轮
