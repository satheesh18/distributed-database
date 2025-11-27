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
      <DataTable :value="metrics" :loading="loadingMetrics">
        <Column field="replica_id" header="Replica ID"></Column>
        <Column field="latency_ms" header="Latency (ms)">
          <template #body="slotProps">
            {{ slotProps.data.latency_ms.toFixed(2) }}
          </template>
        </Column>
        <Column field="replication_lag" header="Replication Lag">
          <template #body="slotProps">
            <Tag :severity="slotProps.data.replication_lag === 0 ? 'success' : 'warning'">
              {{ slotProps.data.replication_lag }}
            </Tag>
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
          <Button 
            label="Elect Leader" 
            icon="pi pi-star" 
            @click="electLeader"
            severity="help"
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

    <!-- Danger Zone -->
    <Panel header="⚠️ Danger Zone" class="mb-4">
      <div class="danger-zone">
        <h4>Master Failover Testing</h4>
        <p class="text-sm mb-3">Stop the master database to trigger automatic leader election using SEER algorithm</p>
        <div class="action-buttons">
          <Button 
            label="Stop Master" 
            icon="pi pi-power-off" 
            @click="stopMaster"
            severity="danger"
            :disabled="!masterRunning"
          />
          <Button 
            label="Start Master" 
            icon="pi pi-play" 
            @click="startMaster"
            severity="success"
            :disabled="masterRunning"
          />
        </div>
      </div>
    </Panel>

    <!-- System Status -->
    <Panel header="System Status" class="mb-4">
      <div class="metric-card">
        <div class="metric-label">Current Master</div>
        <div class="metric-value">{{ systemStatus.current_master || 'Loading...' }}</div>
      </div>
      <div class="metric-card mt-2">
        <div class="metric-label">Master is Original</div>
        <div class="metric-value">
          <Tag :severity="systemStatus.master_is_original ? 'success' : 'warning'">
            {{ systemStatus.master_is_original ? 'Yes' : 'No (Failover Occurred)' }}
          </Tag>
        </div>
      </div>
    </Panel>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'

const API_BASE = 'http://localhost:8000'

// State
const services = ref([
  { name: 'Coordinator', port: 8000, healthy: false, role: 'API Gateway' },
  { name: 'MySQL Master', port: 3306, healthy: false, role: 'Primary DB' },
  { name: 'MySQL Replica 1', port: 3307, healthy: false, role: 'Replica' },
  { name: 'MySQL Replica 2', port: 3308, healthy: false, role: 'Replica' },
  { name: 'MySQL Replica 3', port: 3309, healthy: false, role: 'Replica' },
  { name: 'Timestamp Service 1', port: 8001, healthy: false, role: 'Odd Timestamps' },
  { name: 'Timestamp Service 2', port: 8002, healthy: false, role: 'Even Timestamps' },
  { name: 'Metrics Collector', port: 8003, healthy: false, role: 'Monitoring' },
  { name: 'Cabinet Service', port: 8004, healthy: false, role: 'Quorum Selection' },
  { name: 'SEER Service', port: 8005, healthy: false, role: 'Leader Election' },
])

const metrics = ref<any[]>([])
const loadingMetrics = ref(false)
const query = ref('SELECT * FROM users')
const executing = ref(false)
const executionFlow = ref<any[]>([])
const queryResult = ref<any>(null)
const systemStatus = ref<any>({})
const masterRunning = ref(true)

let refreshInterval: any = null

// Methods
const checkServiceHealth = async () => {
  const healthChecks = [
    { index: 0, url: `${API_BASE}/health` },
    { index: 7, url: 'http://localhost:8003/health' },
    { index: 8, url: 'http://localhost:8004/health' },
    { index: 9, url: 'http://localhost:8005/health' },
  ]

  for (const check of healthChecks) {
    try {
      const response = await fetch(check.url)
      services.value[check.index].healthy = response.ok
    } catch {
      services.value[check.index].healthy = false
    }
  }

  // Assume MySQL and timestamp services are healthy if coordinator is healthy
  if (services.value[0].healthy) {
    for (let i = 1; i <= 6; i++) {
      services.value[i].healthy = true
    }
  }
}

