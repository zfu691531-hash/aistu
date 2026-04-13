<template>
  <el-drawer
    :model-value="visible"
    title="学生关怀画像"
    size="760px"
    @close="$emit('update:visible', false)"
  >
    <template v-if="student">
      <div class="care-student-card">
        <div>
          <div class="student-name">{{ student.name }}</div>
          <div class="student-meta">
            {{ student.student_no }} / {{ student.grade || '-' }} / {{ student.class_name || '未分班' }}
          </div>
        </div>
        <div class="care-actions">
          <el-button size="small" @click="$emit('recalculate')">手动重算</el-button>
          <el-button size="small" type="primary" @click="$emit('agent-eval')">智能研判</el-button>
          <el-tag :type="riskTagType(profile?.risk_level)">
            {{ displayRiskLabel(profile?.risk_level, { majorIncident: majorIncidentDetected, overall: true }) }}
          </el-tag>
        </div>
      </div>

      <div v-if="loading" class="care-loading">
        <el-skeleton :rows="8" animated />
      </div>

      <template v-else-if="profile">
        <div class="chart-card" :class="`risk-${profile.risk_level}`">
          <div class="chart-shell">
            <svg class="radar-svg" viewBox="0 0 320 320">
              <polygon
                v-for="ring in gridPolygons"
                :key="ring.key"
                :points="ring.points"
                class="grid-ring"
              />
              <line
                v-for="axis in axes"
                :key="axis.key"
                :x1="160"
                y1="160"
                :x2="axis.x"
                :y2="axis.y"
                class="grid-axis"
              />
              <polygon :points="profilePolygon" class="profile-area" />
              <circle
                v-for="point in profilePoints"
                :key="point.key"
                :cx="point.x"
                :cy="point.y"
                r="4"
                class="profile-point"
              />
              <text
                v-for="label in labelPoints"
                :key="label.key"
                :x="label.x"
                :y="label.y"
                class="axis-label"
              >
                {{ label.label }}
              </text>
            </svg>
          </div>

          <div class="chart-summary">
            <div class="summary-title">综合风险</div>
            <div class="summary-score">{{ Math.round((profile.overall_risk || 0) * 100) }}%</div>
            <div class="summary-trend">趋势：{{ trendLabel(profile.trend) }}</div>
            <div class="summary-updated">更新时间：{{ profile.updated_at || '-' }}</div>
          </div>
        </div>
        <div class="overview-strip">
          <div class="overview-card">
            <div class="overview-card-title">当前态势</div>
            <div class="overview-chip-list">
              <span class="quality-chip" :class="majorIncidentDetected ? 'quality-chip--incident' : 'quality-chip--neutral'">
                {{ majorIncidentDetected ? '恶性事件后阶段' : '常规观察阶段' }}
              </span>
              <span v-for="item in overviewHighlights" :key="item.dimension" class="quality-chip quality-chip--focus">
                {{ item.label }} {{ formatPercent(item.score) }}
              </span>
            </div>
          </div>
        </div>

        <div v-if="majorIncidentDetected" class="signal-card incident-card">
          <button type="button" class="section-toggle" @click="toggleSection('incident')">
            <span class="section-title">恶性事件传导</span>
            <span class="section-toggle-text">{{ isSectionOpen('incident') ? '收起' : '展开' }}</span>
          </button>
          <div v-show="isSectionOpen('incident')" class="incident-body">
            <div class="incident-summary-card">
              <div class="incident-summary-main">
                <div class="incident-summary-title">当前已命中恶性事件后阶段</div>
                <div class="incident-summary-text">
                  系统识别到 {{ majorIncidentTypeText }}，置信度 {{ formatPercent(profile.major_incident_confidence || 0) }}。
                </div>
                <div v-if="majorIncidentEvidence.length" class="incident-evidence-list">
                  <div v-for="(item, index) in majorIncidentEvidence" :key="`incident-evidence-${index}`" class="incident-evidence-item">
                    {{ item }}
                  </div>
                </div>
              </div>
              <div class="incident-summary-side">
                <el-tag type="danger">恶性事件</el-tag>
                <div class="incident-summary-caption">以下维度包含事件后次生风险</div>
              </div>
            </div>

            <div v-if="incidentImpactItems.length" class="incident-impact-grid">
              <div v-for="item in incidentImpactItems" :key="item.dimension" class="incident-impact-card">
                <div class="incident-impact-head">
                  <span>{{ item.label }}</span>
                  <div class="incident-impact-side">
                    <el-tag v-if="item.isBnSuggested" size="small" type="warning">前瞻预警</el-tag>
                    <span>{{ formatSignedScore(item.spilloverScore, 2) }}</span>
                  </div>
                </div>
                <div class="incident-impact-metrics">
                  <div class="incident-impact-metric">
                    <span>原始风险</span>
                    <strong>{{ formatPercent(item.baseScore) }}</strong>
                  </div>
                  <div class="incident-impact-metric">
                    <span>传导影响</span>
                    <strong>{{ formatPercent(item.spilloverScore) }}</strong>
                  </div>
                  <div class="incident-impact-metric">
                    <span>当前结果</span>
                    <strong>{{ formatPercent(item.totalScore) }}</strong>
                  </div>
                </div>
                <div v-if="item.note" class="incident-impact-note">{{ item.note }}</div>
              </div>
            </div>

            <div v-if="majorIncidentPropagationSignals.length" class="incident-propagation-list">
              <div class="incident-subtitle">传导信号</div>
              <div v-for="item in majorIncidentPropagationSignals" :key="item.id" class="incident-propagation-item">
                <div class="incident-propagation-head">
                  <span>{{ dimensionLabel(item.dimension) }}</span>
                  <span>{{ formatSignedScore(item.signal_weight, 2) }}</span>
                </div>
                <div class="incident-propagation-text">{{ item.signal_text }}</div>
              </div>
            </div>

            <div v-if="majorIncidentBnEnabled" class="incident-bn-section">
              <div class="incident-subtitle">贝叶斯传播判断</div>
              <div class="incident-bn-summary">
                这部分主要用于判断在恶性事件后，哪条次生传播路径当前更可能发生。像学习维度这类 BN 建议值，默认按前瞻风险展示，提醒老师先核查，不直接等同于已发生学业异常。
              </div>

              <div v-if="majorIncidentBnNodeItems.length" class="incident-bn-node-grid">
                <div v-for="item in majorIncidentBnNodeItems" :key="item.node" class="incident-bn-node-card">
                  <div class="incident-bn-node-head">
                    <span>{{ item.label }}</span>
                    <strong>{{ formatPercent(item.probability) }}</strong>
                  </div>
                  <div class="incident-bn-node-meta">
                    先验 {{ formatPercent(item.dynamic_prior) }} · 影响度 {{ formatPercent(item.impact) }}
                  </div>
                  <div v-if="item.evidence?.length" class="incident-bn-node-evidence">
                    <div
                      v-for="(evidence, index) in item.evidence.slice(0, 2)"
                      :key="`${item.node}-evidence-${index}`"
                      class="incident-bn-node-evidence-item"
                    >
                      {{ evidence.label }}：{{ evidence.signal_text || '-' }}
                    </div>
                  </div>
                </div>
              </div>

              <div v-if="majorIncidentBnPathItems.length" class="incident-bn-path-list">
                <div v-for="item in majorIncidentBnPathItems" :key="item.path_id" class="incident-bn-path-card">
                  <div class="incident-bn-path-head">
                    <span>{{ item.nodes.join(' → ') }}</span>
                    <strong>{{ formatPercent(item.path_probability) }}</strong>
                  </div>
                  <div class="incident-bn-path-text">{{ item.summary }}</div>
                </div>
              </div>

              <div v-if="majorIncidentBnSuggestedItems.length" class="incident-bn-suggest-grid">
                <div v-for="item in majorIncidentBnSuggestedItems" :key="item.dimension" class="incident-bn-suggest-card">
                  <div class="incident-bn-suggest-main">
                    <span>{{ item.label }}</span>
                    <strong>{{ formatPercent(item.score) }}</strong>
                  </div>
                  <div class="incident-bn-suggest-note">{{ item.note }}</div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="signal-card">
          <button type="button" class="section-toggle" @click="toggleSection('dimensions')">
            <span class="section-title">维度概览</span>
            <span class="section-toggle-text">{{ isSectionOpen('dimensions') ? '收起' : '展开' }}</span>
          </button>
          <div v-show="isSectionOpen('dimensions')" class="dimension-section">
            <div class="dimension-section-title">重点维度</div>
            <div class="dimension-list">
              <div v-for="item in focusDimensionItems" :key="item.key" class="dimension-item">
                <div class="dimension-head">
                  <span>{{ item.label }}</span>
                  <span>{{ Math.round(item.score * 100) }}%</span>
                </div>
                <div class="dimension-bar">
                  <div
                    class="dimension-fill"
                    :class="`risk-${scoreLevel(item.score)}`"
                    :style="{ width: `${Math.round(item.score * 100)}%` }"
                  />
                </div>
                <div v-if="item.spilloverScore > 0" class="dimension-split">
                  <span>原始 {{ formatPercent(item.baseScore) }}</span>
                  <span>传导 {{ formatPercent(item.spilloverScore) }}</span>
                </div>
                <div v-if="item.reasons.length" class="dimension-reasons">
                  <div
                    v-for="reason in item.reasons"
                    :key="`${item.key}-${reason.id}`"
                    class="dimension-reason"
                  >
                    {{ reason.signal_text }}
                  </div>
                </div>
                <div v-else class="dimension-empty">
                  当前没有明显风险依据
                </div>
              </div>
            </div>

            <div v-if="secondaryDimensionItems.length" class="dimension-secondary">
              <button type="button" class="subtle-toggle" @click="toggleSection('dimensionsSecondary')">
                <span>其余维度 {{ secondaryDimensionItems.length }} 项</span>
                <span>{{ isSectionOpen('dimensionsSecondary') ? '收起' : '展开' }}</span>
              </button>
              <div v-show="isSectionOpen('dimensionsSecondary')" class="dimension-list dimension-list--secondary">
                <div v-for="item in secondaryDimensionItems" :key="item.key" class="dimension-item">
                  <div class="dimension-head">
                    <span>{{ item.label }}</span>
                    <span>{{ Math.round(item.score * 100) }}%</span>
                  </div>
                  <div class="dimension-bar">
                    <div
                      class="dimension-fill"
                      :class="`risk-${scoreLevel(item.score)}`"
                      :style="{ width: `${Math.round(item.score * 100)}%` }"
                    />
                  </div>
                  <div v-if="item.spilloverScore > 0" class="dimension-split">
                    <span>原始 {{ formatPercent(item.baseScore) }}</span>
                    <span>传导 {{ formatPercent(item.spilloverScore) }}</span>
                  </div>
                  <div v-if="item.reasons.length" class="dimension-reasons">
                    <div
                      v-for="reason in item.reasons.slice(0, 2)"
                      :key="`${item.key}-${reason.id}`"
                      class="dimension-reason"
                    >
                      {{ reason.signal_text }}
                    </div>
                  </div>
                  <div v-else class="dimension-empty">
                    当前没有明显风险依据
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div v-if="bayesCards.length" class="signal-card bayes-card">
          <button type="button" class="section-toggle" @click="toggleSection('bayes')">
            <span class="section-title">贝叶斯辅助判断</span>
            <span class="section-toggle-text">{{ isSectionOpen('bayes') ? '收起' : '展开' }}</span>
          </button>
          <div class="section-title">贝叶斯辅助判断</div>
          <div v-show="isSectionOpen('bayes')" class="bayes-card-list">
            <div v-for="card in bayesCards" :key="card.dimension" class="bayes-dimension-card">
              <div class="bayes-dimension-head">
                <span>{{ card.label }}</span>
                <span>{{ riskLabel(scoreLevel(card.final_score)) }}</span>
              </div>
              <div class="bayes-summary">
                <div class="bayes-metric">
                  <span class="bayes-label">规则分</span>
                  <strong>{{ formatPercent(card.linear_score) }}</strong>
                </div>
                <div class="bayes-metric">
                  <span class="bayes-label">后验概率</span>
                  <strong>{{ formatPercent(card.posterior) }}</strong>
                </div>
                <div class="bayes-metric">
                  <span class="bayes-label">融合分</span>
                  <strong>{{ formatPercent(card.final_score) }}</strong>
                </div>
              </div>
              <div v-if="card.evidence_details?.length" class="bayes-evidence">
                <div class="bayes-evidence-title">命中证据</div>
                <div
                  v-for="item in card.evidence_details"
                  :key="`${card.dimension}-${item.key}`"
                  class="bayes-evidence-item"
                >
                  <div class="bayes-evidence-head">
                    <span>{{ item.key }}</span>
                    <span>LR {{ Number(item.lr || 0).toFixed(2) }}</span>
                  </div>
                  <div class="bayes-evidence-text">{{ item.text || '-' }}</div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div
          v-if="props.isolationLoading || isolationAnalysis"
          class="signal-card isolation-card"
        >
          <button type="button" class="section-toggle" @click="toggleSection('isolation')">
            <span class="section-title">孤立预警因果推理</span>
            <span class="section-toggle-text">{{ isSectionOpen('isolation') ? '收起' : '展开' }}</span>
          </button>
          <div v-show="isSectionOpen('isolation')" class="isolation-body">
            <div v-if="props.isolationLoading" class="agent-loading">
              <el-skeleton :rows="4" animated />
            </div>
            <template v-else-if="isolationAnalysis">
              <div class="isolation-summary-card">
                <div>
                  <div class="isolation-summary-title">孤立预警插件</div>
                  <div class="isolation-summary-text">
                    风险概率 {{ formatPercent(isolationAnalysis.risk_probability) }}，
                    置信度 {{ formatPercent(isolationAnalysis.confidence) }}。
                  </div>
                </div>
                <el-tag :type="riskTagType(isolationAnalysis.risk_level)">
                  {{ riskLabel(isolationAnalysis.risk_level) }}
                </el-tag>
              </div>

              <div class="isolation-metric-list">
                <div class="isolation-metric">
                  <span class="isolation-metric-label">核心场景</span>
                  <strong>学生孤立预警</strong>
                </div>
                <div class="isolation-metric">
                  <span class="isolation-metric-label">证据数量</span>
                  <strong>{{ isolationAnalysis.evidence_summary?.matched_signal_count || 0 }}</strong>
                </div>
                <div class="isolation-metric">
                  <span class="isolation-metric-label">保护因子</span>
                  <strong>{{ isolationAnalysis.evidence_summary?.protective_factor_count || 0 }}</strong>
                </div>
              </div>

              <div v-if="isolationCoverage" class="isolation-section">
                <div class="isolation-section-title">专项证据充分度</div>
                <div class="isolation-coverage-grid">
                  <div class="isolation-coverage-card">
                    <span class="isolation-metric-label">当前状态</span>
                    <strong>{{ isolationCoverage.evidence_sufficient ? '证据较充分' : '证据仍不足' }}</strong>
                  </div>
                  <div class="isolation-coverage-card">
                    <span class="isolation-metric-label">已覆盖关键项</span>
                    <strong>{{ isolationCoverage.covered_count || 0 }}/{{ isolationCoverage.required_count || 0 }}</strong>
                  </div>
                  <div class="isolation-coverage-card">
                    <span class="isolation-metric-label">覆盖率</span>
                    <strong>{{ formatPercent(isolationCoverage.coverage_ratio || 0) }}</strong>
                  </div>
                </div>
                <div v-if="isolationCoveredItems.length" class="isolation-subsection">
                  <div class="isolation-subsection-title">当前已覆盖</div>
                  <div class="quality-chip-list">
                    <span v-for="item in isolationCoveredItems" :key="item.id" class="quality-chip">
                      {{ item.label }}
                    </span>
                  </div>
                </div>
                <div v-if="isolationMissingItems.length" class="isolation-subsection">
                  <div class="isolation-subsection-title">当前缺失项</div>
                  <div class="quality-chip-list">
                    <span v-for="item in isolationMissingItems" :key="item.id" class="quality-chip quality-chip--gap">
                      {{ item.label }}
                    </span>
                  </div>
                  <div class="quality-note-list">
                    <div v-for="item in isolationMissingItems" :key="`${item.id}-desc`" class="quality-note">
                      <div class="quality-note-head">
                        <span>{{ item.label }}</span>
                      </div>
                      <div class="quality-note-text">{{ item.description }}</div>
                      <div v-if="item.action_hint" class="quality-note-action">建议：{{ item.action_hint }}</div>
                    </div>
                  </div>
                </div>
              </div>

              <div v-if="isolationSourceGroups.length" class="isolation-section">
                <div class="isolation-section-title">证据来源分组</div>
                <div class="isolation-source-group-list">
                  <div v-for="group in isolationSourceGroups" :key="group.id" class="isolation-source-group-card">
                    <div class="isolation-source-group-head">
                      <span>{{ group.label }}</span>
                      <span>{{ group.count }} 条</span>
                    </div>
                    <div class="isolation-source-group-desc">{{ group.description }}</div>
                    <div class="quality-chip-list">
                      <span v-for="item in group.items" :key="`${group.id}-${item.label}-${item.source}`" class="quality-chip">
                        {{ item.label }}
                      </span>
                    </div>
                  </div>
                </div>
              </div>

              <div v-if="isolationTrend" class="isolation-section">
                <div class="isolation-section-title">近期趋势判断</div>
                <div class="isolation-trend-card">
                  <div class="isolation-trend-head">
                    <span>{{ isolationTrendLabel(isolationTrend.direction) }}</span>
                    <span>{{ formatSignedScore((isolationTrend.recent_risk_weight || 0) - (isolationTrend.recent_support_weight || 0), 2) }}</span>
                  </div>
                  <div class="isolation-trend-text">{{ isolationTrend.summary }}</div>
                </div>
              </div>

              <div v-if="isolationInterpretationNotes.length" class="isolation-section">
                <div class="isolation-section-title">研判说明</div>
                <div class="quality-note-list">
                  <div v-for="item in isolationInterpretationNotes" :key="item.id" class="quality-note">
                    <div class="quality-note-head">
                      <span>{{ item.label }}</span>
                    </div>
                    <div class="quality-note-text">{{ item.summary }}</div>
                  </div>
                </div>
              </div>

              <div v-if="isolationRootCauses.length" class="isolation-section">
                <div class="isolation-section-title">根因定位</div>
                <div class="isolation-cause-list">
                  <div v-for="item in isolationRootCauses" :key="item.node" class="isolation-cause-card">
                    <div class="isolation-cause-head">
                      <span>{{ item.label }}</span>
                      <span>{{ formatPercent(item.probability) }}</span>
                    </div>
                    <div class="isolation-cause-desc">{{ item.description }}</div>
                    <div class="isolation-cause-impact">
                      影响度 {{ formatPercent(item.impact) }} · 贡献值 {{ formatPercent(item.contribution) }}
                    </div>
                    <div v-if="item.evidence?.length" class="isolation-evidence-list">
                      <div
                        v-for="evidence in item.evidence.slice(0, 2)"
                        :key="`${item.node}-${evidence.rule_id}`"
                        class="isolation-evidence-item"
                      >
                        <div class="isolation-evidence-head">
                          <span>{{ evidence.label }}</span>
                          <span>{{ sourceLabel(evidence.source) }}</span>
                        </div>
                        <div class="isolation-evidence-text">{{ evidence.signal_text || '-' }}</div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <div v-if="isolationPaths.length" class="isolation-section">
                <div class="isolation-section-title">风险传导路径</div>
                <div class="isolation-path-list">
                  <div v-for="path in isolationPaths" :key="path.path_id" class="isolation-path-card">
                    <div class="isolation-path-head">
                      <span>{{ formatPercent(path.path_probability) }}</span>
                      <span>{{ path.nodes.join(' → ') }}</span>
                    </div>
                    <div class="isolation-path-summary">{{ path.summary }}</div>
                  </div>
                </div>
              </div>

              <div v-if="isolationProtectiveFactors.length" class="isolation-section">
                <div class="isolation-section-title">保护因子</div>
                <div class="isolation-factor-list">
                  <div v-for="item in isolationProtectiveFactors" :key="item.id" class="isolation-factor-item">
                    <span>{{ item.label }}</span>
                    <span>{{ formatSignedScore(item.weight, 2) }}</span>
                  </div>
                </div>
              </div>
            </template>
            <el-empty
              v-else
              description="当前暂无孤立预警推理结果"
              :image-size="56"
            />
          </div>
        </div>

        <div class="signal-card graph-card">
          <button type="button" class="section-toggle" @click="toggleSection('graph')">
            <span class="section-title">关系图谱状态</span>
            <span class="section-toggle-text">{{ isSectionOpen('graph') ? '收起' : '展开' }}</span>
          </button>
          <div v-show="isSectionOpen('graph')" class="graph-body">
            <div class="graph-summary-card">
              <div class="graph-summary-main">
                <div class="graph-summary-title">图谱分析层</div>
                <div class="graph-summary-text">{{ graphSummaryText }}</div>
                <div v-if="graphStatusHint" class="graph-summary-hint">{{ graphStatusHint }}</div>
              </div>
              <div class="graph-summary-side">
                <el-tag :type="graphTagType" effect="light">{{ graphStatusLabel }}</el-tag>
                <el-button
                  size="small"
                  type="primary"
                  plain
                  :loading="graphSyncing"
                  @click="$emit('graph-sync')"
                >
                  同步图谱
                </el-button>
              </div>
            </div>

            <div v-if="graphLoading" class="agent-loading">
              <el-skeleton :rows="3" animated />
            </div>
            <template v-else>
              <div class="graph-metric-list">
                <div class="graph-metric">
                  <span class="graph-metric-label">服务状态</span>
                  <strong>{{ graphEnabledText }}</strong>
                </div>
                <div class="graph-metric">
                  <span class="graph-metric-label">连接状态</span>
                  <strong>{{ graphConnectedText }}</strong>
                </div>
                <div class="graph-metric">
                  <span class="graph-metric-label">当前图谱线索</span>
                  <strong>{{ graphSignalCount }} 条</strong>
                </div>
              </div>

              <div class="graph-visual-card">
                <div class="graph-visual-head">
                  <div>
                    <div class="graph-visual-title">关系网络视图</div>
                    <div class="graph-visual-caption">
                      基于近 {{ props.graphView?.window_days || 30 }} 天班级与行为数据生成，点击图谱可放大查看
                    </div>
                  </div>
                  <div class="graph-visual-stats">
                    <span>学生 {{ graphViewStats.student_count }}</span>
                    <span>同班 {{ graphViewStats.peer_count }}</span>
                    <span>事件 {{ graphViewStats.event_count }}</span>
                    <el-button
                      v-if="graphViewModel?.nodes?.length"
                      size="small"
                      type="primary"
                      plain
                      @click="openGraphDialog"
                    >
                      放大查看
                    </el-button>
                  </div>
                </div>

                <div v-if="graphViewLoading" class="agent-loading">
                  <el-skeleton :rows="4" animated />
                </div>
                <template v-else-if="graphViewModel?.nodes?.length">
                  <button type="button" class="graph-visual-shell graph-visual-shell--button" @click="openGraphDialog">
                    <svg
                      class="graph-visual-svg"
                      :viewBox="`0 0 ${graphViewModel.width} ${graphViewModel.height}`"
                    >
                      <line
                        v-for="edge in graphViewModel.edges"
                        :key="edge.id"
                        :x1="edge.x1"
                        :y1="edge.y1"
                        :x2="edge.x2"
                        :y2="edge.y2"
                        class="graph-edge"
                        :class="`graph-edge--${edge.type}`"
                      />

                      <g
                        v-for="node in graphViewModel.nodes"
                        :key="node.id"
                        class="graph-node"
                        :class="`graph-node--${node.type}`"
                      >
                        <title>{{ graphNodeTooltip(node) }}</title>
                        <circle
                          :cx="node.x"
                          :cy="node.y"
                          :r="graphNodeRadius(node)"
                          :fill="graphNodeFill(node)"
                          :stroke="graphNodeStroke(node)"
                          :stroke-width="node.focus ? 3 : 2"
                        />
                        <text :x="node.x" :y="node.y - 2" class="graph-node-label">
                          {{ graphNodeLabel(node) }}
                        </text>
                        <text :x="node.x" :y="node.y + 14" class="graph-node-subtitle">
                          {{ graphNodeSubtitle(node) }}
                        </text>
                      </g>
                    </svg>
                  </button>
                  <div class="graph-legend">
                    <span class="graph-legend-item"><i class="graph-legend-dot graph-legend-dot--focus" /> 当前学生</span>
                    <span class="graph-legend-item"><i class="graph-legend-dot graph-legend-dot--peer" /> 同班同学</span>
                    <span class="graph-legend-item"><i class="graph-legend-dot graph-legend-dot--class" /> 班级</span>
                    <span class="graph-legend-item"><i class="graph-legend-dot graph-legend-dot--safety" /> 安全事件</span>
                    <span class="graph-legend-item"><i class="graph-legend-dot graph-legend-dot--behavior" /> 行为事件</span>
                  </div>
                </template>
                <el-empty
                  v-else
                  description="当前暂无可视化关系数据，可先补充近期行为事件后再同步图谱"
                  :image-size="60"
                />
              </div>

              <div v-if="graphLastSync?.synced_at" class="graph-last-sync">
                上次手动同步：{{ graphLastSync.synced_at }}
              </div>

              <div v-if="graphSignalGroups.length" class="graph-signal-list">
                <div class="graph-signal-title">本次图谱发现</div>
                <div
                  v-for="group in graphSignalGroups"
                  :key="group.dimension"
                  :ref="(el) => setGraphGroupRef(group.dimension, el)"
                  class="graph-signal-group"
                  :class="{ 'graph-signal-group--active': activeGraphGroup === group.dimension }"
                >
                  <div class="graph-signal-group-title">{{ group.label }}</div>
                  <div
                    v-for="item in group.items"
                    :key="item.id || `${item.signal_type}-${item.signal_text}`"
                    class="graph-signal-item"
                  >
                    <div class="graph-signal-head">
                      <span>{{ item.signal_type }}</span>
                      <span>{{ Math.round((item.signal_weight || 0) * 100) }}%</span>
                    </div>
                    <div class="graph-signal-text">{{ item.signal_text }}</div>
                  </div>
                </div>
              </div>
              <el-empty
                v-else
                description="当前暂未发现需要补充关注的关系图谱线索"
                :image-size="64"
              />
            </template>
          </div>
        </div>

        <div class="signal-card">
          <button type="button" class="section-toggle" @click="toggleSection('dataQuality')">
            <span class="section-title">证据质量</span>
            <span class="section-toggle-text">{{ isSectionOpen('dataQuality') ? '收起' : '展开' }}</span>
          </button>
          <div v-show="isSectionOpen('dataQuality')" class="quality-body">
            <div class="quality-summary-grid">
              <div class="quality-card">
                <span class="quality-label">证据充分度</span>
                <strong>{{ dataQuality?.evidence_sufficient ? '较充分' : '仍需补充' }}</strong>
              </div>
              <div class="quality-card">
                <span class="quality-label">缺失来源</span>
                <strong>{{ dataQuality?.missing_count || 0 }}</strong>
              </div>
              <div class="quality-card">
                <span class="quality-label">保护性证据</span>
                <strong>{{ dataQuality?.protective_signal_count || 0 }}</strong>
              </div>
            </div>

            <div v-if="missingSourceLabels.length" class="quality-section">
              <div class="quality-section-title">当前数据缺口</div>
              <div class="quality-chip-list">
                <span v-for="item in missingSourceLabels" :key="item" class="quality-chip quality-chip--gap">
                  {{ item }}
                </span>
              </div>
            </div>

            <div v-if="protectiveSignals.length" class="quality-section">
              <div class="quality-section-title">本次保护性证据</div>
              <div class="quality-note-list">
                <div v-for="item in protectiveSignals.slice(0, 4)" :key="item.id" class="quality-note quality-note--positive">
                  <div class="quality-note-head">
                    <span>{{ sourceLabel(item.source) }}</span>
                    <span>{{ formatSignedScore(item.signal_weight, 2) }}</span>
                  </div>
                  <div class="quality-note-text">{{ item.signal_text }}</div>
                </div>
              </div>
            </div>

            <div v-if="attenuatedRiskSignals.length" class="quality-section">
              <div class="quality-section-title">已衰减的历史风险</div>
              <div class="quality-note-list">
                <div v-for="item in attenuatedRiskSignals.slice(0, 4)" :key="item.id" class="quality-note">
                  <div class="quality-note-head">
                    <span>{{ sourceLabel(item.source) }}</span>
                    <span>{{ Math.round((item.signal_weight || 0) * 100) }}%</span>
                  </div>
                  <div class="quality-note-text">{{ item.signal_text }}</div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="signal-card">
          <button type="button" class="section-toggle" @click="toggleSection('signals')">
            <span class="section-title">各维度依据</span>
            <span class="section-toggle-text">{{ isSectionOpen('signals') ? '收起' : '展开' }}</span>
          </button>
          <div class="section-title">各维度依据</div>
          <div v-show="isSectionOpen('signals')">
          <el-empty
            v-if="!groupedSignals.length"
            description="当前没有明显风险线索"
            :image-size="72"
          />
          <div v-else class="signal-list">
            <div v-for="group in groupedSignals" :key="group.dimension" class="signal-group">
              <div class="signal-group-title">{{ group.label }}</div>
              <div v-for="item in group.items" :key="item.id" class="signal-item">
                <div class="signal-top">
                  <span class="signal-dimension">{{ group.label }}</span>
                  <span class="signal-weight">权重 {{ Math.round((item.signal_weight || 0) * 100) }}%</span>
                </div>
                <div v-if="signalBadgeLabel(item)" class="signal-badge-row">
                  <span class="evidence-chip" :class="signalBadgeClass(item)">{{ signalBadgeLabel(item) }}</span>
                </div>
                <div class="signal-text">{{ item.signal_text }}</div>
                <div class="signal-source">{{ sourceLabel(item.source) }}</div>
              </div>
            </div>
          </div>
          </div>
        </div>

        <div class="agent-card">
          <button type="button" class="section-toggle" @click="toggleSection('agent')">
            <span class="section-title">智能研判结果</span>
            <span class="section-toggle-text">{{ isSectionOpen('agent') ? '收起' : '展开' }}</span>
          </button>
          <div class="section-title">
            智能研判结果
            <span v-if="agentResult?.fallback" class="agent-fallback">（已启用兜底）</span>
          </div>
          <div v-show="isSectionOpen('agent')">
          <div v-if="agentLoading" class="agent-loading">
            <el-skeleton :rows="4" animated />
          </div>
          <el-empty
            v-else-if="!agentResult"
            description="暂未生成研判结果"
            :image-size="72"
          />
          <div v-else class="agent-body">
            <div class="agent-overall">
              <div class="agent-score">
                {{ Math.round((agentResult.result?.overall_score || 0) * 100) }}%
              </div>
              <div class="agent-level">
                {{ displayRiskLabel(agentResult.result?.overall_level, { majorIncident: majorIncidentDetected, overall: true }) }}
              </div>
              <div class="agent-meta">
                模型：{{ agentResult.model_name || '-' }} · 超时：{{ agentResult.timeout_seconds }}s
              </div>
              <div class="agent-review-row">
                <el-tag v-if="agentResult.review_status === 'confirmed'" type="success" size="small">
                  已确认
                </el-tag>
                <el-button
                  v-if="agentResult.record_id || agentResult.id"
                  size="small"
                  type="primary"
                  plain
                  @click="openReviewDialog"
                >
                  确认/修订研判
                </el-button>
              </div>
              <div v-if="agentResult.error_msg" class="agent-error">
                {{ humanizeAgentError(agentResult.error_msg) }}
              </div>
            </div>

            <div v-if="agentMajorIncidentMode" class="agent-incident-card">
              <div class="agent-incident-title">恶性事件后核查模式</div>
              <div class="agent-incident-text">
                {{ agentResult.result?.major_incident_summary || '当前属于恶性事件后阶段，应优先核实安全事实与次生影响。' }}
              </div>
              <div v-if="agentSecondaryImpacts.length" class="quality-chip-list">
                <span v-for="item in agentSecondaryImpacts" :key="`agent-secondary-${item.dimension}`" class="quality-chip quality-chip--incident">
                  {{ item.label }} · 传导 {{ formatPercent(item.spillover_score || 0) }}
                </span>
              </div>
            </div>

            <div class="agent-dimensions">
              <div v-for="item in displayAgentDimensions" :key="item.dimension" class="agent-dimension">
                <div class="agent-dimension-head">
                  <span>{{ dimensionLabel(item.dimension) }}</span>
                  <span>{{ Math.round((item.score || 0) * 100) }}%</span>
                </div>
                <div class="agent-dimension-summary">{{ buildDimensionSummaryLead(item) }}</div>
                <div v-if="buildDimensionSummaryDetail(item)" class="agent-dimension-detail">
                  {{ buildDimensionSummaryDetail(item) }}
                </div>
                <ul v-if="item.evidence?.length" class="agent-evidence">
                  <li v-for="(row, index) in item.evidence" :key="`${item.dimension}-${index}`" class="evidence-item">
                    <template v-if="isGraphEvidence(row)">
                      <button
                        type="button"
                        class="evidence-chip evidence-chip--graph evidence-chip--button"
                        @click="focusGraphGroup(item.dimension)"
                      >
                        {{ graphEvidenceChipLabel(item.dimension) }}
                      </button>
                      <span>{{ stripGraphEvidencePrefix(row) }}</span>
                    </template>
                    <template v-else>
                      {{ row }}
                    </template>
                  </li>
                </ul>
                <div v-if="item.score_breakdown?.length" class="dimension-score-box">
                  <div class="dimension-score-title">分数说明</div>
                  <div
                    v-for="(row, index) in item.score_breakdown"
                    :key="`${item.dimension}-breakdown-${index}`"
                    class="dimension-score-row"
                  >
                    <span>{{ formatScoreBreakdownLabel(row) }}</span>
                    <span>{{ formatScoreBreakdownDisplay(row) }}</span>
                    <span>{{ formatScoreBreakdownNote(row, item.dimension) }}</span>
                  </div>
                </div>
                <ul v-if="!item.score_breakdown?.length && item.score_explanation?.length" class="dimension-score-explanation">
                  <li v-for="(row, index) in item.score_explanation" :key="`${item.dimension}-explain-${index}`">
                    {{ row }}
                  </li>
                </ul>
              </div>
            </div>

            <div v-if="agentResult.result?.overall_breakdown" class="agent-breakdown">
              <div class="agent-actions-title">总体分数构成</div>
              <div v-if="agentResult.fallback" class="agent-breakdown-note">当前为规则兜底结果</div>
              <div class="agent-breakdown-formula">
                {{ agentResult.result.overall_breakdown.formula }}
              </div>
              <div class="agent-breakdown-list">
                <div
                  v-for="item in agentResult.result.overall_breakdown.items"
                  :key="item.dimension"
                  class="agent-breakdown-item"
                >
                  <span>{{ item.label }}</span>
                  <span>{{ formatPercent(item.score) }} × {{ item.weight.toFixed(2) }}</span>
                  <span>{{ item.contribution.toFixed(4) }}</span>
                </div>
              </div>
              <div class="agent-breakdown-total">
                贡献合计：{{ agentResult.result.overall_breakdown.sum.toFixed(4) }}
                （总体分数 {{ agentResult.result.overall_breakdown.overall_score.toFixed(4) }}）
              </div>
            </div>

            <div v-if="agentResult.result?.suggestions?.length" class="agent-actions">
              <div class="agent-actions-title">建议跟进</div>
              <div v-for="(item, index) in agentResult.result.suggestions" :key="`${index}-${item}`" class="agent-action">
                {{ index + 1 }}. {{ item }}
              </div>
            </div>

            <div v-if="agentResult.result?.explanation_highlights?.length" class="agent-actions">
              <div class="agent-actions-title">解释强化</div>
              <div
                v-for="(item, index) in agentResult.result.explanation_highlights"
                :key="`${index}-${item}`"
                class="agent-action"
              >
                {{ index + 1 }}. {{ item }}
              </div>
            </div>

            <div v-if="agentResult.result?.review_suggestions?.length" class="agent-actions">
              <div class="agent-actions-title">老师核查建议</div>
              <div
                v-for="(item, index) in agentResult.result.review_suggestions"
                :key="`${item.dimension}-${index}`"
                class="agent-review-card"
              >
                <div class="agent-review-head">
                  <span>{{ item.title }}</span>
                  <el-tag size="small" :type="item.priority === 'high' ? 'danger' : 'warning'">
                    {{ item.priority === 'high' ? '高优先级' : '中优先级' }}
                  </el-tag>
                </div>
                <div v-if="item.checks?.length" class="agent-review-list">
                  <div
                    v-for="(check, checkIndex) in item.checks"
                    :key="`${item.dimension}-${checkIndex}`"
                    class="agent-review-item"
                  >
                    {{ checkIndex + 1 }}. {{ check }}
                  </div>
                </div>
              </div>
            </div>
          </div>
          </div>
        </div>

        <div class="expert-card">
          <el-collapse v-model="expertCollapse">
            <el-collapse-item name="experts">
              <template #title>
                <span class="section-title">专家对比视图</span>
              </template>
              <div v-if="!expertOutputs.length" class="expert-empty">
                暂无专家输出
              </div>
              <div v-else class="expert-list">
                <div v-for="item in expertOutputs" :key="item.dimension" class="expert-item">
                  <div class="expert-head">
                    <span>{{ dimensionLabel(item.dimension) }}</span>
                    <div class="expert-meta">
                      <span>{{ Math.round((item.result?.score || 0) * 100) }}%</span>
                      <el-tag :type="item.fallback ? 'warning' : 'success'" size="small">
                        {{ item.fallback ? '兜底' : '正常' }}
                      </el-tag>
                    </div>
                  </div>
                  <div class="expert-summary">{{ item.view.lead }}</div>
                  <div v-if="item.view.detail" class="expert-detail">
                    {{ item.view.detail }}
                  </div>
                  <div class="expert-consistency-grid">
                    <div class="expert-consistency-card">
                      <span class="expert-consistency-label">解释基调</span>
                      <strong>{{ item.view.tone }}</strong>
                    </div>
                    <div class="expert-consistency-card">
                      <span class="expert-consistency-label">证据状态</span>
                      <strong>{{ item.view.evidenceStatus }}</strong>
                    </div>
                    <div class="expert-consistency-card">
                      <span class="expert-consistency-label">核查重点</span>
                      <strong>{{ item.view.focus }}</strong>
                    </div>
                  </div>
                  <div v-if="item.view.primaryEvidence" class="expert-key-point">
                    核心依据：{{ item.view.primaryEvidence }}
                  </div>
                  <div v-if="item.view.consistencyHint" class="expert-key-point expert-key-point--muted">
                    {{ item.view.consistencyHint }}
                  </div>
                  <ul v-if="item.result?.evidence?.length" class="expert-evidence">
                    <li v-for="(row, index) in item.result.evidence" :key="`${item.dimension}-${index}`" class="evidence-item">
                      <template v-if="isGraphEvidence(row)">
                        <button
                          type="button"
                          class="evidence-chip evidence-chip--graph evidence-chip--button"
                          @click="focusGraphGroup(item.dimension)"
                        >
                          {{ graphEvidenceChipLabel(item.dimension) }}
                        </button>
                        <span>{{ stripGraphEvidencePrefix(row) }}</span>
                      </template>
                      <template v-else>
                        {{ row }}
                      </template>
                    </li>
                  </ul>
                  <div v-if="item.result?.score_breakdown?.length" class="dimension-score-box dimension-score-box--expert">
                    <div class="dimension-score-title">分数说明</div>
                    <div
                      v-for="(row, index) in item.result.score_breakdown"
                      :key="`${item.dimension}-expert-breakdown-${index}`"
                      class="dimension-score-row"
                    >
                      <span>{{ formatScoreBreakdownLabel(row) }}</span>
                      <span>{{ formatScoreBreakdownDisplay(row) }}</span>
                      <span>{{ formatScoreBreakdownNote(row, item.dimension) }}</span>
                    </div>
                  </div>
                  <div v-if="item.error_msg" class="expert-error">
                    {{ humanizeExpertError(item.error_msg, item.dimension) }}
                  </div>
                </div>
              </div>
            </el-collapse-item>
          </el-collapse>
        </div>

        <div class="agent-history-card">
          <button type="button" class="section-toggle" @click="toggleSection('history')">
            <span class="section-title">研判历史</span>
            <span class="section-toggle-text">{{ isSectionOpen('history') ? '收起' : '展开' }}</span>
          </button>
          <div class="section-title">研判历史</div>
          <div v-show="isSectionOpen('history')">
          <div v-if="agentHistoryLoading" class="agent-loading">
            <el-skeleton :rows="4" animated />
          </div>
          <el-empty
            v-else-if="!agentHistory.length"
            description="暂无研判历史"
            :image-size="72"
          />
          <div v-else class="agent-history-list">
            <el-table :data="agentHistory" border stripe size="small">
              <el-table-column type="expand">
                <template #default="{ row }">
                  <div class="history-detail">
                    <div class="history-detail-title">输入快照</div>
                    <pre>{{ formatJson(row.input_snapshot) }}</pre>
                    <div class="history-detail-title">结构化结果</div>
                    <pre>{{ formatJson(row.result) }}</pre>
                    <div v-if="row.raw_text" class="history-detail-title">原始输出</div>
                    <pre v-if="row.raw_text">{{ row.raw_text }}</pre>
                  </div>
                </template>
              </el-table-column>
              <el-table-column prop="created_at" label="时间" width="180" />
              <el-table-column prop="model_name" label="模型" min-width="120" />
              <el-table-column label="风险等级" width="110">
                <template #default="{ row }">
                  {{ displayRiskLabel(row.result?.overall_level, { majorIncident: Boolean(row.result?.major_incident_mode), overall: true }) }}
                </template>
              </el-table-column>
              <el-table-column label="综合分" width="90">
                <template #default="{ row }">
                  {{ Math.round((row.result?.overall_score || 0) * 100) }}%
                </template>
              </el-table-column>
              <el-table-column label="兜底" width="80">
                <template #default="{ row }">
                  <el-tag :type="row.fallback ? 'warning' : 'success'">
                    {{ row.fallback ? '是' : '否' }}
                  </el-tag>
                </template>
              </el-table-column>
            </el-table>
            <Pagination
              :total="agentHistoryTotal"
              :page="agentHistoryPage"
              :page-size="5"
              @change="handleHistoryPageChange"
            />
          </div>
          </div>
        </div>

        <div class="action-card">
          <button type="button" class="section-toggle" @click="toggleSection('actions')">
            <span class="section-title">建议跟进动作</span>
            <span class="section-toggle-text">{{ isSectionOpen('actions') ? '收起' : '展开' }}</span>
          </button>
          <div class="section-title">建议跟进动作</div>
          <div v-show="isSectionOpen('actions')">
          <div v-for="(item, index) in actions" :key="`${index}-${item}`" class="action-item">
            {{ index + 1 }}. {{ item }}
          </div>
          </div>
        </div>

        <div class="signal-card data-card">
          <button type="button" class="section-toggle" @click="toggleSection('data')">
            <span class="section-title">关怀数据维护</span>
            <span class="section-toggle-text">{{ isSectionOpen('data') ? '收起' : '展开' }}</span>
          </button>
          <div v-show="isSectionOpen('data')">
            <StudentCareDataTabs ref="dataTabsRef" :student="student" :visible="visible" @data-changed="handleDataChanged" />
          </div>
        </div>
      </template>

      <el-empty v-else description="暂无关怀画像数据" :image-size="72" />
    </template>
    <el-dialog v-model="reviewDialogVisible" title="确认/修订智能研判" width="680px" append-to-body>
      <div class="review-tip">
        老师可以修订专家文字依据和建议，分数、风险等级与权重保持系统原值。
      </div>
      <el-form label-position="top">
        <el-form-item label="处置状态">
          <el-select v-model="reviewForm.resolution_status" placeholder="请选择处置状态">
            <el-option label="待跟进" value="pending" />
            <el-option label="处理中" value="in_progress" />
            <el-option label="已处理完成" value="resolved" />
            <el-option label="误报/已核实无风险" value="false_alarm" />
          </el-select>
        </el-form-item>
      <el-form-item label="老师确认备注">
          <el-input
            v-model="reviewForm.teacher_notes"
            type="textarea"
            :rows="3"
            placeholder="例如：已联系家长并核实，学生目前安全，后续继续观察一周。"
          />
        </el-form-item>
        <div class="review-section-title">结构化复核标签</div>
        <div class="review-grid">
          <el-form-item label="主要场景">
            <el-select v-model="reviewForm.review_labels.scene" placeholder="请选择场景">
              <el-option label="社交孤立" value="social_isolation" />
              <el-option label="校园安全" value="safety_risk" />
              <el-option label="情绪困扰" value="emotion_distress" />
              <el-option label="家庭支持不足" value="family_support_gap" />
              <el-option label="学习压力" value="study_pressure" />
              <el-option label="行为失稳" value="behavior_instability" />
              <el-option label="其他" value="other" />
            </el-select>
          </el-form-item>
          <el-form-item label="是否真实风险">
            <el-select v-model="reviewForm.review_labels.is_true_risk" placeholder="请选择">
              <el-option label="待判断" value="unknown" />
              <el-option label="是" value="yes" />
              <el-option label="否" value="no" />
            </el-select>
          </el-form-item>
          <el-form-item label="老师判断严重度">
            <el-select v-model="reviewForm.review_labels.severity" placeholder="请选择">
              <el-option label="未知" value="unknown" />
              <el-option label="低" value="low" />
              <el-option label="中" value="medium" />
              <el-option label="高" value="high" />
            </el-select>
          </el-form-item>
          <el-form-item label="确认信心">
            <el-rate v-model="reviewForm.review_labels.confidence_by_teacher" :max="5" show-score />
          </el-form-item>
        </div>
        <el-form-item label="已采取干预">
          <el-input
            v-model="reviewForm.review_labels.intervention_taken"
            type="textarea"
            :rows="2"
            placeholder="例如：已完成谈话、联系家长、安排同伴支持。"
          />
        </el-form-item>
        <el-form-item label="后续跟踪结果">
          <el-input
            v-model="reviewForm.review_labels.follow_up_outcome"
            type="textarea"
            :rows="2"
            placeholder="例如：一周后复看，状态稳定；或仍需继续跟进。"
          />
        </el-form-item>
        <div class="review-section-title">专家评价修订</div>
        <div
          v-for="dimension in reviewForm.reviewed_result.dimensions"
          :key="dimension.dimension"
          class="review-dimension"
        >
          <div class="review-dimension-head">
            <span>{{ dimensionLabel(dimension.dimension) }}</span>
            <span>{{ Math.round((dimension.score || 0) * 100) }}% · {{ riskLabel(dimension.risk_level) }}</span>
          </div>
          <el-input v-model="dimension.summary" type="textarea" :rows="2" />
          <div class="review-evidence-list">
            <div
              v-for="(item, index) in dimension.evidence"
              :key="`${dimension.dimension}-${index}`"
              class="review-evidence-row"
            >
              <el-input v-model="dimension.evidence[index]" />
              <el-button text type="danger" @click="removeEvidence(dimension, index)">删除</el-button>
            </div>
            <el-button size="small" text type="primary" @click="addEvidence(dimension)">新增依据</el-button>
          </div>
        </div>
        <el-form-item label="建议跟进">
          <div class="review-evidence-list">
            <div
              v-for="(item, index) in reviewForm.reviewed_result.suggestions"
              :key="`suggestion-${index}`"
              class="review-evidence-row"
            >
              <el-input v-model="reviewForm.reviewed_result.suggestions[index]" />
              <el-button text type="danger" @click="removeSuggestion(index)">删除</el-button>
            </div>
            <el-button size="small" text type="primary" @click="addSuggestion">新增建议</el-button>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="reviewDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitReview">确认保存</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="graphViewDialogVisible"
      title="关系网络视图"
      width="92%"
      top="4vh"
      class="graph-dialog"
      destroy-on-close
      @closed="closeGraphDialog"
    >
      <div class="graph-dialog-body">
        <div class="graph-dialog-summary">
          <div class="graph-dialog-title">放大图谱视图</div>
          <div class="graph-dialog-text">
            当前以 {{ props.student?.name || '该学生' }} 为中心，展示班级、同班同学和近期行为事件关系。
          </div>
          <div class="graph-dialog-summary-actions">
            <el-button size="small" plain @click="openGraphMaintenance">管理图谱关系</el-button>
            <el-button size="small" type="primary" @click="createGraphRelationFromSelection">新增图谱关系</el-button>
          </div>
        </div>

        <div v-if="graphViewModel?.nodes?.length" class="graph-dialog-layout">
          <div class="graph-dialog-stage">
            <div class="graph-dialog-toolbar">
              <div class="graph-dialog-toolbar-left">
                <span class="graph-dialog-scale">缩放 {{ Math.round(graphScale * 100) }}%</span>
                <span class="graph-dialog-hint">滚轮缩放，按住拖拽画布</span>
              </div>
              <div class="graph-dialog-toolbar-actions">
                <el-button size="small" @click="zoomGraph(0.12)">放大</el-button>
                <el-button size="small" @click="zoomGraph(-0.12)">缩小</el-button>
                <el-button size="small" plain @click="resetGraphViewport">重置视图</el-button>
              </div>
            </div>

            <div
              class="graph-dialog-shell"
              @wheel.prevent="handleGraphWheel"
              @mousedown="startGraphDrag"
              @mousemove="handleGraphDrag"
              @mouseup="stopGraphDrag"
              @mouseleave="stopGraphDrag"
            >
              <svg
                class="graph-visual-svg graph-visual-svg--large"
                :viewBox="`0 0 ${graphViewModel.width} ${graphViewModel.height}`"
              >
                <g :transform="graphCanvasTransform">
                  <line
                    v-for="edge in graphViewModel.edges"
                    :key="`dialog-${edge.id}`"
                    :x1="edge.x1"
                    :y1="edge.y1"
                    :x2="edge.x2"
                    :y2="edge.y2"
                    class="graph-edge"
                    :class="`graph-edge--${edge.type}`"
                  />

                  <g
                    v-for="node in graphViewModel.nodes"
                    :key="`dialog-${node.id}`"
                    class="graph-node graph-node--interactive"
                    :class="[
                      `graph-node--${node.type}`,
                      { 'graph-node--selected': selectedGraphNode?.id === node.id }
                    ]"
                    @click.stop="selectGraphNode(node)"
                  >
                    <title>{{ graphNodeTooltip(node) }}</title>
                    <circle
                      :cx="node.x"
                      :cy="node.y"
                      :r="graphNodeRadius(node) + 4"
                      :fill="graphNodeFill(node)"
                      :stroke="graphNodeStroke(node)"
                      :stroke-width="node.focus ? 4 : 3"
                    />
                    <text :x="node.x" :y="node.y - 4" class="graph-node-label graph-node-label--large">
                      {{ graphNodeLabel(node) }}
                    </text>
                    <text :x="node.x" :y="node.y + 18" class="graph-node-subtitle graph-node-subtitle--large">
                      {{ graphNodeSubtitle(node) }}
                    </text>
                  </g>
                </g>
              </svg>
            </div>
          </div>

          <div class="graph-detail-card">
            <div class="graph-detail-title">节点详情</div>
            <template v-if="selectedGraphNode">
              <div class="graph-detail-name">{{ selectedGraphNode.label }}</div>
              <div class="graph-detail-type">{{ graphNodeTypeLabel(selectedGraphNode) }}</div>
              <div class="graph-detail-meta">
                <span>关联边 {{ selectedGraphNodeEdgeCount }}</span>
                <span v-if="selectedGraphNode.subtitle">{{ selectedGraphNode.subtitle }}</span>
              </div>
              <div class="graph-detail-section">
                <div class="graph-detail-section-title">说明</div>
                <div class="graph-detail-text">{{ graphNodeDetailText(selectedGraphNode) }}</div>
              </div>
              <div class="graph-detail-actions">
                <el-button size="small" plain @click="openGraphMaintenance">管理图谱关系</el-button>
                <el-button size="small" type="primary" @click="createGraphRelationFromSelection">基于当前节点新增关系</el-button>
                <el-button
                  v-if="selectedGraphEditableRelationId"
                  size="small"
                  type="warning"
                  plain
                  @click="editSelectedGraphRelation"
                >
                  编辑当前关系
                </el-button>
              </div>
              <div v-if="selectedGraphNodeRelations.length" class="graph-detail-section">
                <div class="graph-detail-section-title">相连节点</div>
                <div class="graph-detail-chip-list">
                  <button
                    v-for="item in selectedGraphNodeRelations"
                    :key="item.id"
                    type="button"
                    class="graph-detail-chip"
                    @click="selectGraphNode(item)"
                  >
                    {{ item.label }}
                  </button>
                </div>
              </div>
            </template>
            <div v-else class="graph-detail-empty">
              点击图中的任意节点，即可在这里查看详细信息。
            </div>
          </div>
        </div>

        <div class="graph-legend graph-legend--dialog">
          <span class="graph-legend-item"><i class="graph-legend-dot graph-legend-dot--focus" /> 当前学生</span>
          <span class="graph-legend-item"><i class="graph-legend-dot graph-legend-dot--peer" /> 同班同学</span>
          <span class="graph-legend-item"><i class="graph-legend-dot graph-legend-dot--class" /> 班级</span>
          <span class="graph-legend-item"><i class="graph-legend-dot graph-legend-dot--safety" /> 安全事件</span>
          <span class="graph-legend-item"><i class="graph-legend-dot graph-legend-dot--behavior" /> 行为事件</span>
        </div>
      </div>
      <template #footer>
        <el-button @click="graphViewDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </el-drawer>
