<template>
  <div class="container">
    <!-- Header -->
    <div class="header">
      <h1>🗄️ Distributed Database Dashboard</h1>
      <p>Real-time monitoring and control of distributed MySQL system with adaptive quorum and leader election</p>
    </div>

    <!-- Service Status -->
    <Panel header="Service Status" class="mb-4">
      <div class="grid grid-3">
        <Card v-for="service in services" :key="service.name">
          <template #title>
            <div class="flex justify-content-between align-items-center">
              <span>{{ service.name }}</span>
              <Tag :severity="service.healthy ? 'success' : 'danger'">
                <span class="status-badge">
                  <span class="status-dot" :class="{ healthy: service.healthy, unhealthy: !service.healthy }"></span>
                  {{ service.healthy ? 'Healthy' : 'Down' }}
                </span>
              </Tag>
            </div>
          </template>
          <template #content>
            <div class="text-sm text-color-secondary">
              <div><strong>Port:</strong> {{ service.port }}</div>
              <div v-if="service.role"><strong>Role:</strong> {{ service.role }}</div>
            </div>
          </template>
        </Card>
      </div>
    </Panel>

    <!-- Metrics -->
    <Panel header="Replica Metrics" class="mb-4">
      <div class="metric-card mb-3">
        <div class="metric-label">Master Timestamp</div>
        <div class="metric-value">
          <Tag severity="info">{{ masterTimestamp }}</Tag>
        </div>
      </div>
      <DataTable :value="metrics" :loading="loadingMetrics">
        <Column field="replica_id" header="Replica ID"></Column>
        <Column field="latency_ms" header="Latency (ms)">
          <template #body="slotProps">
            {{ slotProps.data.latency_ms.toFixed(2) }}
          </template>
        </Column>
        <Column field="replication_lag" header="Timestamp Lag">
          <template #body="slotProps">
            <Tag :severity="slotProps.data.replication_lag === 0 ? 'success' : slotProps.data.replication_lag < 5 ? 'warning' : 'danger'">
              {{ slotProps.data.replication_lag }} behind
            </Tag>
          </template>
        </Column>
        <Column header="Replica Timestamp">
          <template #body="slotProps">
            {{ masterTimestamp - slotProps.data.replication_lag }}
          </template>
        </Column>
        <Column field="uptime_seconds" header="Uptime (s)">
          <template #body="slotProps">
            {{ slotProps.data.uptime_seconds.toFixed(1) }}
          </template>
        </Column>
        <Column field="crash_count" header="Crashes"></Column>
        <Column field="is_healthy" header="Status">
          <template #body="slotProps">
            <Tag :severity="slotProps.data.is_healthy ? 'success' : 'danger'">
              {{ slotProps.data.is_healthy ? 'Healthy' : 'Unhealthy' }}
            </Tag>
          </template>
        </Column>
      </DataTable>
    </Panel>

    <!-- Consistency Metrics -->
    <Panel header="Consistency Level Metrics" class="mb-4">
      <DataTable :value="consistencyMetricsArray" :loading="loadingConsistencyMetrics">
        <Column field="level" header="Level">
          <template #body="slotProps">
            <Tag :severity="getConsistencySeverity(slotProps.data.level)">{{ slotProps.data.level }}</Tag>
          </template>
        </Column>
        <Column field="count" header="Requests">
          <template #body="slotProps">
            {{ slotProps.data.count }}
          </template>
        </Column>
        <Column field="avg_latency_ms" header="Avg Latency (ms)">
          <template #body="slotProps">
            <Tag :severity="getLatencySeverity(slotProps.data.avg_latency_ms)">
              {{ slotProps.data.avg_latency_ms.toFixed(2) }}
            </Tag>
          </template>
        </Column>
        <Column field="failures" header="Failures">
          <template #body="slotProps">
            <Tag :severity="slotProps.data.failures > 0 ? 'danger' : 'success'">
              {{ slotProps.data.failures }}
            </Tag>
          </template>
        </Column>
        <Column field="success_rate" header="Success Rate">
          <template #body="slotProps">
            <Tag :severity="slotProps.data.success_rate >= 95 ? 'success' : 'warning'">
              {{ slotProps.data.success_rate.toFixed(1) }}%
            </Tag>
          </template>
        </Column>
      </DataTable>
    </Panel>

    <!-- Query Execution -->
    <Panel header="Query Execution" class="mb-4">
      <div class="query-section">
        <div class="mb-3">
          <label class="block mb-2 font-semibold">SQL Query</label>
          <Textarea 
            v-model="query" 
            rows="3" 
            class="w-full"
            placeholder="Enter SQL query (e.g., SELECT * FROM users)"
          />
        </div>
        
        <div class="mb-3">
          <label class="block mb-2 font-semibold">Consistency Levels</label>
          <Dropdown 
            v-model="consistencyLevel" 
            :options="consistencyOptions" 
            optionLabel="label" 
            optionValue="value"
            placeholder="Select Consistency Level"
            class="w-full"
          >
            <template #value="slotProps">
              <div v-if="slotProps.value">
                <Tag :severity="getConsistencySeverity(slotProps.value)" class="mr-2">{{ slotProps.value }}</Tag>
                <span class="text-sm">{{ getConsistencyDescription(slotProps.value) }}</span>
              </div>
            </template>
            <template #option="slotProps">
              <div>
                <Tag :severity="getConsistencySeverity(slotProps.option.value)" class="mr-2">{{ slotProps.option.value }}</Tag>
                <span class="text-sm">{{ slotProps.option.description }}</span>
              </div>
            </template>
          </Dropdown>
        </div>
        
        <div class="action-buttons mb-3">
          <Button 
            label="Execute Query" 
            icon="pi pi-play" 
            @click="executeQuery"
            :loading="executing"
            severity="primary"
          />
          <Button 
            label="Insert Sample Data" 
            icon="pi pi-plus" 
            @click="insertSampleData"
            severity="secondary"
          />
          <Button 
            label="Get Quorum" 
            icon="pi pi-users" 
            @click="getQuorum"
            severity="info"
          />
        </div>

        <!-- Execution Flow -->
        <div v-if="executionFlow.length > 0" class="execution-flow">
          <h4 class="mb-3">Execution Flow</h4>
          <div v-for="(step, index) in executionFlow" :key="index" class="flow-step">
            <div class="flow-step-number">{{ index + 1 }}</div>
            <div class="flow-step-content">
              <div class="flow-step-title">{{ step.title }}</div>
              <div class="flow-step-detail">{{ step.detail }}</div>
            </div>
          </div>
        </div>

        <!-- Query Result -->
        <div v-if="queryResult" class="mt-3">
          <Message :severity="queryResult.success ? 'success' : 'error'" :closable="false">
            {{ queryResult.message }}
          </Message>
          <div v-if="queryResult.data && queryResult.data.length > 0" class="mt-2">
            <DataTable :value="queryResult.data" class="mt-2">
              <Column v-for="col in Object.keys(queryResult.data[0])" :key="col" :field="col" :header="col"></Column>
            </DataTable>
          </div>
        </div>
      </div>
    </Panel>

    <!-- Failover Testing -->
    <Panel header="🔄 Failover Testing" class="mb-4">
      <div class="danger-zone">
        <h4>Master Failover (Binlog-Based with 3 Replicas)</h4>
        <p class="text-sm mb-3">Test failover scenarios. SEER will elect the best replica based on latency, lag, and stability.</p>
        <div class="action-buttons">
          <Button 
            label="Stop Master (Crash + Recovery)" 
            icon="pi pi-power-off" 
            @click="stopMaster"
            severity="danger"
            :loading="failoverInProgress"
          />
          <Button 
            label="Elect New Leader (Graceful)" 
            icon="pi pi-star" 
            @click="electLeaderOnly"
            severity="warning"
            :loading="electionInProgress"
          />
        </div>
        <p v-if="failoverInProgress" class="text-sm mt-2" style="color: orange;">
          ⏳ Stopping master and recovering... {{ recoveryCountdown > 0 ? `(${recoveryCountdown}s)` : '' }}
        </p>
        
        <!-- Failover Execution Flow -->
        <div v-if="failoverFlow.length > 0" class="execution-flow mt-3">
          <h4 class="mb-3">Failover Progress</h4>
          <div v-for="(step, index) in failoverFlow" :key="index" class="flow-step">
            <div class="flow-step-number">{{ index + 1 }}</div>
            <div class="flow-step-content">
              <div class="flow-step-title">{{ step.title }}</div>
              <div class="flow-step-detail">{{ step.detail }}</div>
            </div>
          </div>
        </div>
        
        <!-- Failover Result -->
        <div v-if="failoverResult" class="mt-3">
          <Message :severity="failoverResult.success ? 'success' : 'error'" :closable="false">
            {{ failoverResult.message }}
          </Message>
        </div>
      </div>
    </Panel>

    <!-- System Status -->
    <Panel header="System Status" class="mb-4">
      <div class="metric-card">
        <div class="metric-label">Current Master</div>
        <div class="metric-value">{{ systemStatus.current_master?.id || 'Loading...' }} ({{ systemStatus.current_master?.host || '' }})</div>
      </div>
      <div class="metric-card mt-2">
        <div class="metric-label">Current Replicas ({{ systemStatus.total_replicas || 0 }})</div>
        <div class="metric-value">
          <div v-for="replica in systemStatus.current_replicas" :key="replica.id" class="text-sm">
            {{ replica.id }} ({{ replica.host }})
          </div>
        </div>
      </div>
      <div class="metric-card mt-2">
        <div class="metric-label">Replication Mode</div>
        <div class="metric-value">
          <Tag severity="info">
            {{ systemStatus.replication_mode || 'binlog' }} (MySQL Native)
          </Tag>
        </div>
      </div>
      <div class="metric-card mt-2">
        <div class="metric-label">Quorum Size</div>
        <div class="metric-value">
          <Tag severity="success">
            2 out of {{ systemStatus.total_replicas || 3 }} replicas
          </Tag>
        </div>
      </div>
    </Panel>

    <!-- Stress Testing -->
    <Panel header="🔥 Stress Testing" class="mb-4">
      <div class="stress-test-section">
        <p class="text-sm mb-3">Test distributed system performance under load. These tests demonstrate timestamp ordering, quorum replication, and consistency trade-offs.</p>
        
        <!-- Data Count & Clear -->
        <div class="metric-card mb-3">
          <div class="flex justify-content-between align-items-center">
            <div>
              <div class="metric-label">Current Test Data</div>
              <div class="metric-value">
                <Tag severity="info" class="mr-2">{{ dataCount.users }} users</Tag>
                <Tag severity="info">{{ dataCount.products }} products</Tag>
              </div>
            </div>
            <Button 
              label="Clear All Data" 
              icon="pi pi-trash" 
              @click="clearData"
              severity="secondary"
              size="small"
              :loading="clearingData"
            />
          </div>
        </div>

        <!-- Test Configuration -->
        <div class="grid grid-2 mb-3">
          <div>
            <label class="block mb-2 font-semibold">Operations Count</label>
            <Dropdown 
              v-model="stressTestOps" 
              :options="[10, 25, 50, 100, 200]" 
              placeholder="Select count"
              class="w-full"
            />
          </div>
          <div>
            <label class="block mb-2 font-semibold">Consistency Level</label>
            <Dropdown 
              v-model="stressTestConsistency" 
              :options="consistencyOptions" 
              optionLabel="label" 
              optionValue="value"
              placeholder="Select level"
              class="w-full"
            />
          </div>
        </div>

        <!-- Test Buttons -->
        <div class="action-buttons mb-3">
          <Button 
            label="Concurrent Writes" 
            icon="pi pi-bolt" 
            @click="runConcurrentWritesTest"
            severity="primary"
            :loading="stressTestRunning === 'concurrent'"
            :disabled="stressTestRunning !== null"
          />
          <Button 
            label="Read/Write Mix" 
            icon="pi pi-sync" 
            @click="runReadWriteMixTest"
            severity="info"
            :loading="stressTestRunning === 'mix'"
            :disabled="stressTestRunning !== null"
          />
          <Button 
            label="Compare Consistency Levels" 
            icon="pi pi-chart-bar" 
            @click="runConsistencyComparisonTest"
            severity="warning"
            :loading="stressTestRunning === 'comparison'"
            :disabled="stressTestRunning !== null"
          />
        </div>

        <!-- Test Progress -->
        <div v-if="stressTestRunning" class="mb-3">
          <ProgressBar mode="indeterminate" style="height: 6px" />
          <p class="text-sm mt-2" style="color: orange;">
            ⏳ Running {{ stressTestRunning }} test with {{ stressTestOps }} operations...
          </p>
        </div>

        <!-- Test Results -->
        <div v-if="stressTestResult" class="stress-test-results">
          <h4 class="mb-3">📊 {{ stressTestResult.test_name }} Results</h4>
          
          <!-- Summary Cards -->
          <div class="grid grid-4 mb-3">
            <div class="result-card">
              <div class="result-value">{{ stressTestResult.throughput_ops_per_sec }}</div>
              <div class="result-label">ops/sec</div>
            </div>
            <div class="result-card">
              <div class="result-value">{{ stressTestResult.avg_latency_ms }}ms</div>
              <div class="result-label">avg latency</div>
            </div>
            <div class="result-card success">
              <div class="result-value">{{ stressTestResult.successful }}/{{ stressTestResult.total_operations }}</div>
              <div class="result-label">successful</div>
            </div>
            <div class="result-card">
              <div class="result-value">{{ stressTestResult.duration_seconds }}s</div>
              <div class="result-label">duration</div>
            </div>
          </div>

          <!-- Detailed Stats -->
          <DataTable :value="[stressTestResult]" class="mb-3">
            <Column field="consistency_level" header="Consistency">
              <template #body="slotProps">
                <Tag :severity="getConsistencySeverity(slotProps.data.consistency_level)">
                  {{ slotProps.data.consistency_level }}
                </Tag>
              </template>
            </Column>
            <Column field="min_latency_ms" header="Min Latency">
              <template #body="slotProps">{{ slotProps.data.min_latency_ms }}ms</template>
            </Column>
            <Column field="max_latency_ms" header="Max Latency">
              <template #body="slotProps">{{ slotProps.data.max_latency_ms }}ms</template>
            </Column>
            <Column field="failed" header="Failed">
              <template #body="slotProps">
                <Tag :severity="slotProps.data.failed > 0 ? 'danger' : 'success'">
                  {{ slotProps.data.failed }}
                </Tag>
              </template>
            </Column>
          </DataTable>

          <!-- Timestamp Range (for writes) -->
          <div v-if="stressTestResult.timestamp_range" class="metric-card mb-3">
            <div class="metric-label">Timestamp Range (proves ordering)</div>
            <div class="metric-value">
              {{ stressTestResult.timestamp_range.min }} → {{ stressTestResult.timestamp_range.max }}
              <Tag severity="success" class="ml-2">Sequential ✓</Tag>
            </div>
          </div>

          <!-- Errors if any -->
          <div v-if="stressTestResult.errors" class="mt-3">
            <Message severity="warn" :closable="false">
              <div class="font-semibold mb-2">Errors encountered:</div>
              <div v-for="(count, error) in stressTestResult.errors" :key="error" class="text-sm">
                • {{ error }}: {{ count }} occurrences
              </div>
            </Message>
          </div>
        </div>

        <!-- Consistency Comparison Results -->
        <div v-if="consistencyComparisonResult" class="stress-test-results">
          <h4 class="mb-3">📊 Consistency Level Comparison</h4>
          
          <!-- Summary -->
          <div class="grid grid-3 mb-3">
            <div class="result-card">
              <div class="result-value">{{ consistencyComparisonResult.summary.fastest }}</div>
              <div class="result-label">Fastest</div>
            </div>
            <div class="result-card success">
              <div class="result-value">{{ consistencyComparisonResult.summary.most_reliable }}</div>
              <div class="result-label">Most Reliable</div>
            </div>
            <div class="result-card">
              <div class="result-value">{{ consistencyComparisonResult.summary.highest_throughput }}</div>
              <div class="result-label">Highest Throughput</div>
            </div>
          </div>

          <!-- Comparison Table -->
          <DataTable :value="consistencyComparisonArray">
            <Column field="level" header="Level">
              <template #body="slotProps">
                <Tag :severity="getConsistencySeverity(slotProps.data.level)">
                  {{ slotProps.data.level }}
                </Tag>
              </template>
            </Column>
            <Column field="successful" header="Success">
              <template #body="slotProps">
                <Tag :severity="slotProps.data.successful === slotProps.data.total ? 'success' : 'warning'">
                  {{ slotProps.data.successful }}/{{ slotProps.data.total }}
                </Tag>
              </template>
            </Column>
            <Column field="avg_latency_ms" header="Avg Latency">
              <template #body="slotProps">
                <Tag :severity="getLatencySeverity(slotProps.data.avg_latency_ms)">
                  {{ slotProps.data.avg_latency_ms }}ms
                </Tag>
              </template>
            </Column>
            <Column field="throughput_ops_per_sec" header="Throughput">
              <template #body="slotProps">{{ slotProps.data.throughput_ops_per_sec }} ops/s</template>
            </Column>
            <Column field="duration_seconds" header="Duration">
              <template #body="slotProps">{{ slotProps.data.duration_seconds }}s</template>
            </Column>
          </DataTable>
        </div>
      </div>
    </Panel>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'

