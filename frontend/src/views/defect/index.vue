<template>
  <section class="page" data-module="defect">
    <header class="page-head">
      <div>
        <h2>缺陷登记管理</h2>
        <p class="page-desc">维护设备缺陷，围绕缺陷编号、所属设备、缺陷类型、严重等级做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
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

    <div class="batch-bar">
      <button class="btn primary" type="button" :disabled="!selectedCodes.length" @click="openBatchPanel">
        批量确认定级<span v-if="selectedCodes.length">（{{ selectedCodes.length }}）</span>
      </button>
      <span class="batch-hint">仅「待定级」缺陷可勾选；严重等级按缺陷类型给出建议值，修改需填写定级依据，处理期限随定级一并落上</span>
    </div>

    <table class="data-table">
      <thead>
        <tr>
          <th class="check-col">
            <input
              type="checkbox"
              :checked="allPendingSelected"
              :disabled="!pendingRows.length"
              title="全选待定级缺陷"
              @change="toggleAll"
            />
          </th>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td class="check-col">
            <input
              v-if="isPending(row)"
              type="checkbox"
              :checked="selectedCodes.includes(String(row['缺陷编号']))"
              @change="toggleOne(String(row['缺陷编号']))"
            />
            <span v-else>—</span>
          </td>
          <td v-for="column in columns" :key="column">{{ row[column] || '—' }}</td>
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
    </footer>

    <div v-if="panelOpen" class="grading-mask" @click.self="closePanel">
      <div class="grading-panel">
        <header class="panel-head">
          <h3>批量确认定级</h3>
          <p class="page-desc">严重等级与处理期限已按缺陷类型预填建议值，可逐条调整；调整严重等级必须留下定级依据。</p>
        </header>

        <table v-if="gradeItems.length" class="data-table">
          <thead>
            <tr>
              <th>缺陷编号</th>
              <th>所属设备</th>
              <th>缺陷类型</th>
              <th>建议严重等级</th>
              <th>严重等级</th>
              <th>处理期限</th>
              <th>定级依据</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in gradeItems" :key="item.缺陷编号">
              <td>{{ item.缺陷编号 }}</td>
              <td>{{ item.所属设备 }}</td>
              <td>{{ item.缺陷类型 }}</td>
              <td>{{ item.建议严重等级 }}（{{ item.建议处理期限 }} 前）</td>
              <td>
                <select v-model="item.严重等级">
                  <option v-for="level in severityLevels" :key="level" :value="level">{{ level }}</option>
                </select>
              </td>
              <td><input v-model="item.处理期限" type="date" /></td>
              <td>
                <input
                  v-model="item.定级依据"
                  :placeholder="needsBasis(item) ? '与建议值不一致，必填定级依据' : '可留空，默认按建议值定级'"
                />
                <span v-if="needsBasis(item)" class="basis-required">* 必填</span>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-else class="empty-state">所选缺陷均已完成定级，无待提交条目</p>

        <div v-if="failedReceipts.length" class="receipt-block failed">
          <h4>失败 {{ failedReceipts.length }} 条（未落库，可在上方修正后重试）</h4>
          <ul>
            <li v-for="receipt in failedReceipts" :key="receipt.缺陷编号">
              <strong>{{ receipt.缺陷编号 || '（空编号）' }}</strong>：{{ receipt.message }}
            </li>
          </ul>
        </div>
        <div v-if="doneReceipts.length" class="receipt-block done">
          <h4>已生效 {{ doneReceipts.length }} 条（成功条目不可随批量回退）</h4>
          <ul>
            <li v-for="receipt in doneReceipts" :key="receipt.缺陷编号">
              <strong>{{ receipt.缺陷编号 }}</strong>：{{ receipt.message }}
              <span v-if="receipt.repeated" class="repeated-tag">重复提交已跳过</span>
            </li>
          </ul>
        </div>

        <footer class="panel-foot">
          <span v-if="panelMessage" class="panel-message">{{ panelMessage }}</span>
          <span v-if="panelError" class="error-text">{{ panelError }}</span>
          <span class="panel-actions">
            <button
              v-if="gradeItems.length"
              class="btn primary"
              type="button"
              :disabled="submitting"
              @click="submitBatch"
            >
              {{ submitting ? '提交中…' : failedReceipts.length ? `重试失败项（${failedReceipts.length}）` : '提交定级' }}
            </button>
            <button class="btn ghost" type="button" @click="closePanel">关闭</button>
          </span>
        </footer>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | null>