</template>

<script setup>
import { computed, nextTick, ref } from 'vue'
import Pagination from '@/components/common/Pagination.vue'
import StudentCareDataTabs from './StudentCareDataTabs.vue'

const emit = defineEmits([
  'update:visible',
  'recalculate',
  'agent-eval',
  'agent-review',
  'agent-history-page-change',
  'graph-sync',
  'data-changed'
])

const props = defineProps({
  visible: {
    type: Boolean,
    default: false
  },
  loading: {
    type: Boolean,
    default: false
  },
  student: {
    type: Object,
    default: null
  },
  profile: {
    type: Object,
    default: null
  },
  signals: {
    type: Array,
    default: () => []
  },
  actions: {
    type: Array,
    default: () => []
  },
  dataQuality: {
    type: Object,
    default: null
  },
  isolationAnalysis: {
    type: Object,
    default: null
  },
  isolationLoading: {
    type: Boolean,
    default: false
  },
  agentResult: {
    type: Object,
    default: null
  },
  agentLoading: {
    type: Boolean,
    default: false
  },
  agentHistory: {
    type: Array,
    default: () => []
  },
  agentHistoryTotal: {
    type: Number,
    default: 0
  },
  agentHistoryPage: {
    type: Number,
    default: 1
  },
  agentHistoryLoading: {
    type: Boolean,
    default: false
  },
  graphHealth: {
    type: Object,
    default: null
  },
  graphLoading: {
    type: Boolean,
    default: false
  },
  graphView: {
    type: Object,
    default: null
  },
  graphViewLoading: {
    type: Boolean,
    default: false
  },
  graphSyncing: {
    type: Boolean,
    default: false
  },
  graphLastSync: {
    type: Object,
    default: null
  },
  graphAutoSync: {
    type: Object,
    default: () => ({
      status: 'idle',
      message: '',
      synced_at: ''
    })
  }
})

