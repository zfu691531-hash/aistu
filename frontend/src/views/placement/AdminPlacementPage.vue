<template>
  <div class="page-container grouping-page">
    <div class="page-shell">
      <el-card shadow="never">
        <template #header>
          <div>
            <div class="card-title">校务分班管理</div>
            <div class="card-desc">AI 只提供初始建议，管理员在这里完成人工校验、正式确认和批次留痕。</div>
          </div>
        </template>

        <el-form :model="form" label-width="96px">
          <el-form-item label="年级">
            <el-select v-model="form.grade" class="full-width" placeholder="请选择年级" @change="handleLoadOverview">
              <el-option v-for="item in gradeOptions" :key="item" :label="item" :value="item" />
            </el-select>
          </el-form-item>

          <el-form-item label="批次名称">
            <el-input v-model="form.batch_name" placeholder="例如：2024级新学年正式分班" />
          </el-form-item>

          <el-form-item label="均衡因素">
            <el-checkbox-group v-model="form.balance_factors">
              <el-checkbox label="score">成绩</el-checkbox>
              <el-checkbox label="gender">性别</el-checkbox>
              <el-checkbox label="tag">标签</el-checkbox>
            </el-checkbox-group>
          </el-form-item>

          <el-alert
            type="warning"
            :closable="false"
            show-icon
            title="本页会影响正式班级归属。只有校验通过并确认后，才会写入学生 class_id。"
            class="page-alert"
          />

          <div class="action-row">
            <el-button type="primary" @click="handleLoadOverview">加载待分班学生</el-button>
            <el-button :loading="profileLoading" @click="handleGenerateProfilePlan">画像生成方案</el-button>
            <el-button :loading="aiLoading" @click="handleImportAiSuggestion">导入 AI 建议</el-button>
            <el-button @click="createEmptyAssignments">新建空白分班</el-button>
            <el-button :loading="validateLoading" @click="handleValidate">校验结果</el-button>
            <el-button type="success" :loading="confirmLoading" @click="handleConfirm">确认正式分班</el-button>
            <el-button :disabled="!assignments.length" @click="handleExport">导出预览</el-button>
          </div>
        </el-form>
      </el-card>

      <el-card shadow="never">
        <template #header>
          <div>
            <div class="card-title">当前概况</div>
            <div class="card-desc">查看本次待分班范围和校验摘要。</div>
          </div>
        </template>

        <div class="overview-grid">
          <div class="overview-item">
            <div class="overview-label">目标班级</div>
            <div class="overview-value">{{ targetClasses.length }}</div>
          </div>
          <div class="overview-item">
            <div class="overview-label">待分班学生</div>
            <div class="overview-value">{{ allStudents.length }}</div>
          </div>
          <div class="overview-item">
            <div class="overview-label">学生来源</div>
            <div class="overview-value">{{ sourceTypeLabel }}</div>
          </div>
        </div>

        <el-divider />

        <el-table :data="validationRows" size="small" border empty-text="尚未执行校验">
          <el-table-column prop="class_name" label="班级" min-width="120" />
          <el-table-column prop="assigned_count" label="人数" width="90" />
          <el-table-column prop="male_count" label="男生" width="90" />
          <el-table-column prop="female_count" label="女生" width="90" />
          <el-table-column prop="avg_score" label="均分" width="90" />
        </el-table>

        <el-divider />

        <div class="report-grid">
          <div class="overview-item">
            <div class="overview-label">人数差</div>
            <div class="overview-value report-value">{{ balanceReport.student_count_gap ?? '-' }}</div>
          </div>
          <div class="overview-item">
            <div class="overview-label">高风险人数差</div>
            <div class="overview-value report-value">{{ balanceReport.high_risk_count_gap ?? '-' }}</div>
          </div>
          <div class="overview-item">
            <div class="overview-label">平均风险分差</div>
            <div class="overview-value report-value">{{ balanceReport.avg_risk_score_gap ?? '-' }}</div>
          </div>
        </div>

        <el-alert
          v-if="missingProfiles.length"
          type="warning"
          :closable="false"
          show-icon
          class="page-alert top-gap"
          :title="`有 ${missingProfiles.length} 名学生缺少关怀画像，已按降级方式参与分班。`"
        />
      </el-card>
    </div>

    <div class="workspace">
      <el-card shadow="never">
        <template #header>
          <div class="panel-head">
            <div>
              <div class="card-title">待分配学生池</div>
              <div class="card-desc">支持按姓名、学号、原班级和年级快速判断学生归属。</div>
            </div>
            <div class="pool-actions" v-if="assignments.length">
              <el-button
                v-for="item in assignments"
                :key="item.class_id"
                size="small"
                @click="assignSelectedToClass(item.class_id)"
              >
                加入{{ item.class_name }}
              </el-button>
            </div>
          </div>
        </template>

        <el-table :data="unassignedStudents" border size="small" @selection-change="handlePoolSelectionChange">
          <el-table-column type="selection" width="50" />
          <el-table-column prop="student_no" label="学号" width="120" />
          <el-table-column prop="name" label="姓名" min-width="90" />
          <el-table-column prop="grade" label="年级" width="90" />
          <el-table-column prop="class_name" label="原班级" min-width="120" />
          <el-table-column label="性别" width="70">
            <template #default="{ row }">
              {{ row.gender === 'male' ? '男' : '女' }}
            </template>
          </el-table-column>
          <el-table-column prop="avg_score" label="均分" width="80" />
          <el-table-column prop="tags" label="标签" min-width="140" show-overflow-tooltip />
        </el-table>
      </el-card>

      <div class="group-board">
        <el-card v-for="item in assignments" :key="item.class_id" shadow="never">
          <template #header>
            <div class="panel-head">
              <div>
                <div class="card-title">{{ item.class_name }}</div>
                <div class="card-desc">
                  {{ getAssignmentSummary(item).assignedCount }} / {{ item.max_count }} 人，男生 {{ getAssignmentSummary(item).maleCount }} 人，女生 {{ getAssignmentSummary(item).femaleCount }} 人，均分 {{ getAssignmentSummary(item).avgScore }}
                </div>
                <div class="card-desc" v-if="getAssignmentSummary(item).highRiskCount || getAssignmentSummary(item).avgRiskScore">
                  高风险 {{ getAssignmentSummary(item).highRiskCount }} 人，平均风险分 {{ getAssignmentSummary(item).avgRiskScore }}
                </div>
              </div>
              <el-button link type="warning" @click="clearAssignment(item.class_id)">清空</el-button>
            </div>
          </template>

          <el-table :data="getStudentsByIds(item.student_ids)" size="small" border empty-text="暂无学生">
            <el-table-column prop="student_no" label="学号" width="120" />
            <el-table-column prop="name" label="姓名" min-width="90" />
            <el-table-column label="性别" width="70">
              <template #default="{ row }">
                {{ row.gender === 'male' ? '男' : '女' }}
              </template>
            </el-table-column>
            <el-table-column prop="avg_score" label="均分" width="80" />
            <el-table-column label="操作" width="80">
              <template #default="{ row }">
                <el-button link type="danger" @click="removeStudentFromClass(item.class_id, row.id)">移出</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </div>
    </div>

    <el-card shadow="never">
      <template #header>
        <div>
          <div class="card-title">分班批次记录</div>
          <div class="card-desc">已确认的正式分班结果会留在这里，方便追溯。</div>
        </div>
      </template>

      <el-table :data="batchList" border size="small">
        <el-table-column prop="batch_name" label="批次名称" min-width="160" />
        <el-table-column prop="grade" label="年级" width="100" />
        <el-table-column prop="student_count" label="学生数" width="100" />
        <el-table-column prop="class_count" label="班级数" width="100" />
        <el-table-column label="操作" width="100">
          <template #default="{ row }">
            <el-button link type="primary" @click="handleViewBatch(row)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="batchDialogVisible" title="分班批次详情" width="760px">
      <template v-if="currentBatch">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="批次">{{ currentBatch.batch_name }}</el-descriptions-item>
          <el-descriptions-item label="年级">{{ currentBatch.grade }}</el-descriptions-item>
          <el-descriptions-item label="学生数">{{ currentBatch.student_count }}</el-descriptions-item>
          <el-descriptions-item label="班级数">{{ currentBatch.class_count }}</el-descriptions-item>
        </el-descriptions>

        <el-table :data="currentBatch.summary_json?.class_summaries || []" size="small" border style="margin-top: 16px">
          <el-table-column prop="class_name" label="班级" min-width="120" />
          <el-table-column prop="assigned_count" label="人数" width="90" />
          <el-table-column prop="male_count" label="男生" width="90" />
          <el-table-column prop="female_count" label="女生" width="90" />
          <el-table-column prop="avg_score" label="均分" width="90" />
        </el-table>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { generateGroup } from '@/api/aiTools'