const API_BASE = 'http://localhost:9000'

// State
const services = ref([
  { name: 'Coordinator', port: 9000, healthy: false, role: 'API Gateway' },
  { name: 'MySQL Instance 1', port: 3306, healthy: false, role: 'Master (Binlog Source)' },
  { name: 'MySQL Instance 2', port: 3307, healthy: false, role: 'Replica (Binlog Consumer)' },
  { name: 'MySQL Instance 3', port: 3308, healthy: false, role: 'Replica (Binlog Consumer)' },
  { name: 'MySQL Instance 4', port: 3309, healthy: false, role: 'Replica (Binlog Consumer)' },
  { name: 'Timestamp Service 1', port: 9001, healthy: false, role: 'Odd Timestamps' },
  { name: 'Timestamp Service 2', port: 9002, healthy: false, role: 'Even Timestamps' },
  { name: 'Metrics Collector', port: 9003, healthy: false, role: 'Monitoring' },
  { name: 'Cabinet Service', port: 9004, healthy: false, role: 'Quorum Selection' },
  { name: 'SEER Service', port: 9005, healthy: false, role: 'Leader Election' },
])

const metrics = ref<any[]>([])
const masterTimestamp = ref<number>(0)
const loadingMetrics = ref(false)
const query = ref('SELECT * FROM users')
const executing = ref(false)
const executionFlow = ref<any[]>([])
const failoverFlow = ref<any[]>([])
const queryResult = ref<any>(null)
const systemStatus = ref<any>({})
const masterRunning = ref(true)
const failoverInProgress = ref(false)
const electionInProgress = ref(false)
const recoveryCountdown = ref(0)
const failoverResult = ref<any>(null)
const consistencyLevel = ref('QUORUM')
const consistencyMetrics = ref<any>({})
const consistencyMetricsArray = ref<any[]>([])
const loadingConsistencyMetrics = ref(false)