const sectionState = ref({
  incident: true,
  dimensions: true,
  dimensionsSecondary: false,
  bayes: false,
  isolation: false,
  graph: false,
  dataQuality: false,
  signals: false,
  agent: true,
  expert: false,
  history: false,
  actions: false,
  data: false
})
const expertCollapse = ref([])
const graphGroupRefs = ref({})
const activeGraphGroup = ref('')
const graphViewDialogVisible = ref(false)
const dataTabsRef = ref(null)
const selectedGraphNodeId = ref('')
const graphScale = ref(1)
const graphOffsetX = ref(0)
const graphOffsetY = ref(0)
const graphDragging = ref(false)
const graphDragStartX = ref(0)
const graphDragStartY = ref(0)
const reviewDialogVisible = ref(false)
const reviewForm = ref({
  teacher_notes: '',
  resolution_status: 'pending',
  review_labels: {
    scene: 'other',
    is_true_risk: 'unknown',
    severity: 'unknown',
    confidence_by_teacher: 3,
    intervention_taken: '',
    follow_up_outcome: ''
  },
  reviewed_result: {
    suggestions: [],
    dimensions: []
  }
})

const dimensionMeta = [
  { scoreKey: 'emotion_score', signalKey: 'emotion', label: '情绪状态' },
  { scoreKey: 'social_score', signalKey: 'social', label: '社交融入' },
  { scoreKey: 'safety_score', signalKey: 'safety', label: '校园安全' },
  { scoreKey: 'family_score', signalKey: 'family', label: '家庭支持' },
  { scoreKey: 'study_score', signalKey: 'study', label: '学习压力' },
  { scoreKey: 'behavior_score', signalKey: 'behavior', label: '行为稳定' }
]

