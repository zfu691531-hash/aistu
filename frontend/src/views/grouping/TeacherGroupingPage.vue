<template>
  <div class="page-container grouping-page">
    <div class="page-shell">
      <el-card shadow="never" class="config-card">
        <template #header>
          <div>
            <div class="card-title">教师分组管理</div>
            <div class="card-desc">
              AI 负责给建议，教师在这里完成班内分组、手动调整、保存方案和导出。
            </div>
          </div>
        </template>

        <el-form :model="form" label-width="92px">
          <el-form-item label="班级">
            <el-select v-model="form.class_id" class="full-width" placeholder="请选择班级" @change="handleClassChange">
              <el-option v-for="item in classOptions" :key="item.id" :label="item.name" :value="item.id" />
            </el-select>
          </el-form-item>

          <el-form-item label="方案名称">
            <el-input v-model="form.scheme_name" placeholder="例如：高一1班-课堂讨论分组" />
          </el-form-item>

          <el-form-item label="分组数量">
            <el-input-number v-model="form.group_count" :min="1" :max="12" />
          </el-form-item>

          <el-form-item label="均衡因素">
            <el-checkbox-group v-model="form.balance_factors">
              <el-checkbox label="score">成绩</el-checkbox>
              <el-checkbox label="gender">性别</el-checkbox>
              <el-checkbox label="tag">标签</el-checkbox>
            </el-checkbox-group>
          </el-form-item>

          <el-form-item label="备注">
            <el-input v-model="form.remark" type="textarea" :rows="3" placeholder="记录本次分组用途或说明" />
          </el-form-item>

          <el-alert
            type="info"
            :closable="false"
            show-icon
            title="这里是正式的教师分组管理页。AI 结果仅作为起始参考，不会改变学生正式班级归属。"
            class="page-alert"
          />

          <div class="action-row">
            <el-button type="primary" @click="handleLoadStudents">加载班级学生</el-button>
            <el-button :loading="profileLoading" @click="handleGenerateProfilePlan">画像生成方案</el-button>
            <el-button :loading="aiLoading" @click="handleImportAiSuggestion">导入 AI 建议</el-button>
            <el-button @click="createEmptyGroups">新建空白分组</el-button>
            <el-button type="success" :loading="saveLoading" @click="handleSaveScheme">保存方案</el-button>
            <el-button :disabled="groups.length === 0" @click="handleExport">导出 Word</el-button>
          </div>
        </el-form>
      </el-card>

      <el-card shadow="never" class="history-card">
        <template #header>
          <div>
            <div class="card-title">方案记录</div>
            <div class="card-desc">可直接加载已保存的教师分组方案继续调整。</div>
          </div>
        </template>

        <el-table :data="schemeList" size="small" border empty-text="暂无已保存方案">
          <el-table-column prop="scheme_name" label="方案名" min-width="140" />
          <el-table-column prop="source_type" label="来源" width="90">
            <template #default="{ row }">
              {{ row.source_type === 'ai' ? 'AI建议' : '手动' }}
            </template>
          </el-table-column>
          <el-table-column label="操作" width="120">
            <template #default="{ row }">
              <el-button link type="primary" @click="handleLoadScheme(row)">加载</el-button>
              <el-button link type="danger" @click="handleDeleteScheme(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>

        <el-divider />

        <div class="summary-stack">
          <div class="summary-item">
            <span>人数差</span>
            <strong>{{ balanceReport.student_count_gap ?? '-' }}</strong>
          </div>
          <div class="summary-item">
            <span>高风险人数差</span>
            <strong>{{ balanceReport.high_risk_count_gap ?? '-' }}</strong>
          </div>
          <div class="summary-item">
            <span>平均风险分差</span>
            <strong>{{ balanceReport.avg_risk_score_gap ?? '-' }}</strong>
          </div>
        </div>

        <el-alert
          v-if="missingProfiles.length"
          type="warning"
          :closable="false"
          show-icon
          class="page-alert top-gap"
          :title="`有 ${missingProfiles.length} 名学生缺少关怀画像，已按降级方式参与分组。`"
        />
      </el-card>
    </div>

    <div class="workspace">
      <el-card shadow="never">
        <template #header>
          <div class="panel-head">
            <div>
              <div class="card-title">待分配学生</div>
              <div class="card-desc">先勾选学生，再点击按钮加入指定小组。</div>
            </div>
            <div class="pool-actions" v-if="groups.length">
              <el-button
                v-for="group in groups"
                :key="group.group_no"
                size="small"
                @click="assignSelectedToGroup(group.group_no)"
              >
                加入第 {{ group.group_no }} 组
              </el-button>
            </div>
          </div>
        </template>

        <el-table :data="unassignedStudents" border size="small" @selection-change="handlePoolSelectionChange">
          <el-table-column type="selection" width="50" />
          <el-table-column prop="student_no" label="学号" width="120" />
          <el-table-column prop="name" label="姓名" min-width="90" />
          <el-table-column label="性别" width="70">
            <template #default="{ row }">
              {{ row.gender === 'male' ? '男' : '女' }}
            </template>
          </el-table-column>
          <el-table-column prop="avg_score" label="均分" width="80" />
          <el-table-column prop="tags" label="标签" min-width="120" show-overflow-tooltip />
        </el-table>
      </el-card>

      <div class="group-board">
        <el-card v-for="group in groups" :key="group.group_no" shadow="never" class="group-card">
          <template #header>
            <div class="panel-head">
              <div>
                <div class="card-title">第 {{ group.group_no }} 组</div>
                <div class="card-desc">
                  {{ getGroupSummary(group).assignedCount }} 人，男生 {{ getGroupSummary(group).maleCount }} 人，女生
                  {{ getGroupSummary(group).femaleCount }} 人，均分 {{ getGroupSummary(group).avgScore }}
                </div>
                <div class="card-desc" v-if="getGroupSummary(group).highRiskCount || getGroupSummary(group).avgRiskScore">
                  高风险 {{ getGroupSummary(group).highRiskCount }} 人，平均风险分 {{ getGroupSummary(group).avgRiskScore }}
                </div>
              </div>
              <el-button link type="warning" @click="clearGroup(group.group_no)">清空本组</el-button>
            </div>
          </template>

          <el-table :data="getStudentsByIds(group.student_ids)" size="small" border empty-text="暂无学生">
            <el-table-column prop="name" label="姓名" min-width="90" />
            <el-table-column label="性别" width="70">
              <template #default="{ row }">
                {{ row.gender === 'male' ? '男' : '女' }}
              </template>
            </el-table-column>
            <el-table-column prop="avg_score" label="均分" width="80" />
            <el-table-column label="操作" width="80">
              <template #default="{ row }">
                <el-button link type="danger" @click="removeStudentFromGroup(group.group_no, row.id)">移出</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import { generateGroup } from '@/api/aiTools'