// Stress test state
const stressTestRunning = ref<string | null>(null)
const stressTestOps = ref(50)
const stressTestConsistency = ref('QUORUM')
const stressTestResult = ref<any>(null)
const consistencyComparisonResult = ref<any>(null)
const consistencyComparisonArray = ref<any[]>([])
const dataCount = ref({ users: 0, products: 0, total: 0 })
const clearingData = ref(false)

const consistencyOptions = [
  { label: 'ONE', value: 'ONE', description: 'Fastest - Eventual Consistency' },
  { label: 'QUORUM', value: 'QUORUM', description: 'Balanced - Strong Consistency' },
  { label: 'ALL', value: 'ALL', description: 'Strongest - All Nodes' }
]

let refreshInterval: any = null

// Methods
const checkServiceHealth = async () => {
  const healthChecks = [
    { index: 0, url: `${API_BASE}/health` },
    { index: 7, url: 'http://localhost:9003/health' },
    { index: 8, url: 'http://localhost:9004/health' },
    { index: 9, url: 'http://localhost:9005/health' },
  ]

  for (const check of healthChecks) {
    try {
      const response = await fetch(check.url)
      const service = services.value[check.index]
      if (service) {
        service.healthy = response.ok
      }
    } catch {
      const service = services.value[check.index]
      if (service) {
        service.healthy = false
      }
    }
  }

  // Assume MySQL and timestamp services are healthy if coordinator is healthy
  const coordinator = services.value[0]
  if (coordinator?.healthy) {
    for (let i = 1; i <= 6; i++) {
      const service = services.value[i]
      if (service) {
        service.healthy = true
      }
    }
  }
}