const groupedSignalsMap = computed(() => {
  const map = {
    emotion: [],
    social: [],
    safety: [],
    family: [],
    study: [],
    behavior: []
  }
  props.signals.forEach((item) => {
    if (map[item.dimension]) {
      map[item.dimension].push(item)
    }
  })
  return map
})

const dataQuality = computed(() => props.dataQuality || null)
const missingSourceLabels = computed(() =>
  (dataQuality.value?.missing_sources || []).map((item) => dataGapLabel(item))
)
const protectiveSignals = computed(() =>
  (props.signals || []).filter((item) => Number(item?.signal_weight || 0) < 0)
)
const attenuatedRiskSignals = computed(() =>
  (props.signals || []).filter((item) => {
    const weight = Number(item?.signal_weight || 0)
    return weight > 0 && weight <= 0.2 && ['attendance', 'behavior_event', 'score'].includes(item?.source)
  })
)

const dimensions = computed(() => dimensionMeta.map((item) => ({
  key: item.scoreKey,
  signalKey: item.signalKey,
  label: item.label,
  score: props.profile?.[item.scoreKey] || 0,
  baseScore: Number(props.profile?.[`${item.signalKey}_base_score`] || props.profile?.[item.scoreKey] || 0),
  spilloverScore: Number(props.profile?.[`${item.signalKey}_spillover_score`] || 0),
  reasons: groupedSignalsMap.value[item.signalKey] || []
})))

const dimensionItems = computed(() => dimensions.value)
const sortedDimensionItems = computed(() =>
  dimensions.value
    .slice()
    .sort((a, b) => {
      const aPriority = Math.max(Number(a.spilloverScore || 0), Number(a.score || 0))
      const bPriority = Math.max(Number(b.spilloverScore || 0), Number(b.score || 0))
      return bPriority - aPriority
    })
)
const focusDimensionItems = computed(() => {
  const focused = sortedDimensionItems.value.filter((item) => item.spilloverScore > 0 || item.score >= 0.3)
  return focused.length ? focused : sortedDimensionItems.value.slice(0, 3)
})
const secondaryDimensionItems = computed(() => {
  const focusKeys = new Set(focusDimensionItems.value.map((item) => item.key))
  return sortedDimensionItems.value.filter((item) => !focusKeys.has(item.key))
})
const overviewHighlights = computed(() => sortedDimensionItems.value.slice(0, 3))
const majorIncidentDetected = computed(() => Boolean(props.profile?.major_incident_detected))
const majorIncidentEvidence = computed(() => props.profile?.major_incident_evidence || [])
const majorIncidentTypeText = computed(() => {
  const types = props.profile?.major_incident_types || []
  if (!types.length) return '恶性事件线索'
  return types.slice(0, 3).join('、')
})
const incidentImpactItems = computed(() => dimensionMeta
  .map((item) => ({
    dimension: item.signalKey,
    label: item.label,
    baseScore: Number(props.profile?.[`${item.signalKey}_base_score`] || 0),
    spilloverScore: Number(props.profile?.[`${item.signalKey}_spillover_score`] || 0),
    totalScore: Number(props.profile?.[item.scoreKey] || 0),
    isBnSuggested: isBnSuggestedDimension(item.signalKey),
    note: buildIncidentImpactNote(item.signalKey)
  }))
  .filter((item) => item.spilloverScore > 0)
  .sort((a, b) => b.spilloverScore - a.spilloverScore))
const majorIncidentPropagationSignals = computed(() =>
  (props.signals || []).filter((item) => item?.source === 'major_incident')
)
const majorIncidentBn = computed(() => props.profile?.major_incident_bn || {})
const majorIncidentBnEnabled = computed(() => Boolean(majorIncidentBn.value?.enabled))
const majorIncidentBnNodeItems = computed(() =>
  (majorIncidentBn.value?.nodes || [])
    .slice()
    .sort((a, b) => Number(b?.probability || 0) - Number(a?.probability || 0))
)
const majorIncidentBnPathItems = computed(() =>
  (majorIncidentBn.value?.paths || [])
    .slice()
    .sort((a, b) => Number(b?.path_probability || 0) - Number(a?.path_probability || 0))
)
const majorIncidentBnSuggestedItems = computed(() => {
  const scores = majorIncidentBn.value?.suggested_spillover_scores || {}
  return dimensionMeta
    .map((item) => ({
      dimension: item.signalKey,
      label: item.label,
      score: Number(scores?.[item.signalKey] || 0),
      note: item.signalKey === 'study'
        ? '前瞻风险，优先核查课堂专注、作业状态和短期波动。'
        : '用于辅助判断可能的次生影响路径。'
    }))
    .filter((item) => item.score > 0)
    .sort((a, b) => b.score - a.score)
})
const bayesCards = computed(() => {
  const bayesResults = props.profile?.bayes_results || {}
  const order = ['emotion', 'safety', 'family']
  return order
    .map((dimension) => {
      const item = bayesResults[dimension]
      if (!item?.enabled) return null
      return {
        ...item,
        label: dimensionLabel(dimension)
      }
    })
    .filter(Boolean)
})

