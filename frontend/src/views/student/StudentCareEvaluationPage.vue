<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <div class="page-title">研判评估</div>
        <div class="page-subtitle">合并系统研判统计与教师复核评估。</div>
      </div>
      <div class="header-actions">
        <el-button size="small" :loading="loading" @click="fetchAll">刷新</el-button>
        <el-button size="small" @click="exportStats">导出研判统计</el-button>
        <el-button size="small" type="primary" @click="exportSummary">导出评估</el-button>
      </div>
    </div>

    <div class="filter-bar">
      <div class="filter-item">
        <span class="filter-label">时间范围</span>
        <el-date-picker
          v-model="dateRange"
          type="daterange"
          unlink-panels
          range-separator="至"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          value-format="YYYY-MM-DD"
        />
      </div>
      <div v-if="isAdmin" class="filter-item">
        <span class="filter-label">班级</span>
        <el-select v-model="classId" placeholder="全部班级" clearable filterable>
          <el-option v-for="item in classOptions" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
      </div>
      <el-button size="small" type="success" @click="fetchAll">应用筛选</el-button>
    </div>

    <div class="section-title">系统研判概览</div>
    <div class="stats-grid">
      <div class="stats-card">
        <div class="stats-label">研判总量</div>
        <div class="stats-value">{{ formatCount(stats.total) }}</div>
      </div>
      <div class="stats-card">
        <div class="stats-label">兜底率</div>
        <div class="stats-value accent-warn">{{ formatPercent(stats.fallback_rate) }}</div>
      </div>
      <div class="stats-card">
        <div class="stats-label">高风险占比</div>
        <div class="stats-value accent-danger">{{ formatPercent(highRiskRatio) }}</div>
      </div>
      <div class="stats-card">
        <div class="stats-label">模型数量</div>
        <div class="stats-value">{{ formatCount(modelBars.length) }}</div>
      </div>
    </div>

    <div class="panel-grid">
      <div class="panel-card">
        <div class="panel-title">风险等级分布</div>
        <div v-if="riskBars.length" class="bar-list">
          <div v-for="item in riskBars" :key="item.key" class="bar-item">
            <div class="bar-head">
              <span>{{ item.label }}</span>
              <span>{{ formatCount(item.count) }}</span>
            </div>
            <div class="bar-track">
              <div class="bar-fill" :class="item.className" :style="{ width: item.percent + '%' }" />
            </div>
          </div>
        </div>
        <div v-else class="empty-text">暂无数据</div>
      </div>

      <div class="panel-card">
        <div class="panel-title">模型分布</div>
        <div v-if="modelBars.length" class="bar-list">
          <div v-for="item in modelBars" :key="item.key" class="bar-item">
            <div class="bar-head">
              <span>{{ item.label }}</span>
              <span>{{ formatCount(item.count) }}</span>
            </div>
            <div class="bar-track">
              <div class="bar-fill bar-fill-indigo" :style="{ width: item.percent + '%' }" />
            </div>
          </div>
        </div>
        <div v-else class="empty-text">暂无数据</div>
      </div>

      <div class="panel-card panel-wide">
        <div class="panel-title">近 30 天研判趋势</div>
        <div v-if="agentTrendBars.length" class="bar-list compact-list">
          <div v-for="item in agentTrendBars" :key="item.date" class="bar-item">
            <div class="bar-head">
              <span>{{ item.date }}</span>
              <span>{{ formatCount(item.count) }}</span>
            </div>
            <div class="bar-track">
              <div class="bar-fill bar-fill-green" :style="{ width: item.percent + '%' }" />
            </div>
          </div>
        </div>
        <div v-else class="empty-text">暂无数据</div>
      </div>
    </div>

    <div class="insight-card" :class="{ warning: showSystemWarning }">
      <div class="insight-title">研判质量提示</div>
      <div class="insight-body">
        <div v-if="showSystemWarning && stats.fallback_rate > 0.3">兜底率偏高，建议检查模型稳定性或补充数据来源。</div>
        <div v-if="showSystemWarning && highRiskRatio > 0.2">高风险占比较高，建议重点关注对应班级或时间段的异常波动。</div>
        <div v-if="!showSystemWarning">当前研判运行较稳定，暂无明显异常提示。</div>
      </div>
    </div>

    <div class="section-title section-title-spaced">复核效果评估</div>
    <div class="stats-grid">
      <div class="stats-card">
        <div class="stats-label">总研判记录</div>
        <div class="stats-value">{{ formatCount(summary.total_records) }}</div>
      </div>
      <div class="stats-card">
        <div class="stats-label">已复核</div>
        <div class="stats-value">{{ formatCount(summary.confirmed_reviews) }}</div>
        <div class="stats-meta">覆盖率 {{ formatPercent(summary.reviewed_ratio) }}</div>
      </div>
      <div class="stats-card">
        <div class="stats-label">真风险</div>
        <div class="stats-value accent-danger">{{ formatCount(summary.true_risk_count) }}</div>
      </div>
      <div class="stats-card">
        <div class="stats-label">误报</div>
        <div class="stats-value accent-warn">{{ formatCount(summary.false_alarm_count) }}</div>
      </div>
      <div class="stats-card">
        <div class="stats-label">一致率</div>
        <div class="stats-value accent-primary">{{ formatPercent(summary.agreement_rate) }}</div>
      </div>
      <div class="stats-card">
        <div class="stats-label">平均信心</div>
        <div class="stats-value">{{ formatConfidence(summary.avg_teacher_confidence) }}</div>
        <div class="stats-meta">满分 5 分</div>
      </div>
    </div>

    <div class="panel-grid">
      <div class="panel-card panel-wide">
        <div class="panel-title">规则影响洞察</div>
        <div class="stats-grid">
          <div class="stats-card slim-card">
            <div class="stats-label">数据缺口记录</div>
            <div class="stats-value">{{ formatCount(summary.rule_impact.data_gap_record_count) }}</div>
          </div>
          <div class="stats-card slim-card">
            <div class="stats-label">保护性证据</div>
            <div class="stats-value accent-success">{{ formatCount(summary.rule_impact.protective_record_count) }}</div>
          </div>
          <div class="stats-card slim-card">
            <div class="stats-label">历史衰减记录</div>
            <div class="stats-value accent-primary">{{ formatCount(summary.rule_impact.attenuated_record_count) }}</div>
          </div>
          <div class="stats-card slim-card">
            <div class="stats-label">误报且有缺口</div>
            <div class="stats-value accent-warn">{{ formatCount(summary.rule_impact.false_alarm_with_data_gap) }}</div>
          </div>
        </div>
      </div>

      <div class="panel-card">
        <div class="panel-title">场景分布</div>
        <div v-if="sceneBars.length" class="bar-list">
          <div v-for="item in sceneBars" :key="item.key" class="bar-item">
            <div class="bar-head">
              <span>{{ item.label }}</span>
              <span>{{ formatCount(item.count) }}</span>
            </div>
            <div class="bar-track">
              <div class="bar-fill bar-fill-blue" :style="{ width: item.percent + '%' }" />
            </div>
          </div>
        </div>
        <div v-else class="empty-text">暂无数据</div>
      </div>

      <div class="panel-card">
        <div class="panel-title">处理状态</div>
        <div v-if="resolutionBars.length" class="bar-list">
          <div v-for="item in resolutionBars" :key="item.key" class="bar-item">
            <div class="bar-head">
              <span>{{ item.label }}</span>
              <span>{{ formatCount(item.count) }}</span>
            </div>
            <div class="bar-track">
              <div class="bar-fill" :class="item.className" :style="{ width: item.percent + '%' }" />
            </div>
          </div>
        </div>
        <div v-else class="empty-text">暂无数据</div>
      </div>

      <div class="panel-card panel-wide">
        <div class="panel-title">场景下钻</div>
        <el-table :data="sceneBreakdown" size="small" border stripe empty-text="暂无数据">
          <el-table-column prop="scene" label="场景" min-width="120">
            <template #default="{ row }">
              {{ sceneLabels[row.scene] || row.scene }}
            </template>
          </el-table-column>
          <el-table-column prop="review_count" label="复核数" width="90" />
          <el-table-column prop="true_risk_count" label="真风险" width="90" />
          <el-table-column prop="false_alarm_count" label="误报" width="90" />
          <el-table-column prop="unresolved_count" label="未闭环" width="90" />
          <el-table-column label="一致率" width="100">
            <template #default="{ row }">
              {{ formatPercent(row.agreement_rate) }}
            </template>
          </el-table-column>
        </el-table>
      </div>

      <div class="panel-card panel-wide">
        <div class="panel-title">最近复核记录</div>
        <el-table :data="recentReviews" size="small" border stripe empty-text="暂无数据">
          <el-table-column prop="student_name" label="学生" min-width="120" />
          <el-table-column prop="class_name" label="班级" min-width="120" />
          <el-table-column label="场景" min-width="120">
            <template #default="{ row }">
              {{ sceneLabels[row.scene] || row.scene }}
            </template>
          </el-table-column>
          <el-table-column label="老师判断" width="110">
            <template #default="{ row }">
              {{ riskTruthLabel(row.is_true_risk) }}
            </template>
          </el-table-column>
          <el-table-column label="系统等级" width="100">
            <template #default="{ row }">
              {{ systemLevelLabel(row.system_level) }}
            </template>
          </el-table-column>
          <el-table-column label="处理状态" width="100">
            <template #default="{ row }">
              {{ resolutionLabels[row.resolution_status] || row.resolution_status }}
            </template>
          </el-table-column>
          <el-table-column prop="confirmed_at" label="确认时间" min-width="170" />
          <el-table-column label="规则标签" min-width="220" show-overflow-tooltip>
            <template #default="{ row }">
              {{ buildImpactText(row) }}
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <div class="insight-card" :class="{ warning: hasQualityRisk }">
      <div class="insight-title">评估提示</div>
      <div class="insight-body">
        <div v-if="hasQualityRisk && summary.reviewed_ratio < 0.3">当前复核覆盖率偏低，建议先推动老师对高风险记录做结构化确认。</div>
        <div v-if="hasQualityRisk && summary.agreement_rate < 0.6">系统与老师一致率偏低，建议优先检查规则权重、文本极性和时间衰减。</div>
        <div v-if="hasQualityRisk && summary.false_alarm_count > summary.true_risk_count">当前误报数量高于真风险数量，建议优先优化误报控制。</div>
        <div v-if="!hasQualityRisk">当前复核覆盖率与一致率整体可用，可以作为下一轮规则调优的基础视图。</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores/user'