const fetchMetrics = async () => {
  loadingMetrics.value = true
  try {
    const response = await fetch('http://localhost:9003/metrics')
    const data = await response.json()
    metrics.value = data.replicas
    masterTimestamp.value = data.master_timestamp
  } catch (error) {
    console.error('Failed to fetch metrics:', error)
  } finally {
    loadingMetrics.value = false
  }
}

const fetchSystemStatus = async () => {
  try {
    const response = await fetch(`${API_BASE}/status`)
    systemStatus.value = await response.json()
    // Check if current master is instance-1 (original master)
    masterRunning.value = systemStatus.value.current_master?.id === 'instance-1'
  } catch (error) {
    console.error('Failed to fetch system status:', error)
  }
}

const fetchConsistencyMetrics = async () => {
  loadingConsistencyMetrics.value = true
  try {
    const response = await fetch(`${API_BASE}/consistency-metrics`)
    const data = await response.json()
    consistencyMetrics.value = data
    
    // Convert to array for DataTable
    consistencyMetricsArray.value = Object.keys(data).map(level => ({
      level,
      ...data[level]
    }))
  } catch (error) {
    console.error('Failed to fetch consistency metrics:', error)
  } finally {
    loadingConsistencyMetrics.value = false
  }
}

const getConsistencySeverity = (level: string) => {
  switch (level) {
    case 'ONE': return 'success'
    case 'QUORUM': return 'info'
    case 'ALL': return 'warning'
    default: return 'secondary'
  }
}

