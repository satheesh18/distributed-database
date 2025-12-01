<template>
  <div class="dashboard">
    <!-- Header -->
    <header class="dashboard-header">
      <h1>Distributed Database Dashboard</h1>
      <p>Real-time monitoring and control for MySQL cluster with adaptive quorum and leader election</p>
    </header>

    <!-- Section 1: Service Status -->
    <section class="dashboard-section">
      <div class="section-header">
        <h2>Service Status</h2>
        <span class="section-subtitle">Health check of all distributed components</span>
      </div>
      
      <div class="services-grid">
        <div v-for="service in services" :key="service.name" class="service-card" :class="{ healthy: service.healthy, unhealthy: !service.healthy }">
          <div class="service-status-indicator"></div>
          <div class="service-info">
            <div class="service-name">{{ service.name }}</div>
            <div class="service-details">
              <span class="service-port">Port {{ service.port }}</span>
              <span class="service-role">{{ service.role }}</span>
            </div>
          </div>
          <div class="service-status-text">{{ service.healthy ? 'Online' : 'Offline' }}</div>
        </div>
      </div>
    </section>

    <!-- Section 2: Cluster Topology -->
    <section class="dashboard-section">
      <div class="section-header">
        <h2>Cluster Topology</h2>
        <span class="section-subtitle">Current master-replica configuration and replication metrics</span>
      </div>

      <div class="topology-container">
        <!-- Master Node -->
        <div class="topology-master">
          <div class="node-card master">
            <div class="node-badge">MASTER</div>
            <div class="node-id">{{ systemStatus.current_master?.id || 'Loading...' }}</div>
            <div class="node-host">{{ systemStatus.current_master?.host || '' }}</div>
            <div class="node-info">
              <span>Accepts all writes</span>
              <span>Binlog source</span>
            </div>
          </div>
        </div>

        <!-- Replication Arrow -->
        <div class="replication-flow">
          <div class="flow-line"></div>
          <div class="flow-label">Binlog Replication</div>
        </div>

        <!-- Replica Nodes -->
        <div class="topology-replicas">
          <div v-for="replica in metrics" :key="replica.replica_id" class="node-card replica" :class="{ unhealthy: !replica.is_healthy }">
            <div class="node-badge">REPLICA</div>
            <div class="node-id">{{ replica.replica_id }}</div>
            
            <div class="replica-metrics">
              <div class="metric-row">
                <span class="metric-name">Latency</span>
                <span class="metric-value" :class="getLatencyClass(replica.latency_ms)">{{ replica.latency_ms.toFixed(1) }}ms</span>
              </div>
              <div class="metric-row">
                <span class="metric-name">Replication Lag</span>
                <span class="metric-value" :class="getLagClass(replica.replication_lag)">{{ replica.replication_lag }} txns</span>
              </div>
              <div class="metric-row">
                <span class="metric-name">Uptime</span>
                <span class="metric-value">{{ formatUptime(replica.uptime_seconds) }}</span>
              </div>
              <div class="metric-row">
                <span class="metric-name">Status</span>
                <span class="metric-value" :class="replica.is_healthy ? 'good' : 'bad'">{{ replica.is_healthy ? 'Healthy' : 'Unhealthy' }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Metrics Explanation -->
      <div class="metrics-explanation">
        <h3>Understanding the Metrics</h3>
        <div class="explanation-grid">
          <div class="explanation-item">
            <div class="explanation-term">Latency</div>
            <div class="explanation-desc">Round-trip time to reach the replica. Lower is better. High latency (&gt;100ms) may indicate network issues or overloaded nodes.</div>
          </div>
          <div class="explanation-item">
            <div class="explanation-term">Replication Lag</div>
            <div class="explanation-desc">Number of transactions the replica is behind the master. A lag of 0 means the replica has all committed data. High lag may cause stale reads.</div>
          </div>
          <div class="explanation-item">
            <div class="explanation-term">Uptime</div>
            <div class="explanation-desc">Time since the replica was last started. Longer uptime generally indicates stability. Recent restarts may indicate issues.</div>
          </div>
          <div class="explanation-item">
            <div class="explanation-term">Timestamp</div>
            <div class="explanation-desc">Current master timestamp: <strong>{{ masterTimestamp }}</strong>. Each write operation gets a unique, monotonically increasing timestamp for ordering.</div>
          </div>
        </div>
      </div>
    </section>

    <!-- Section 3: Failover Testing -->
    <section class="dashboard-section">
      <div class="section-header">
        <h2>Failover Testing</h2>
        <span class="section-subtitle">Test leader election and automatic recovery mechanisms</span>
      </div>

      <div class="failover-container">
        <div class="failover-info">
          <p>The SEER (Smart Election and Evaluation for Replicas) algorithm automatically selects the best replica to become the new master based on:</p>
          <ul>
            <li><strong>Latency Score:</strong> Lower latency replicas are preferred for faster response times</li>
            <li><strong>Replication Lag:</strong> Replicas closer to the master's state minimize data loss</li>
            <li><strong>Stability:</strong> Uptime and crash history affect the selection</li>
          </ul>
        </div>

        <div class="failover-actions">
          <div class="action-card">
            <h4>Crash and Recovery Test</h4>
            <p>Stops the current master container, triggers SEER election, promotes best replica, then restarts old master as a replica.</p>
            <Button 
              label="Stop Master and Failover" 
              @click="stopMaster"
              severity="danger"
              :loading="failoverInProgress"
              :disabled="failoverInProgress || electionInProgress"
            />
          </div>
          
          <div class="action-card">
            <h4>Graceful Leader Election</h4>
            <p>Performs a controlled failover without stopping any containers. Current master is demoted to replica.</p>
            <Button 
              label="Elect New Leader" 
              @click="electLeaderOnly"
              severity="warning"
              :loading="electionInProgress"
              :disabled="failoverInProgress || electionInProgress"
            />
          </div>
        </div>

        <!-- Failover Progress -->
        <div v-if="failoverFlow.length > 0" class="failover-progress">
          <h4>Failover Progress</h4>
          <div class="progress-steps">
            <div v-for="(step, index) in failoverFlow" :key="index" class="progress-step">
              <div class="step-number">{{ index + 1 }}</div>
              <div class="step-content">
                <div class="step-title">{{ step.title }}</div>
                <div class="step-detail">{{ step.detail }}</div>
              </div>
            </div>
          </div>
        </div>

        <!-- Failover Result -->
        <div v-if="failoverResult" class="failover-result" :class="{ success: failoverResult.success, error: !failoverResult.success }">
          {{ failoverResult.message }}
        </div>
      </div>
    </section>

    <!-- Section 4: Stress Testing -->
    <section class="dashboard-section">
      <div class="section-header">
        <h2>Stress Testing</h2>
        <span class="section-subtitle">Observe distributed database behavior under concurrent load</span>
      </div>

      <div class="stress-test-container">
        <!-- What This Tests -->
        <div class="test-explanation">
          <h4>What Are We Testing?</h4>
          <div class="test-goals">
            <div class="test-goal">
              <div class="goal-icon">1</div>
              <div class="goal-content">
                <strong>Timestamp Ordering</strong>
                <p>Every write gets a unique, monotonically increasing timestamp from our distributed timestamp services. We verify all operations are correctly ordered.</p>
              </div>
            </div>
            <div class="test-goal">
              <div class="goal-icon">2</div>
              <div class="goal-content">
                <strong>Replication Consistency</strong>
                <p>Writes go to the master, then propagate to replicas via binlog replication. We measure how quickly replicas catch up.</p>
              </div>
            </div>
            <div class="test-goal">
              <div class="goal-icon">3</div>
              <div class="goal-content">
                <strong>Quorum Behavior</strong>
                <p>Different consistency levels wait for different numbers of replicas to confirm. See the real latency vs durability tradeoff.</p>
              </div>
            </div>
          </div>
        </div>

        <!-- Test Configuration -->
        <div class="test-config">
          <div class="config-header">
            <h4>Configure Test</h4>
            <div class="data-info">
              <span>Current data: {{ dataCount.users }} users, {{ dataCount.products }} products</span>
              <Button 
                label="Clear Data" 
                @click="clearData"
                severity="secondary"
                size="small"
                :loading="clearingData"
                text
              />
            </div>
          </div>
          <div class="config-options">
            <div class="config-option">
              <label>Number of Concurrent Operations</label>
              <div class="option-buttons">
                <button 
                  v-for="n in [10, 25, 50, 100]" 
                  :key="n" 
                  :class="{ active: stressTestOps === n }"
                  @click="stressTestOps = n"
                >{{ n }}</button>
              </div>
            </div>
            <div class="config-option">
              <label>Consistency Level</label>
              <div class="option-buttons consistency-buttons">
                <button 
                  v-for="opt in consistencyOptions" 
                  :key="opt.value" 
                  :class="['consistency-btn', opt.value.toLowerCase(), { active: stressTestConsistency === opt.value }]"
                  @click="stressTestConsistency = opt.value"
                >
                  <span class="btn-label">{{ opt.value }}</span>
                  <span class="btn-desc">{{ opt.shortDesc }}</span>
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- Run Test Button -->
        <div class="run-test-section">
          <Button 
            label="Run Stress Test" 
            @click="runStressTest"
            severity="primary"
            size="large"
            :loading="stressTestRunning !== null"
            :disabled="stressTestRunning !== null"
            icon="pi pi-play"
          />
          <p class="run-description">
            Will execute {{ stressTestOps }} concurrent INSERT operations with <strong>{{ stressTestConsistency }}</strong> consistency
          </p>
          <p v-if="stressTestConsistency === 'STRONG'" class="consistency-info">
            STRONG consistency waits for Cabinet-selected optimal replicas to confirm. Cabinet intelligently chooses the fastest, healthiest replicas for the quorum.
          </p>
        </div>

        <!-- Live Test Progress -->
        <div v-if="stressTestRunning" class="live-progress">
          <div class="progress-header">
            <h4>Test In Progress</h4>
            <span class="elapsed-time">{{ elapsedTime }}s</span>
          </div>
          
          <div class="progress-bar-container">
            <div class="progress-bar-fill" :style="{ width: progressPercent + '%' }"></div>
          </div>
          
          <div class="live-stats">
            <div class="live-stat">
              <div class="live-stat-value">{{ liveStats.completed }}</div>
              <div class="live-stat-label">Completed</div>
            </div>
            <div class="live-stat">
              <div class="live-stat-value">{{ liveStats.successful }}</div>
              <div class="live-stat-label">Successful</div>
            </div>
            <div class="live-stat">
              <div class="live-stat-value">{{ liveStats.failed }}</div>
              <div class="live-stat-label">Failed</div>
            </div>
            <div class="live-stat">
              <div class="live-stat-value">{{ liveStats.avgLatency }}ms</div>
              <div class="live-stat-label">Avg Latency</div>
            </div>
          </div>

          <div class="operation-log">
            <h5>Recent Operations</h5>
            <div class="log-entries">
              <div v-for="(entry, i) in recentOperations" :key="i" class="log-entry" :class="entry.success ? 'success' : 'failure'">
                <span class="log-time">{{ entry.time }}</span>
                <span class="log-message">{{ entry.message }}</span>
                <span class="log-latency">{{ entry.latency }}ms</span>
              </div>
            </div>
          </div>
        </div>

        <!-- Test Results -->
        <div v-if="stressTestResult && !stressTestRunning" class="test-results">
          <div class="results-header">
            <h4>Test Complete</h4>
            <span class="result-badge" :class="stressTestResult.failed === 0 ? 'success' : 'partial'">
              {{ stressTestResult.failed === 0 ? 'All Passed' : 'Some Failures' }}
            </span>
          </div>

          <!-- Key Metrics -->
          <div class="key-metrics">
            <div class="key-metric">
              <div class="metric-icon throughput"></div>
              <div class="metric-data">
                <div class="metric-value">{{ stressTestResult.throughput_ops_per_sec }}</div>
                <div class="metric-label">Operations/Second</div>
                <div class="metric-context">Higher = better system performance</div>
              </div>
            </div>
            <div class="key-metric">
              <div class="metric-icon latency"></div>
              <div class="metric-data">
                <div class="metric-value">{{ stressTestResult.avg_latency_ms }}ms</div>
                <div class="metric-label">Average Latency</div>
                <div class="metric-context">Time for write to complete</div>
              </div>
            </div>
            <div class="key-metric">
              <div class="metric-icon success"></div>
              <div class="metric-data">
                <div class="metric-value">{{ stressTestResult.successful }}/{{ stressTestResult.total_operations }}</div>
                <div class="metric-label">Success Rate</div>
                <div class="metric-context">{{ ((stressTestResult.successful / stressTestResult.total_operations) * 100).toFixed(1) }}% successful</div>
              </div>
            </div>
            <div class="key-metric">
              <div class="metric-icon time"></div>
              <div class="metric-data">
                <div class="metric-value">{{ stressTestResult.duration_seconds }}s</div>
                <div class="metric-label">Total Duration</div>
                <div class="metric-context">Time to complete all ops</div>
              </div>
            </div>
          </div>

          <!-- Latency Distribution -->
          <div class="latency-section">
            <h5>Latency Distribution</h5>
            <div class="latency-bars">
              <div class="latency-bar">
                <div class="bar-label">Min</div>
                <div class="bar-visual">
                  <div class="bar-fill min" :style="{ width: getLatencyBarWidth(stressTestResult.min_latency_ms) }"></div>
                </div>
                <div class="bar-value">{{ stressTestResult.min_latency_ms }}ms</div>
              </div>
              <div class="latency-bar">
                <div class="bar-label">Avg</div>
                <div class="bar-visual">
                  <div class="bar-fill avg" :style="{ width: getLatencyBarWidth(stressTestResult.avg_latency_ms) }"></div>
                </div>
                <div class="bar-value">{{ stressTestResult.avg_latency_ms }}ms</div>
              </div>
              <div class="latency-bar">
                <div class="bar-label">Max</div>
                <div class="bar-visual">
                  <div class="bar-fill max" :style="{ width: getLatencyBarWidth(stressTestResult.max_latency_ms) }"></div>
                </div>
                <div class="bar-value">{{ stressTestResult.max_latency_ms }}ms</div>
              </div>
            </div>
            <div class="latency-explanation">
              <p v-if="stressTestConsistency === 'EVENTUAL'">
                <strong>EVENTUAL consistency:</strong> Fast because we only wait for the master to confirm. 
                Replicas receive the write via binlog replication asynchronously.
              </p>
              <p v-else>
                <strong>STRONG consistency:</strong> Moderate latency because we wait for Cabinet-selected 
                optimal replicas to confirm they've received the write before returning success.
              </p>
            </div>
          </div>

          <!-- Timestamp Verification -->
          <div v-if="stressTestResult.timestamp_range" class="timestamp-section">
            <h5>Timestamp Ordering Verification</h5>
            <div class="timestamp-content">
              <div class="timestamp-visual">
                <div class="ts-start">
                  <span class="ts-label">First</span>
                  <span class="ts-value">{{ stressTestResult.timestamp_range.min }}</span>
                </div>
                <div class="ts-arrow">
                  <div class="arrow-line"></div>
                  <span class="arrow-label">{{ stressTestResult.total_operations }} operations</span>
                </div>
                <div class="ts-end">
                  <span class="ts-label">Last</span>
                  <span class="ts-value">{{ stressTestResult.timestamp_range.max }}</span>
                </div>
              </div>
              <p class="timestamp-explanation">
                Each write received a unique, monotonically increasing timestamp from our distributed timestamp services.
                This ensures global ordering even with concurrent writes from multiple clients.
              </p>
            </div>
          </div>

          <!-- Errors if any -->
          <div v-if="stressTestResult.errors && Object.keys(stressTestResult.errors).length > 0" class="errors-section">
            <h5>Errors Encountered</h5>
            <div class="error-list">
              <div v-for="(count, error) in stressTestResult.errors" :key="error" class="error-item">
                <span class="error-count">{{ count }}x</span>
                <span class="error-message">{{ error }}</span>
              </div>
            </div>
          </div>

          <!-- What Happened -->
          <div class="what-happened">
            <h5>What Just Happened?</h5>
           <ol class="step-list">
              <li>
                <strong>{{ stressTestResult.total_operations }} concurrent INSERT requests</strong> were sent to the coordinator
              </li>
              <li>
                Each request received a <strong>unique timestamp</strong> from the timestamp service
              </li>
              <li>
                Writes were executed on the <strong>master MySQL instance</strong>
              </li>
              <li v-if="stressTestConsistency === 'EVENTUAL'">
                With EVENTUAL consistency, we returned success immediately after master confirmed
              </li>
              <li v-else>
                With STRONG consistency, we waited for <strong>Cabinet-selected optimal replicas</strong> to catch up via binlog replication
              </li>
              <li>
                Data now exists on master and is being replicated to all replicas
              </li>
            </ol>
          </div>
        </div>

        <!-- Cumulative Stats -->
        <div v-if="consistencyMetricsArray.some(m => m.count > 0)" class="cumulative-stats">
          <h4>Session Statistics</h4>
          <p class="stats-subtitle">Aggregated from all operations since last clear</p>
          <div class="stats-grid">
            <div v-for="metric in consistencyMetricsArray" :key="metric.level" class="stat-card" :class="metric.level.toLowerCase()">
              <div class="stat-header">
                <span class="stat-level">{{ metric.level }}</span>
                <span class="stat-count">{{ metric.count }} ops</span>
              </div>
              <div class="stat-body">
                <div class="stat-row">
                  <span>Avg Latency</span>
                  <span>{{ metric.avg_latency_ms.toFixed(1) }}ms</span>
                </div>
                <div class="stat-row">
                  <span>Success Rate</span>
                  <span :class="{ 'good': metric.success_rate >= 95 }">{{ metric.success_rate.toFixed(1) }}%</span>
                </div>
                <div class="stat-row" v-if="metric.failures > 0">
                  <span>Failures</span>
                  <span class="bad">{{ metric.failures }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import ProgressBar from 'primevue/progressbar'

const API_BASE = 'http://localhost:9000'

// Service Status State
const services = ref([
  { name: 'Coordinator', port: 9000, healthy: false, role: 'API Gateway' },
  { name: 'MySQL Instance 1', port: 3306, healthy: false, role: 'Master/Replica' },
  { name: 'MySQL Instance 2', port: 3307, healthy: false, role: 'Replica' },
  { name: 'MySQL Instance 3', port: 3308, healthy: false, role: 'Replica' },
  { name: 'MySQL Instance 4', port: 3309, healthy: false, role: 'Replica' },
  { name: 'Timestamp Service 1', port: 9001, healthy: false, role: 'Odd Timestamps' },
  { name: 'Timestamp Service 2', port: 9002, healthy: false, role: 'Even Timestamps' },
  { name: 'Metrics Collector', port: 9003, healthy: false, role: 'Monitoring' },
  { name: 'Cabinet Service', port: 9004, healthy: false, role: 'Quorum Selection' },
  { name: 'SEER Service', port: 9005, healthy: false, role: 'Leader Election' },
])

// Cluster Topology State
const metrics = ref<any[]>([])
const masterTimestamp = ref<number>(0)
const systemStatus = ref<any>({})

// Failover State
const failoverInProgress = ref(false)
const electionInProgress = ref(false)
const failoverFlow = ref<any[]>([])
const failoverResult = ref<any>(null)

// Stress Test State
const stressTestRunning = ref<string | null>(null)
const stressTestOps = ref(50)
const stressTestConsistency = ref('STRONG')
const stressTestResult = ref<any>(null)
const dataCount = ref({ users: 0, products: 0, total: 0 })
const clearingData = ref(false)
const consistencyMetricsArray = ref<any[]>([])

// Live progress state
const elapsedTime = ref(0)
const progressPercent = ref(0)
const liveStats = ref({ completed: 0, successful: 0, failed: 0, avgLatency: 0 })
const recentOperations = ref<any[]>([])
let progressTimer: any = null

const consistencyOptions = [
  { label: 'EVENTUAL', value: 'EVENTUAL', shortDesc: 'Fast, async replication' },
  { label: 'STRONG', value: 'STRONG', shortDesc: 'Cabinet quorum confirms' }
]

let refreshInterval: any = null

// Helper functions
const getLatencyClass = (latency: number) => {
  if (latency < 20) return 'good'
  if (latency < 50) return 'warning'
  return 'bad'
}

const getLagClass = (lag: number) => {
  if (lag === 0) return 'good'
  if (lag < 5) return 'warning'
  return 'bad'
}

const formatUptime = (seconds: number) => {
  if (seconds < 60) return `${seconds.toFixed(0)}s`
  if (seconds < 3600) return `${(seconds / 60).toFixed(1)}m`
  return `${(seconds / 3600).toFixed(1)}h`
}

const sleep = (ms: number) => new Promise(resolve => setTimeout(resolve, ms))

// Data fetching functions
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
      if (service) service.healthy = response.ok
    } catch {
      const service = services.value[check.index]
      if (service) service.healthy = false
    }
  }

  const coordinator = services.value[0]
  if (coordinator?.healthy) {
    const ts1 = services.value[5]
    const ts2 = services.value[6]
    if (ts1) ts1.healthy = true
    if (ts2) ts2.healthy = true
  }

  try {
    const metricsResponse = await fetch('http://localhost:9003/metrics')
    if (metricsResponse.ok) {
      const metricsData = await metricsResponse.json()
      const replicas = metricsData.replicas || []
      
      const instanceToIndex: Record<string, number> = {
        'instance-1': 1,
        'instance-2': 2,
        'instance-3': 3,
        'instance-4': 4
      }
      
      for (let i = 1; i <= 4; i++) {
        const service = services.value[i]
        if (service) service.healthy = false
      }
      
      for (const replica of replicas) {
        const index = instanceToIndex[replica.replica_id]
        if (index !== undefined) {
          const service = services.value[index]
          if (service) service.healthy = replica.is_healthy
        }
      }
    }
  } catch (error) {
    if (coordinator?.healthy) {
      for (let i = 1; i <= 4; i++) {
        const service = services.value[i]
        if (service) service.healthy = true
      }
    }
  }
}

