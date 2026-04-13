<template>
  <div class="page-container ai-page">
    <div class="ai-layout">
      <el-card shadow="never">
        <template #header>
          <div>
            <div class="card-title">成绩波动诊断</div>
            <div class="card-desc">结合历史成绩趋势和学生画像状态，生成更个性化、带关怀建议的分析结果。</div>
          </div>
        </template>

        <el-form :model="form" label-width="90px">
          <el-form-item label="学生">
            <el-select v-model="form.student_id" clearable filterable class="full-width" placeholder="留空则按当前学生">
              <el-option v-for="item in studentOptions" :key="item.id" :label="item.name" :value="item.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="学科">
            <el-select v-model="form.subject" clearable class="full-width" placeholder="留空则分析全部学科">
              <el-option v-for="item in subjectOptions" :key="item" :label="item" :value="item" />
            </el-select>
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="loading" @click="handleGenerate">生成诊断</el-button>
          </el-form-item>
        </el-form>

        <el-divider />

        <el-alert
          type="info"
          :closable="false"
          show-icon
          title="诊断会参考学生画像状态，但输出只采用温和、支持性的表达，不直接展示风险标签。"
          style="margin-bottom: 16px"
        />

        <el-table v-if="result?.score_data?.length" :data="result.score_data.slice(-6)" size="small" border>
          <el-table-column prop="exam_batch" label="批次" min-width="120" />
          <el-table-column prop="subject" label="学科" width="100" />
          <el-table-column prop="score" label="分数" width="80" />
          <el-table-column prop="date" label="日期" width="110" />
        </el-table>
      </el-card>

      <AiOutputPanel
        title="诊断报告"
        subtitle="会根据趋势变化给出优势、风险点和后续建议。"
        :content="result?.diagnosis || ''"
        :loading="loading"
        :error="error"
        show-download
        @retry="handleGenerate"
        @download="handleDownload"
      >
        <template v-if="result?.diagnosis">
          <div class="diagnosis-body">
            <pre class="content-text">{{ result.diagnosis }}</pre>
            <div v-if="result.subject_analysis?.length" class="analysis-list">
              <div class="analysis-title">学科趋势摘要</div>
              <ul>
                <li v-for="item in result.subject_analysis" :key="item">{{ item }}</li>
              </ul>
            </div>
          </div>
        </template>
      </AiOutputPanel>
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import AiOutputPanel from '@/components/ai/AiOutputPanel.vue'
import { useAiGenerate } from '@/composables/useAiGenerate'
import { diagnoseScore } from '@/api/aiTools'
import { getStudentList } from '@/api/student'
import { getAiHistoryDetail } from '@/api/aiHistory'
import { downloadWordDocument } from '@/utils/export'

const route = useRoute()
const studentOptions = ref([])
const subjectOptions = ['语文', '数学', '英语', '物理', '化学', '生物', '历史', '地理', '政治']
const form = reactive({
  student_id: '',
  subject: ''
})

const { loading, error, result, generate } = useAiGenerate(diagnoseScore)

onMounted(async () => {
  await fetchStudents()
  await loadHistory(route.query.historyId)
})

watch(
  () => route.query.historyId,
  async (historyId, prevId) => {
    if (historyId && historyId !== prevId) {
      await loadHistory(historyId)
    }
  }
)

async function fetchStudents() {
  const res = await getStudentList({ page: 1, page_size: 100 })
  studentOptions.value = res.list
}

async function handleGenerate() {
  await generate({
    student_id: form.student_id || undefined,
    subject: form.subject || undefined
  })
}

async function loadHistory(historyId) {
  if (!historyId) {
    return
  }

  const detail = await getAiHistoryDetail(Number(historyId))
  Object.assign(form, detail.input_params || {})
  result.value = {
    diagnosis: detail.content,
    score_data: [],
    subject_analysis: []
  }
}

function handleDownload() {
  const extra = result.value?.subject_analysis?.length
    ? `\n\n学科趋势摘要：\n${result.value.subject_analysis.join('\n')}`
    : ''
  downloadWordDocument('成绩波动诊断', `${result.value?.diagnosis || ''}${extra}`, '成绩波动诊断.doc')
}
</script>

<style scoped lang="scss">
.ai-layout {
  display: grid;
  grid-template-columns: minmax(320px, 420px) minmax(0, 1fr);
  gap: 16px;
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

.full-width {
  width: 100%;
}

.diagnosis-body {
  display: grid;
  gap: 20px;
}

.content-text {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.8;
}

.analysis-title {
  margin-bottom: 8px;
  font-weight: 600;
}

.analysis-list ul {
  margin: 0;
  padding-left: 20px;
  color: #4b5563;
  line-height: 1.7;
}

@media (max-width: 960px) {
  .ai-layout {
    grid-template-columns: 1fr;
  }
}
</style>