const getConsistencyDescription = (level: string) => {
  switch (level) {
    case 'ONE': return 'Fastest - Eventual Consistency'
    case 'QUORUM': return 'Balanced - Strong Consistency'
    case 'ALL': return 'Strongest - All Nodes'
    default: return ''
  }
}

const getLatencySeverity = (latency: number) => {
  if (latency < 20) return 'success'
  if (latency < 50) return 'info'
  return 'warning'
}

const executeQuery = async () => {
  executing.value = true
  executionFlow.value = []
  queryResult.value = null

  try {
    // Show execution flow
    executionFlow.value.push({
      title: 'Parsing Query',
      detail: `Query type: ${query.value.trim().split(' ')[0]}`
    })

    const response = await fetch(`${API_BASE}/query`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ 
        query: query.value,
        consistency: consistencyLevel.value 
      })
    })

    const result = await response.json()

    if (result.timestamp) {
      executionFlow.value.push({
        title: 'Timestamp Assigned',
        detail: `Timestamp: ${result.timestamp}`
      })
    }

    executionFlow.value.push({
      title: 'Query Executed',
      detail: `Executed on: ${result.executed_on}`
    })

    if (result.message.includes('quorum')) {
      const quorumMatch = result.message.match(/quorum: (\d+\/\d+)/)
      if (quorumMatch) {
        executionFlow.value.push({
          title: 'Quorum Achieved',
          detail: `Replicas confirmed: ${quorumMatch[1]}`
        })
      }
    }

    queryResult.value = result
    await fetchMetrics()
    await fetchSystemStatus()
    await fetchConsistencyMetrics()
  } catch (error: any) {
    queryResult.value = {
      success: false,
      message: `Error: ${error.message}`
    }
  } finally {
    executing.value = false
  }
}

const insertSampleData = () => {
  const names = ['Alice', 'Bob', 'Charlie', 'Diana', 'Eve']
  const name = names[Math.floor(Math.random() * names.length)] || 'User'
  const email = `${name.toLowerCase()}@example.com`
  query.value = `INSERT INTO users (name, email) VALUES ("${name}", "${email}")`
  executeQuery()
}

const getQuorum = async () => {
  executionFlow.value = []
  try {
    const response = await fetch('http://localhost:9004/select-quorum', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ operation: 'write' })
    })
    const data = await response.json()
    
    executionFlow.value.push({
      title: 'Cabinet Algorithm Executed',
      detail: `Selected quorum: ${data.quorum.join(', ')}`
    })
    
    executionFlow.value.push({
      title: 'Quorum Size',
      detail: `${data.quorum_size} out of ${data.total_replicas} replicas`
    })

    queryResult.value = {
      success: true,
      message: `Quorum selected: ${data.quorum.join(', ')}`
    }
  } catch (error: any) {
    queryResult.value = {
      success: false,
      message: `Error: ${error.message}`
    }
  }
}

const electLeader = async () => {
  executionFlow.value = []
  executing.value = true
  queryResult.value = null
  
  try {
    // First call SEER to elect leader
    executionFlow.value.push({
      title: 'Calling SEER Algorithm',
      detail: 'Analyzing replicas to select optimal leader...'
    })
    
    const seerResponse = await fetch('http://localhost:9005/elect-leader', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({})
    })
    const seerData = await seerResponse.json()
    
    executionFlow.value.push({
      title: 'SEER Algorithm Executed',
      detail: `Elected leader: ${seerData.leader_id}`
    })

    executionFlow.value.push({
      title: 'Leader Score',
      detail: `Score: ${seerData.score.toFixed(3)} (latency: ${seerData.latency_ms.toFixed(2)}ms, lag: ${seerData.replication_lag})`
    })

    // Now trigger failover through coordinator to actually update the system
    executionFlow.value.push({
      title: 'Updating System Configuration',
      detail: `Promoting ${seerData.leader_id} to master...`
    })
    
    const failoverResponse = await fetch(`${API_BASE}/admin/trigger-failover`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ new_leader: seerData.leader_id })
    })
    
    const failoverData = await failoverResponse.json()
    
    if (failoverData.success) {
      executionFlow.value.push({
        title: 'System Updated',
        detail: `Master changed from ${failoverData.old_master} to ${failoverData.new_master}`
      })
      
      queryResult.value = {
        success: true,
        message: `Leader elected and system updated: ${seerData.leader_id} is now the master with score ${seerData.score.toFixed(3)}`
      }
    } else {
      queryResult.value = {
        success: true,
        message: `Leader elected: ${seerData.leader_id} with score ${seerData.score.toFixed(3)} (Note: System failover may require manual trigger)`
      }
    }
    
    // Refresh system status and metrics after electing leader
    setTimeout(async () => {
      await fetchSystemStatus()
      await fetchMetrics()
    }, 1500)
  } catch (error: any) {
    queryResult.value = {
      success: false,
      message: `Error: ${error.message}`
    }
  } finally {
    executing.value = false
  }
}

