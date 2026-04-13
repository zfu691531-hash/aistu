<template>
  <div class="page-container teacher-rule-page">
    <el-alert
      title="教师版校规助手默认先给处置结论，再按需展开校规依据、学生上下文和审计细节。"
      type="info"
      :closable="false"
      show-icon
      class="page-alert"
    />

    <div class="teacher-layout">
      <div class="main-column">
        <el-card shadow="never" class="query-card">
          <div class="card-title">教师版校规助手</div>
          <div class="card-desc">适用于教师和管理员处理迟到、课堂纪律、手机管理、请假与家校沟通等校园规则场景。</div>

          <el-form :model="form" label-width="88px" class="query-form">
            <el-form-item label="选择学生">
              <el-select
                v-model="form.student_id"
                filterable
                remote
                clearable
                reserve-keyword
                :remote-method="handleStudentSearch"
                :loading="studentLoading"
                placeholder="可搜索姓名、学号后选择"
                style="width: 100%;"
              >
                <el-option
                  v-for="item in studentOptions"
                  :key="item.value"
                  :label="item.label"
                  :value="item.value"
                />
              </el-select>
            </el-form-item>

            <el-form-item label="事件类型">
              <el-input v-model="form.event_type" placeholder="例如：late / discipline / phone" />
            </el-form-item>

            <el-form-item label="问题描述">
              <el-input
                v-model="form.question"
                type="textarea"
                :rows="4"
                placeholder="例如：这个学生最近老是迟到，老师按校规应该怎么处理？"
              />
            </el-form-item>

            <el-form-item>
              <el-button type="primary" :loading="loading" @click="handleAsk">开始分析</el-button>
              <el-button @click="handleReset">清空</el-button>
              <el-button :disabled="!records.length" @click="handleDownload">导出记录</el-button>
            </el-form-item>
          </el-form>
        </el-card>

        <el-card shadow="never" class="result-card">
          <template #header>
            <div>
              <div class="card-title">处理结论</div>
              <div class="card-desc">默认只展示老师最需要的结论、动作和协同建议，其他细节按需展开。</div>
            </div>
          </template>

          <el-empty v-if="!result" description="提交问题后，这里会展示教师版处置结论。" />

          <div v-else class="result-body">
            <el-alert
              v-if="isClarification"
              title="当前问题还需要补充信息"
              type="warning"
              :closable="false"
              show-icon
            />

            <el-alert
              v-else
              title="当前结果已完成校规检索、上下文整合与基础审计"
              type="success"
              :closable="false"
              show-icon
            />

            <div class="hero-panel">
              <div class="hero-label">结论</div>
              <div class="hero-title">{{ result.decision_summary?.conclusion || result.answer }}</div>
              <div class="hero-answer">{{ result.answer }}</div>
            </div>

            <div class="decision-grid">
              <el-card shadow="never" class="decision-card action-card">
                <div class="decision-title">建议动作</div>
                <div class="decision-main">{{ result.decision_summary?.primary_action || quickActions[0] || '先核对事实经过。' }}</div>
                <ul v-if="quickActions.length" class="plain-list compact-list">
                  <li v-for="item in quickActions" :key="item">{{ item }}</li>
                </ul>
              </el-card>

              <el-card shadow="never" class="decision-card">
                <div class="decision-title">联系家长</div>
                <div class="decision-badge" :class="{ yes: result.parent_contact_advice?.suggested }">
                  {{ result.decision_summary?.parent_contact || formatAdviceTag(result.parent_contact_advice) }}
                </div>
                <div class="decision-reason">{{ result.parent_contact_advice?.reason || '-' }}</div>
              </el-card>

              <el-card shadow="never" class="decision-card">
                <div class="decision-title">关怀跟进</div>
                <div class="decision-badge" :class="{ yes: result.care_followup_advice?.suggested }">
                  {{ result.decision_summary?.care_followup || formatAdviceTag(result.care_followup_advice) }}
                </div>
                <div class="decision-reason">{{ result.care_followup_advice?.reason || '-' }}</div>
              </el-card>
            </div>

            <el-collapse v-model="activePanels" class="detail-collapse">
              <el-collapse-item name="policy" title="查看制度依据">
                <el-empty v-if="!result.policy_basis?.length" description="暂无命中条款" />
                <div v-else class="detail-list">
                  <div v-for="item in result.policy_basis" :key="item.rule_id" class="detail-item">
                    <strong>{{ item.title }}</strong>
                    <span>{{ item.excerpt }}</span>
                  </div>
                </div>
              </el-collapse-item>

              <el-collapse-item name="student" title="查看学生上下文">
                <div class="detail-list">
                  <div class="detail-item"><strong>学生</strong><span>{{ formatStudentLine(result.student_context_summary) }}</span></div>
                  <div class="detail-item"><strong>行为</strong><span>{{ result.student_context_summary?.behavior_summary || '-' }}</span></div>
                  <div class="detail-item"><strong>考勤</strong><span>{{ result.student_context_summary?.attendance_summary || '-' }}</span></div>
                  <div class="detail-item"><strong>关怀</strong><span>{{ result.student_context_summary?.care_hint || '-' }}</span></div>
                </div>
              </el-collapse-item>

              <el-collapse-item name="planner" title="查看执行计划">
                <ul class="plain-list">
                  <li v-for="item in result.meta?.planner || []" :key="item">{{ item }}</li>
                </ul>
              </el-collapse-item>

              <el-collapse-item name="history" title="查看历史经验">
                <div class="detail-list">
                  <div class="detail-item"><strong>摘要</strong><span>{{ result.history_experience?.history_summary || '暂无历史经验摘要' }}</span></div>
                  <div class="detail-item"><strong>历史反馈数</strong><span>{{ result.history_experience?.history_feedback_count ?? 0 }}</span></div>
                  <div class="detail-item"><strong>复核提示</strong><span>{{ result.history_experience?.history_risk_hint ? '建议重点复核' : '当前无明显历史风险提示' }}</span></div>
                </div>
              </el-collapse-item>

              <el-collapse-item name="manual" title="查看人工确认项">
                <ul class="plain-list">
                  <li v-for="item in result.needs_manual_confirmation || []" :key="item">{{ item }}</li>
                </ul>
              </el-collapse-item>

              <el-collapse-item name="audit" title="查看审计结果">
                <div class="detail-list">
                  <div class="detail-item"><strong>状态</strong><span>{{ result.audit?.passed ? '通过' : '待复核' }}</span></div>
                  <div v-if="result.audit?.issues?.length" class="detail-item">
                    <strong>问题</strong>
                    <span>{{ result.audit.issues.join('；') }}</span>
                  </div>
                  <div v-else class="detail-item">
                    <strong>说明</strong>
                    <span>当前结果已通过基础证据和脱敏检查。</span>
                  </div>
                </div>
              </el-collapse-item>

              <el-collapse-item name="sources" title="查看命中来源">
                <el-empty v-if="!result.sources?.length" description="暂无命中来源" />
                <div v-else class="detail-list">
                  <div v-for="item in result.sources" :key="sourceKey(item)" class="detail-item source-item">
                    <strong>校规 #{{ item.rule_id }} / 融合分 {{ item.scores?.fused ?? '-' }}</strong>
                    <span>{{ item.chunk_text }}</span>
                  </div>
                </div>
              </el-collapse-item>
            </el-collapse>
          </div>
        </el-card>
      </div>

      <el-card shadow="never" class="side-card">
        <template #header>
          <div>
            <div class="card-title">门卫节点</div>
            <div class="card-desc">帮助老师快速判断当前问题是已可分析，还是还需要补充信息。</div>
          </div>
        </template>

        <div v-if="result" class="detail-list">
          <div class="detail-item">
            <strong>状态</strong>
            <span>{{ gatekeeperPassed ? '已通过，进入分析' : '待补充信息' }}</span>
          </div>
          <div class="detail-item">
            <strong>原因</strong>
            <span>{{ result.meta?.gatekeeper?.reason || '-' }}</span>
          </div>
          <div v-if="!gatekeeperPassed" class="detail-item">
            <strong>建议</strong>
            <span>补充学生、事件类型或时间范围后再分析。</span>
          </div>
        </div>
        <el-empty v-else description="提交问题后可查看门卫判断。" />
      </el-card>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { askTeacherRuleAssistant } from '@/api/teacherRuleAssistant'
