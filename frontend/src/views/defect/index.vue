<template>
  <section class="page" data-module="defect">
    <header class="page-head">
      <div>
        <h2>缺陷登记管理</h2>
        <p class="page-desc">维护设备缺陷，围绕缺陷编号、所属设备、缺陷类型、严重等级做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button
          class="btn primary"
          type="button"
          :disabled="!selectedCodes.length"
          @click="openGradePanel"
        >
          批量确认定级{{ selectedCodes.length ? `（已选 ${selectedCodes.length} 条）` : '' }}
        </button>
        <button class="btn primary" type="button" @click="openCreate">登记设备缺陷</button>
        <button class="btn" type="button" @click="exportRows">导出缺陷登记清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <section v-if="panelOpen" class="grade-panel">
      <div class="grade-panel-head">
        <h3 class="grade-panel-title">批量确认定级</h3>
        <button class="btn ghost" type="button" @click="closePanel">收起面板</button>
      </div>
      <p class="hint-text">
        严重等级已按所属设备与缺陷类型给出建议值；调整建议等级时必须填写定级依据，处理期限随定级一并生效。
      </p>
      <table class="data-table">
        <thead>
          <tr>
            <th>缺陷编号</th>
            <th>所属设备</th>
            <th>缺陷类型</th>
            <th>建议等级</th>
            <th>严重等级</th>
            <th>处理期限</th>
            <th>定级依据</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in editableRows" :key="row.缺陷编号">
            <td>{{ row.缺陷编号 }}</td>
            <td>{{ row.所属设备 }}</td>
            <td>{{ row.缺陷类型 }}</td>
            <td>{{ row.建议等级 }}</td>
            <td>
              <select v-model="row.严重等级">
                <option v-for="level in severityLevels" :key="level" :value="level">{{ level }}</option>
              </select>
            </td>
            <td><input v-model="row.处理期限" type="date" /></td>
            <td>
              <input
                v-model="row.定级依据"
                :class="{ 'field-error': needsBasis(row) && !row.定级依据.trim() }"
                :placeholder="needsBasis(row) ? '已调整建议等级，必填定级依据' : '按建议等级定级可留空'"
              />
            </td>
          </tr>
          <tr v-if="!editableRows.length">
            <td colspan="7" class="empty-state">本批缺陷均已定级，无待处理项</td>
          </tr>
        </tbody>
      </table>
      <div class="panel-actions">
        <button class="btn primary" type="button" :disabled="submitting || !editableRows.length" @click="submitBatch">
          {{ submitting ? '提交中…' : submitLabel }}
        </button>
        <button class="btn" type="button" :disabled="submitting" @click="closePanel">取消</button>
        <span v-if="panelError" class="error-text">{{ panelError }}</span>
        <span v-else-if="panelNotice" class="notice-text">{{ panelNotice }}</span>
      </div>

      <div v-if="failedReceipts.length" class="receipt-block">
        <h4 class="receipt-fail">定级失败（{{ failedReceipts.length }} 条）</h4>
        <ul class="receipt-list">
          <li v-for="receipt in failedReceipts" :key="receipt.缺陷编号">
            <strong>{{ receipt.缺陷编号 || '（无编号）' }}</strong>
            <span class="receipt-fail">——{{ receipt.message }}</span>
          </li>
        </ul>
      </div>
      <div v-if="successReceipts.length" class="receipt-block">
        <h4 class="receipt-ok">定级成功（{{ successReceipts.length }} 条）</h4>
        <ul class="receipt-list">
          <li v-for="receipt in successReceipts" :key="receipt.缺陷编号">
            <strong>{{ receipt.缺陷编号 }}</strong>
            <span class="receipt-ok">——{{ receipt.message }}</span>
          </li>
        </ul>
      </div>
    </section>

    <table class="data-table">
      <thead>
        <tr>
          <th>
            <input
              type="checkbox"
              title="全选本页待定级缺陷"
              :checked="allSelectableChecked"
              :disabled="!selectableRows.length"
              @change="toggleSelectAll"
            />
          </th>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td>
            <input
              v-if="row.status === '待定级'"
              type="checkbox"
              :checked="selectedCodes.includes(String(row.缺陷编号))"
              @change="toggleSelect(row)"
            />
          </td>
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 2" class="empty-state">暂无缺陷登记数据，可先登记设备缺陷</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条缺陷登记记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
      <span v-else-if="noticeMessage" class="notice-text">{{ noticeMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>
type StatItem = { label: string; value: number }
type Receipt = { 缺陷编号: string; ok: boolean; message: string }
type Suggestion = {
  缺陷编号: string
  found: boolean
  建议严重等级?: string
  建议处理期限?: string
}
type GradeRow = {
  缺陷编号: string
  所属设备: string
  缺陷类型: string
  建议等级: string
  建议期限: string
  严重等级: string
  处理期限: string
  定级依据: string
}

const ENDPOINT = '/api/defect'
const columns = ["缺陷编号", "所属设备", "缺陷类型", "严重等级", "发现时间", "发现人", "处理期限", "缺陷状态"]
const actions = ["确认定级", "提交闭环", "挂起缺陷"]
const severityLevels = ["一般", "严重", "危急"]

const stats = ref<StatItem[]>([
  { label: '待定级缺陷', value: 0 },
  { label: '处理中缺陷', value: 0 },
  { label: '超期未闭环', value: 0 },
])

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const noticeMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

const selectedCodes = ref<string[]>([])

const panelOpen = ref(false)
const submitting = ref(false)
const gradeRows = ref<GradeRow[]>([])
// 回执按缺陷编号合并：重试时同一条缺陷只保留最新回执，不会重复显示。
const receipts = ref<Record<string, Receipt>>({})
const panelError = ref('')
const panelNotice = ref('')

const selectableRows = computed(() => rows.value.filter((row) => row.status === '待定级'))
const allSelectableChecked = computed(
  () =>
    selectableRows.value.length > 0 &&
    selectableRows.value.every((row) => selectedCodes.value.includes(String(row.缺陷编号))),
)
// 已定级成功的缺陷从编辑区移除，只保留待提交与失败的行，重试不会重复提交成功项。
const editableRows = computed(() => gradeRows.value.filter((row) => !receipts.value[row.缺陷编号]?.ok))
const failedReceipts = computed(() => Object.values(receipts.value).filter((receipt) => !receipt.ok))
const successReceipts = computed(() => Object.values(receipts.value).filter((receipt) => receipt.ok))
const submitLabel = computed(() => (Object.keys(receipts.value).length ? '重试未完成缺陷' : '提交定级'))

function needsBasis(row: GradeRow) {
  return row.严重等级 !== row.建议等级
}

function toggleSelect(row: Row) {
  const code = String(row.缺陷编号 ?? '')
  if (!code) return
  const index = selectedCodes.value.indexOf(code)
  if (index >= 0) {
    selectedCodes.value.splice(index, 1)
  } else {
    selectedCodes.value.push(code)
  }
}

function toggleSelectAll() {
  const visible = selectableRows.value.map((row) => String(row.缺陷编号))
  if (allSelectableChecked.value) {
    selectedCodes.value = selectedCodes.value.filter((code) => !visible.includes(code))
  } else {
    selectedCodes.value = [...new Set([...selectedCodes.value, ...visible])]
  }
}

function pruneSelection() {
  const selectable = selectableRows.value.map((row) => String(row.缺陷编号))
  selectedCodes.value = selectedCodes.value.filter((code) => selectable.includes(code))
}

async function openGradePanel() {
  panelError.value = ''
  panelNotice.value = ''
  receipts.value = {}
  gradeRows.value = selectableRows.value
    .filter((row) => selectedCodes.value.includes(String(row.缺陷编号)))
    .map((row) => ({
      缺陷编号: String(row.缺陷编号 ?? ''),
      所属设备: String(row.所属设备 ?? ''),
      缺陷类型: String(row.缺陷类型 ?? ''),
      建议等级: '一般',
      建议期限: '',
      严重等级: '一般',
      处理期限: '',
      定级依据: '',
    }))
  panelOpen.value = true
  try {
    const response = await request(`${ENDPOINT}/grade-suggestions`, {
      method: 'POST',
      body: JSON.stringify({ 缺陷编号列表: gradeRows.value.map((row) => row.缺陷编号) }),
    })
    if (!response.ok) {
      throw new Error('建议等级获取失败')
    }
    const payload = await response.json()
    const byCode = new Map<string, Suggestion>(
      ((payload.items ?? []) as Suggestion[]).map((item) => [String(item.缺陷编号), item]),
    )
    for (const row of gradeRows.value) {
      const suggestion = byCode.get(row.缺陷编号)
      if (!suggestion || !suggestion.found) continue
      row.建议等级 = suggestion.建议严重等级 ?? row.建议等级
      row.建议期限 = suggestion.建议处理期限 ?? ''
      row.严重等级 = row.建议等级
      row.处理期限 = row.建议期限
    }
  } catch {
    panelNotice.value = '建议等级获取失败，已按默认等级预填，可手工调整后提交'
  }
}

function closePanel() {
  panelOpen.value = false
  submitting.value = false
  gradeRows.value = []
  receipts.value = {}
  panelError.value = ''
  panelNotice.value = ''
  pruneSelection()
}

async function submitBatch() {
  panelError.value = ''
  panelNotice.value = ''
  const targets = editableRows.value
  for (const row of targets) {
    if (needsBasis(row) && !row.定级依据.trim()) {
      panelError.value = `缺陷 ${row.缺陷编号} 调整了建议等级，必须填写定级依据`
      return
    }
  }
  submitting.value = true
  try {
    const response = await request(`${ENDPOINT}/batch-grade`, {
      method: 'POST',
      body: JSON.stringify({
        items: targets.map((row) => ({
          缺陷编号: row.缺陷编号,
          严重等级: row.严重等级,
          定级依据: row.定级依据.trim(),
          处理期限: row.处理期限,
        })),
      }),
    })
    if (!response.ok) {
      throw new Error(`批量定级接口返回 ${response.status}`)
    }
    const payload = await response.json()
    for (const receipt of (payload.receipts ?? []) as Receipt[]) {
      receipts.value[String(receipt.缺陷编号)] = receipt
    }
    // 回执落定后刷新列表与统计，保证回执结果与列表保持一致。
    await Promise.all([reload(), loadStats()])
    if (failedReceipts.value.length === 0) {
      noticeMessage.value = payload.message ?? '批量定级完成'
      closePanel()
    } else {
      panelNotice.value = payload.message ?? ''
    }
  } catch (error) {
    // 提交中断时已定级的结果在服务端保留，刷新列表对齐实际状态后可继续重试。
    panelError.value = `提交过程被打断：${error instanceof Error ? error.message : '网络异常'}；已定级的结果已保留，可重试剩余缺陷`
    await Promise.all([reload(), loadStats()])
  } finally {
    submitting.value = false
  }
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '设备缺陷登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error('缺陷登记动作未生效，请稍后重试')
    }
    await Promise.all([reload(), loadStats()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '缺陷登记操作失败'
  }
}

async function loadStats() {
  try {
    const response = await request(`${ENDPOINT}/stats`)
    if (!response.ok) {
      throw new Error('缺陷统计读取失败')
    }
    const payload = await response.json()
    stats.value = payload.items ?? stats.value
  } catch {
    // 统计读取失败不打断列表展示，保留上一次的结果。
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('设备缺陷列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    pruneSelection()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '缺陷登记列表读取失败'
  }
}

onMounted(() => {
  void reload()
  void loadStats()
})
</script>