import { getClassList } from '@/api/class_'
import {
  createGroupingScheme,
  deleteGroupingScheme,
  generateGroupingWithProfile,
  getGroupingSchemeDetail,
  getGroupingSchemes,
  updateGroupingScheme
} from '@/api/grouping'
import { getStudentList } from '@/api/student'
import { downloadWordDocument } from '@/utils/export'

const AI_DRAFT_KEY = 'teacher-grouping-draft'

const classOptions = ref([])
const allStudents = ref([])
const schemeList = ref([])
const selectedPoolIds = ref([])
const aiLoading = ref(false)
const profileLoading = ref(false)
const saveLoading = ref(false)
const currentSchemeId = ref(null)
const schemeSourceType = ref('manual')
const balanceReport = ref({})
const missingProfiles = ref([])

const form = reactive({
  class_id: '',
  scheme_name: '',
  group_count: 4,
  balance_factors: ['score', 'gender'],
  remark: ''
})

const groups = ref([])

const studentMap = computed(() => {
  const map = new Map()
  allStudents.value.forEach((item) => map.set(item.id, item))
  return map
})

const assignedStudentIds = computed(() => groups.value.flatMap((group) => group.student_ids))

const unassignedStudents = computed(() => {
  const assignedSet = new Set(assignedStudentIds.value)
  return allStudents.value.filter((item) => !assignedSet.has(item.id))
})