import { getClassList } from '@/api/class_'
import {
  confirmPlacement,
  generatePlacementWithProfile,
  getPlacementBatchDetail,
  getPlacementBatches,
  getPlacementOverview,
  validatePlacement
} from '@/api/placement'
import { downloadWordDocument } from '@/utils/export'

const aiLoading = ref(false)
const profileLoading = ref(false)
const validateLoading = ref(false)
const confirmLoading = ref(false)
const batchDialogVisible = ref(false)
const selectedPoolIds = ref([])

const gradeOptions = ref([])
const sourceType = ref('')
const targetClasses = ref([])
const allStudents = ref([])
const assignments = ref([])
const batchList = ref([])
const currentBatch = ref(null)
const validationSummary = ref(null)
const balanceReport = ref({})
const missingProfiles = ref([])

const form = reactive({
  grade: '',
  batch_name: '',
  balance_factors: ['score', 'gender']
})

const studentMap = computed(() => {
  const map = new Map()
  allStudents.value.forEach((item) => map.set(item.id, item))
  return map
})

const assignedStudentIds = computed(() => assignments.value.flatMap((item) => item.student_ids))

const unassignedStudents = computed(() => {
  const assignedSet = new Set(assignedStudentIds.value)
  return allStudents.value.filter((item) => !assignedSet.has(item.id))
})