const fetchMetrics = async () => {
  try {
    const response = await fetch('http://localhost:9003/metrics')
    const data = await response.json()
    metrics.value = data.replicas
    masterTimestamp.value = data.master_timestamp
  } catch (error) {
    console.error('Failed to fetch metrics:', error)
  }
}

const fetchSystemStatus = async () => {
  try {
    const response = await fetch(`${API_BASE}/status`)
    systemStatus.value = await response.json()
  } catch (error) {
    console.error('Failed to fetch system status:', error)
  }
}

const fetchConsistencyMetrics = async () => {
  try {
    const response = await fetch(`${API_BASE}/consistency-metrics`)
    const data = await response.json()
    consistencyMetricsArray.value = Object.keys(data).map(level => ({
      level,
      ...data[level]
    }))
  } catch (error) {
    console.error('Failed to fetch consistency metrics:', error)
  }
}

const fetchDataCount = async () => {
  try {
    const response = await fetch(`${API_BASE}/admin/stress-test/data-count`)
    const data = await response.json()
    dataCount.value = data
  } catch (error) {
    console.error('Failed to fetch data count:', error)
  }
}

// Failover functions
const electLeaderOnly = async () => {
  failoverFlow.value = []
  electionInProgress.value = true
  failoverResult.value = null
  
  try {
    failoverFlow.value.push({
      title: 'Initiating SEER Algorithm',
      detail: 'Analyzing replicas to select optimal leader based on latency, lag, and stability...'
    })
    
    const seerResponse = await fetch('http://localhost:9005/elect-leader', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({})
    })
    const seerData = await seerResponse.json()
    
    failoverFlow.value.push({
      title: 'Leader Selected',
      detail: `${seerData.leader_id} chosen with score ${seerData.score.toFixed(3)} (latency: ${seerData.latency_ms.toFixed(2)}ms, lag: ${seerData.replication_lag})`
    })

    failoverFlow.value.push({
      title: 'Promoting New Leader',
      detail: `Promoting ${seerData.leader_id} to master, demoting current master to replica`
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
        detail: `New master: ${failoverData.new_master}, Old master ${failoverData.old_master} is now a replica`
      })
      
      failoverResult.value = {
        success: true,
        message: `Graceful failover complete. New master: ${failoverData.new_master}`
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
    const oldMasterId = systemStatus.value.current_master?.id || 'instance-1'
    const oldMasterContainer = systemStatus.value.current_master?.container || 'mysql-instance-1'
    
    failoverFlow.value.push({
      title: 'Stopping Master Container',
      detail: `Executing docker stop ${oldMasterContainer}`
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
      title: 'Master Stopped',
      detail: `Container ${oldMasterContainer} is now down`
    })
    
    await sleep(2000)
    
    failoverFlow.value.push({
      title: 'Running SEER Election',
      detail: 'Analyzing remaining replicas to select optimal leader...'
    })
    
    const seerResponse = await fetch('http://localhost:9005/elect-leader', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ exclude_replicas: [oldMasterId] })
    })
    
    if (!seerResponse.ok) throw new Error('SEER election failed')
    
    const seerData = await seerResponse.json()
    
    failoverFlow.value.push({
      title: 'New Leader Elected',
      detail: `${seerData.leader_id} selected with score ${seerData.score.toFixed(3)}`
    })
    
    await sleep(1000)
    
    failoverFlow.value.push({
      title: 'Promoting New Leader',
      detail: `Promoting ${seerData.leader_id} to master...`
    })
    
    const failoverResponse = await fetch(`${API_BASE}/admin/trigger-failover`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ new_leader: seerData.leader_id })
    })
    
    if (!failoverResponse.ok) throw new Error('Failover promotion failed')
    
    const failoverData = await failoverResponse.json()
    
    if (!failoverData.success) {
      throw new Error(failoverData.error || failoverData.message || 'Failover failed')
    }
    
    failoverFlow.value.push({
      title: 'New Master Active',
      detail: `${failoverData.new_master} is now the master`
    })
    
    await fetchSystemStatus()
    await fetchMetrics()
    await sleep(3000)
    
    failoverFlow.value.push({
      title: 'Restarting Old Master',
      detail: `Starting ${oldMasterContainer} and configuring as replica...`
    })
    
    const restartResponse = await fetch(`${API_BASE}/admin/start-instance`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ instance_id: oldMasterId })
    })
    
    if (!restartResponse.ok) throw new Error('Failed to restart old master')
    
    const restartData = await restartResponse.json()
    
    failoverFlow.value.push({
      title: 'Recovery Complete',
      detail: `${oldMasterId} is now replicating from ${restartData.current_master.id}. Total replicas: ${restartData.total_replicas}`
    })
    
    systemStatus.value = {
      current_master: restartData.current_master,
      current_replicas: restartData.current_replicas,
      total_replicas: restartData.total_replicas,
      replication_mode: 'binlog'
    }
    
    failoverResult.value = {
      success: true,
      message: `Complete failover with recovery. New master: ${restartData.current_master.id}, old master ${oldMasterId} recovered as replica.`
    }
    
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

