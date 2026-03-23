# Observed Label / Canonical Family Rollout Checklist

## Goal

把当前稳定的 `raw_type / family` 工程能力收口成用户可理解的产品体验：

- 原始标签
- 稳定类别
- 影响范围

## Phase 0. Preconditions

- [ ] 当前 `Families` / `Changes` 主链路稳定
- [ ] 当前 API surface 已固定在 `/families*` / `/changes*`
- [ ] UI agent 与 backend agent 使用同一份 spec

## Phase 1. Product wording

### Backend

- [ ] `/changes` item payload 提供 `observed_label`
- [ ] `/changes` item payload 提供 `canonical_family_label`

### Frontend

- [ ] 页面主词从 `raw type` 改成 `Observed label / 原始标签`
- [ ] 页面主词从 `family` 改成 `Canonical family / 稳定类别`
- [ ] `Changes` detail 显示 `Observed label` / `Current family`

### Smoke

- [ ] 打开 `Families`
- [ ] 打开一个 `Changes` detail
- [ ] 不需要阅读内部术语也能理解当前映射

## Phase 2. Impact counts

### Backend

- [ ] `/families` 返回：
  - [ ] `observed_label_count`
  - [ ] `active_event_count`
  - [ ] `pending_change_count`
- [ ] `/families/raw-types` 返回：
  - [ ] `observed_label`
  - [ ] `canonical_family_label`
  - [ ] `active_event_count`
  - [ ] `pending_change_count`

### Frontend

- [ ] `Families` list 显示 impact counts
- [ ] observed-label rows 显示 impact summary

### Smoke

- [ ] `Families` 中每条映射都能看到影响范围

## Phase 3. Relink preview

### Backend

- [ ] 新增 `POST /families/raw-types/relink-preview`
- [ ] preview 返回 current / target family
- [ ] preview 返回 impact counts
- [ ] preview 返回 affected samples

### Frontend

- [ ] relink 前先弹 preview sheet
- [ ] CTA 用动作句，不暴露 ids
- [ ] 用户可在 preview 内确认或取消

### Smoke

- [ ] preview 可打开
- [ ] confirm 后写路径成功
- [ ] cancel 无副作用

## Phase 4. Changes mapping explanation

### Backend

- [ ] `/changes` item payload 返回 `mapping_explanation_code`
- [ ] `/changes` item payload 返回 `mapping_explanation_params`

### Frontend

- [ ] `Changes` detail 显示 mapping explanation
- [ ] 提供 `Open Families` CTA

### Smoke

- [ ] 至少一条与 family mapping 相关的 change 能解释“为什么它长这样”

## Phase 5. Cleanup

### Backend

- [ ] 文档更新：
  - [ ] `docs/api_surface_current.md`
  - [ ] OpenAPI snapshot

### Frontend

- [ ] 清理主界面残留 `raw type` 文案
- [ ] 清理主界面残留 `family_id` 心智

## Validation

### Backend

- [ ] `python -m py_compile ...`
- [ ] targeted pytest
- [ ] OpenAPI update

### Frontend

- [ ] `npm run typecheck`
- [ ] `npm run lint`
- [ ] `NEXT_DIST_DIR=.next-prod npm run build`

### End-to-end

- [ ] `Families` list
- [ ] observed-label relink preview
- [ ] `Changes` mapping explanation
- [ ] refresh after relink still一致

## Release rule

- [ ] additive fields 先上线
- [ ] 前端切到新 projection 后再考虑清旧词
- [ ] 不允许 UI 先行伪造 impact / preview 数据