const sourceTypeLabel = computed(() =>
  sourceType.value === 'unassigned' ? '未分班学生池' : sourceType.value === 'current_grade' ? '当前年级重分班' : '-'
)

const validationRows = computed(() => validationSummary.value?.class_summaries || [])

onMounted(async () => {
  await fetchGradeOptions()
  if (gradeOptions.value.length && !form.grade) {
    form.grade = gradeOptions.value[0]
  }
  if (form.grade) {
    await Promise.all([handleLoadOverview(), fetchBatchList()])
  }
})

async function fetchGradeOptions() {
  const res = await getClassList({ page: 1, page_size: 100, status: 1 })
  gradeOptions.value = Array.from(new Set((res.list || []).map((item) => item.grade).filter(Boolean)))
}

async function handleLoadOverview() {
  if (!form.grade) {
    ElMessage.warning('请先选择年级')
    return
  }
  const res = await getPlacementOverview({ grade: form.grade })
  sourceType.value = res.source_type
  targetClasses.value = res.classes || []
  allStudents.value = res.students || []
  createEmptyAssignments()
  if (!form.batch_name) {
    form.batch_name = `${form.grade}正式分班`
  }
  await fetchBatchList()
}

function createEmptyAssignments() {
  assignments.value = targetClasses.value.map((item) => ({
    class_id: item.id,
    class_name: item.name,
    max_count: item.max_count,
    student_ids: []
  }))
  validationSummary.value = null
  balanceReport.value = {}
  missingProfiles.value = []
  selectedPoolIds.value = []
}

async function handleGenerateProfilePlan() {
  if (!form.grade) {
    ElMessage.warning('请先选择年级')
    return
  }
  if (!targetClasses.value.length || !allStudents.value.length) {
    await handleLoadOverview()
  }

  profileLoading.value = true
  try {
    const res = await generatePlacementWithProfile({
      grade: form.grade,
      target_classes: targetClasses.value.map((item) => item.id),
      constraints: {
        balance_risk: true,
        disperse_high_risk: true
      }
    })
    const incomingStudents = (res.class_summaries || []).flatMap((item) => item.students || [])
    if (incomingStudents.length) {
      const merged = new Map(allStudents.value.map((item) => [item.id, item]))
      incomingStudents.forEach((item) => merged.set(item.id, { ...merged.get(item.id), ...item }))
      allStudents.value = [...merged.values()]
    }
    assignments.value = (res.assignments || []).map((item) => {
      const target = targetClasses.value.find((classItem) => classItem.id === item.class_id)
      return {
        class_id: item.class_id,
        class_name: target?.name || `班级${item.class_id}`,
        max_count: target?.max_count || 0,
        student_ids: item.student_ids || []
      }
    })
    validationSummary.value = res.validation_summary || { class_summaries: [] }
    balanceReport.value = res.balance_report || {}
    missingProfiles.value = res.missing_profiles || []
    if (!form.batch_name) {
      form.batch_name = `${form.grade}画像分班`
    }
    ElMessage.success('已生成画像分班方案')
  } finally {
    profileLoading.value = false
  }
}

async function handleImportAiSuggestion() {
  if (!form.grade) {
    ElMessage.warning('请先选择年级')
    return
  }
  if (!targetClasses.value.length) {
    await handleLoadOverview()
  }

  aiLoading.value = true
  try {
    const res = await generateGroup({
      mode: 'admin',
      grade: form.grade,
      group_count: targetClasses.value.length,
      balance_factors: form.balance_factors
    })
    assignments.value = (res.groups || []).map((group, index) => ({
      class_id: group.target_class_id,
      class_name: group.target_class_name || targetClasses.value[index]?.name,
      max_count: targetClasses.value.find((item) => item.id === group.target_class_id)?.max_count || 0,
      student_ids: (group.students || []).map((student) => student.id)
    }))
    ElMessage.success('已导入 AI 分班建议')
  } finally {
    aiLoading.value = false
  }
}

function handlePoolSelectionChange(selection) {
  selectedPoolIds.value = selection.map((item) => item.id)
}