// Stress Test functions
const clearData = async () => {
  clearingData.value = true
  stressTestResult.value = null
  
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

const getLatencyBarWidth = (latency: number) => {
  const maxLatency = stressTestResult.value?.max_latency_ms || 100
  return Math.min((latency / maxLatency) * 100, 100) + '%'
}

const startProgressTimer = () => {
  elapsedTime.value = 0
  progressTimer = setInterval(() => {
    elapsedTime.value += 0.1
  }, 100)
}

const stopProgressTimer = () => {
  if (progressTimer) {
    clearInterval(progressTimer)
    progressTimer = null
  }
}

const addOperation = (success: boolean, latency: number, timestamp: number | null) => {
  const now = new Date()
  const timeStr = now.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })
  
  recentOperations.value.unshift({
    time: timeStr,
    success,
    message: success 
      ? `INSERT completed${timestamp ? ` (ts: ${timestamp})` : ''}`
      : 'INSERT failed',
    latency: latency.toFixed(1)
  })
  
  // Keep only last 8 entries
  if (recentOperations.value.length > 8) {
    recentOperations.value.pop()
  }
}

const runStressTest = async () => {
  stressTestRunning.value = 'concurrent'
  stressTestResult.value = null
  
  // Reset live stats
  liveStats.value = { completed: 0, successful: 0, failed: 0, avgLatency: 0 }
  recentOperations.value = []
  progressPercent.value = 0
  startProgressTimer()
  
  const numOps = stressTestOps.value
  const consistency = stressTestConsistency.value
  const startTime = Date.now()
  const latencies: number[] = []
  const timestamps: number[] = []
  const errors: Record<string, number> = {}
  
  // Generate unique base timestamp
  const baseTs = Date.now()
  
  // Run operations with progress updates
  const runOperation = async (i: number) => {
    const opStart = Date.now()
    const name = `StressUser_${baseTs}_${i}`
    const email = `stress_${baseTs}_${i}@test.com`
    const query = `INSERT INTO users (name, email) VALUES ("${name}", "${email}")`
    
    try {
      // Add timeout - ALL consistency can take longer (waiting for all replicas)
      const controller = new AbortController()
      const timeoutId = setTimeout(() => controller.abort(), consistency === 'STRONG' ? 12000 : 8000)

      
      const response = await fetch(`${API_BASE}/query`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query, consistency }),
        signal: controller.signal
      })
      
      clearTimeout(timeoutId)
      
      const result = await response.json()
      const latency = Date.now() - opStart
      latencies.push(latency)
      
      if (result.success) {
        liveStats.value.successful++
        if (result.timestamp) timestamps.push(result.timestamp)
        addOperation(true, latency, result.timestamp)
      } else {
        liveStats.value.failed++
        // Better error messages for common issues
        let errorMsg = result.detail || result.error || 'Unknown error'
        if (errorMsg.includes('Not enough healthy replicas') || errorMsg.includes('Cabinet quorum')) {
          errorMsg = 'Not enough healthy replicas for ' + consistency + ' consistency'
        }
        errors[errorMsg] = (errors[errorMsg] || 0) + 1
        addOperation(false, latency, null)
      }
    } catch (error: any) {
      const latency = Date.now() - opStart
      latencies.push(latency)
      liveStats.value.failed++
      
      // Provide meaningful error messages
      let errorMsg = 'Connection failed'
      if (error.name === 'AbortError') {
        errorMsg = consistency === 'STRONG' 
          ? 'Timeout: Waiting for Cabinet quorum took too long'
          : 'Request timeout'
      } else if (error.message?.includes('fetch')) {
        errorMsg = 'Backend not reachable - is the server running?'
      } else if (error.message) {
        errorMsg = error.message
      }
      
      errors[errorMsg] = (errors[errorMsg] || 0) + 1
      addOperation(false, latency, null)
    }
    
    liveStats.value.completed++
    liveStats.value.avgLatency = Math.round(latencies.reduce((a, b) => a + b, 0) / latencies.length)
    progressPercent.value = Math.round((liveStats.value.completed / numOps) * 100)
  }
  
  // Execute operations based on consistency level
  // STRONG: Small batches to avoid overwhelming Cabinet
  // EVENTUAL: Larger batches for maximum throughput
  const batchSize = consistency === 'STRONG' ? 5 : 20
  for (let i = 0; i < numOps; i += batchSize) {
    const batch = []
    for (let j = i; j < Math.min(i + batchSize, numOps); j++) {
      batch.push(runOperation(j))
    }
    await Promise.all(batch)
  }
    
  stopProgressTimer()
  
  const duration = (Date.now() - startTime) / 1000
  
  stressTestResult.value = {
    test_name: 'Concurrent Writes',
    total_operations: numOps,
    successful: liveStats.value.successful,
    failed: liveStats.value.failed,
    duration_seconds: Math.round(duration * 1000) / 1000,
    throughput_ops_per_sec: Math.round((numOps / duration) * 100) / 100,
    avg_latency_ms: Math.round(latencies.reduce((a, b) => a + b, 0) / latencies.length * 100) / 100,
    min_latency_ms: Math.round(Math.min(...latencies) * 100) / 100,
    max_latency_ms: Math.round(Math.max(...latencies) * 100) / 100,
    consistency_level: consistency,
    timestamp_range: timestamps.length > 0 ? { min: Math.min(...timestamps), max: Math.max(...timestamps) } : null,
    errors: Object.keys(errors).length > 0 ? errors : null
  }
  
  await fetchDataCount()
  await fetchMetrics()
  await fetchConsistencyMetrics()
  
  stressTestRunning.value = null
}

