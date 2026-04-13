<template>
  <div class="page-container ai-page">
    <div class="ai-layout">
      <el-card shadow="never" class="config-card">
        <template #header>
          <div>
            <div class="card-title">期末评语生成</div>
            <div class="card-desc">支持单个学生精细生成，也支持按班级批量生成。系统会参考学生画像，把评语写得更贴近状态，但只使用温和表达。</div>
          </div>
        </template>

        <el-form :model="form" label-width="90px">
          <el-form-item label="生成方式">
            <el-radio-group v-model="mode">
              <el-radio-button label="student">单个学生</el-radio-button>
              <el-radio-button label="class">整班批量</el-radio-button>
            </el-radio-group>
          </el-form-item>

          <el-form-item v-if="mode === 'student'" label="学生">
            <el-select v-model="form.student_id" placeholder="请选择学生" filterable clearable class="full-width">
              <el-option v-for="item in studentOptions" :key="item.id" :label="item.name" :value="item.id" />
            </el-select>
          </el-form-item>

          <el-form-item v-else label="班级">
            <el-select v-model="form.class_id" placeholder="请选择班级" clearable class="full-width">
              <el-option v-for="item in classOptions" :key="item.id" :label="item.name" :value="item.id" />
            </el-select>
          </el-form-item>

          <el-form-item label="评语风格">
            <el-select v-model="form.style" class="full-width">
              <el-option label="鼓励型" value="鼓励型" />
              <el-option label="客观型" value="客观型" />
              <el-option label="建议型" value="建议型" />
            </el-select>
          </el-form-item>

          <el-form-item label="学期">
            <el-input v-model="form.semester" placeholder="例如：2025-2026学年第一学期" />
          </el-form-item>

          <el-form-item>
            <el-button type="primary" :loading="loading" @click="handleGenerate">生成评语</el-button>
            <el-button @click="handleReset">重置</el-button>
          </el-form-item>
        </el-form>
      </el-card>

      <AiOutputPanel
        title="评语结果"
        subtitle="生成完成后可直接复制或下载 Word 文档。"
        :content="displayContent"
        :loading="loading"
        :error="error"
        show-download
        @retry="handleGenerate"
        @download="handleDownload"
      />
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import AiOutputPanel from '@/components/ai/AiOutputPanel.vue'
import { useAiGenerate } from '@/composables/useAiGenerate'
import { generateComment } from '@/api/aiTools'
import { getStudentList } from '@/api/student'
import { getClassList } from '@/api/class_'
import { getAiHistoryDetail } from '@/api/aiHistory'
import { downloadWordDocument } from '@/utils/export'

const route = useRoute()
const router = useRouter()

const mode = ref('student')
const studentOptions = ref([])
const classOptions = ref([])
const form = reactive({
  student_id: '',
  class_id: '',
  style: '鼓励型',
  semester: ''
})

const { loading, error, result, generate, reset } = useAiGenerate(generateComment)

const displayContent = computed(() => {
  if (Array.isArray(result.value)) {
    return result.value
      .map((item, index) => `${index + 1}. ${item.student_name}\n${item.comment}`)
      .join('\n\n')
  }

  return typeof result.value === 'string' ? result.value : ''
})

onMounted(async () => {
  await Promise.all([fetchStudents(), fetchClasses()])
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

async function fetchClasses() {
  const res = await getClassList({ page: 1, page_size: 100 })
  classOptions.value = res.list
}

async function handleGenerate() {
  const payload = {
    style: form.style,
    semester: form.semester,
    student_id: mode.value === 'student' ? form.student_id || undefined : undefined,
    class_id: mode.value === 'class' ? form.class_id || undefined : undefined
  }

  if (!payload.semester) {
    ElMessage.warning('请先填写学期')
    return
  }

  if (!payload.student_id && !payload.class_id) {
    ElMessage.warning(`请选择${mode.value === 'student' ? '学生' : '班级'}`)
    return
  }

  await generate(payload)
}

function handleReset() {
  mode.value = 'student'
  form.student_id = ''
  form.class_id = ''
  form.style = '鼓励型'
  form.semester = ''
  reset('')
  router.replace({ query: {} })
}

async function loadHistory(historyId) {
  if (!historyId) {
    return
  }

  const detail = await getAiHistoryDetail(Number(historyId))
  const params = detail.input_params || {}

  mode.value = params.class_id ? 'class' : 'student'
  form.student_id = params.student_id || ''
  form.class_id = params.class_id || ''
  form.style = params.style || '鼓励型'
  form.semester = params.semester || ''
  result.value = detail.content
}

function handleDownload() {
  downloadWordDocument('期末评语生成结果', displayContent.value, '期末评语结果.doc')
}
</script>

<style scoped lang="scss">
.ai-layout {
  display: grid;
  grid-template-columns: minmax(320px, 420px) minmax(0, 1fr);
  gap: 16px;
}

.config-card {
  align-self: start;
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

@media (max-width: 960px) {
  .ai-layout {
    grid-template-columns: 1fr;
  }
}
</style>