const currentClassName = computed(() =>
  classOptions.value.find((item) => item.id === form.class_id)?.name || '当前班级'
)

onMounted(async () => {
  await fetchClasses()
  await tryLoadDraft()
})

async function fetchClasses() {
  const res = await getClassList({ page: 1, page_size: 100, status: 1 })
  classOptions.value = res.list || []
}

async function handleClassChange() {
  currentSchemeId.value = null
  schemeSourceType.value = 'manual'
  form.scheme_name = ''
  form.remark = ''
  groups.value = []
  allStudents.value = []
  await Promise.all([handleLoadStudents(), fetchSchemeList()])
}

async function handleLoadStudents() {
  if (!form.class_id) {
    ElMessage.warning('请先选择班级')
    return
  }
  const res = await getStudentList({ page: 1, page_size: 100, class_id: form.class_id })
  allStudents.value = res.list || []
  if (!groups.value.length) {
    createEmptyGroups()
  }
}

async function fetchSchemeList() {
  if (!form.class_id) {
    schemeList.value = []
    return
  }
  const res = await getGroupingSchemes({ page: 1, page_size: 50, class_id: form.class_id })
  schemeList.value = res.list || []
}

function createEmptyGroups() {
  if (!allStudents.value.length && form.class_id) {
    ElMessage.warning('请先加载班级学生')
    return
  }
  groups.value = Array.from({ length: form.group_count }, (_, index) => ({
    group_no: index + 1,
    student_ids: []
  }))
  balanceReport.value = {}
  missingProfiles.value = []
  selectedPoolIds.value = []
}

async function handleGenerateProfilePlan() {
  if (!form.class_id) {
    ElMessage.warning('请先选择班级')
    return
  }
  if (!allStudents.value.length) {
    await handleLoadStudents()
  }

  profileLoading.value = true
  try {
    const res = await generateGroupingWithProfile({
      class_id: form.class_id,
      group_count: form.group_count,
      constraints: {
        balance_risk: true,
        ensure_support_distribution: true
      }
    })
    const incomingStudents = (res.group_summaries || []).flatMap((group) => group.students || [])
    if (incomingStudents.length) {
      const merged = new Map(allStudents.value.map((item) => [item.id, item]))
      incomingStudents.forEach((item) => merged.set(item.id, { ...merged.get(item.id), ...item }))
      allStudents.value = [...merged.values()]
    }
    groups.value = (res.assignments || []).map((group) => ({
      group_no: group.group_no,
      student_ids: group.student_ids || []
    }))
    balanceReport.value = res.balance_report || {}
    missingProfiles.value = res.missing_profiles || []
    schemeSourceType.value = 'manual'
    if (!form.scheme_name) {
      form.scheme_name = `${currentClassName.value}-画像分组`
    }
    ElMessage.success('已生成画像分组方案')
  } finally {
    profileLoading.value = false
  }
}

async function handleImportAiSuggestion() {
  if (!form.class_id) {
    ElMessage.warning('请先选择班级')
    return
  }
  if (!allStudents.value.length) {
    await handleLoadStudents()
  }

  aiLoading.value = true
  try {
    const res = await generateGroup({
      mode: 'teacher',
      class_id: form.class_id,
      group_count: form.group_count,
      balance_factors: form.balance_factors
    })
    applyAiSuggestion(res)
    ElMessage.success('已导入 AI 分组建议')
  } finally {
    aiLoading.value = false
  }
}