type StatItem = { label: string; value: number }
type GradeItemState = {
  缺陷编号: string
  所属设备: string
  缺陷类型: string
  建议严重等级: string
  建议处理期限: string
  严重等级: string
  处理期限: string
  定级依据: string
}
type Receipt = { 缺陷编号: string; ok: boolean; repeated: boolean; message: string }

const ENDPOINT = '/api/defect'
const columns = ["缺陷编号", "所属设备", "缺陷类型", "严重等级", "发现时间", "发现人", "处理期限", "缺陷状态"]
const actions = ["确认定级", "提交闭环", "挂起缺陷"]
const severityLevels = ["一般", "严重", "危急"]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const stats = ref<StatItem[]>([
  { label: '待定级缺陷', value: 0 },
  { label: '处理中缺陷', value: 0 },
  { label: '超期未闭环', value: 0 },
])

const selectedCodes = ref<string[]>([])
const panelOpen = ref(false)
const submitting = ref(false)
const panelMessage = ref('')
const panelError = ref('')
const gradeItems = ref<GradeItemState[]>([])
// 回执按缺陷编号去重：重试时覆盖旧回执，不会重复显示同一条。
const receiptMap = ref(new Map<string, Receipt>())

const pendingRows = computed(() => rows.value.filter((row) => isPending(row)))
const allPendingSelected = computed(
  () => pendingRows.value.length > 0 && pendingRows.value.every((row) => selectedCodes.value.includes(String(row['缺陷编号']))),
)
const receipts = computed(() => [...receiptMap.value.values()])
const failedReceipts = computed(() => receipts.value.filter((receipt) => !receipt.ok))
const doneReceipts = computed(() => receipts.value.filter((receipt) => receipt.ok))

function isPending(row: Row) {
  return row.status === '待定级'
}

function needsBasis(item: GradeItemState) {
  return item.严重等级 !== item.建议严重等级
}

function toggleOne(code: string) {
  selectedCodes.value = selectedCodes.value.includes(code)
    ? selectedCodes.value.filter((item) => item !== code)
    : [...selectedCodes.value, code]
}

function toggleAll() {
  const pendingCodes = pendingRows.value.map((row) => String(row['缺陷编号']))
  selectedCodes.value = allPendingSelected.value ? [] : pendingCodes
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
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error('缺陷登记动作未生效，请稍后重试')
    }
    await refresh()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '缺陷登记操作失败'
  }
}

async function openBatchPanel() {
  panelOpen.value = true
  panelMessage.value = ''
  panelError.value = ''
  gradeItems.value = []
  receiptMap.value = new Map()
  try {
    const response = await request(`${ENDPOINT}/grading/suggest`, {
      method: 'POST',
      body: JSON.stringify({ codes: selectedCodes.value }),
    })
    if (!response.ok) {
      throw new Error('定级建议值读取失败，请稍后重试')
    }
    const payload = await response.json()
    const suggestions = (payload.items ?? []) as Array<Record<string, string | boolean>>
    gradeItems.value = suggestions
      .filter((item) => item.可定级)
      .map((item) => ({
        缺陷编号: String(item.缺陷编号),
        所属设备: String(item.所属设备 ?? ''),
        缺陷类型: String(item.缺陷类型 ?? ''),
        建议严重等级: String(item.建议严重等级),
        建议处理期限: String(item.建议处理期限),
        严重等级: String(item.建议严重等级),
        处理期限: String(item.建议处理期限),
        定级依据: '',
      }))
    // 勾选后状态已变化的条目直接给出原因，不进入待提交清单。
    for (const item of suggestions.filter((entry) => !entry.可定级)) {
      upsertReceipt({ 缺陷编号: String(item.缺陷编号), ok: false, repeated: false, message: String(item.提示) })
    }
  } catch (error) {
    panelError.value = error instanceof Error ? error.message : '定级建议值读取失败'
  }
}