const isolationAnalysis = computed(() => props.isolationAnalysis || null)
const isolationRootCauses = computed(() => isolationAnalysis.value?.root_causes || [])
const isolationPaths = computed(() => isolationAnalysis.value?.propagation_paths || [])
const isolationProtectiveFactors = computed(() => isolationAnalysis.value?.evidence_summary?.protective_factors || [])
const isolationCoverage = computed(() => isolationAnalysis.value?.evidence_summary?.social_data_coverage || null)
const isolationCoveredItems = computed(() => isolationCoverage.value?.covered_items || [])
const isolationMissingItems = computed(() => isolationCoverage.value?.missing_items || [])
const isolationTrend = computed(() => isolationAnalysis.value?.evidence_summary?.social_trend || null)
const isolationSourceGroups = computed(() => isolationAnalysis.value?.evidence_summary?.evidence_source_groups || [])
const isolationInterpretationNotes = computed(() => isolationAnalysis.value?.evidence_summary?.evidence_interpretation || [])

const graphSignals = computed(() =>
  (props.signals || []).filter((item) => item?.source === 'graph')
)

const graphSignalGroups = computed(() => dimensionMeta
  .map((item) => ({
    dimension: item.signalKey,
    label: item.label,
    items: graphSignals.value.filter((signal) => signal.dimension === item.signalKey)
  }))
  .filter((item) => item.items.length))

const graphSignalCount = computed(() => graphSignals.value.length)

const graphViewStats = computed(() => props.graphView?.stats || {
  student_count: 0,
  peer_count: 0,
  event_count: 0
})

const graphViewModel = computed(() => {
  const rawNodes = Array.isArray(props.graphView?.nodes) ? props.graphView.nodes : []
  const rawEdges = Array.isArray(props.graphView?.edges) ? props.graphView.edges : []
  if (!rawNodes.length) return null

  const width = 540
  const height = 360
  const centerX = 270
  const centerY = 164
  const nodeMap = new Map(rawNodes.map((item) => [item.id, { ...item }]))
  const focusNode = rawNodes.find((item) => item.focus) || rawNodes.find((item) => item.type === 'student')
  const classNode = rawNodes.find((item) => item.type === 'class')
  const peerNodes = rawNodes.filter((item) => item.type === 'classmate' || item.type === 'related_student')
  const eventNodes = rawNodes.filter((item) => item.type === 'event' || item.type === 'manual_event')

  if (focusNode) {
    Object.assign(nodeMap.get(focusNode.id), { x: centerX, y: centerY })
  }
  if (classNode) {
    Object.assign(nodeMap.get(classNode.id), { x: centerX, y: 62 })
  }

  placeArcNodes(peerNodes, nodeMap, centerX, centerY - 10, 172, 210, 330)
  placeArcNodes(eventNodes, nodeMap, centerX, centerY + 24, 156, 25, 155)

  const nodes = rawNodes
    .map((item) => nodeMap.get(item.id))
    .filter((item) => Number.isFinite(item?.x) && Number.isFinite(item?.y))

  const edges = rawEdges
    .map((edge) => {
      const source = nodeMap.get(edge.source)
      const target = nodeMap.get(edge.target)
      if (!source || !target) return null
      return {
        ...edge,
        x1: source.x,
        y1: source.y,
        x2: target.x,
        y2: target.y
      }
    })
    .filter(Boolean)

  return { width, height, nodes, edges }
})

const graphCanvasTransform = computed(
  () => `translate(${graphOffsetX.value} ${graphOffsetY.value}) scale(${graphScale.value})`
)

const selectedGraphNode = computed(() => {
  if (!graphViewModel.value?.nodes?.length) return null
  return graphViewModel.value.nodes.find((item) => item.id === selectedGraphNodeId.value) || null
})

const selectedGraphNodeEdgeCount = computed(() => {
  if (!selectedGraphNode.value || !graphViewModel.value?.edges?.length) return 0
  return graphViewModel.value.edges.filter(
    (edge) => edge.source === selectedGraphNode.value.id || edge.target === selectedGraphNode.value.id
  ).length
})

const selectedGraphNodeRelations = computed(() => {
  if (!selectedGraphNode.value || !graphViewModel.value?.edges?.length) return []
  const relatedIds = new Set()
  graphViewModel.value.edges.forEach((edge) => {
    if (edge.source === selectedGraphNode.value.id) relatedIds.add(edge.target)
    if (edge.target === selectedGraphNode.value.id) relatedIds.add(edge.source)
  })
  return graphViewModel.value.nodes.filter((item) => relatedIds.has(item.id))
})

const selectedGraphManualEdges = computed(() => {
  if (!selectedGraphNode.value || !graphViewModel.value?.edges?.length) return []
  return graphViewModel.value.edges.filter((edge) => {
    if (edge.type !== 'manual_relation') return false
    return edge.source === selectedGraphNode.value.id || edge.target === selectedGraphNode.value.id
  })
})

const selectedGraphEditableRelationId = computed(() => {
  if (!selectedGraphNode.value) return null
  if (selectedGraphNode.value.manual_relation_id) return selectedGraphNode.value.manual_relation_id
  const relationIds = [...new Set(selectedGraphManualEdges.value.map((edge) => edge.relation_id).filter(Boolean))]
  return relationIds.length === 1 ? relationIds[0] : null
})

const graphStatusLabel = computed(() => {
  if (props.graphLoading) return '检查中'
  if (props.graphHealth?.error) return '状态获取失败'
  if (!props.graphHealth?.enabled) return '未启用'
  if (props.graphHealth?.connected) return '已连接'
  return '待检查'
})

const graphTagType = computed(() => {
  if (props.graphLoading) return 'info'
  if (props.graphHealth?.error) return 'danger'
  if (!props.graphHealth?.enabled) return 'info'
  if (props.graphHealth?.connected) return 'success'
  return 'warning'
})

const graphEnabledText = computed(() => {
  if (props.graphHealth?.error) return '状态获取失败'
  return props.graphHealth?.enabled ? '已启用' : '未启用'
})

const graphConnectedText = computed(() => {
  if (props.graphHealth?.error) return '状态获取失败'
  if (!props.graphHealth?.enabled) return '未启用'
  return props.graphHealth?.connected ? '连接正常' : '连接待检查'
})

const graphSummaryText = computed(() => {
  if (props.graphLoading) {
    return '正在检查关系图谱层状态，稍后就可以看到关系线索是否已经生效。'
  }
  if (props.graphHealth?.error) {
    return '当前未能成功获取关系图谱状态，请稍后重试；系统仍会基于规则画像、贝叶斯辅助层和专家研判继续运行。'
  }
  if (!props.graphHealth?.enabled) {
    return '当前未启用关系图谱层，系统仍会基于规则画像、贝叶斯辅助层和专家研判继续运行。'
  }
  if (props.graphHealth?.connected) {
    return '关系图谱层已连接，可用于发现学生之间的共现冲突、融入线索等关系型事实。'
  }
  return '关系图谱层已配置但连接尚未确认，建议先手动同步一次，再观察是否生成图谱线索。'
})

const graphStatusHint = computed(() => {
  if (props.graphAutoSync?.status === 'syncing') {
    return props.graphAutoSync.message || '系统正在根据最新关怀数据自动刷新关系图谱。'
  }
  if (props.graphAutoSync?.status === 'success') {
    const timeText = props.graphAutoSync?.synced_at ? `：${props.graphAutoSync.synced_at}` : ''
    return `${props.graphAutoSync.message || '系统已自动刷新关系图谱'}${timeText}`
  }
  if (props.graphAutoSync?.status === 'error') {
    return props.graphAutoSync.message || '自动刷新关系图谱失败，请稍后重试或手动同步。'
  }
  if (props.graphLastSync?.synced_at) {
    return `本次手动同步已完成：${props.graphLastSync.synced_at}`
  }
  if (props.graphHealth?.reason) {
    return `系统提示：${props.graphHealth.reason}`
  }
  return ''
})

const groupedSignals = computed(() => dimensionMeta
  .map((item) => ({
    dimension: item.signalKey,
    label: item.label,
    items: groupedSignalsMap.value[item.signalKey] || []
  }))
  .filter((item) => item.items.length))

const displayAgentDimensions = computed(() =>
  (props.agentResult?.result?.dimensions || []).map((item) => ({
    ...item,
    evidence: normalizeEvidenceList(item?.evidence)
  }))
)
const agentMajorIncidentMode = computed(() => Boolean(props.agentResult?.result?.major_incident_mode))
const agentSecondaryImpacts = computed(() => props.agentResult?.result?.secondary_impacts || [])

const expertOutputs = computed(() => {
  const outputs = props.agentResult?.expert_outputs || []
  const order = dimensionMeta.map((item) => item.signalKey)
  return [...outputs]
    .sort((a, b) => order.indexOf(a.dimension) - order.indexOf(b.dimension))
    .map((item) => ({
      ...item,
      result: {
        ...(item.result || {}),
        evidence: normalizeEvidenceList(item.result?.evidence)
      },
      view: buildExpertViewModel(item)
    }))
})

function placeArcNodes(nodes, nodeMap, centerX, centerY, radius, startDeg, endDeg) {
  if (!nodes.length) return
  const step = nodes.length === 1 ? 0 : (endDeg - startDeg) / (nodes.length - 1)
  nodes.forEach((item, index) => {
    const angle = (startDeg + (step * index)) * (Math.PI / 180)
    const x = centerX + (radius * Math.cos(angle))
    const y = centerY + (radius * Math.sin(angle))
    const node = nodeMap.get(item.id)
    if (node) {
      node.x = Number(x.toFixed(2))
      node.y = Number(y.toFixed(2))
    }
  })
}

function graphNodeRadius(node) {
  if (node?.focus) return 34
  if (node?.type === 'class') return 28
  if (node?.type === 'event' || node?.type === 'manual_event') return 24
  return 26
}

function graphNodeFill(node) {
  if (node?.focus) return '#2563eb'
  if (node?.type === 'class') return '#0f766e'
  if (node?.group === 'safety') return '#ef4444'
  if (node?.group === 'behavior') return '#f59e0b'
  return '#14b8a6'
}

function graphNodeStroke(node) {
  if (node?.focus) return '#bfdbfe'
  if (node?.type === 'class') return '#99f6e4'
  if (node?.group === 'safety') return '#fecaca'
  if (node?.group === 'behavior') return '#fde68a'
  return '#99f6e4'
}

function graphNodeLabel(node) {
  return String(node?.label || '')
    .slice(0, node?.type === 'event' ? 6 : 8)
}

function graphNodeSubtitle(node) {
  if (node?.type === 'event') {
    const levelMap = {
      low: '低',
      medium: '中',
      high: '高'
    }
    return levelMap[node?.subtitle] ? `${levelMap[node.subtitle]}风险` : '事件'
  }
  if (node?.type === 'class') return node?.subtitle || '班级'
  return node?.subtitle ? String(node.subtitle).slice(-6) : ''
}

function graphNodeTooltip(node) {
  if (!node) return ''
  const parts = [node.label]
  if (node.subtitle) parts.push(node.subtitle)
  if (node.description) parts.push(node.description)
  return parts.join(' / ')
}

function graphNodeTypeLabel(node) {
  if (node?.focus) return '当前关注学生'
  if (node?.type === 'class') return '班级节点'
  if (node?.type === 'classmate') return '同班同学'
  if (node?.type === 'related_student') return '手工关联同学'
  if (node?.type === 'manual_event') return '手工关联事件'
  if (node?.group === 'safety') return '安全事件'
  if (node?.group === 'behavior') return '行为事件'
  if (node?.type === 'event') return '行为事件'
  return '关系节点'
}

function graphNodeDetailText(node) {
  if (!node) return ''
  if (node.description) return node.description
  if (node.type === 'class') {
    return `该节点表示学生当前所属班级：${node.label}。`
  }
  if (node.type === 'classmate') {
    return `${node.label} 是与当前学生处于同一班级的同学节点。`
  }
  if (node.type === 'related_student') {
    return node.description || `${node.label} 是老师手工补录的关联同学关系。`
  }
  if (node.type === 'manual_event') {
    return node.description || `${node.label} 是老师手工补录的关联事件。`
  }
  if (node.focus) {
    return `${node.label} 是当前关怀画像的中心学生节点。`
  }
  return `${node.label} 是当前关系网络中的关联节点。`
}

function selectGraphNode(node) {
  selectedGraphNodeId.value = node?.id || ''
}

function clampGraphScale(value) {
  return Math.min(2.4, Math.max(0.6, Number(value || 1)))
}

function zoomGraph(delta) {
  graphScale.value = clampGraphScale(graphScale.value + delta)
}

function resetGraphViewport() {
  graphScale.value = 1
  graphOffsetX.value = 0
  graphOffsetY.value = 0
  graphDragging.value = false
}

function handleGraphWheel(event) {
  const next = graphScale.value + (event.deltaY < 0 ? 0.12 : -0.12)
  graphScale.value = clampGraphScale(next)
}

function startGraphDrag(event) {
  if (event.button !== 0) return
  graphDragging.value = true
  graphDragStartX.value = event.clientX - graphOffsetX.value
  graphDragStartY.value = event.clientY - graphOffsetY.value
}

function handleGraphDrag(event) {
  if (!graphDragging.value) return
  graphOffsetX.value = event.clientX - graphDragStartX.value
  graphOffsetY.value = event.clientY - graphDragStartY.value
}

function stopGraphDrag() {
  graphDragging.value = false
}

function openGraphDialog() {
  if (!graphViewModel.value?.nodes?.length) return
  resetGraphViewport()
  const focusNode = graphViewModel.value.nodes.find((item) => item.focus) || graphViewModel.value.nodes[0]
  selectGraphNode(focusNode)
  graphViewDialogVisible.value = true
}

async function openGraphMaintenance() {
  graphViewDialogVisible.value = false
  sectionState.value.data = true
  await nextTick()
  dataTabsRef.value?.openGraphTab?.()
}

function buildGraphRelationPrefillFromNode(node) {
  if (!node) {
    return {
      target_type: 'student',
      dimension: 'social',
      relation_type: 'peer_support',
      relation_level: 'medium',
      summary: ''
    }
  }

  if (node.type === 'manual_event' && node.manual_relation_id) {
    return null
  }

  if (node.type === 'event') {
    return {
      target_type: 'event',
      event_title: node.label || '',
      occurred_at: node.occurred_at || '',
      dimension: node.group === 'safety' ? 'safety' : 'behavior',
      relation_type: 'concern',
      relation_level: node.subtitle || 'medium',
      summary: node.description || ''
    }
  }

  if (!node.focus && (node.type === 'classmate' || node.type === 'related_student')) {
    return {
      target_type: 'student',
      target_student_id: node.entity_id || null,
      dimension: 'social',
      relation_type: 'peer_support',
      relation_level: 'medium',
      summary: node.description || ''
    }
  }

  return {
    target_type: 'student',
    dimension: 'social',
    relation_type: 'peer_support',
    relation_level: 'medium',
    summary: node.description || ''
  }
}

async function createGraphRelationFromSelection() {
  graphViewDialogVisible.value = false
  sectionState.value.data = true
  await nextTick()
  dataTabsRef.value?.openCreateGraphRelation?.(buildGraphRelationPrefillFromNode(selectedGraphNode.value))
}

async function editSelectedGraphRelation() {
  if (!selectedGraphEditableRelationId.value) return
  graphViewDialogVisible.value = false
  sectionState.value.data = true
  await nextTick()
  dataTabsRef.value?.openEditGraphRelationById?.(selectedGraphEditableRelationId.value)
}

function closeGraphDialog() {
  graphViewDialogVisible.value = false
  stopGraphDrag()
}

function formatPercent(value) {
  return `${Math.round((Number(value || 0)) * 100)}%`
}

function isSectionOpen(key) {
  return sectionState.value[key] !== false
}