function handlePoolSelectionChange(selection) {
  selectedPoolIds.value = selection.map((item) => item.id)
}

function assignSelectedToGroup(groupNo) {
  if (!selectedPoolIds.value.length) {
    ElMessage.warning('请先在待分配区域勾选学生')
    return
  }
  const group = groups.value.find((item) => item.group_no === groupNo)
  const mergedIds = new Set([...group.student_ids, ...selectedPoolIds.value])
  group.student_ids = [...mergedIds]
  selectedPoolIds.value = []
}

function removeStudentFromGroup(groupNo, studentId) {
  const group = groups.value.find((item) => item.group_no === groupNo)
  group.student_ids = group.student_ids.filter((id) => id !== studentId)
}

function clearGroup(groupNo) {
  const group = groups.value.find((item) => item.group_no === groupNo)
  group.student_ids = []
}

function getStudentsByIds(ids) {
  return ids.map((id) => studentMap.value.get(id)).filter(Boolean)
}

function getGroupSummary(group) {
  const students = getStudentsByIds(group.student_ids)
  const maleCount = students.filter((item) => item.gender === 'male').length
  const highRiskCount = students.filter((item) => ['high', 'critical'].includes(item.risk_level)).length
  const riskScores = students.map((item) => Number(item.risk_score)).filter((score) => !Number.isNaN(score))
  const avgScore = students.length
    ? (students.reduce((sum, item) => sum + Number(item.avg_score || 0), 0) / students.length).toFixed(1)
    : '0.0'
  return {
    assignedCount: students.length,
    maleCount,
    femaleCount: students.length - maleCount,
    avgScore,
    highRiskCount,
    avgRiskScore: riskScores.length ? (riskScores.reduce((sum, score) => sum + score, 0) / riskScores.length).toFixed(3) : '0.000'
  }
}

async function handleSaveScheme() {
  if (!form.class_id) {
    ElMessage.warning('请先选择班级')
    return
  }
  if (!form.scheme_name.trim()) {
    ElMessage.warning('请填写方案名称')
    return
  }
  if (unassignedStudents.value.length) {
    ElMessage.warning('仍有学生未分配，请完成分组后再保存')
    return
  }

  const payload = {
    class_id: form.class_id,
    scheme_name: form.scheme_name.trim(),
    group_count: form.group_count,
    balance_factors: form.balance_factors,
    source_type: schemeSourceType.value,
    remark: form.remark,
    assignments: groups.value
  }

  saveLoading.value = true
  try {
    if (currentSchemeId.value) {
      await updateGroupingScheme(currentSchemeId.value, payload)
      ElMessage.success('分组方案已更新')
    } else {
      const res = await createGroupingScheme(payload)
      currentSchemeId.value = res.id
      ElMessage.success('分组方案已保存')
    }
    await fetchSchemeList()
  } finally {
    saveLoading.value = false
  }
}

async function handleLoadScheme(row) {
  const res = await getGroupingSchemeDetail(row.id)
  currentSchemeId.value = row.id
  form.class_id = res.class_id
  form.scheme_name = res.scheme_name
  form.group_count = res.group_count
  form.balance_factors = res.balance_factors || ['score', 'gender']
  form.remark = res.remark || ''
  schemeSourceType.value = res.source_type || 'manual'
  await handleLoadStudents()
  groups.value = (res.group_result_json || []).map((group) => ({
    group_no: group.group_no,
    student_ids: group.student_ids || (group.students || []).map((student) => student.id)
  }))
  ElMessage.success('已加载分组方案')
}

async function handleDeleteScheme(row) {
  await ElMessageBox.confirm(`确定删除方案“${row.scheme_name}”吗？`, '删除确认', {
    type: 'warning'
  })
  await deleteGroupingScheme(row.id)
  if (currentSchemeId.value === row.id) {
    currentSchemeId.value = null
  }
  ElMessage.success('方案已删除')
  await fetchSchemeList()
}