async function submitBatch() {
  panelError.value = ''
  panelMessage.value = ''
  // 严重等级偏离建议值却没填依据的条目先拦在本地，按失败回执展示。
  const ready: GradeItemState[] = []
  for (const item of gradeItems.value) {
    if (needsBasis(item) && !item.定级依据.trim()) {
      upsertReceipt({ 缺陷编号: item.缺陷编号, ok: false, repeated: false, message: `严重等级与建议值「${item.建议严重等级}」不一致，必须填写定级依据` })
    } else if (!item.处理期限) {
      upsertReceipt({ 缺陷编号: item.缺陷编号, ok: false, repeated: false, message: '处理期限不能为空，需随定级一起落上' })
    } else {
      ready.push(item)
    }
  }
  if (!ready.length) {
    return
  }
  submitting.value = true
  try {
    const response = await request(`${ENDPOINT}/grading/batch`, {
      method: 'POST',
      body: JSON.stringify({
        items: ready.map((item) => ({
          缺陷编号: item.缺陷编号,
          严重等级: item.严重等级,
          处理期限: item.处理期限,
          定级依据: item.定级依据,
        })),
      }),
    })
    if (!response.ok) {
      throw new Error('批量定级提交未生效，已定级条目会保留，可重试')
    }
    const payload = await response.json()
    panelMessage.value = String(payload.message ?? '')
    const doneCodes: string[] = []
    for (const receipt of (payload.receipts ?? []) as Receipt[]) {
      upsertReceipt(receipt)
      if (receipt.ok) {
        doneCodes.push(receipt.缺陷编号)
      }
    }
    // 成功条目移出待提交清单并取消勾选，面板里只留下失败项供修正重试。
    gradeItems.value = gradeItems.value.filter((item) => !doneCodes.includes(item.缺陷编号))
    selectedCodes.value = selectedCodes.value.filter((code) => !doneCodes.includes(code))
    await refresh()
  } catch (error) {
    // 提交被打断时保留面板与已收到的回执，重试由后端幂等兜底。
    panelError.value = error instanceof Error ? error.message : '批量定级提交失败，可重试'
  } finally {
    submitting.value = false
  }
}

function upsertReceipt(receipt: Receipt) {
  const next = new Map(receiptMap.value)
  next.set(receipt.缺陷编号, receipt)
  receiptMap.value = next
}

function closePanel() {
  panelOpen.value = false
  gradeItems.value = []
  receiptMap.value = new Map()
  panelMessage.value = ''
  panelError.value = ''
}

async function refresh() {
  await Promise.all([reload(), loadStats()])
}

async function loadStats() {
  try {
    const response = await request(`${ENDPOINT}/stats`)
    if (!response.ok) {
      return
    }
    const payload = await response.json()
    stats.value = payload.items ?? stats.value
  } catch {
    // 统计读取失败不阻塞列表使用
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
    // 列表刷新后清掉已不在待定级范围的勾选，保证勾选与回执、列表口径一致。
    const pendingCodes = new Set(pendingRows.value.map((row) => String(row['缺陷编号'])))
    selectedCodes.value = selectedCodes.value.filter((code) => pendingCodes.has(code))
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '缺陷登记列表读取失败'
  }
}

onMounted(refresh)
</script>

<style scoped>
.check-col {
  width: 36px;
  text-align: center;
}
.batch-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}
.batch-hint {
  font-size: 12px;
  color: var(--muted);
}
.grading-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.35);
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding: 40px 16px;
  z-index: 10;
}
.grading-panel {
  background: #fff;
  border-radius: 8px;
  padding: 16px;
  width: min(1040px, 100%);
  max-height: 85vh;
  overflow: auto;
}
.panel-head h3 {
  margin: 0 0 4px;
}
.grading-panel select,
.grading-panel input {
  width: 100%;
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 4px 6px;
  font-size: 13px;
}
.basis-required {
  color: #b42318;
  font-size: 12px;
}
.receipt-block {
  margin-top: 12px;
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 8px 12px;
  font-size: 13px;
}
.receipt-block h4 {
  margin: 0 0 6px;
  font-size: 13px;
}
.receipt-block ul {
  margin: 0;
  padding-left: 18px;
}
.receipt-block.failed {
  border-color: #f04438;
  background: #fef3f2;
}
.receipt-block.done {
  border-color: #12b76a;
  background: #f6fef9;
}
.repeated-tag {
  margin-left: 6px;
  font-size: 12px;
  color: var(--muted);
}
.panel-foot {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 12px;
}
.panel-message {
  font-size: 13px;
  color: var(--muted);
}
.panel-actions {
  margin-left: auto;
  display: flex;
  gap: 8px;
}
</style>