function toggleSection(key) {
  sectionState.value[key] = !isSectionOpen(key)
}

function formatScoreDecimal(value) {
  return Number(value || 0).toFixed(4)
}

function formatSignedScore(value, digits = 2) {
  const number = Number(value || 0)
  if (number > 0) return `+${number.toFixed(digits)}`
  if (number < 0) return number.toFixed(digits)
  return (0).toFixed(digits)
}

function formatScoreBreakdownLabel(row) {
  const label = String(row?.label || '')
  if (label.includes('补充证据')) return '补充线索'
  return label
}

function formatScoreBreakdownDisplay(row) {
  const label = String(row?.label || '')
  const value = Number(row?.value || 0)
  if (label.includes('基础得分') || label.includes('最终得分')) {
    return value.toFixed(2)
  }
  return formatSignedScore(value, 2)
}

function formatScoreBreakdownNote(row, dimension) {
  const label = String(row?.label || '')
  const note = String(row?.note || '').trim()
  const value = Number(row?.value || 0)
  const dimLabel = dimensionLabel(dimension)
  if (!note) return ''

  if (label.includes('基础得分')) {
    return `这是${dimLabel}当前的规则画像基础分。`
  }
  if (label.includes('补充证据')) {
    return note.replace('当前缺少', '当前暂缺')
  }
  if (label.includes('贝叶斯修正')) {
    const match = note.match(/([0-9]+(?:\.[0-9]+)?)/)
    const posteriorText = match ? `（后验概率约 ${Math.round(Number(match[1]) * 100)}%）` : ''
    if (Math.abs(value) < 0.005) {
      return `结合现有线索与先验判断，贝叶斯辅助层暂未对该维度得分产生明显修正${posteriorText}。`
    }
    return `结合现有线索与先验判断，贝叶斯辅助层对该维度得分做了${value > 0 ? '上调' : '下调'}${posteriorText}。`
  }
  if (label.includes('最终得分')) {
    return `${dimLabel}当前最终判定得分。`
  }
  return note
}

function normalizeSummaryText(summary) {
  return String(summary || '')
    .replace(/\s+/g, ' ')
    .replace(/[。．]{2,}/g, '。')
    .trim()
}

function buildDimensionSummaryLead(item) {
  const dimension = item?.dimension || ''
  const label = dimensionLabel(dimension)
  const score = Number(item?.score || 0)
  if (score >= 0.7) {
    return `${label}当前处于高风险水平，建议优先跟进并尽快核实相关情况。`
  }
  if (score >= 0.5) {
    return `${label}当前处于中度风险水平，建议尽快持续跟进。`
  }
  if (score >= 0.3) {
    return `${label}当前存在需要关注的线索，建议继续观察并补充事实依据。`
  }
  return `${label}当前整体风险较低，建议保持常规关注。`
}

function buildDimensionSummaryDetail(item) {
  const summary = normalizeSummaryText(item?.summary)
  if (!summary) return ''
  const lead = normalizeSummaryText(buildDimensionSummaryLead(item))
  if (summary === lead) return ''

  const genericLow = ['风险较低', '保持常规关注']
  const genericAttention = ['持续关注', '继续观察']
  const score = Number(item?.score || 0)

  if (score < 0.3 && genericLow.every((part) => summary.includes(part))) {
    return ''
  }
  if (score >= 0.3 && score < 0.5 && genericAttention.some((part) => summary.includes(part)) && summary.length <= 24) {
    return ''
  }
  return summary
}

function buildExpertViewModel(item) {
  const result = item?.result || {}
  const lead = buildDimensionSummaryLead(result || { dimension: item?.dimension })
  const detail = buildDimensionSummaryDetail(result || {})
  const score = Number(result?.score || 0)
  const evidence = normalizeEvidenceList(result?.evidence)
  const primaryEvidence = evidence[0] || ''
  const dimension = item?.dimension || result?.dimension || ''
  const majorIncident = Boolean(props.profile?.major_incident_detected)
  const isSafetyEscalation = majorIncident && dimension === 'safety' && score >= 0.7
  const isIncidentAttention = majorIncident && score >= 0.3
  return {
    lead,
    detail,
    tone: isSafetyEscalation ? '风险升高' : score >= 0.5 ? '明确预警' : isIncidentAttention ? '升级关注' : score >= 0.3 ? '持续关注' : '常规关注',
    evidenceStatus: isSafetyEscalation
      ? '高危安全线索已命中'
      : evidence.length ? `已列出 ${evidence.length} 条依据` : '依据较少',
    focus: isSafetyEscalation
      ? '先核实风险是否仍持续'
      : primaryEvidence ? '先核对首条依据' : '先补充事实核查',
    primaryEvidence,
    consistencyHint: item?.fallback
      ? '本维度当前使用兜底解释，建议结合老师观察补充人工判断。'
      : isSafetyEscalation
        ? '当前不是相对平稳状态，应按安全事件持续性和影响面优先核查。'
        : isIncidentAttention
          ? '当前已进入事件后影响观察阶段，不建议按常规平稳个案理解。'
      : detail
        ? '已按统一结构展示为：结论先行、补充说明随后。'
        : '当前以简要结论为主，适合快速横向比较各维度判断。'
  }
}

const axes = computed(() => {
  const center = 160
  const radius = 110
  return dimensions.value.map((item, index) => {
    const angle = (-Math.PI / 2) + (Math.PI * 2 * index) / dimensions.value.length
    return {
      key: item.key,
      x: center + radius * Math.cos(angle),
      y: center + radius * Math.sin(angle)
    }
  })
})

const labelPoints = computed(() => {
  const center = 160
  const radius = 138
  return dimensions.value.map((item, index) => {
    const angle = (-Math.PI / 2) + (Math.PI * 2 * index) / dimensions.value.length
    return {
      key: item.key,
      label: item.label,
      x: center + radius * Math.cos(angle),
      y: center + radius * Math.sin(angle)
    }
  })
})

const gridPolygons = computed(() => {
  return [0.25, 0.5, 0.75, 1].map((ratio, index) => ({
    key: `ring-${index}`,
    points: buildPolygonPoints(dimensions.value.map(() => ratio))
  }))
})

const profilePoints = computed(() => {
  const center = 160
  const radius = 110
  return dimensions.value.map((item, index) => {
    const angle = (-Math.PI / 2) + (Math.PI * 2 * index) / dimensions.value.length
    return {
      key: item.key,
      x: center + radius * item.score * Math.cos(angle),
      y: center + radius * item.score * Math.sin(angle)
    }
  })
})

const profilePolygon = computed(() => buildPolygonPoints(dimensions.value.map((item) => item.score)))

function buildPolygonPoints(scores) {
  const center = 160
  const radius = 110
  return scores
    .map((score, index) => {
      const angle = (-Math.PI / 2) + (Math.PI * 2 * index) / scores.length
      const x = center + radius * score * Math.cos(angle)
      const y = center + radius * score * Math.sin(angle)
      return `${x},${y}`
    })
    .join(' ')
}

function riskLabel(level) {
  return {
    low: '低风险',
    attention: '轻度关注',
    medium: '中度风险',
    high: '高风险'
  }[level] || '待评估'
}

function displayRiskLabel(level, options = {}) {
  const { majorIncident = false, overall = false } = options
  if (majorIncident && overall) {
    return {
      low: '事件预警',
      attention: '重点关注',
      medium: '重点干预',
      high: '紧急干预'
    }[level] || riskLabel(level)
  }
  return riskLabel(level)
}

function trendLabel(trend) {
  return {
    up: '上升',
    down: '下降',
    steady: '平稳'
  }[trend] || '平稳'
}

function isolationTrendLabel(direction) {
  return {
    improving: '改善趋势',
    worsening: '恶化趋势',
    stable: '相对平稳'
  }[direction] || '相对平稳'
}

function riskTagType(level) {
  return {
    low: 'success',
    attention: 'warning',
    medium: 'warning',
    high: 'danger'
  }[level] || 'info'
}

function scoreLevel(score) {
  if (score >= 0.7) return 'high'
  if (score >= 0.5) return 'medium'
  if (score >= 0.3) return 'attention'
  return 'low'
}

function sourceLabel(source) {
  return {
    student_tag: '学生标签',
    score: '成绩波动',
    student_status: '学生状态',
    data_gap: '数据缺口',
    attendance: '出勤记录',
    behavior_event: '行为事件',
    family_contact: '家校沟通',
    assistant_summary: '助手摘要',
    agent_social_summary: '智能研判摘要',
    teacher_confirmed_social_evidence: '教师确认线索',
    agent_review: '教师复核',
    care_observation: '关怀观察',
    profile: '画像分数',
    graph: '关系图谱',
    major_incident: '恶性事件传导',
    major_incident_bn: '恶性事件BN传播'
  }[source] || source
}

function dataGapLabel(signalType) {
  return {
    score_missing: '缺少成绩记录',
    attendance_missing: '缺少出勤记录',
    behavior_event_missing: '缺少行为事件',
    care_observation_missing: '缺少关怀观察',
    family_contact_missing: '缺少家校沟通',
    assistant_summary_missing: '缺少助手摘要',
    assistant_signal_missing: '助手摘要未提取信号'
  }[signalType] || signalType
}

function signalBadgeLabel(item) {
  const weight = Number(item?.signal_weight || 0)
  if (item?.source === 'data_gap') return '证据不足'
  if (item?.source === 'major_incident') return '事件后次生风险'
  if (item?.source === 'major_incident_bn') return '前瞻预警'
  if (weight < 0) return '保护性证据'
  if (weight > 0 && weight <= 0.2 && ['attendance', 'behavior_event', 'score'].includes(item?.source)) {
    return '历史影响已衰减'
  }
  return ''
}

function signalBadgeClass(item) {
  const weight = Number(item?.signal_weight || 0)
  if (item?.source === 'data_gap') return 'evidence-chip--gap'
  if (item?.source === 'major_incident') return 'evidence-chip--incident'
  if (item?.source === 'major_incident_bn') return 'evidence-chip--incident'
  if (weight < 0) return 'evidence-chip--positive'
  if (weight > 0 && weight <= 0.2 && ['attendance', 'behavior_event', 'score'].includes(item?.source)) {
    return 'evidence-chip--attenuated'
  }
  return ''
}

function isBnSuggestedDimension(dimension) {
  return (props.signals || []).some((item) =>
    item?.source === 'major_incident_bn' && item?.dimension === dimension
  )
}

function buildIncidentImpactNote(dimension) {
  if (dimension === 'study' && isBnSuggestedDimension(dimension)) {
    return '当前主要来自 BN 前瞻判断，表示已进入建议核查阶段，不直接等同于已出现明确学习异常。'
  }
  return '当前已进入事件后次生风险范围，建议结合老师观察继续核实。'
}

function dimensionLabel(dimension) {
  return {
    emotion: '情绪状态',
    social: '社交融入',
    safety: '校园安全',
    family: '家庭支持',
    study: '学习压力',
    behavior: '行为稳定'
  }[dimension] || dimension
}

function formatJson(value) {
  if (!value) return '-'
  try {
    return JSON.stringify(value, null, 2)
  } catch (error) {
    return String(value)
  }
}

function normalizeEvidenceList(evidence) {
  if (!Array.isArray(evidence)) return []
  return evidence
    .map((item) => {
      if (typeof item === 'string') return item
      if (item && typeof item === 'object') return item.text || item.key || item.type || ''
      return String(item || '')
    })
    .map((item) => item.trim())
    .filter(Boolean)
}

function isGraphEvidence(value) {
  return String(value || '').startsWith('关系图谱：')
}

function stripGraphEvidencePrefix(value) {
  return String(value || '').replace(/^关系图谱：/, '').trim()
}

function graphEvidenceChipLabel(dimension) {
  return {
    social: '社交图谱',
    safety: '安全图谱',
    family: '家庭图谱',
    emotion: '情绪图谱',
    study: '学习图谱',
    behavior: '行为图谱'
  }[dimension] || '关系图谱'
}

function setGraphGroupRef(dimension, el) {
  if (!dimension) return
  if (el) {
    graphGroupRefs.value[dimension] = el
    return
  }
  delete graphGroupRefs.value[dimension]
}

async function focusGraphGroup(dimension) {
  if (!dimension) return
  sectionState.value.graph = true
  activeGraphGroup.value = dimension
  await nextTick()
  const target = graphGroupRefs.value[dimension]
  if (target?.scrollIntoView) {
    target.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }
  window.setTimeout(() => {
    if (activeGraphGroup.value === dimension) {
      activeGraphGroup.value = ''
    }
  }, 1800)
}

function humanizeAgentError(error) {
  const text = String(error || '')
  if (!text) return ''
  if (text.toLowerCase().includes('json')) return '本次智能研判输出格式不稳定，系统已自动采用更稳妥的结果。'
  if (text.toLowerCase().includes('timeout') || text.includes('超时')) return '本次智能研判响应超时，系统已自动采用更稳妥的结果。'
  if (text.toLowerCase().includes('validation error') || text.toLowerCase().includes('pydantic')) {
    return '本次智能研判返回内容不够规范，系统已自动整理并采用更稳妥的结果。'
  }
  return text
}

function humanizeExpertError(error, dimension) {
  const text = String(error || '')
  if (!text) return ''
  const label = dimensionLabel(dimension)
  if (text.toLowerCase().includes('validation error') || text.toLowerCase().includes('pydantic')) {
    return `${label}专家输出格式不够规范，系统已自动切换为兜底结果。`
  }
  if (text.toLowerCase().includes('json')) {
    return `${label}专家输出格式不稳定，系统已自动切换为兜底结果。`
  }
  if (text.toLowerCase().includes('timeout') || text.includes('超时')) {
    return `${label}专家响应超时，系统已自动切换为兜底结果。`
  }
  return text
}

function handleHistoryPageChange({ page }) {
  if (!page) return
  emit('agent-history-page-change', page)
}

function handleDataChanged(payload) {
  emit('data-changed', payload)
}

function cloneJson(value) {
  return JSON.parse(JSON.stringify(value || {}))
}

function openReviewDialog() {
  const result = cloneJson(props.agentResult?.reviewed_result || props.agentResult?.result || {})
  reviewForm.value = {
    teacher_notes: props.agentResult?.teacher_notes || '',
    resolution_status: props.agentResult?.resolution_status || 'pending',
    review_labels: {
      scene: props.agentResult?.review_labels?.scene || 'other',
      is_true_risk: props.agentResult?.review_labels?.is_true_risk || 'unknown',
      severity: props.agentResult?.review_labels?.severity || 'unknown',
      confidence_by_teacher: Number(props.agentResult?.review_labels?.confidence_by_teacher || 3),
      intervention_taken: props.agentResult?.review_labels?.intervention_taken || '',
      follow_up_outcome: props.agentResult?.review_labels?.follow_up_outcome || ''
    },
    reviewed_result: {
      ...result,
      suggestions: result.suggestions || [],
      dimensions: (result.dimensions || []).map((item) => ({
        ...item,
        evidence: normalizeEvidenceList(item.evidence)
      }))
    }
  }
  reviewDialogVisible.value = true
}

function addEvidence(dimension) {
  if (!Array.isArray(dimension.evidence)) {
    dimension.evidence = []
  }
  dimension.evidence.push('')
}

function removeEvidence(dimension, index) {
  dimension.evidence.splice(index, 1)
}

function addSuggestion() {
  reviewForm.value.reviewed_result.suggestions.push('')
}

function removeSuggestion(index) {
  reviewForm.value.reviewed_result.suggestions.splice(index, 1)
}

function submitReview() {
  emit('agent-review', {
    recordId: props.agentResult?.record_id || props.agentResult?.id,
    reviewedResult: reviewForm.value.reviewed_result,
    teacherNotes: reviewForm.value.teacher_notes,
    resolutionStatus: reviewForm.value.resolution_status,
    reviewLabels: reviewForm.value.review_labels
  })
  reviewDialogVisible.value = false
}
</script>