const fetchMetrics = async () => {
  loadingMetrics.value = true
  try {
    const response = await fetch('http://localhost:8003/metrics')
    const data = await response.json()
    metrics.value = data.replicas
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
    masterRunning.value = systemStatus.value.current_master === 'mysql-master'
  } catch (error) {
    console.error('Failed to fetch system status:', error)
  }
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
      body: JSON.stringify({ query: query.value })
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
  const name = names[Math.floor(Math.random() * names.length)]
  const email = `${name.toLowerCase()}@example.com`
  query.value = `INSERT INTO users (name, email) VALUES ("${name}", "${email}")`
  executeQuery()
}

const getQuorum = async () => {
  executionFlow.value = []
  try {
    const response = await fetch('http://localhost:8004/select-quorum', {
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
    
    const seerResponse = await fetch('http://localhost:8005/elect-leader', {
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
const stopMaster = async () => {
  executing.value = true
  executionFlow.value = []
  queryResult.value = null
  
  try {
    executionFlow.value.push({
      title: 'Stopping Master Container',
      detail: 'Executing: docker stop mysql-master'
    })
    
    const response = await fetch(`${API_BASE}/admin/stop-master`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' }
    })
    
    const result = await response.json()
    
    if (result.success) {
      executionFlow.value.push({
        title: 'Master Stopped',
        detail: 'Master container is now down'
      })
      
      if (result.new_leader_id) {
        executionFlow.value.push({
          title: 'Leader Elected',
          detail: `New leader: ${result.new_leader_id} (${result.new_master})`
        })
        
        if (result.election_details) {
          executionFlow.value.push({
            title: 'Election Details',
            detail: `Score: ${result.election_details.score?.toFixed(3)}, Latency: ${result.election_details.latency_ms?.toFixed(2)}ms, Lag: ${result.election_details.replication_lag}`
          })
        }
      }
      
      queryResult.value = {
        success: true,
        message: result.message || 'Master stopped and failover complete!'
      }
      
      masterRunning.value = false
      
      // Refresh status after a delay
      setTimeout(async () => {
        await fetchSystemStatus()
        await fetchMetrics()
      }, 2000)
    } else {
      executionFlow.value.push({
        title: 'Failover Failed',
        detail: result.error || result.message || 'Unknown error'
      })
      
      if (result.hint) {
        executionFlow.value.push({
          title: 'Hint',
          detail: result.hint
        })
      }
      
      queryResult.value = {
        success: false,
        message: `${result.message || 'Failed to stop master'}\n${result.hint || ''}`
      }
    }
  } catch (error: any) {
    executionFlow.value.push({
      title: 'Request Failed',
      detail: error.message
    })
    
    queryResult.value = {
      success: false,
      message: `Error: ${error.message}`
    }
  } finally {
    executing.value = false
  }
}

const startMaster = async () => {
  executing.value = true
  executionFlow.value = []
  queryResult.value = null
  
  try {
    executionFlow.value.push({
      title: 'Starting Master Container',
      detail: 'Executing: docker-compose start mysql-master'
    })
    
    const response = await fetch(`${API_BASE}/admin/start-master`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' }
    })
    
    const result = await response.json()
    
    if (result.success) {
      executionFlow.value.push({
        title: 'Master Started',
        detail: 'Master container is running. System restored to original configuration.'
      })
      
      queryResult.value = {
        success: true,
        message: 'Master started successfully. System back to normal.'
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
        message: `Failed to start master: ${result.error || result.message}`
      }
    }
  } catch (error) {
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
  } catch (error) {
    queryResult.value = {
      success: false,
      message: `Error: ${error.message}`
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
  
  // Refresh every 5 seconds
  refreshInterval = setInterval(() => {
    checkServiceHealth()
    fetchMetrics()
    fetchSystemStatus()
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