const electLeaderOnly = async () => {
  failoverFlow.value = []
  electionInProgress.value = true
  failoverResult.value = null
  
  try {
    failoverFlow.value.push({
      title: 'Calling SEER Algorithm',
      detail: 'Analyzing replicas to select optimal leader...'
    })
    
    const seerResponse = await fetch('http://localhost:9005/elect-leader', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({})
    })
    const seerData = await seerResponse.json()
    
    failoverFlow.value.push({
      title: 'SEER Algorithm Executed',
      detail: `Elected leader: ${seerData.leader_id} (Score: ${seerData.score.toFixed(3)})`
    })

    failoverFlow.value.push({
      title: 'Promoting New Leader',
      detail: `${seerData.leader_id} → Master, Current master → Replica`
    })
    
    const failoverResponse = await fetch(`${API_BASE}/admin/trigger-failover`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ new_leader: seerData.leader_id })
    })
    
    const failoverData = await failoverResponse.json()
    
    if (failoverData.success) {
      failoverFlow.value.push({
        title: 'Failover Complete',
        detail: `${failoverData.old_master} → ${failoverData.new_master}`
      })
      
      failoverResult.value = {
        success: true,
        message: `Graceful failover complete! New master: ${failoverData.new_master}`
      }
    } else {
      failoverResult.value = {
        success: false,
        message: `Failover failed: ${failoverData.error || failoverData.message}`
      }
    }
    
    setTimeout(async () => {
      await fetchSystemStatus()
      await fetchMetrics()
    }, 1500)
  } catch (error: any) {
    failoverResult.value = {
      success: false,
      message: `Error: ${error.message}`
    }
  } finally {
    electionInProgress.value = false
  }
}

// Helper function for delays
const sleep = (ms: number) => new Promise(resolve => setTimeout(resolve, ms))

const stopMaster = async () => {
  failoverInProgress.value = true
  failoverFlow.value = []
  failoverResult.value = null
  
  try {
    const oldMasterId = systemStatus.value.current_master?.id || 'instance-1'
    const oldMasterHost = systemStatus.value.current_master?.host || 'mysql-instance-1'
    const oldMasterContainer = systemStatus.value.current_master?.container || 'mysql-instance-1'
    
    // Step 1: Stop the master container
    failoverFlow.value.push({
      title: 'Step 1: Stopping Master Container',
      detail: `Executing: docker stop ${oldMasterContainer}`
    })
    
    const stopResponse = await fetch(`${API_BASE}/admin/stop-master-only`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ master_id: oldMasterId })
    })
    
    const stopResult = await stopResponse.json()
    
    if (!stopResult.success) {
      throw new Error(stopResult.error || stopResult.message || 'Failed to stop master')
    }
    
    failoverFlow.value.push({
      title: 'Step 2: Master Stopped',
      detail: `Container ${oldMasterContainer} is now down`
    })
    
    await sleep(2000)
    
    // Step 2: Call SEER to elect new leader (exclude the stopped master)
    failoverFlow.value.push({
      title: 'Step 3: Calling SEER Algorithm',
      detail: 'Analyzing remaining replicas to select optimal leader...'
    })
    
    const seerResponse = await fetch('http://localhost:9005/elect-leader', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        exclude_replicas: [oldMasterId]  // Exclude the stopped master from election
      })
    })
    
    if (!seerResponse.ok) {
      throw new Error('SEER election failed')
    }
    
    const seerData = await seerResponse.json()
    
    failoverFlow.value.push({
      title: 'Step 4: SEER Elected New Leader',
      detail: `Elected: ${seerData.leader_id} (Score: ${seerData.score.toFixed(3)}, Latency: ${seerData.latency_ms.toFixed(2)}ms, Lag: ${seerData.replication_lag})`
    })
    
    await sleep(1000)
    
    // Step 3: Promote the elected leader
    failoverFlow.value.push({
      title: 'Step 5: Promoting New Leader',
      detail: `Promoting ${seerData.leader_id} to master...`
    })
    
    const failoverResponse = await fetch(`${API_BASE}/admin/trigger-failover`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ new_leader: seerData.leader_id })
    })
    
    if (!failoverResponse.ok) {
      throw new Error('Failover promotion failed')
    }
    
    const failoverData = await failoverResponse.json()
    
    if (!failoverData.success) {
      throw new Error(failoverData.error || failoverData.message || 'Failover failed')
    }
    
    failoverFlow.value.push({
      title: 'Step 6: New Master Promoted',
      detail: `${failoverData.new_master} is now the master`
    })
    
    // Update UI to show new topology
    await fetchSystemStatus()
    await fetchMetrics()
    
    await sleep(3000)
    
    // Step 4: Restart old master as replica
    failoverFlow.value.push({
      title: 'Step 7: Restarting Old Master',
      detail: `Starting ${oldMasterContainer} container and configuring as replica...`
    })
    
    const restartResponse = await fetch(`${API_BASE}/admin/start-instance`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ instance_id: oldMasterId })
    })
    
    if (!restartResponse.ok) {
      throw new Error('Failed to restart old master')
    }
    
    const restartData = await restartResponse.json()
    
    failoverFlow.value.push({
      title: 'Step 8: Old Master Restarted',
      detail: `Container ${oldMasterContainer} is running and healthy`
    })
    
    failoverFlow.value.push({
      title: 'Step 9: Configured as Replica',
      detail: `${oldMasterId} is now replicating from ${restartData.current_master.id}`
    })
    
    failoverFlow.value.push({
      title: 'Step 10: Failover Complete',
      detail: `New master: ${restartData.current_master.id}, Total replicas: ${restartData.total_replicas}`
    })
    
    // Update system status with final state
    systemStatus.value = {
      current_master: restartData.current_master,
      current_replicas: restartData.current_replicas,
      total_replicas: restartData.total_replicas,
      replication_mode: 'binlog'
    }
    
    failoverResult.value = {
      success: true,
      message: `Complete failover with recovery! New master: ${restartData.current_master.id}, Old master ${oldMasterId} recovered as replica.`
    }
    
    masterRunning.value = true
    
    // Final refresh to ensure UI is in sync
    await sleep(2000)
    await fetchSystemStatus()
    await fetchMetrics()
    
  } catch (error: any) {
    failoverFlow.value.push({
      title: 'Failover Failed',
      detail: error.message
    })
    
    failoverResult.value = {
      success: false,
      message: `Error: ${error.message}`
    }
  } finally {
    failoverInProgress.value = false
  }
}