function handleExport() {
  const content = groups.value
    .map((group) => {
      const summary = getGroupSummary(group)
      const students = getStudentsByIds(group.student_ids)
        .map((item) => `- ${item.name} / ${item.gender === 'male' ? '男' : '女'} / 均分 ${item.avg_score || 0}${item.tags ? ` / ${item.tags}` : ''}`)
        .join('\n')
      return `第 ${group.group_no} 组\n人数 ${summary.assignedCount}，男生 ${summary.maleCount}，女生 ${summary.femaleCount}，均分 ${summary.avgScore}\n${students}`
    })
    .join('\n\n')

  downloadWordDocument(
    form.scheme_name || '教师分组方案',
    [form.remark, content].filter(Boolean).join('\n\n'),
    `${form.scheme_name || '教师分组方案'}.doc`
  )
}

function applyAiSuggestion(res) {
  const incomingStudents = (res.groups || []).flatMap((group) => group.students || [])
  if (incomingStudents.length) {
    const merged = new Map(allStudents.value.map((item) => [item.id, item]))
    incomingStudents.forEach((item) => merged.set(item.id, { ...merged.get(item.id), ...item }))
    allStudents.value = [...merged.values()]
  }

  groups.value = (res.groups || []).map((group, index) => ({
    group_no: index + 1,
    student_ids: (group.students || []).map((student) => student.id)
  }))

  if (!form.scheme_name) {
    form.scheme_name = `${currentClassName.value}-AI建议分组`
  }
  schemeSourceType.value = 'ai'
  balanceReport.value = {}
  missingProfiles.value = []
}

async function tryLoadDraft() {
  const raw = sessionStorage.getItem(AI_DRAFT_KEY)
  if (!raw) return

  sessionStorage.removeItem(AI_DRAFT_KEY)

  try {
    const draft = JSON.parse(raw)
    form.class_id = draft.class_id || ''
    form.group_count = draft.group_count || form.group_count
    form.balance_factors = draft.balance_factors?.length ? draft.balance_factors : form.balance_factors
    form.scheme_name = draft.scheme_name || ''
    form.remark = draft.remark || ''
    schemeSourceType.value = 'ai'

    if (form.class_id) {
      await handleLoadStudents()
    }

    applyAiSuggestion({
      groups: draft.groups || [],
      description: draft.description || ''
    })
    await fetchSchemeList()
    ElMessage.success('已自动载入 AI 建议，请确认后保存方案')
  } catch (error) {
    console.error('加载 AI 草稿失败', error)
  }
}
</script>

<style scoped lang="scss">
.grouping-page {
  display: grid;
  gap: 16px;
}

.page-shell,
.workspace {
  display: grid;
  gap: 16px;
}

.page-shell {
  grid-template-columns: minmax(0, 1.2fr) minmax(320px, 0.8fr);
}

.workspace {
  grid-template-columns: minmax(320px, 380px) minmax(0, 1fr);
}

.group-board {
  display: grid;
  gap: 16px;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
}

.card-title {
  font-size: 16px;
  font-weight: 600;
}

.card-desc {
  margin-top: 4px;
  font-size: 13px;
  color: #6b7280;
  line-height: 1.7;
}

.full-width {
  width: 100%;
}

.page-alert {
  margin-bottom: 18px;
}

.action-row {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}

.panel-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}

.pool-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: flex-end;
}

.summary-stack {
  display: grid;
  gap: 10px;
}

.summary-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 14px;
  border-radius: 12px;
  background: #f8fafc;
  color: #475569;
}

.summary-item strong {
  color: #0f172a;
}

.top-gap {
  margin-top: 16px;
}

@media (max-width: 1100px) {
  .page-shell,
  .workspace {
    grid-template-columns: 1fr;
  }
}
</style>