import { getClassList } from '@/api/class_'
import {
  exportStudentCareAgentStats,
  exportStudentCareEvaluationSummary,
  getStudentCareAgentStats,
  getStudentCareEvaluationDetail,
  getStudentCareEvaluationSummary
} from '@/api/studentCare'

const userStore = useUserStore()
const isAdmin = computed(() => userStore.role === 'admin')
const loading = ref(false)
const classOptions = ref([])
const classId = ref('')
const dateRange = ref([formatDate(daysAgo(30)), formatDate(new Date())])
const stats = ref({
  total: 0,
  fallback_rate: 0,
  risk_distribution: { low: 0, attention: 0, medium: 0, high: 0 },
  model_distribution: {},
  daily_trend: []
})
const summary = ref({
  total_records: 0,
  confirmed_reviews: 0,
  reviewed_ratio: 0,
  true_risk_count: 0,
  false_alarm_count: 0,
  unresolved_count: 0,
  agreement_rate: 0,
  avg_teacher_confidence: 0,
  scene_distribution: {},
  severity_distribution: { low: 0, medium: 0, high: 0, unknown: 0 },
  resolution_distribution: { pending: 0, in_progress: 0, resolved: 0, false_alarm: 0 },
  rule_impact: {
    data_gap_record_count: 0,
    protective_record_count: 0,
    attenuated_record_count: 0,
    false_alarm_with_data_gap: 0,
    false_alarm_with_protective: 0,
    teacher_confirmed_with_data_gap: 0,
    teacher_confirmed_with_attenuated: 0
  },
  system_vs_teacher: {
    aligned: 0,
    misaligned: 0,
    system_positive_teacher_yes: 0,
    system_positive_teacher_no: 0,
    system_low_teacher_yes: 0,
    system_low_teacher_no: 0
  },
  trend: []
})
const sceneBreakdown = ref([])
const recentReviews = ref([])
const sceneLabels = {
  social_isolation: '社交孤立',
  emotion: '情绪状态',
  safety: '校园安全',
  family: '家庭支持',
  study: '学业压力',
  behavior: '行为稳定',
  other: '其他'
}
const resolutionLabels = {
  pending: '待处理',
  in_progress: '处理中',
  resolved: '已缓解',
  false_alarm: '误报'
}