<style scoped lang="scss">
.care-student-card,
.chart-card,
.signal-card,
.action-card,
.agent-card,
.agent-history-card,
.expert-card {
  border-radius: 20px;
  background: #fff;
  border: 1px solid rgba(148, 163, 184, 0.18);
  box-shadow: 0 10px 30px rgba(15, 23, 42, 0.05);
}

.care-student-card {
  padding: 18px 20px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.care-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.student-name {
  font-size: 18px;
  font-weight: 700;
  color: #16202c;
}

.student-meta {
  margin-top: 6px;
  font-size: 13px;
  color: #627389;
}

.care-loading {
  margin-top: 16px;
}

.chart-card {
  margin-top: 16px;
  padding: 20px;
  display: grid;
  grid-template-columns: 1fr 170px;
  gap: 18px;
}

.chart-card.risk-high {
  background: linear-gradient(135deg, rgba(254, 226, 226, 0.75) 0%, rgba(255, 255, 255, 0.96) 56%);
}

.chart-card.risk-medium,
.chart-card.risk-attention {
  background: linear-gradient(135deg, rgba(255, 237, 213, 0.72) 0%, rgba(255, 255, 255, 0.96) 58%);
}

.chart-card.risk-low {
  background: linear-gradient(135deg, rgba(220, 252, 231, 0.72) 0%, rgba(255, 255, 255, 0.96) 58%);
}

.chart-shell {
  display: flex;
  align-items: center;
  justify-content: center;
}

.radar-svg {
  width: 100%;
  max-width: 320px;
  height: auto;
}

.grid-ring,
.grid-axis {
  fill: none;
  stroke: rgba(100, 116, 139, 0.24);
  stroke-width: 1;
}

.profile-area {
  fill: rgba(239, 68, 68, 0.22);
  stroke: rgba(220, 38, 38, 0.85);
  stroke-width: 2;
}

.profile-point {
  fill: #dc2626;
}

.axis-label {
  fill: #425569;
  font-size: 12px;
  text-anchor: middle;
}

.chart-summary {
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.summary-title {
  font-size: 13px;
  color: #64748b;
}

.summary-score {
  margin-top: 8px;
  font-size: 34px;
  font-weight: 800;
  color: #b91c1c;
}

.summary-trend,
.summary-updated {
  margin-top: 10px;
  font-size: 13px;
  color: #4b5563;
  line-height: 1.6;
}

.dimension-list {
  margin-top: 16px;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.dimension-item {
  padding: 14px 16px;
  border-radius: 16px;
  background: #fff;
  border: 1px solid rgba(148, 163, 184, 0.16);
}

.dimension-head {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
  color: #334155;
  font-weight: 600;
}

.dimension-bar {
  margin-top: 10px;
  height: 10px;
  border-radius: 999px;
  background: #edf2f7;
  overflow: hidden;
}

.dimension-fill {
  height: 100%;
  border-radius: inherit;
}

.dimension-fill.risk-low { background: #22c55e; }
.dimension-fill.risk-attention { background: #facc15; }
.dimension-fill.risk-medium { background: #fb923c; }
.dimension-fill.risk-high { background: #ef4444; }

.dimension-reasons,
.dimension-empty {
  margin-top: 10px;
}

.dimension-reason,
.dimension-empty {
  font-size: 12px;
  line-height: 1.6;
  color: #64748b;
}

.signal-card,
.action-card,
.agent-card,
.agent-history-card,
.expert-card {
  margin-top: 16px;
  padding: 18px 20px;
}

.section-title {
  font-size: 15px;
  font-weight: 700;
  color: #1f2937;
  display: flex;
  align-items: center;
  gap: 8px;
}

.section-toggle {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 0;
  margin: 0;
  border: none;
  background: transparent;
  cursor: pointer;
  text-align: left;
}

.section-toggle-text {
  flex-shrink: 0;
  font-size: 12px;
  font-weight: 600;
  color: #64748b;
}

.section-toggle + .section-title {
  display: none;
}

.agent-fallback {
  font-size: 12px;
  color: #dc2626;
  font-weight: 600;
}

.signal-list {
  margin-top: 14px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.signal-group {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.signal-group-title {
  font-size: 13px;
  font-weight: 700;
  color: #1f2937;
}

.signal-item {
  padding: 14px 16px;
  border-radius: 16px;
  background: #f8fafc;
}

.signal-top {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}

.signal-dimension {
  font-size: 12px;
  font-weight: 700;
  color: #1d4ed8;
}

.signal-weight {
  font-size: 12px;
  color: #64748b;
}

.signal-text {
  margin-top: 8px;
  line-height: 1.7;
  color: #334155;
}

.signal-badge-row {
  margin-top: 8px;
}

.signal-source {
  margin-top: 8px;
  font-size: 12px;
  color: #94a3b8;
}

.agent-body {
  margin-top: 12px;
  display: grid;
  gap: 16px;
}

.agent-breakdown {
  padding: 12px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.7);
  border: 1px solid rgba(148, 163, 184, 0.18);
}

.agent-breakdown-note {
  margin-top: 6px;
  font-size: 12px;
  color: #9a7a44;
}

.agent-breakdown-formula {
  margin-top: 8px;
  font-size: 12px;
  color: #64748b;
}

.agent-breakdown-list {
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.agent-breakdown-item {
  display: grid;
  grid-template-columns: 1fr 140px 90px;
  gap: 8px;
  font-size: 13px;
  color: #1f2937;
}

.agent-breakdown-total {
  margin-top: 10px;
  font-size: 13px;
  color: #475569;
}

.agent-overall {
  padding: 14px 16px;
  border-radius: 16px;
  background: #f8fafc;
}

.agent-score {
  font-size: 26px;
  font-weight: 800;
  color: #dc2626;
}

.agent-level {
  margin-top: 6px;
  font-size: 14px;
  font-weight: 700;
  color: #1f2937;
}

.agent-meta {
  margin-top: 6px;
  font-size: 12px;
  color: #64748b;
}

.agent-review-row {
  margin-top: 10px;
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.agent-error {
  margin-top: 6px;
  font-size: 12px;
  color: #dc2626;
}

.agent-incident-card {
  display: grid;
  gap: 10px;
  padding: 12px 14px;
  border-radius: 14px;
  background: linear-gradient(135deg, rgba(255, 245, 245, 0.96) 0%, rgba(255, 250, 250, 0.98) 100%);
  border: 1px solid rgba(239, 68, 68, 0.14);
}

.agent-dimensions {
  display: grid;
  gap: 12px;
}

.agent-dimension {
  padding: 12px 14px;
  border-radius: 14px;
  background: #fff;
  border: 1px solid rgba(148, 163, 184, 0.16);
}

.agent-dimension-head {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
  font-weight: 600;
  color: #1f2937;
}

.agent-dimension-summary {
  margin-top: 8px;
  font-size: 12px;
  color: #475569;
  line-height: 1.6;
}

.agent-dimension-detail {
  margin-top: 6px;
  font-size: 12px;
  color: #6b7280;
  line-height: 1.6;
}

.agent-evidence {
  margin-top: 8px;
  padding-left: 16px;
  color: #64748b;
  font-size: 12px;
  line-height: 1.6;
}

.evidence-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin-bottom: 4px;
}

.evidence-chip {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
  line-height: 1.4;
  white-space: nowrap;
}

.evidence-chip--graph {
  color: #047857;
  background: rgba(16, 185, 129, 0.12);
  border: 1px solid rgba(16, 185, 129, 0.18);
}

.evidence-chip--positive {
  color: #0f766e;
  background: rgba(20, 184, 166, 0.12);
  border: 1px solid rgba(20, 184, 166, 0.18);
}

.evidence-chip--gap {
  color: #9a6700;
  background: rgba(250, 204, 21, 0.16);
  border: 1px solid rgba(245, 158, 11, 0.2);
}

.evidence-chip--attenuated {
  color: #475569;
  background: rgba(148, 163, 184, 0.14);
  border: 1px solid rgba(148, 163, 184, 0.22);
}

.evidence-chip--incident {
  color: #b42318;
  background: rgba(239, 68, 68, 0.12);
  border: 1px solid rgba(239, 68, 68, 0.18);
}

.evidence-chip--button {
  cursor: pointer;
}

.dimension-score-box {
  margin-top: 10px;
  padding: 10px 12px;
  border-radius: 12px;
  background: #f8fafc;
  border: 1px solid rgba(148, 163, 184, 0.16);
}

.dimension-score-box--expert {
  background: rgba(255, 255, 255, 0.72);
}

.dimension-score-title {
  font-size: 12px;
  font-weight: 700;
  color: #334155;
}

.dimension-score-row {
  margin-top: 8px;
  display: grid;
  grid-template-columns: 88px 74px 1fr;
  gap: 10px;
  align-items: start;
  font-size: 12px;
  color: #475569;
  line-height: 1.5;
}

.dimension-score-row span:nth-child(2) {
  color: #0f172a;
  font-weight: 700;
}

.dimension-score-explanation {
  margin-top: 8px;
  padding-left: 16px;
  font-size: 12px;
  color: #64748b;
  line-height: 1.6;
}

.incident-card {
  background: linear-gradient(180deg, #fff7f5 0%, #fff1ee 100%);
}

.incident-body {
  margin-top: 14px;
  display: grid;
  gap: 14px;
}

.incident-summary-card {
  padding: 14px;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid rgba(239, 68, 68, 0.14);
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 14px;
}

.incident-summary-main {
  display: grid;
  gap: 6px;
}

.incident-summary-title,
.incident-subtitle,
.agent-incident-title {
  font-size: 13px;
  font-weight: 700;
  color: #991b1b;
}

.incident-summary-text,
.incident-summary-caption,
.incident-propagation-text,
.agent-incident-text {
  font-size: 12px;
  line-height: 1.7;
  color: #475569;
}

.incident-summary-side {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 8px;
}

.incident-evidence-list,
.incident-propagation-list {
  display: grid;
  gap: 8px;
}

.incident-evidence-item,
.incident-propagation-item {
  padding: 10px 12px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.9);
  border: 1px solid rgba(239, 68, 68, 0.12);
}

.incident-impact-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.incident-bn-section {
  display: grid;
  gap: 12px;
}

.incident-bn-summary {
  font-size: 12px;
  line-height: 1.7;
  color: #64748b;
}

.incident-impact-card {
  padding: 12px 14px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid rgba(239, 68, 68, 0.12);
  display: grid;
  gap: 10px;
}

.incident-impact-head,
.incident-propagation-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  font-size: 13px;
  font-weight: 700;
  color: #1f2937;
}

.incident-impact-metrics {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.incident-impact-metric {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  color: #64748b;
}

.incident-impact-metric strong {
  color: #0f172a;
}

.incident-bn-node-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.incident-bn-node-card,
.incident-bn-path-card,
.incident-bn-suggest-card {
  padding: 12px 14px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid rgba(148, 163, 184, 0.16);
}

.incident-bn-node-head,
.incident-bn-path-head,
.incident-bn-suggest-card {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
  font-size: 13px;
  font-weight: 700;
  color: #1f2937;
}

.incident-bn-node-meta,
.incident-bn-path-text {
  margin-top: 6px;
  font-size: 12px;
  line-height: 1.6;
  color: #64748b;
}

.incident-bn-node-evidence {
  margin-top: 8px;
  display: grid;
  gap: 6px;
}

.incident-bn-node-evidence-item {
  font-size: 12px;
  line-height: 1.6;
  color: #475569;
}

.incident-bn-path-list,
.incident-bn-suggest-grid {
  display: grid;
  gap: 10px;
}

.incident-bn-suggest-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.overview-strip {
  margin-top: 12px;
}

.overview-card {
  padding: 12px 14px;
  border-radius: 16px;
  background: linear-gradient(180deg, #fff 0%, #f8fafc 100%);
  border: 1px solid rgba(148, 163, 184, 0.14);
}

.overview-card-title,
.dimension-section-title {
  font-size: 13px;
  font-weight: 700;
  color: #1f2937;
}

.overview-chip-list {
  margin-top: 10px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.quality-chip--neutral {
  color: #475569;
  background: rgba(148, 163, 184, 0.12);
  border: 1px solid rgba(148, 163, 184, 0.16);
}

.quality-chip--focus {
  color: #1d4ed8;
  background: rgba(59, 130, 246, 0.1);
  border: 1px solid rgba(59, 130, 246, 0.16);
}

.dimension-section {
  display: grid;
  gap: 14px;
}

.dimension-secondary {
  display: grid;
  gap: 10px;
}

.dimension-list--secondary .dimension-item {
  background: #fcfdff;
}

.subtle-toggle {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  width: 100%;
  border: none;
  border-radius: 12px;
  background: rgba(148, 163, 184, 0.08);
  color: #475569;
  padding: 10px 12px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}

.dimension-split {
  margin-top: 8px;
  display: flex;
  justify-content: space-between;
  gap: 8px;
  font-size: 12px;
  color: #64748b;
}

.agent-actions-title {
  font-size: 13px;
  font-weight: 700;
  color: #1f2937;
}

.agent-action {
  margin-top: 8px;
  line-height: 1.7;
  color: #334155;
}

.agent-review-card {
  margin-top: 10px;
  padding: 12px 14px;
  border-radius: 12px;
  background: #f8fafc;
  border: 1px solid rgba(148, 163, 184, 0.16);
}

.agent-review-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  font-size: 13px;
  font-weight: 700;
  color: #1f2937;
}

.agent-review-list {
  margin-top: 8px;
  display: grid;
  gap: 8px;
}

.agent-review-item {
  font-size: 12px;
  line-height: 1.7;
  color: #475569;
}

.bayes-card {
  background: linear-gradient(180deg, #f8fbff 0%, #f1f8ff 100%);
}

.graph-card {
  background: linear-gradient(180deg, #f9fcfb 0%, #f4fbf8 100%);
}

.graph-body {
  margin-top: 14px;
  display: grid;
  gap: 14px;
}

.graph-summary-card {
  padding: 14px;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid rgba(16, 185, 129, 0.14);
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 14px;
}

.graph-summary-main {
  display: grid;
  gap: 6px;
}

.graph-summary-title {
  font-size: 13px;
  font-weight: 700;
  color: #065f46;
}

.graph-summary-text,
.graph-summary-hint,
.graph-last-sync {
  font-size: 12px;
  line-height: 1.7;
  color: #475569;
}

.graph-summary-hint {
  padding: 8px 10px;
  border-radius: 10px;
  background: rgba(15, 118, 110, 0.08);
  border: 1px solid rgba(15, 118, 110, 0.12);
}

.graph-summary-side {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 10px;
}

.graph-metric-list {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.graph-metric {
  padding: 12px 14px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.88);
  border: 1px solid rgba(16, 185, 129, 0.12);
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.graph-metric-label {
  font-size: 12px;
  color: #64748b;
}

.graph-visual-card {
  padding: 14px;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid rgba(16, 185, 129, 0.14);
  display: grid;
  gap: 12px;
}

.graph-visual-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
}

.graph-visual-title {
  font-size: 13px;
  font-weight: 700;
  color: #0f172a;
}

.graph-visual-caption {
  margin-top: 4px;
  font-size: 12px;
  color: #64748b;
}

.graph-visual-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: flex-end;
  font-size: 12px;
  color: #475569;
}

.graph-visual-stats span {
  padding: 4px 8px;
  border-radius: 999px;
  background: rgba(15, 118, 110, 0.08);
}

.graph-visual-shell {
  border-radius: 16px;
  background:
    radial-gradient(circle at 50% 50%, rgba(148, 163, 184, 0.08) 0, rgba(148, 163, 184, 0.02) 34%, transparent 70%),
    linear-gradient(180deg, rgba(248, 250, 252, 0.96) 0%, rgba(241, 245, 249, 0.9) 100%);
  border: 1px solid rgba(148, 163, 184, 0.16);
  overflow: hidden;
}

.graph-visual-shell--button {
  width: 100%;
  padding: 0;
  cursor: zoom-in;
  text-align: left;
}

.graph-visual-svg {
  display: block;
  width: 100%;
  height: auto;
}

.graph-visual-svg--large {
  min-height: 520px;
}

.graph-edge {
  stroke-linecap: round;
  opacity: 0.9;
}

.graph-edge--same_class {
  stroke: rgba(37, 99, 235, 0.28);
  stroke-width: 2.5;
}

.graph-edge--in_class {
  stroke: rgba(15, 118, 110, 0.35);
  stroke-width: 2.5;
  stroke-dasharray: 5 5;
}

.graph-edge--involved_in {
  stroke: rgba(148, 163, 184, 0.7);
  stroke-width: 2;
}

.graph-node-label,
.graph-node-subtitle {
  text-anchor: middle;
  pointer-events: none;
}

.graph-node-label {
  fill: #fff;
  font-size: 11px;
  font-weight: 700;
}

.graph-node-label--large {
  font-size: 13px;
}

.graph-node-subtitle {
  fill: rgba(255, 255, 255, 0.88);
  font-size: 10px;
}

.graph-node-subtitle--large {
  font-size: 11px;
}

.graph-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 10px 14px;
  font-size: 12px;
  color: #475569;
}

.graph-legend-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.graph-legend-dot {
  width: 10px;
  height: 10px;
  border-radius: 999px;
  display: inline-block;
}

.graph-legend-dot--focus { background: #2563eb; }
.graph-legend-dot--peer { background: #14b8a6; }
.graph-legend-dot--class { background: #0f766e; }
.graph-legend-dot--safety { background: #ef4444; }
.graph-legend-dot--behavior { background: #f59e0b; }

.graph-dialog-body {
  display: grid;
  gap: 14px;
}

.graph-dialog-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 300px;
  gap: 14px;
  align-items: start;
}

.graph-dialog-stage {
  display: grid;
  gap: 10px;
}

.graph-dialog-toolbar {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
}

.graph-dialog-toolbar-left,
.graph-dialog-toolbar-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.graph-dialog-scale {
  font-size: 12px;
  font-weight: 700;
  color: #1e3a8a;
}

.graph-dialog-hint {
  font-size: 12px;
  color: #64748b;
}

.graph-dialog-summary {
  padding: 14px 16px;
  border-radius: 16px;
  background: linear-gradient(135deg, rgba(239, 246, 255, 0.9) 0%, rgba(248, 250, 252, 0.96) 100%);
  border: 1px solid rgba(59, 130, 246, 0.14);
}

.graph-dialog-title {
  font-size: 14px;
  font-weight: 700;
  color: #1e3a8a;
}

.graph-dialog-text {
  margin-top: 6px;
  font-size: 13px;
  line-height: 1.7;
  color: #475569;
}

.graph-dialog-summary-actions {
  margin-top: 10px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.graph-dialog-shell {
  border-radius: 18px;
  overflow: auto;
  background:
    radial-gradient(circle at 50% 50%, rgba(96, 165, 250, 0.1) 0, rgba(96, 165, 250, 0.03) 34%, transparent 72%),
    linear-gradient(180deg, rgba(248, 250, 252, 0.98) 0%, rgba(241, 245, 249, 0.96) 100%);
  border: 1px solid rgba(148, 163, 184, 0.18);
}

.graph-detail-card {
  padding: 14px;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.96);
  border: 1px solid rgba(148, 163, 184, 0.16);
  box-shadow: 0 12px 24px rgba(15, 23, 42, 0.06);
  display: grid;
  gap: 10px;
  position: sticky;
  top: 0;
}

.graph-detail-title {
  font-size: 13px;
  font-weight: 700;
  color: #0f172a;
}

.graph-detail-name {
  font-size: 18px;
  font-weight: 800;
  color: #1e293b;
}

.graph-detail-type {
  font-size: 12px;
  color: #2563eb;
  font-weight: 700;
}

.graph-detail-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 12px;
  color: #64748b;
}

.graph-detail-meta span {
  padding: 4px 8px;
  border-radius: 999px;
  background: rgba(37, 99, 235, 0.08);
}

.graph-detail-section {
  display: grid;
  gap: 6px;
}

.graph-detail-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.graph-detail-section-title {
  font-size: 12px;
  font-weight: 700;
  color: #334155;
}

.graph-detail-text,
.graph-detail-empty {
  font-size: 13px;
  line-height: 1.7;
  color: #475569;
}

.graph-detail-chip-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.graph-detail-chip {
  border: none;
  border-radius: 999px;
  padding: 6px 10px;
  font-size: 12px;
  color: #0f172a;
  background: rgba(15, 118, 110, 0.1);
  cursor: pointer;
}

.graph-node--interactive {
  cursor: pointer;
}

.graph-node--selected circle {
  filter: drop-shadow(0 0 10px rgba(59, 130, 246, 0.35));
}

.graph-legend--dialog {
  padding-top: 4px;
}

.graph-signal-list {
  display: grid;
  gap: 10px;
}

.graph-signal-group {
  display: grid;
  gap: 10px;
  padding: 8px;
  border-radius: 12px;
  transition: background-color 0.2s ease, box-shadow 0.2s ease;
}

.graph-signal-group--active {
  background: rgba(16, 185, 129, 0.08);
  box-shadow: inset 0 0 0 1px rgba(16, 185, 129, 0.18);
}

.graph-signal-group-title {
  font-size: 13px;
  font-weight: 700;
  color: #1f2937;
}

.graph-signal-title {
  font-size: 13px;
  font-weight: 700;
  color: #1f2937;
}

.graph-signal-item {
  padding: 12px 14px;
  border-radius: 12px;
  background: #fff;
  border: 1px solid rgba(148, 163, 184, 0.16);
}

.graph-signal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  font-size: 12px;
  font-weight: 700;
  color: #0f172a;
}

.graph-signal-text {
  margin-top: 6px;
  font-size: 12px;
  line-height: 1.6;
  color: #475569;
}

.bayes-card-list {
  margin-top: 14px;
  display: grid;
  gap: 14px;
}

.bayes-dimension-card {
  padding: 14px;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid rgba(59, 130, 246, 0.12);
}

.bayes-dimension-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
  font-size: 13px;
  font-weight: 700;
  color: #0f172a;
}

.bayes-summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.bayes-metric {
  padding: 12px 14px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.85);
  border: 1px solid rgba(59, 130, 246, 0.14);
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.bayes-label {
  font-size: 12px;
  color: #64748b;
}

.bayes-evidence {
  margin-top: 14px;
  display: grid;
  gap: 10px;
}

.bayes-evidence-title {
  font-size: 13px;
  font-weight: 700;
  color: #1f2937;
}

.bayes-evidence-item {
  padding: 10px 12px;
  border-radius: 12px;
  background: #fff;
  border: 1px solid rgba(148, 163, 184, 0.16);
}

.bayes-evidence-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  font-size: 12px;
  font-weight: 600;
  color: #0f172a;
}

.bayes-evidence-text {
  margin-top: 6px;
  font-size: 12px;
  line-height: 1.6;
  color: #475569;
}

.expert-empty {
  margin-top: 12px;
  font-size: 12px;
  color: #64748b;
}

.expert-list {
  margin-top: 12px;
  display: grid;
  gap: 12px;
}

.expert-item {
  padding: 12px 14px;
  border-radius: 14px;
  background: #f8fafc;
}

.expert-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  font-size: 13px;
  font-weight: 600;
  color: #1f2937;
}

.expert-meta {
  display: flex;
  gap: 8px;
  align-items: center;
  color: #475569;
}

.expert-summary {
  margin-top: 8px;
  font-size: 12px;
  color: #475569;
  line-height: 1.6;
}

.expert-detail {
  margin-top: 6px;
  font-size: 12px;
  color: #6b7280;
  line-height: 1.6;
}

.expert-consistency-grid {
  margin-top: 10px;
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.expert-consistency-card {
  padding: 10px 12px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.78);
  border: 1px solid rgba(148, 163, 184, 0.16);
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.expert-consistency-label {
  font-size: 12px;
  color: #64748b;
}

.expert-key-point {
  margin-top: 10px;
  font-size: 12px;
  line-height: 1.7;
  color: #334155;
}

.expert-key-point--muted {
  color: #64748b;
}

.expert-evidence {
  margin-top: 8px;
  padding-left: 16px;
  font-size: 12px;
  color: #64748b;
  line-height: 1.6;
}

.expert-error {
  margin-top: 8px;
  font-size: 12px;
  color: #dc2626;
}

.agent-history-list {
  margin-top: 12px;
  display: grid;
  gap: 12px;
}

.history-detail {
  padding: 12px 14px;
  background: #f8fafc;
  border-radius: 12px;
  font-size: 12px;
  color: #475569;
  line-height: 1.6;
}

.history-detail-title {
  margin-top: 10px;
  font-weight: 600;
  color: #1f2937;
}

.history-detail pre {
  margin-top: 6px;
  background: #0f172a;
  color: #e2e8f0;
  padding: 10px;
  border-radius: 8px;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 220px;
  overflow: auto;
}

.action-item {
  margin-top: 12px;
  line-height: 1.7;
  color: #334155;
}

.review-tip {
  margin-bottom: 14px;
  font-size: 13px;
  color: #64748b;
  line-height: 1.6;
}

.review-section-title {
  margin: 6px 0 12px;
  font-size: 14px;
  font-weight: 700;
  color: #1f2937;
}

.review-dimension {
  margin-bottom: 14px;
  padding: 12px;
  border-radius: 12px;
  background: #f8fafc;
  border: 1px solid rgba(148, 163, 184, 0.18);
}

.review-dimension-head {
  margin-bottom: 8px;
  display: flex;
  justify-content: space-between;
  gap: 12px;
  font-size: 13px;
  font-weight: 600;
  color: #1f2937;
}

.review-evidence-list {
  margin-top: 10px;
  display: grid;
  gap: 8px;
}

.review-evidence-row {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 8px;
  align-items: center;
}

.review-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.isolation-body {
  display: grid;
  gap: 16px;
}

.isolation-summary-card,
.isolation-metric-list,
.isolation-cause-list {
  display: grid;
  gap: 12px;
}

.isolation-summary-card {
  grid-template-columns: 1fr auto;
  align-items: center;
  padding: 16px;
  border-radius: 16px;
  background: linear-gradient(135deg, #fff9ed 0%, #fff 100%);
  border: 1px solid #fde4ba;
}

.isolation-summary-title,
.isolation-section-title {
  font-size: 14px;
  font-weight: 700;
  color: #7c3f00;
}

.isolation-summary-text,
.isolation-cause-desc,
.isolation-cause-impact,
.isolation-path-summary,
.isolation-evidence-text {
  color: #5b6475;
  line-height: 1.6;
}

.isolation-metric-list {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.isolation-metric,
.isolation-cause-card,
.isolation-path-card {
  padding: 14px 16px;
  border-radius: 14px;
  border: 1px solid #ebeef5;
  background: #fff;
}

.isolation-metric-label {
  display: block;
  margin-bottom: 6px;
  color: #7a8699;
  font-size: 12px;
}

.isolation-section {
  display: grid;
  gap: 12px;
}

.isolation-coverage-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.isolation-coverage-card {
  padding: 12px 14px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.88);
  border: 1px solid rgba(148, 163, 184, 0.16);
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.isolation-subsection {
  display: grid;
  gap: 10px;
}

.isolation-subsection-title {
  font-size: 12px;
  font-weight: 700;
  color: #334155;
}

.isolation-source-group-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.isolation-source-group-card {
  padding: 12px 14px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid rgba(148, 163, 184, 0.16);
  display: grid;
  gap: 8px;
}

.isolation-source-group-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  font-size: 13px;
  font-weight: 700;
  color: #1f2937;
}

.isolation-source-group-desc {
  font-size: 12px;
  line-height: 1.6;
  color: #64748b;
}

.isolation-trend-card {
  padding: 14px 16px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid rgba(148, 163, 184, 0.16);
  display: grid;
  gap: 8px;
}

.isolation-trend-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  font-size: 13px;
  font-weight: 700;
  color: #0f172a;
}

.isolation-trend-text {
  font-size: 12px;
  line-height: 1.7;
  color: #475569;
}

.isolation-cause-head,
.isolation-path-head,
.isolation-evidence-head,
.isolation-factor-item {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}

.isolation-cause-head,
.isolation-path-head {
  font-weight: 600;
  color: #1f2937;
}

.isolation-evidence-list,
.isolation-path-list,
.isolation-factor-list {
  display: grid;
  gap: 10px;
}

.isolation-evidence-item {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed #e5e7eb;
}

.isolation-evidence-head {
  margin-bottom: 4px;
  color: #6b7280;
  font-size: 12px;
}

.isolation-factor-item {
  padding: 12px 14px;
  border-radius: 12px;
  background: #f7fafc;
  color: #334155;
}

.quality-body {
  display: grid;
  gap: 14px;
}

.quality-summary-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.quality-card {
  padding: 12px 14px;
  border-radius: 14px;
  background: #f8fafc;
  border: 1px solid rgba(148, 163, 184, 0.16);
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.quality-label {
  font-size: 12px;
  color: #64748b;
}

.quality-section {
  display: grid;
  gap: 10px;
}

.quality-section-title {
  font-size: 13px;
  font-weight: 700;
  color: #1f2937;
}

.quality-chip-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.quality-chip {
  display: inline-flex;
  align-items: center;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
}

.quality-chip--gap {
  color: #9a6700;
  background: rgba(250, 204, 21, 0.14);
  border: 1px solid rgba(245, 158, 11, 0.18);
}

.quality-note-list {
  display: grid;
  gap: 10px;
}

.quality-note {
  padding: 12px 14px;
  border-radius: 12px;
  background: #f8fafc;
  border: 1px solid rgba(148, 163, 184, 0.16);
}

.quality-note--positive {
  background: rgba(236, 253, 245, 0.9);
  border-color: rgba(16, 185, 129, 0.16);
}

.quality-note-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  font-size: 12px;
  font-weight: 700;
  color: #334155;
}

.quality-note-text {
  margin-top: 6px;
  font-size: 12px;
  line-height: 1.6;
  color: #475569;
}

.quality-note-action {
  margin-top: 6px;
  font-size: 12px;
  line-height: 1.6;
  color: #7c3f00;
  font-weight: 600;
}

@media (max-width: 768px) {
  .chart-card {
    grid-template-columns: 1fr;
  }

  .dimension-list {
    grid-template-columns: 1fr;
  }

  .bayes-summary {
    grid-template-columns: 1fr;
  }

  .graph-summary-card,
  .graph-metric-list,
  .isolation-metric-list,
  .isolation-coverage-grid,
  .isolation-source-group-list,
  .incident-impact-grid,
  .incident-bn-node-grid,
  .incident-bn-suggest-grid,
  .expert-consistency-grid,
  .quality-summary-grid,
  .review-grid {
    grid-template-columns: 1fr;
  }

  .graph-summary-side {
    align-items: stretch;
  }

  .graph-visual-head {
    flex-direction: column;
  }

  .graph-visual-stats {
    justify-content: flex-start;
  }

  .graph-dialog-layout {
    grid-template-columns: 1fr;
  }

  .graph-detail-card {
    position: static;
  }

  .graph-dialog-toolbar {
    flex-direction: column;
    align-items: flex-start;
  }

  .dimension-score-row {
    grid-template-columns: 1fr;
  }
}
</style>

