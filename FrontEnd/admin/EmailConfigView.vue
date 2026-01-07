<script setup>
import { ref, onMounted } from 'vue'

const API_BASE = 'http://127.0.0.1:8000'
const loading = ref(false)
const saving = ref(false)
const testing = ref(false)
const message = ref('')
const messageType = ref('') // 'success' or 'error'

const config = ref({
  smtp_server: '',
  smtp_port: 465,
  smtp_login: '',
  smtp_password: '',
  sender_name: ''
})

const passwordSet = ref(false)

onMounted(async () => {
  await loadConfig()
})

const loadConfig = async () => {
  loading.value = true
  message.value = ''
  
  try {
    const token = localStorage.getItem('token')
    const res = await fetch(`${API_BASE}/api/admin/email-config`, {
      headers: { 'Authorization': `Bearer ${token}` }
    })
    
    if (res.ok) {
      const data = await res.json()
      config.value.smtp_server = data.smtp_server || ''
      config.value.smtp_port = data.smtp_port || 465
      config.value.smtp_login = data.smtp_login || ''
      config.value.sender_name = data.sender_name || ''
      passwordSet.value = data.password_set || false
      // Password not returned, if set then show placeholder
      if (passwordSet.value) {
        config.value.smtp_password = '********'
      }
    } else {
      throw new Error('Failed to load email configuration')
    }
  } catch (e) {
    message.value = 'Failed to load configuration: ' + e.message
    messageType.value = 'error'
  } finally {
    loading.value = false
  }
}

const saveConfig = async () => {
  // Validate required fields
  if (!config.value.smtp_server || !config.value.smtp_login) {
    message.value = 'Please fill in SMTP server and login account'
    messageType.value = 'error'
    return
  }
  
  if (!config.value.smtp_password || config.value.smtp_password === '********') {
    message.value = 'Please fill in SMTP password'
    messageType.value = 'error'
    return
  }
  
  // Validate port
  if (config.value.smtp_port < 1 || config.value.smtp_port > 65535) {
    message.value = 'SMTP port must be between 1 and 65535'
    messageType.value = 'error'
    return
  }
  
  saving.value = true
  message.value = ''
  
  try {
    const token = localStorage.getItem('token')
    const res = await fetch(`${API_BASE}/api/admin/email-config`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify(config.value)
    })
    
    const data = await res.json()
    
    if (res.ok) {
      message.value = 'Email configuration saved successfully'
      messageType.value = 'success'
      passwordSet.value = true
      // After saving, password displays as placeholder
      config.value.smtp_password = '********'
    } else {
      throw new Error(data.detail || 'Save failed')
    }
  } catch (e) {
    message.value = 'Save failed: ' + e.message
    messageType.value = 'error'
  } finally {
    saving.value = false
  }
}

const testConfig = async () => {
  // Validate required fields
  if (!config.value.smtp_server || !config.value.smtp_login) {
    message.value = 'Please fill in SMTP server and login account'
    messageType.value = 'error'
    return
  }
  
  if (!config.value.smtp_password || config.value.smtp_password === '********') {
    message.value = 'Please fill in SMTP password to test'
    messageType.value = 'error'
    return
  }
  
  testing.value = true
  message.value = ''
  
  try {
    const token = localStorage.getItem('token')
    const res = await fetch(`${API_BASE}/api/admin/email-config/test`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify(config.value)
    })
    
    const data = await res.json()
    
    if (res.ok) {
      message.value = data.msg || 'Test email sent, please check your inbox'
      messageType.value = 'success'
    } else {
      throw new Error(data.detail || 'Test failed')
    }
  } catch (e) {
    message.value = 'Test failed: ' + e.message
    messageType.value = 'error'
  } finally {
    testing.value = false
  }
}

const clearPassword = () => {
  config.value.smtp_password = ''
}
</script>

<template>
  <div>
    <header class="page-header">
      <h1 class="page-title">Email Configuration</h1>
      <p class="subtitle">Configure system email sending service</p>
    </header>

    <div v-if="loading" class="loading">Loading configuration...</div>

    <div v-else class="config-card">
      <div class="form-section">
        <h3 class="section-title">SMTP Server Settings</h3>
        
        <div class="form-group">
          <label>SMTP Server Address</label>
          <input 
            v-model="config.smtp_server" 
            type="text" 
            placeholder="e.g., smtp.126.com"
            class="form-input"
          />
          <small class="form-hint">SMTP server address of your email provider</small>
        </div>

        <div class="form-group">
          <label>SMTP Port</label>
          <input 
            v-model.number="config.smtp_port" 
            type="number" 
            min="1"
            max="65535"
            placeholder="465"
            class="form-input"
          />
          <small class="form-hint">Usually 465 for SSL, 587 for TLS</small>
        </div>

        <div class="form-group">
          <label>Login Account (Email Address)</label>
          <input 
            v-model="config.smtp_login" 
            type="email" 
            placeholder="your-email@example.com"
            class="form-input"
          />
          <small class="form-hint">Email account used for sending emails</small>
        </div>

        <div class="form-group">
          <label>Login Password (Authorization Code)</label>
          <div class="password-input-wrapper">
            <input 
              v-model="config.smtp_password" 
              :type="passwordSet && config.smtp_password === '********' ? 'password' : 'password'"
              placeholder="Enter SMTP password or authorization code"
              class="form-input"
              @focus="clearPassword"
            />
            <button 
              v-if="passwordSet && config.smtp_password === '********'"
              @click="clearPassword"
              class="clear-btn"
              type="button"
            >
              Change
            </button>
          </div>
          <small class="form-hint">Some email providers require authorization code instead of login password</small>
        </div>

        <div class="form-group">
          <label>Sender Name</label>
          <input 
            v-model="config.sender_name" 
            type="text" 
            placeholder="Cattle Match System"
            class="form-input"
          />
          <small class="form-hint">Sender name displayed in emails</small>
        </div>
      </div>

      <div v-if="message" :class="['message', messageType]">
        {{ message }}
      </div>

      <div class="action-buttons">
        <button 
          @click="testConfig" 
          :disabled="testing || saving"
          class="btn btn-test"
        >
          {{ testing ? 'Testing...' : 'Send Test Email' }}
        </button>
        <button 
          @click="saveConfig" 
          :disabled="saving || testing"
          class="btn btn-primary"
        >
          {{ saving ? 'Saving...' : 'Save Configuration' }}
        </button>
      </div>

      <div class="info-box">
        <h4>📌 Configuration Instructions</h4>
        <ul>
          <li><strong>126 Email:</strong> smtp.126.com, port 465 (SSL)</li>
          <li><strong>QQ Email:</strong> smtp.qq.com, port 465 (SSL) or 587 (TLS)</li>
          <li><strong>Gmail:</strong> smtp.gmail.com, port 465 (SSL) or 587 (TLS)</li>
          <li><strong>163 Email:</strong> smtp.163.com, port 465 (SSL)</li>
          <li>Some email providers require enabling SMTP service and obtaining authorization code in email settings</li>
        </ul>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page-header {
  margin-bottom: 30px;
}