const highRiskRatio = computed(() => (stats.value.total ? (stats.value.risk_distribution?.high || 0) / stats.value.total : 0))
const showSystemWarning = computed(() => stats.value.fallback_rate > 0.3 || highRiskRatio.value > 0.2)
const hasQualityRisk = computed(() => Number(summary.value.reviewed_ratio || 0) < 0.3 || Number(summary.value.agreement_rate || 0) < 0.6 || Number(summary.value.false_alarm_count || 0) > Number(summary.value.true_risk_count || 0))
const riskBars = computed(() =>
  buildBars(
    stats.value.risk_distribution,
    { low: '低风险', attention: '关注', medium: '中风险', high: '高风险' },
    { low: 'bar-fill-green', attention: 'bar-fill-amber', medium: 'bar-fill-orange', high: 'bar-fill-red' }
  )
)
const modelBars = computed(() => buildBars(stats.value.model_distribution, {}, {}, false))
const sceneBars = computed(() => buildBars(summary.value.scene_distribution, sceneLabels))
const resolutionBars = computed(() =>
  buildBars(summary.value.resolution_distribution, resolutionLabels, {
    pending: 'bar-fill-slate',
    in_progress: 'bar-fill-orange',
    resolved: 'bar-fill-green',
    false_alarm: 'bar-fill-amber'
  })
)
const agentTrendBars = computed(() => buildTrendBars(stats.value.daily_trend, 'count'))