const startAutoRecovery = () => {
  recoveryCountdown.value = 10
  
  const countdownInterval = setInterval(() => {
    recoveryCountdown.value--
    if (recoveryCountdown.value <= 0) {
      clearInterval(countdownInterval)
      performAutoRecovery()
    }
  }, 1000)
}

const performAutoRecovery = async () => {
  failoverFlow.value.push({
    title: 'Auto-Recovery Started',
    detail: 'Restarting old master as replica...'
  })
  
  try {
    const response = await fetch(`${API_BASE}/admin/restart-old-master`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' }
    })
    
    const result = await response.json()
    
    if (result.success) {
      failoverFlow.value.push({
        title: 'Auto-Recovery Complete',
        detail: 'Old master restarted and configured as replica'
      })
      
      failoverResult.value = {
        success: true,
        message: 'Failover and auto-recovery complete! Old master is now a replica.'
      }
    } else {
      failoverFlow.value.push({
        title: 'Auto-Recovery Failed',
        detail: result.error || 'Use Manual Recovery button'
      })
      
      failoverResult.value = {
        success: false,
        message: `Auto-recovery failed: ${result.error || result.message}. Try Manual Recovery.`
      }
    }
  } catch (error: any) {
    failoverFlow.value.push({
      title: 'Auto-Recovery Failed',
      detail: error.message
    })
    
    failoverResult.value = {
      success: false,
      message: `Auto-recovery failed: ${error.message}. Try Manual Recovery.`
    }
  } finally {
    failoverInProgress.value = false
    masterRunning.value = true
    
    // Refresh status
    setTimeout(async () => {
      await fetchSystemStatus()
      await fetchMetrics()
    }, 3000)
  }
}

const startMaster = async () => {
  executing.value = true
  executionFlow.value = []
  queryResult.value = null
  
  try {
    executionFlow.value.push({
      title: 'Restarting Old Master as Replica',
      detail: 'Starting mysql-instance-1 and configuring binlog replication'
    })
    
    const response = await fetch(`${API_BASE}/admin/restart-old-master`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' }
    })
    
    const result = await response.json()
    
    if (result.success) {
      executionFlow.value.push({
        title: 'Old Master Restarted',
        detail: 'Container started and configured as replica. Binlog replication active.'
      })
      
      queryResult.value = {
        success: true,
        message: result.message || 'Old master restarted as replica successfully.'
      }
      
      masterRunning.value = true
      
      // Refresh status after a delay
      setTimeout(async () => {
        await fetchSystemStatus()
        await fetchMetrics()
      }, 3000)
    } else {
      queryResult.value = {
        success: false,
        message: `Failed to restart old master: ${result.error || result.message}`
      }
    }
  } catch (error: any) {
    queryResult.value = {
      success: false,
      message: `Error: ${error.message}`
    }
  } finally {
    executing.value = false
  }
}


const triggerFailover = async () => {
  executing.value = true
  executionFlow.value = []
  queryResult.value = null
  
  try {
    executionFlow.value.push({
      title: 'Triggering Manual Failover',
      detail: 'Electing new leader using SEER algorithm...'
    })
    
    const response = await fetch(`${API_BASE}/admin/trigger-failover`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' }
    })
    
    const result = await response.json()
    
    if (result.success) {
      executionFlow.value.push({
        title: 'Failover Complete',
        detail: `New master: ${result.new_leader_id}`
      })
      
      executionFlow.value.push({
        title: 'Leader Changed',
        detail: `${result.old_master} → ${result.new_master}`
      })
      
      queryResult.value = {
        success: true,
        message: result.message
      }
      
      // Refresh status
      setTimeout(async () => {
        await fetchSystemStatus()
        await fetchMetrics()
      }, 1000)
    } else {
      queryResult.value = {
        success: false,
        message: result.message
      }
    }
  } catch (error: any) {
    queryResult.value = {
      success: false,
      message: `Error: ${error?.message || 'Unknown error'}`
    }
  } finally {
    executing.value = false
  }
}

// ==================== STRESS TEST FUNCTIONS ====================

const fetchDataCount = async () => {
  try {
    const response = await fetch(`${API_BASE}/admin/stress-test/data-count`)
    const data = await response.json()
    dataCount.value = data
  } catch (error) {
    console.error('Failed to fetch data count:', error)
  }
}

const clearData = async () => {
  clearingData.value = true
  stressTestResult.value = null
  consistencyComparisonResult.value = null
  
  try {
    const response = await fetch(`${API_BASE}/admin/clear-data`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' }
    })
    const result = await response.json()
    
    if (result.success) {
      await fetchDataCount()
      await fetchConsistencyMetrics()
    }
  } catch (error) {
    console.error('Failed to clear data:', error)
  } finally {
    clearingData.value = false
  }
}