// Lifecycle
onMounted(() => {
  checkServiceHealth()
  fetchMetrics()
  fetchSystemStatus()
  fetchConsistencyMetrics()
  fetchDataCount()
  
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
/* Dashboard Layout */
.dashboard {
  max-width: 1400px;
  margin: 0 auto;
  padding: 2rem;
  background: #f5f7fa;
  min-height: 100vh;
}

.dashboard-header {
  background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
  color: white;
  padding: 2rem 2.5rem;
  border-radius: 12px;
  margin-bottom: 2rem;
}

.dashboard-header h1 {
  font-size: 1.75rem;
  font-weight: 600;
  margin-bottom: 0.5rem;
}

.dashboard-header p {
  opacity: 0.85;
  font-size: 0.95rem;
}

/* Sections */
.dashboard-section {
  background: white;
  border-radius: 12px;
  padding: 1.5rem;
  margin-bottom: 1.5rem;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
}

.section-header {
  margin-bottom: 1.5rem;
  padding-bottom: 1rem;
  border-bottom: 1px solid #e5e7eb;
}

.section-header h2 {
  font-size: 1.25rem;
  font-weight: 600;
  color: #1a1a2e;
  margin-bottom: 0.25rem;
}

.section-subtitle {
  font-size: 0.875rem;
  color: #6b7280;
}

/* Service Status */
.services-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 1rem;
}

.service-card {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 1rem;
  border-radius: 8px;
  background: #f9fafb;
  border: 1px solid #e5e7eb;
  transition: all 0.2s;
}

.service-card.healthy {
  border-left: 3px solid #10b981;
}

.service-card.unhealthy {
  border-left: 3px solid #ef4444;
  background: #fef2f2;
}

.service-status-indicator {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}

.service-card.healthy .service-status-indicator {
  background: #10b981;
  box-shadow: 0 0 8px rgba(16, 185, 129, 0.4);
}

.service-card.unhealthy .service-status-indicator {
  background: #ef4444;
  box-shadow: 0 0 8px rgba(239, 68, 68, 0.4);
}

.service-info {
  flex: 1;
  min-width: 0;
}

.service-name {
  font-weight: 600;
  font-size: 0.875rem;
  color: #1f2937;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.service-details {
  display: flex;
  gap: 0.5rem;
  font-size: 0.75rem;
  color: #6b7280;
  margin-top: 0.25rem;
}

.service-status-text {
  font-size: 0.75rem;
  font-weight: 500;
  color: #6b7280;
}

/* Cluster Topology */
.topology-container {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  align-items: center;
  padding: 1.5rem;
  background: #f9fafb;
  border-radius: 8px;
}

.node-card {
  padding: 1.25rem;
  border-radius: 8px;
  text-align: center;
  min-width: 200px;
}

.node-card.master {
  background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
  color: white;
}

.node-card.replica {
  background: white;
  border: 1px solid #e5e7eb;
}

.node-card.replica.unhealthy {
  border-color: #ef4444;
  background: #fef2f2;
}

.node-badge {
  display: inline-block;
  font-size: 0.65rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 0.25rem 0.5rem;
  border-radius: 4px;
  margin-bottom: 0.5rem;
}

.master .node-badge {
  background: rgba(255, 255, 255, 0.2);
}

.replica .node-badge {
  background: #e5e7eb;
  color: #4b5563;
}

.node-id {
  font-size: 1rem;
  font-weight: 600;
  margin-bottom: 0.25rem;
}

.node-host {
  font-size: 0.75rem;
  opacity: 0.8;
}

.node-info {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  margin-top: 0.75rem;
  font-size: 0.75rem;
  opacity: 0.8;
}

.replication-flow {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.5rem;
}

.flow-line {
  width: 2px;
  height: 30px;
  background: linear-gradient(to bottom, #1a1a2e, #6b7280);
}

.flow-label {
  font-size: 0.75rem;
  color: #6b7280;
  font-weight: 500;
}

.topology-replicas {
  display: flex;
  gap: 1rem;
  flex-wrap: wrap;
  justify-content: center;
}

.replica-metrics {
  margin-top: 0.75rem;
  text-align: left;
}

.metric-row {
  display: flex;
  justify-content: space-between;
  padding: 0.25rem 0;
  font-size: 0.8rem;
  border-bottom: 1px solid #f3f4f6;
}

.metric-row:last-child {
  border-bottom: none;
}

.metric-name {
  color: #6b7280;
}

.metric-value {
  font-weight: 500;
  color: #1f2937;
}

.metric-value.good { color: #10b981; }
.metric-value.warning { color: #f59e0b; }
.metric-value.bad { color: #ef4444; }

/* Metrics Explanation */
.metrics-explanation {
  margin-top: 1.5rem;
  padding: 1rem;
  background: #f0fdf4;
  border-radius: 8px;
  border: 1px solid #bbf7d0;
}

.metrics-explanation h3 {
  font-size: 0.9rem;
  font-weight: 600;
  color: #166534;
  margin-bottom: 1rem;
}

.explanation-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 1rem;
}

.explanation-item {
  padding: 0.75rem;
  background: white;
  border-radius: 6px;
}

.explanation-term {
  font-weight: 600;
  font-size: 0.85rem;
  color: #166534;
  margin-bottom: 0.25rem;
}

.explanation-desc {
  font-size: 0.8rem;
  color: #4b5563;
  line-height: 1.4;
}

/* Failover Section */
.failover-container {
  padding: 1rem;
}

.failover-info {
  background: #f9fafb;
  padding: 1rem;
  border-radius: 8px;
  margin-bottom: 1.5rem;
}

.failover-info p {
  font-size: 0.875rem;
  color: #4b5563;
  margin-bottom: 0.75rem;
}

.failover-info ul {
  list-style: none;
  padding: 0;
}

.failover-info li {
  font-size: 0.8rem;
  color: #6b7280;
  padding: 0.25rem 0;
  padding-left: 1rem;
  position: relative;
}

.failover-info li::before {
  content: '';
  position: absolute;
  left: 0;
  top: 50%;
  transform: translateY(-50%);
  width: 4px;
  height: 4px;
  background: #6b7280;
  border-radius: 50%;
}

.failover-actions {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 1rem;
  margin-bottom: 1.5rem;
}

.action-card {
  padding: 1.25rem;
  background: #f9fafb;
  border-radius: 8px;
  border: 1px solid #e5e7eb;
}

.action-card h4 {
  font-size: 0.95rem;
  font-weight: 600;
  color: #1f2937;
  margin-bottom: 0.5rem;
}

.action-card p {
  font-size: 0.8rem;
  color: #6b7280;
  margin-bottom: 1rem;
  line-height: 1.4;
}

.failover-progress {
  background: #f9fafb;
  padding: 1rem;
  border-radius: 8px;
  margin-bottom: 1rem;
}

.failover-progress h4 {
  font-size: 0.9rem;
  font-weight: 600;
  color: #1f2937;
  margin-bottom: 1rem;
}

.progress-steps {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.progress-step {
  display: flex;
  gap: 0.75rem;
  padding: 0.75rem;
  background: white;
  border-radius: 6px;
  border-left: 3px solid #3b82f6;
}

.step-number {
  width: 24px;
  height: 24px;
  background: #3b82f6;
  color: white;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.75rem;
  font-weight: 600;
  flex-shrink: 0;
}

.step-content {
  flex: 1;
}

.step-title {
  font-weight: 600;
  font-size: 0.85rem;
  color: #1f2937;
}

.step-detail {
  font-size: 0.8rem;
  color: #6b7280;
  margin-top: 0.25rem;
}

.failover-result {
  padding: 1rem;
  border-radius: 8px;
  font-size: 0.875rem;
}

.failover-result.success {
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  color: #166534;
}

.failover-result.error {
  background: #fef2f2;
  border: 1px solid #fecaca;
  color: #991b1b;
}

/* Stress Test Section */
.stress-test-container {
  padding: 1rem;
}

/* Test Explanation */
.test-explanation {
  background: linear-gradient(135deg, #f0f9ff 0%, #e0f2fe 100%);
  padding: 1.5rem;
  border-radius: 10px;
  margin-bottom: 1.5rem;
  border: 1px solid #bae6fd;
}

.test-explanation h4 {
  font-size: 1rem;
  font-weight: 600;
  color: #0369a1;
  margin-bottom: 1rem;
}

.test-goals {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.test-goal {
  display: flex;
  gap: 1rem;
  align-items: flex-start;
}

.goal-icon {
  width: 28px;
  height: 28px;
  background: #0284c7;
  color: white;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.85rem;
  font-weight: 600;
  flex-shrink: 0;
}

.goal-content strong {
  display: block;
  font-size: 0.9rem;
  color: #0c4a6e;
  margin-bottom: 0.25rem;
}

.goal-content p {
  font-size: 0.8rem;
  color: #475569;
  line-height: 1.4;
}

/* Test Config */
.test-config {
  background: #f9fafb;
  padding: 1.25rem;
  border-radius: 10px;
  margin-bottom: 1.5rem;
  border: 1px solid #e5e7eb;
}

.config-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1rem;
}

.config-header h4 {
  font-size: 0.95rem;
  font-weight: 600;
  color: #1f2937;
}

.data-info {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  font-size: 0.8rem;
  color: #6b7280;
}

.config-options {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.config-option label {
  display: block;
  font-size: 0.8rem;
  font-weight: 500;
  color: #4b5563;
  margin-bottom: 0.5rem;
}

.option-buttons {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.option-buttons button {
  padding: 0.5rem 1rem;
  border: 1px solid #d1d5db;
  background: white;
  border-radius: 6px;
  font-size: 0.85rem;
  cursor: pointer;
  transition: all 0.2s;
}

.option-buttons button:hover {
  border-color: #3b82f6;
}

.option-buttons button.active {
  background: #3b82f6;
  color: white;
  border-color: #3b82f6;
}

.consistency-buttons {
  gap: 0.75rem;
}

.consistency-btn {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  padding: 0.75rem 1rem !important;
  min-width: 160px;
}

.consistency-btn .btn-label {
  font-weight: 600;
}

.consistency-btn .btn-desc {
  font-size: 0.7rem;
  opacity: 0.8;
  margin-top: 0.25rem;
}

.consistency-btn.eventual.active {
  background: #059669 !important;
  border-color: #059669 !important;
}

.consistency-btn.strong.active {
  background: #2563eb !important;
  border-color: #2563eb !important;
}

/* Run Test Section */
.run-test-section {
  text-align: center;
  padding: 1.5rem;
  background: #fafafa;
  border-radius: 10px;
  margin-bottom: 1.5rem;
  border: 2px dashed #e5e7eb;
}

.run-description {
  margin-top: 0.75rem;
  font-size: 0.85rem;
  color: #6b7280;
}

.consistency-warning {
  margin-top: 0.5rem;
  font-size: 0.8rem;
  color: #d97706;
  background: #fef3c7;
  padding: 0.5rem 0.75rem;
  border-radius: 6px;
  border: 1px solid #fde68a;
}

/* Live Progress */
.live-progress {
  background: #1e293b;
  color: white;
  padding: 1.5rem;
  border-radius: 10px;
  margin-bottom: 1.5rem;
}

.progress-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1rem;
}

.progress-header h4 {
  font-size: 1rem;
  font-weight: 600;
}

.elapsed-time {
  font-family: monospace;
  font-size: 1.1rem;
  color: #60a5fa;
}

.progress-bar-container {
  height: 8px;
  background: #334155;
  border-radius: 4px;
  overflow: hidden;
  margin-bottom: 1.5rem;
}

.progress-bar-fill {
  height: 100%;
  background: linear-gradient(90deg, #3b82f6, #60a5fa);
  transition: width 0.3s ease;
}

.live-stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 1rem;
  margin-bottom: 1.5rem;
}

.live-stat {
  text-align: center;
  padding: 1rem;
  background: #334155;
  border-radius: 8px;
}

.live-stat-value {
  font-size: 1.5rem;
  font-weight: 700;
  color: #f1f5f9;
}

.live-stat-label {
  font-size: 0.75rem;
  color: #94a3b8;
  margin-top: 0.25rem;
}

.operation-log h5 {
  font-size: 0.85rem;
  font-weight: 600;
  margin-bottom: 0.75rem;
  color: #94a3b8;
}

.log-entries {
  font-family: monospace;
  font-size: 0.8rem;
  max-height: 200px;
  overflow-y: auto;
}

.log-entry {
  display: flex;
  gap: 1rem;
  padding: 0.4rem 0.5rem;
  border-radius: 4px;
  margin-bottom: 0.25rem;
}

.log-entry.success {
  background: rgba(16, 185, 129, 0.1);
}

.log-entry.failure {
  background: rgba(239, 68, 68, 0.1);
}

.log-time {
  color: #64748b;
}

.log-message {
  flex: 1;
  color: #e2e8f0;
}

.log-entry.success .log-message {
  color: #4ade80;
}

.log-entry.failure .log-message {
  color: #f87171;
}

.log-latency {
  color: #60a5fa;
}

/* Test Results */
.test-results {
  background: white;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  padding: 1.5rem;
  margin-bottom: 1.5rem;
}

.results-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1.5rem;
}

.results-header h4 {
  font-size: 1.1rem;
  font-weight: 600;
  color: #1f2937;
}

.result-badge {
  padding: 0.35rem 0.75rem;
  border-radius: 20px;
  font-size: 0.8rem;
  font-weight: 500;
}

.result-badge.success {
  background: #d1fae5;
  color: #065f46;
}

.result-badge.partial {
  background: #fef3c7;
  color: #92400e;
}

/* Key Metrics */
.key-metrics {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 1rem;
  margin-bottom: 2rem;
}

.key-metric {
  display: flex;
  gap: 1rem;
  padding: 1rem;
  background: #f9fafb;
  border-radius: 8px;
  border: 1px solid #e5e7eb;
}

.metric-icon {
  width: 48px;
  height: 48px;
  border-radius: 10px;
  flex-shrink: 0;
}

.metric-icon.throughput {
  background: linear-gradient(135deg, #3b82f6, #1d4ed8);
}

.metric-icon.latency {
  background: linear-gradient(135deg, #8b5cf6, #6d28d9);
}

.metric-icon.success {
  background: linear-gradient(135deg, #10b981, #059669);
}

.metric-icon.time {
  background: linear-gradient(135deg, #f59e0b, #d97706);
}

.metric-data .metric-value {
  font-size: 1.4rem;
  font-weight: 700;
  color: #1f2937;
}

.metric-data .metric-label {
  font-size: 0.85rem;
  font-weight: 500;
  color: #4b5563;
}

.metric-data .metric-context {
  font-size: 0.75rem;
  color: #9ca3af;
  margin-top: 0.25rem;
}

/* Latency Section */
.latency-section {
  margin-bottom: 1.5rem;
  padding: 1rem;
  background: #f9fafb;
  border-radius: 8px;
}

.latency-section h5 {
  font-size: 0.9rem;
  font-weight: 600;
  color: #374151;
  margin-bottom: 1rem;
}

.latency-bars {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  margin-bottom: 1rem;
}

.latency-bar {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.bar-label {
  width: 40px;
  font-size: 0.8rem;
  font-weight: 500;
  color: #6b7280;
}

.bar-visual {
  flex: 1;
  height: 24px;
  background: #e5e7eb;
  border-radius: 4px;
  overflow: hidden;
}

.bar-fill {
  height: 100%;
  border-radius: 4px;
  transition: width 0.3s ease;
}

.bar-fill.min {
  background: linear-gradient(90deg, #10b981, #34d399);
}

.bar-fill.avg {
  background: linear-gradient(90deg, #3b82f6, #60a5fa);
}

.bar-fill.max {
  background: linear-gradient(90deg, #f59e0b, #fbbf24);
}

.bar-value {
  width: 80px;
  font-size: 0.85rem;
  font-weight: 600;
  color: #374151;
  text-align: right;
}

.latency-explanation {
  padding: 0.75rem;
  background: #fff;
  border-radius: 6px;
  border-left: 3px solid #3b82f6;
}

.latency-explanation p {
  font-size: 0.8rem;
  color: #4b5563;
  line-height: 1.5;
}

/* Timestamp Section */
.timestamp-section {
  margin-bottom: 1.5rem;
  padding: 1rem;
  background: #f0fdf4;
  border-radius: 8px;
  border: 1px solid #bbf7d0;
}

.timestamp-section h5 {
  font-size: 0.9rem;
  font-weight: 600;
  color: #166534;
  margin-bottom: 1rem;
}

.timestamp-visual {
  display: flex;
  align-items: center;
  gap: 1rem;
  margin-bottom: 1rem;
}

.ts-start, .ts-end {
  text-align: center;
  padding: 0.75rem 1rem;
  background: white;
  border-radius: 8px;
  min-width: 120px;
}

.ts-label {
  display: block;
  font-size: 0.7rem;
  color: #6b7280;
  margin-bottom: 0.25rem;
}

.ts-value {
  font-family: monospace;
  font-size: 0.85rem;
  font-weight: 600;
  color: #166534;
}

.ts-arrow {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.25rem;
}

.arrow-line {
  width: 100%;
  height: 2px;
  background: linear-gradient(90deg, #22c55e, #166534);
  position: relative;
}

.arrow-line::after {
  content: '';
  position: absolute;
  right: 0;
  top: -4px;
  border: 5px solid transparent;
  border-left-color: #166534;
}

.arrow-label {
  font-size: 0.75rem;
  color: #166534;
}

.timestamp-explanation {
  font-size: 0.8rem;
  color: #4b5563;
  line-height: 1.5;
}

/* Errors Section */
.errors-section {
  padding: 1rem;
  background: #fef2f2;
  border-radius: 8px;
  border: 1px solid #fecaca;
  margin-bottom: 1.5rem;
}

.errors-section h5 {
  font-size: 0.9rem;
  font-weight: 600;
  color: #991b1b;
  margin-bottom: 0.75rem;
}

.error-list {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.error-item {
  display: flex;
  gap: 0.75rem;
  font-size: 0.8rem;
}

.error-count {
  font-weight: 600;
  color: #dc2626;
}

.error-message {
  color: #7f1d1d;
}

/* What Happened */
.what-happened {
  padding: 1rem;
  background: #fffbeb;
  border-radius: 8px;
  border: 1px solid #fde68a;
}

.what-happened h5 {
  font-size: 0.9rem;
  font-weight: 600;
  color: #92400e;
  margin-bottom: 0.75rem;
}

.step-list {
  margin: 0;
  padding-left: 1.25rem;
}

.step-list li {
  font-size: 0.8rem;
  color: #78350f;
  line-height: 1.6;
  margin-bottom: 0.25rem;
}

/* Cumulative Stats */
.cumulative-stats {
  background: #f9fafb;
  padding: 1.25rem;
  border-radius: 10px;
  border: 1px solid #e5e7eb;
}

.cumulative-stats h4 {
  font-size: 1rem;
  font-weight: 600;
  color: #1f2937;
  margin-bottom: 0.25rem;
}

.stats-subtitle {
  font-size: 0.8rem;
  color: #6b7280;
  margin-bottom: 1rem;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 1rem;
}

.stat-card {
  background: white;
  border-radius: 8px;
  padding: 1rem;
  border: 1px solid #e5e7eb;
}

.stat-card.eventual {
  border-top: 3px solid #10b981;
}

.stat-card.strong {
  border-top: 3px solid #3b82f6;
}

.stat-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.75rem;
}

.stat-level {
  font-weight: 700;
  font-size: 0.9rem;
}

.stat-card.eventual .stat-level { color: #059669; }
.stat-card.strong .stat-level { color: #2563eb; }

.stat-count {
  font-size: 0.75rem;
  color: #6b7280;
}

.stat-row {
  display: flex;
  justify-content: space-between;
  padding: 0.35rem 0;
  font-size: 0.8rem;
  border-bottom: 1px solid #f3f4f6;
}

.stat-row:last-child {
  border-bottom: none;
}

.stat-row span:first-child {
  color: #6b7280;
}

.stat-row span:last-child {
  font-weight: 500;
  color: #1f2937;
}

.stat-row .good {
  color: #059669;
}

.stat-row .bad {
  color: #dc2626;
}

.consistency-info {
  margin-top: 0.5rem;
  font-size: 0.8rem;
  color: #2563eb;
  background: #dbeafe;
  padding: 0.5rem 0.75rem;
  border-radius: 6px;
  border: 1px solid #93c5fd;
}

/* Responsive */
@media (max-width: 900px) {
  .key-metrics {
    grid-template-columns: repeat(2, 1fr);
  }
  
  .stats-grid {
    grid-template-columns: 1fr;
  }
  
  .live-stats {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 600px) {
  .key-metrics {
    grid-template-columns: 1fr;
  }
  
  .timestamp-visual {
    flex-direction: column;
  }
  
  .ts-arrow {
    transform: rotate(90deg);
    width: 60px;
  }
}
</style>