import { getStudentList } from '@/api/student'
import { downloadWordDocument } from '@/utils/export'

const loading = ref(false)
const studentLoading = ref(false)
const result = ref(null)
const records = ref([])
const studentOptions = ref([])
const activePanels = ref([])

const form = reactive({
  question: '',
  student_id: null,
  event_type: ''
})

const gatekeeperPassed = computed(() => result.value?.meta?.gatekeeper?.question_clear !== false)
const isClarification = computed(() => !!result.value && !gatekeeperPassed.value)
const quickActions = computed(() => (result.value?.recommended_actions || []).slice(0, 3))

onMounted(() => {
  fetchStudentOptions()
})

async function handleAsk() {
  if (!form.question.trim()) {
    ElMessage.warning('请先输入问题描述')
    return
  }

  loading.value = true
  try {
    const res = await askTeacherRuleAssistant({
      question: form.question.trim(),
      student_id: form.student_id || undefined,
      event_type: form.event_type || undefined
    })
    result.value = res
    activePanels.value = isClarification.value ? ['manual'] : []
    records.value.push({
      question: form.question.trim(),
      answer: res.answer,
      conclusion: res.decision_summary?.conclusion || '',
      planner: res.meta?.planner || [],
      isClarification: res.meta?.gatekeeper?.question_clear === false
    })
  } catch (error) {
    ElMessage.error(error.message || '教师版校规助手暂时不可用')
  } finally {
    loading.value = false
  }
}