function buildParams() {
  const [start, end] = dateRange.value || []
  return {
    start_date: start || undefined,
    end_date: end || undefined,
    class_id: isAdmin.value ? classId.value || undefined : undefined
  }
}

function buildBars(source = {}, labels = {}, classes = {}, sortByCount = true) {
  const entries = Object.entries(source || {}).filter(([, count]) => Number(count) > 0)
  const max = Math.max(...entries.map(([, count]) => Number(count)), 1)
  const rows = entries.map(([key, count]) => ({
    key,
    label: labels[key] || key,
    count: Number(count) || 0,
    percent: Math.round(((Number(count) || 0) / max) * 100),
    className: classes[key] || 'bar-fill-blue'
  }))
  return sortByCount ? rows.sort((a, b) => b.count - a.count) : rows
}

function buildTrendBars(rows = [], field) {
  if (!rows.length) return []
  const max = Math.max(...rows.map((item) => Number(item[field]) || 0), 1)
  return rows.map((item) => ({
    date: item.date,
    count: Number(item[field]) || 0,
    percent: Math.round(((Number(item[field]) || 0) / max) * 100)
  }))
}

async function fetchClassOptions() {
  if (!isAdmin.value) return
  try {
    const res = await getClassList({ page: 1, page_size: 200 })
    classOptions.value = (res.list || []).map((item) => ({ value: item.id, label: item.name }))
  } catch (error) {
    console.error('Failed to fetch classes', error)
  }
}

async function fetchAll() {
  loading.value = true
  try {
    const params = buildParams()
    const [statsRes, summaryRes, detailRes] = await Promise.all([
      getStudentCareAgentStats(params),
      getStudentCareEvaluationSummary(params),
      getStudentCareEvaluationDetail(params)
    ])
    stats.value = statsRes || stats.value
    summary.value = summaryRes || summary.value
    sceneBreakdown.value = detailRes?.scene_breakdown || []
    recentReviews.value = detailRes?.recent_reviews || []
  } catch (error) {
    console.error('Failed to fetch care evaluation', error)
  } finally {
    loading.value = false
  }
}

async function exportSummary() {
  await exportFile(() => exportStudentCareEvaluationSummary(buildParams()), 'student-care-evaluation-summary.csv')
}

async function exportStats() {
  await exportFile(() => exportStudentCareAgentStats(buildParams()), 'student-care-agent-stats.csv')
}

async function exportFile(fetcher, filename) {
  try {
    const blob = await fetcher()
    const url = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    link.click()
    window.URL.revokeObjectURL(url)
    ElMessage.success('导出成功')
  } catch (error) {
    ElMessage.error('导出失败')
  }
}

function formatPercent(value) {
  return `${Math.round((Number(value) || 0) * 100)}%`
}

function formatCount(value) {
  return value ? Number(value).toLocaleString() : '0'
}

function formatConfidence(value) {
  const num = Number(value) || 0
  return num ? num.toFixed(1) : '0.0'
}

function riskTruthLabel(value) {
  if (value === 'yes') return '属实'
  if (value === 'no') return '误报'
  return '未标注'
}

function systemLevelLabel(value) {
  if (value === 'high') return '高风险'
  if (value === 'medium') return '中风险'
  if (value === 'attention') return '关注'
  return '低风险'
}

