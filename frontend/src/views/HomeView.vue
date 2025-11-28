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
const stopMaster = async () => {
  failoverInProgress.value = true
  failoverFlow.value = []
  failoverResult.value = null
  
  try {
    failoverFlow.value.push({
      title: 'Stopping Master Container',
      detail: 'Executing: docker stop mysql-instance-1'
    })
    
    const response = await fetch(`${API_BASE}/admin/stop-master`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' }
    })
    
    const result = await response.json()
    
    if (result.success) {
      failoverFlow.value.push({
        title: 'Master Stopped',
        detail: 'Master container is now down'
      })
      
      if (result.new_leader_id) {
        failoverFlow.value.push({
          title: 'Leader Elected',
          detail: `New leader: ${result.new_leader_id} (${result.new_master})`
        })
        
        if (result.election_details) {
          failoverFlow.value.push({
            title: 'Election Details',
            detail: `Score: ${result.election_details.score?.toFixed(3)}, Latency: ${result.election_details.latency_ms?.toFixed(2)}ms, Lag: ${result.election_details.replication_lag}`
          })
        }
      }
      
      failoverResult.value = {
        success: true,
        message: result.message || 'Master stopped and failover complete! Auto-recovery starting...'
      }
      
      masterRunning.value = false
      
      // Refresh status after a delay
      setTimeout(async () => {
        await fetchSystemStatus()
        await fetchMetrics()
      }, 2000)
      
      // Start auto-recovery countdown and process
      startAutoRecovery()
    } else {
      failoverFlow.value.push({
        title: 'Failover Failed',
        detail: result.error || result.message || 'Unknown error'
      })
      
      if (result.hint) {
        failoverFlow.value.push({
          title: 'Hint',
          detail: result.hint
        })
      }
      
      failoverResult.value = {
        success: false,
        message: `${result.message || 'Failed to stop master'}\n${result.hint || ''}`
      }
      failoverInProgress.value = false
    }
  } catch (error: any) {
    failoverFlow.value.push({
      title: 'Request Failed',
      detail: error.message
    })
    
    failoverResult.value = {
      success: false,
      message: `Error: ${error.message}`
    }
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

// Lifecycle
onMounted(() => {
  checkServiceHealth()
  fetchMetrics()
  fetchSystemStatus()
  fetchConsistencyMetrics()
  
  // Refresh every 5 seconds
  refreshInterval = setInterval(() => {
    checkServiceHealth()
    fetchMetrics()
    fetchSystemStatus()
    fetchConsistencyMetrics()
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
.w-full { width: 100%; }
.block { display: block; }
.flex { display: flex; }
.justify-content-between { justify-content: space-between; }
.align-items-center { align-items: center; }
.text-sm { font-size: 0.875rem; }
.text-color-secondary { color: #64748b; }
.font-semibold { font-weight: 600; }
</style>