function assignSelectedToClass(classId) {
  if (!selectedPoolIds.value.length) {
    ElMessage.warning('请先在待分配区域勾选学生')
    return
  }
  const target = assignments.value.find((item) => item.class_id === classId)
  target.student_ids = [...target.student_ids, ...selectedPoolIds.value]
  selectedPoolIds.value = []
  validationSummary.value = null
}

function removeStudentFromClass(classId, studentId) {
  const target = assignments.value.find((item) => item.class_id === classId)
  target.student_ids = target.student_ids.filter((id) => id !== studentId)
  validationSummary.value = null
}

function clearAssignment(classId) {
  const target = assignments.value.find((item) => item.class_id === classId)
  target.student_ids = []
  validationSummary.value = null
}

function getStudentsByIds(ids) {
  return ids.map((id) => studentMap.value.get(id)).filter(Boolean)
}

function getAssignmentSummary(item) {
  const students = getStudentsByIds(item.student_ids)
  const maleCount = students.filter((student) => student.gender === 'male').length
  const highRiskCount = students.filter((student) => ['high', 'critical'].includes(student.risk_level)).length
  const riskScores = students.map((student) => Number(student.risk_score)).filter((score) => !Number.isNaN(score))
  const avgScore = students.length
    ? (students.reduce((sum, student) => sum + Number(student.avg_score || 0), 0) / students.length).toFixed(1)
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

async function handleValidate() {
  validateLoading.value = true
  try {
    const res = await validatePlacement({
      grade: form.grade,
      assignments: assignments.value.map((item) => ({
        class_id: item.class_id,
        student_ids: item.student_ids
      }))
    })
    validationSummary.value = res.summary
    ElMessage.success('分班结果校验通过')
  } finally {
    validateLoading.value = false
  }
}

async function handleConfirm() {
  if (!form.batch_name.trim()) {
    ElMessage.warning('请填写批次名称')
    return
  }
  if (unassignedStudents.value.length) {
    ElMessage.warning('仍有学生未分班，不能正式确认')
    return
  }

  confirmLoading.value = true
  try {
    const res = await confirmPlacement({
      grade: form.grade,
      batch_name: form.batch_name.trim(),
      balance_factors: form.balance_factors,
      summary: validationSummary.value,
      assignments: assignments.value.map((item) => ({
        class_id: item.class_id,
        student_ids: item.student_ids
      }))
    })
    validationSummary.value = res.summary
    ElMessage.success('正式分班已生效')
    await Promise.all([handleLoadOverview(), fetchBatchList()])
  } finally {
    confirmLoading.value = false
  }
}

async function fetchBatchList() {
  const res = await getPlacementBatches({ page: 1, page_size: 20, grade: form.grade || undefined })
  batchList.value = res.list || []
}

async function handleViewBatch(row) {
  currentBatch.value = await getPlacementBatchDetail(row.id)
  batchDialogVisible.value = true
}

function handleExport() {
  const body = assignments.value
    .map((item) => {
      const summary = getAssignmentSummary(item)
      const students = getStudentsByIds(item.student_ids)
        .map((student) => `- ${student.student_no} / ${student.name} / ${student.gender === 'male' ? '男' : '女'} / ${student.grade || '-'} / 原班级 ${student.class_name || '待分班'} / 均分 ${student.avg_score || 0}${student.tags ? ` / ${student.tags}` : ''}`)
        .join('\n')
      return `${item.class_name}\n人数 ${summary.assignedCount} / ${item.max_count}，男生 ${summary.maleCount}，女生 ${summary.femaleCount}，均分 ${summary.avgScore}\n${students}`
    })
    .join('\n\n')

  downloadWordDocument(
    form.batch_name || `${form.grade}正式分班预览`,
    body,
    `${form.batch_name || `${form.grade}正式分班预览`}.doc`
  )
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
  grid-template-columns: minmax(0, 1.15fr) minmax(320px, 0.85fr);
}

.workspace {
  grid-template-columns: minmax(360px, 420px) minmax(0, 1fr);
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

.overview-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.report-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.overview-item {
  padding: 16px;
  border-radius: 16px;
  background: #f8fafc;
}

.overview-label {
  font-size: 12px;
  color: #64748b;
}

.overview-value {
  margin-top: 8px;
  font-size: 24px;
  font-weight: 700;
  color: #1e293b;
}

.report-value {
  font-size: 20px;
}

.top-gap {
  margin-top: 16px;
}

@media (max-width: 1100px) {
  .page-shell,
  .workspace {
    grid-template-columns: 1fr;
  }

  .overview-grid {
    grid-template-columns: 1fr;
  }

  .report-grid {
    grid-template-columns: 1fr;
  }
}
</style>