const runConcurrentWritesTest = async () => {
  stressTestRunning.value = 'concurrent'
  stressTestResult.value = null
  consistencyComparisonResult.value = null
  
  try {
    const response = await fetch(`${API_BASE}/admin/stress-test/concurrent-writes`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        num_operations: stressTestOps.value,
        consistency: stressTestConsistency.value
      })
    })
    
    const result = await response.json()
    stressTestResult.value = result
    
    // Refresh metrics after test
    await fetchDataCount()
    await fetchMetrics()
    await fetchConsistencyMetrics()
  } catch (error: any) {
    stressTestResult.value = {
      test_name: 'Concurrent Writes',
      total_operations: stressTestOps.value,
      successful: 0,
      failed: stressTestOps.value,
      duration_seconds: 0,
      throughput_ops_per_sec: 0,
      avg_latency_ms: 0,
      min_latency_ms: 0,
      max_latency_ms: 0,
      consistency_level: stressTestConsistency.value,
      errors: { [error?.message || 'Connection failed']: stressTestOps.value }
    }
  } finally {
    stressTestRunning.value = null
  }
}

const runReadWriteMixTest = async () => {
  stressTestRunning.value = 'mix'
  stressTestResult.value = null
  consistencyComparisonResult.value = null
  
  try {
    const response = await fetch(`${API_BASE}/admin/stress-test/read-write-mix`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        num_operations: stressTestOps.value,
        consistency: stressTestConsistency.value
      })
    })
    
    const result = await response.json()
    stressTestResult.value = result
    
    await fetchDataCount()
    await fetchMetrics()
    await fetchConsistencyMetrics()
  } catch (error: any) {
    stressTestResult.value = {
      test_name: 'Read/Write Mix',
      total_operations: stressTestOps.value,
      successful: 0,
      failed: stressTestOps.value,
      duration_seconds: 0,
      throughput_ops_per_sec: 0,
      avg_latency_ms: 0,
      min_latency_ms: 0,
      max_latency_ms: 0,
      consistency_level: stressTestConsistency.value,
      errors: { [error?.message || 'Connection failed']: stressTestOps.value }
    }
  } finally {
    stressTestRunning.value = null
  }
}

const runConsistencyComparisonTest = async () => {
  stressTestRunning.value = 'comparison'
  stressTestResult.value = null
  consistencyComparisonResult.value = null
  
  try {
    const response = await fetch(`${API_BASE}/admin/stress-test/consistency-comparison?num_operations=${Math.min(stressTestOps.value, 30)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' }
    })
    
    const result = await response.json()
    consistencyComparisonResult.value = result
    
    // Convert to array for table
    consistencyComparisonArray.value = Object.keys(result.results).map(level => ({
      level,
      ...result.results[level]
    }))
    
    await fetchDataCount()
    await fetchMetrics()
    await fetchConsistencyMetrics()
  } catch (error: any) {
    console.error('Consistency comparison test failed:', error)
  } finally {
    stressTestRunning.value = null
  }
}

// Lifecycle
onMounted(() => {
  checkServiceHealth()
  fetchMetrics()
  fetchSystemStatus()
  fetchConsistencyMetrics()
  fetchDataCount()
  
  // Refresh every 5 seconds
  refreshInterval = setInterval(() => {
    checkServiceHealth()
    fetchMetrics()
    fetchSystemStatus()
    fetchConsistencyMetrics()
    fetchDataCount()
  }, 5000)
})

onUnmounted(() => {
  if (refreshInterval) {
    clearInterval(refreshInterval)
  }
})
</script>

<style scoped>
.mb-2 { margin-bottom: 0.5rem; }
.mb-3 { margin-bottom: 0.75rem; }
.mb-4 { margin-bottom: 1rem; }
.mt-2 { margin-top: 0.5rem; }
.mt-3 { margin-top: 0.75rem; }
.ml-2 { margin-left: 0.5rem; }
.mr-2 { margin-right: 0.5rem; }
.w-full { width: 100%; }
.block { display: block; }
.flex { display: flex; }
.justify-content-between { justify-content: space-between; }
.align-items-center { align-items: center; }
.text-sm { font-size: 0.875rem; }
.text-color-secondary { color: #64748b; }
.font-semibold { font-weight: 600; }

/* Grid layouts */
.grid { display: grid; gap: 1rem; }
.grid-2 { grid-template-columns: repeat(2, 1fr); }
.grid-3 { grid-template-columns: repeat(3, 1fr); }
.grid-4 { grid-template-columns: repeat(4, 1fr); }

/* Stress test result cards */
.result-card {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border-radius: 12px;
  padding: 1rem;
  text-align: center;
  color: white;
}

.result-card.success {
  background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%);
}

.result-value {
  font-size: 1.5rem;
  font-weight: bold;
  margin-bottom: 0.25rem;
}

.result-label {
  font-size: 0.75rem;
  opacity: 0.9;
  text-transform: uppercase;
}

/* Stress test section */
.stress-test-section {
  padding: 0.5rem 0;
}

.stress-test-results {
  background: #f8fafc;
  border-radius: 8px;
  padding: 1rem;
  margin-top: 1rem;
}

/* Metric cards */
.metric-card {
  background: #f1f5f9;
  border-radius: 8px;
  padding: 0.75rem 1rem;
}

.metric-label {
  font-size: 0.75rem;
  color: #64748b;
  text-transform: uppercase;
  font-weight: 600;
  margin-bottom: 0.25rem;
}

.metric-value {
  font-size: 1rem;
  color: #1e293b;
  font-weight: 500;
}

/* Action buttons */
.action-buttons {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
}
</style>