function buildImpactText(row) {
  const tags = []
  if (row.has_data_gap) {
    const missing = (row.missing_sources || []).length ? `（${(row.missing_sources || []).join('、')}）` : ''
    tags.push(`数据缺口${missing}`)
  }
  if (row.has_protective) tags.push('保护性证据')
  if (row.has_attenuated) tags.push('历史信号已衰减')
  return tags.length ? tags.join(' / ') : '无'
}

function daysAgo(days) {
  const date = new Date()
  date.setDate(date.getDate() - days)
  return date
}

function formatDate(value) {
  const date = value instanceof Date ? value : new Date(value)
  return `${date.getFullYear()}-${`${date.getMonth() + 1}`.padStart(2, '0')}-${`${date.getDate()}`.padStart(2, '0')}`
}

onMounted(() => {
  fetchClassOptions()
  fetchAll()
})
</script>

<style scoped lang="scss">
.page-header,.filter-bar,.header-actions,.bar-head{display:flex}
.page-header,.filter-bar{justify-content:space-between;align-items:center;gap:12px}
.page-header{margin-bottom:16px}.filter-bar{flex-wrap:wrap;margin-bottom:16px;padding:14px 16px;border-radius:18px;background:linear-gradient(135deg,rgba(255,255,255,.98),rgba(243,247,255,.95));border:1px solid rgba(125,149,179,.18);box-shadow:0 14px 28px rgba(16,24,40,.05)}
.page-title{font-size:22px;font-weight:700;color:#172033}.page-subtitle,.filter-label,.stats-label,.stats-meta,.empty-text{color:#607086}.page-subtitle{margin-top:4px;font-size:13px}.header-actions{flex-wrap:wrap;gap:10px}.filter-item{display:flex;align-items:center;gap:8px}
.section-title{margin:18px 0 14px;font-size:15px;font-weight:700;color:#172033}.section-title-spaced{margin-top:22px}
.stats-grid,.panel-grid{display:grid;gap:14px}.stats-grid{grid-template-columns:repeat(auto-fit,minmax(180px,1fr))}.panel-grid{margin-top:16px;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}
.stats-card,.panel-card,.insight-card{border-radius:20px;border:1px solid rgba(125,149,179,.16);background:#fff;box-shadow:0 16px 36px rgba(15,23,42,.06)}
.stats-card{padding:16px 18px}.slim-card{box-shadow:none}.panel-card{padding:18px 20px}.panel-wide{grid-column:span 2}.panel-title{margin-bottom:14px;font-size:15px;font-weight:700;color:#172033}
.stats-value{margin-top:8px;font-size:26px;font-weight:700;color:#172033}.accent-danger{color:#d14343}.accent-warn{color:#d68a22}.accent-primary{color:#2459d1}.accent-success{color:#169c66}
.bar-list{display:grid;gap:12px}.compact-list{gap:10px}.bar-item{display:grid;gap:6px}.bar-head{justify-content:space-between;gap:12px;font-size:13px;color:#49566a}.bar-track{height:10px;overflow:hidden;border-radius:999px;background:#edf2f8}.bar-fill{height:100%;border-radius:inherit}
.bar-fill-blue{background:linear-gradient(90deg,#4c7ff7,#2756c7)}.bar-fill-indigo{background:linear-gradient(90deg,#7c86ff,#4f46e5)}.bar-fill-green{background:linear-gradient(90deg,#38c793,#169c66)}.bar-fill-amber{background:linear-gradient(90deg,#f2c14e,#d68a22)}.bar-fill-orange{background:linear-gradient(90deg,#fb923c,#ea580c)}.bar-fill-red{background:linear-gradient(90deg,#ff8a8a,#d14343)}.bar-fill-slate{background:linear-gradient(90deg,#94a3b8,#64748b)}
.insight-card{margin-top:16px;padding:16px 18px;background:linear-gradient(135deg,#f7fbff,#edf4ff)}.insight-card.warning{background:linear-gradient(135deg,rgba(255,245,230,.95),rgba(255,236,214,.92));border-color:rgba(214,138,34,.22)}.insight-title{font-size:14px;font-weight:700;color:#172033}.insight-body{margin-top:8px;display:grid;gap:6px;font-size:13px;line-height:1.6;color:#49566a}
@media (max-width:960px){.page-header,.filter-bar{flex-direction:column;align-items:flex-start}.panel-grid{grid-template-columns:1fr}.panel-wide{grid-column:span 1}}
</style>