.page-title {
  margin: 0;
  font-weight: 300;
  color: #333;
  font-size: 1.8rem;
}

.subtitle {
  color: #888;
  font-size: 0.9rem;
  margin-top: 5px;
}

.loading {
  text-align: center;
  padding: 40px;
  color: #888;
}

.config-card {
  background: white;
  border-radius: 12px;
  box-shadow: 0 4px 15px rgba(0,0,0,0.03);
  padding: 30px;
}

.form-section {
  margin-bottom: 30px;
}

.section-title {
  font-size: 1.1rem;
  color: #2c3e50;
  margin-bottom: 20px;
  padding-bottom: 10px;
  border-bottom: 2px solid #eee;
}

.form-group {
  margin-bottom: 20px;
}

.form-group label {
  display: block;
  font-weight: 500;
  color: #333;
  margin-bottom: 8px;
  font-size: 0.9rem;
}

.form-input {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid #ddd;
  border-radius: 6px;
  font-size: 0.95rem;
  box-sizing: border-box;
  transition: border-color 0.2s;
}

.form-input:focus {
  outline: none;
  border-color: #2c3e50;
}

.form-hint {
  display: block;
  color: #888;
  font-size: 0.8rem;
  margin-top: 5px;
}

.password-input-wrapper {
  position: relative;
  display: flex;
  align-items: center;
}

.password-input-wrapper .form-input {
  padding-right: 80px;
}

.clear-btn {
  position: absolute;
  right: 8px;
  background: #f5f5f5;
  border: 1px solid #ddd;
  padding: 6px 12px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 0.85rem;
  color: #666;
  transition: all 0.2s;
}

.clear-btn:hover {
  background: #e0e0e0;
}

.message {
  padding: 12px 15px;
  border-radius: 6px;
  margin-bottom: 20px;
  font-size: 0.9rem;
}

.message.success {
  background: #e8f5e9;
  color: #2e7d32;
  border: 1px solid #c8e6c9;
}

.message.error {
  background: #ffebee;
  color: #c62828;
  border: 1px solid #ffcdd2;
}

.action-buttons {
  display: flex;
  gap: 15px;
  margin-top: 30px;
  padding-top: 20px;
  border-top: 1px solid #eee;
}

.btn {
  padding: 12px 24px;
  border: none;
  border-radius: 6px;
  font-size: 0.95rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.btn-test {
  background: #f5f5f5;
  color: #333;
  border: 1px solid #ddd;
}

.btn-test:hover:not(:disabled) {
  background: #e0e0e0;
}

.btn-primary {
  background: #2c3e50;
  color: white;
}

.btn-primary:hover:not(:disabled) {
  background: #34495e;
}

.info-box {
  margin-top: 30px;
  padding: 20px;
  background: #f8f9fa;
  border-radius: 8px;
  border-left: 4px solid #3498db;
}

.info-box h4 {
  margin: 0 0 15px 0;
  color: #2c3e50;
  font-size: 1rem;
}

.info-box ul {
  margin: 0;
  padding-left: 20px;
  color: #666;
  font-size: 0.9rem;
  line-height: 1.8;
}

.info-box li {
  margin-bottom: 8px;
}

.info-box strong {
  color: #2c3e50;
}

/* Mobile responsive styles */
@media (max-width: 768px) {
  .page-header {
    margin-bottom: 20px;
  }
  
  .page-title {
    font-size: 1.4rem;
  }
  
  .config-card {
    padding: 20px 15px;
  }
  
  .form-group {
    margin-bottom: 15px;
  }
  
  .form-input {
    font-size: 0.9rem;
    padding: 8px 10px;
  }
  
  .action-buttons {
    flex-direction: column;
    gap: 10px;
  }
  
  .btn {
    width: 100%;
  }
  
  .info-box {
    padding: 15px;
    font-size: 0.85rem;
  }
  
  .info-box ul {
    padding-left: 15px;
  }
  
  .password-input-wrapper .form-input {
    padding-right: 70px;
  }
  
  .clear-btn {
    font-size: 0.75rem;
    padding: 4px 8px;
  }
}
</style>