function handleReset() {
  form.question = ''
  form.student_id = null
  form.event_type = ''
  result.value = null
  activePanels.value = []
}

function handleDownload() {
  const content = records.value
    .map((item, index) => {
      const lines = [
        `记录 ${index + 1}`,
        `问题：${item.question}`,
        `状态：${item.isClarification ? '待补充澄清' : '已分析'}`,
        `结论：${item.conclusion || '无'}`,
        `执行计划：${item.planner.length ? item.planner.join('；') : '无'}`,
        `答复：${item.answer}`
      ]
      return lines.join('\n')
    })
    .join('\n\n')

  downloadWordDocument('教师版校规助手记录', content, '教师版校规助手记录.doc')
}

async function fetchStudentOptions(keyword = '') {
  studentLoading.value = true
  try {
    const res = await getStudentList({
      page: 1,
      page_size: 30,
      keyword: keyword || undefined
    })
    studentOptions.value = (res.list || []).map((item) => ({
      value: item.id,
      label: `${item.name} / ${item.student_no || '无学号'} / ${item.class_name || '未分班'}`
    }))
  } finally {
    studentLoading.value = false
  }
}

function handleStudentSearch(keyword) {
  fetchStudentOptions(keyword)
}

function formatStudentLine(summary) {
  if (!summary?.student_id) return '未指定'
  const parts = [summary.student_name || `ID ${summary.student_id}`]
  if (summary.grade) parts.push(summary.grade)
  if (summary.class_name) parts.push(summary.class_name)
  return parts.join(' / ')
}

function formatAdviceTag(advice) {
  if (!advice) return '-'
  return advice.suggested ? '建议' : '暂不建议'
}

function sourceKey(item) {
  return `${item.rule_id || 'rule'}-${item.chunk_id || 'chunk'}-${(item.chunk_text || '').slice(0, 24)}`
}
</script>

<style scoped lang="scss">
.page-alert {
  margin-bottom: 16px;
}

.teacher-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) 320px;
  gap: 16px;
}

.main-column {
  display: grid;
  gap: 16px;
}

.query-form {
  margin-top: 16px;
}

.card-title {
  font-size: 16px;
  font-weight: 600;
}

.card-desc {
  margin-top: 4px;
  font-size: 13px;
  color: #6b7280;
}

.result-body {
  display: grid;
  gap: 16px;
}

.hero-panel {
  padding: 20px;
  border-radius: 18px;
  background: linear-gradient(135deg, #eef6ff 0%, #f8fbff 100%);
  border: 1px solid #d7e7ff;
}

.hero-label {
  font-size: 12px;
  color: #4b5563;
}

.hero-title {
  margin-top: 6px;
  font-size: 22px;
  font-weight: 700;
  line-height: 1.5;
  color: #163a63;
}

.hero-answer {
  margin-top: 12px;
  font-size: 14px;
  line-height: 1.9;
  color: #334155;
  white-space: pre-wrap;
}

.decision-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.decision-card {
  border: 1px solid #e5e7eb;
}

.decision-title {
  font-size: 13px;
  color: #64748b;
}

.decision-main {
  margin-top: 10px;
  font-size: 15px;
  font-weight: 600;
  line-height: 1.7;
  color: #1f2937;
}

.decision-badge {
  display: inline-flex;
  align-items: center;
  margin-top: 10px;
  padding: 6px 10px;
  border-radius: 999px;
  background: #eef2ff;
  color: #3730a3;
  font-size: 13px;
  font-weight: 600;
}

.decision-badge.yes {
  background: #ecfdf5;
  color: #166534;
}

.decision-reason {
  margin-top: 10px;
  font-size: 13px;
  line-height: 1.8;
  color: #475569;
}

.detail-collapse {
  margin-top: 4px;
}

.detail-list {
  display: grid;
  gap: 12px;
}

.detail-item {
  display: grid;
  gap: 6px;
  font-size: 13px;
  line-height: 1.8;
  color: #334155;
}

.plain-list {
  margin: 0;
  padding-left: 18px;
  color: #334155;
  line-height: 1.8;
}

.compact-list {
  margin-top: 10px;
}

.source-item {
  padding-bottom: 10px;
  border-bottom: 1px dashed #e5e7eb;
}

.side-card {
  align-self: start;
}

@media (max-width: 1100px) {
  .teacher-layout {
    grid-template-columns: 1fr;
  }

  .decision-grid {
    grid-template-columns: 1fr;
  }
}
</style>
