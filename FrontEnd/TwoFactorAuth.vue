<script setup>
import { ref, watch } from 'vue'

const props = defineProps({
  show: {
    type: Boolean,
    default: false
  },
  userEmail: {
    type: String,
    default: ''
  }
})

const emit = defineEmits(['close', 'verified'])

const verificationCode = ref('')
const sendingCode = ref(false)
const verifying = ref(false)
const codeSent = ref(false)
const errorMsg = ref('')
const countdown = ref(0)

const API_BASE = 'http://127.0.0.1:8000'

// Watch show status, reset state
watch(() => props.show, (newVal) => {
  if (newVal) {
    resetState()
  }
})

const resetState = () => {
  verificationCode.value = ''
  sendingCode.value = false
  verifying.value = false
  codeSent.value = false
  errorMsg.value = ''
  countdown.value = 0
}

const sendCode = async () => {
  sendingCode.value = true
  errorMsg.value = ''
  
  try {
    const token = localStorage.getItem('token')
    const res = await fetch(`${API_BASE}/api/2fa/send-code`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${token}`
      }
    })
    
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || 'Failed to send verification code')
    }
    
    // Successfully sent, switch to verification code input interface
    codeSent.value = true
    startCountdown()
    // Clear previous verification code input
    verificationCode.value = ''
  } catch (e) {
    errorMsg.value = e.message || 'Failed to send verification code, please try again later'
  } finally {
    sendingCode.value = false
  }
}

const startCountdown = () => {
  countdown.value = 60
  const timer = setInterval(() => {
    countdown.value--
    if (countdown.value <= 0) {
      clearInterval(timer)
    }
  }, 1000)
}

const verifyCode = async () => {
  if (!verificationCode.value || verificationCode.value.length !== 6) {
    errorMsg.value = 'Please enter a 6-digit verification code'
    return
  }
  
  verifying.value = true
  errorMsg.value = ''
  
  try {
    const token = localStorage.getItem('token')
    const res = await fetch(`${API_BASE}/api/2fa/verify-code`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify({
        code: verificationCode.value
      })
    })
    
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || 'Invalid or expired verification code')
    }
    
    // Verification successful, notify parent component
    emit('verified', verificationCode.value)
  } catch (e) {
    errorMsg.value = e.message || 'Invalid or expired verification code, please request a new one'
    verificationCode.value = ''
  } finally {
    verifying.value = false
  }
}

const handleClose = () => {
  resetState()
  emit('close')
}

// Restrict input to numbers only
const handleInput = (e) => {
  const value = e.target.value.replace(/\D/g, '').slice(0, 6)
  verificationCode.value = value
}
</script>

<template>
  <div v-if="show" class="modal-overlay" @click="handleClose">
    <div class="modal-card" @click.stop>
      <button class="close-btn" @click="handleClose">×</button>
      
      <div class="modal-header">
        <div class="modal-icon">🔐</div>
        <h3>Two-Factor Authentication</h3>
        <p class="subtitle">Please complete two-factor authentication for your account security</p>
      </div>
      
      <div class="modal-body">
        <!-- Step 1: Send verification code -->
        <div v-if="!codeSent" class="step-one">
          <p class="info-text">For your account security, we need to verify your identity</p>
          <p class="info-text-small">Verification code will be sent to:</p>
          <p v-if="userEmail" class="email-display">{{ userEmail }}</p>
          <p v-else class="email-display loading-email">Loading email address...</p>
          <button 
            class="send-btn" 
            @click="sendCode" 
            :disabled="sendingCode || countdown > 0 || !userEmail"
          >
            {{ sendingCode ? 'Sending...' : countdown > 0 ? `Resend (${countdown}s)` : 'Send Verification Code' }}
          </button>
          <p class="hint-text">After clicking, please check your email for the 6-digit verification code</p>
        </div>
        
        <!-- Step 2: Enter verification code -->
        <div v-else class="step-two">
          <div class="success-icon">✓</div>
          <p class="info-text success-text">Verification code sent to your email</p>
          <p class="info-text-small">Please enter the 6-digit verification code:</p>
          <input 
            v-model="verificationCode"
            @input="handleInput"
            @keyup.enter="verifyCode"
            type="text"
            class="code-input"
            placeholder="000000"
            maxlength="6"
            :disabled="verifying"
            autofocus
          />
          <button 
            class="verify-btn" 
            @click="verifyCode" 
            :disabled="verifying || verificationCode.length !== 6"
          >
            {{ verifying ? 'Verifying...' : 'Complete Verification' }}
          </button>
          <button 
            class="resend-btn" 
            @click="sendCode" 
            :disabled="sendingCode || countdown > 0"
          >
            {{ sendingCode ? 'Sending...' : countdown > 0 ? `Resend (${countdown}s)` : 'Resend Verification Code' }}
          </button>
        </div>
        
        <div v-if="errorMsg" class="error-msg">{{ errorMsg }}</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background: rgba(0, 0, 0, 0.6);
  backdrop-filter: blur(4px);
  display: flex;
  justify-content: center;
  align-items: center;
  z-index: 2000;
  animation: fadeIn 0.2s ease;
}

.modal-card {
  background: white;
  width: 400px;
  border-radius: 16px;
  padding: 0;
  box-shadow: 0 25px 50px rgba(0, 0, 0, 0.2);
  position: relative;
  animation: slideUp 0.3s ease;
  overflow: hidden;
}

.close-btn {
  position: absolute;
  top: 15px;
  right: 15px;
  background: none;
  border: none;
  font-size: 1.5rem;
  cursor: pointer;
  color: #999;
  z-index: 10;
  width: 30px;
  height: 30px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  transition: background 0.2s;
}

.close-btn:hover {
  background: #f5f5f5;
}

.modal-header {
  padding: 30px;
  text-align: center;
  background: #fcfcfc;
  border-bottom: 1px solid #eee;
}

.modal-icon {
  font-size: 3rem;
  margin-bottom: 15px;
}

.modal-header h3 {
  margin: 0 0 10px 0;
  font-size: 1.5rem;
  color: #2c3e50;
}

.subtitle {
  color: #888;
  font-size: 0.9rem;
  margin: 0;
}

.modal-body {
  padding: 30px;
}

.step-one,
.step-two {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.info-text {
  color: #333;
  font-size: 1rem;
  text-align: center;
  margin: 0 0 10px 0;
  font-weight: 500;
}

.info-text-small {
  color: #888;
  font-size: 0.85rem;
  text-align: center;
  margin: 0 0 15px 0;
}

.info-text.success-text {
  color: #27ae60;
  font-weight: 600;
}

.email-display {
  background: #f8f9fa;
  padding: 15px;
  border-radius: 8px;
  color: #2c3e50;
  font-weight: 500;
  text-align: center;
  margin: 0 0 20px 0;
  border: 1px solid #e0e0e0;
}

.email-display.loading-email {
  color: #999;
  font-style: italic;
}

.hint-text {
  color: #999;
  font-size: 0.8rem;
  text-align: center;
  margin: 10px 0 0 0;
}

.success-icon {
  width: 60px;
  height: 60px;
  background: #27ae60;
  color: white;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 2rem;
  font-weight: bold;
  margin: 0 auto 20px;
  animation: scaleIn 0.3s ease;
}

.send-btn,
.verify-btn {
  width: 100%;
  padding: 12px;
  background: #2c3e50;
  color: white;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  font-size: 1rem;
  font-weight: 500;
  transition: background 0.2s;
}

.send-btn:hover:not(:disabled),
.verify-btn:hover:not(:disabled) {
  background: #34495e;
}

.send-btn:disabled,
.verify-btn:disabled {
  background: #95a5a6;
  cursor: not-allowed;
}

.code-input {
  width: 100%;
  padding: 15px;
  font-size: 1.5rem;
  text-align: center;
  letter-spacing: 8px;
  border: 2px solid #ddd;
  border-radius: 8px;
  box-sizing: border-box;
  font-weight: 600;
  color: #2c3e50;
  transition: border-color 0.2s;
}

.code-input:focus {
  outline: none;
  border-color: #2c3e50;
}

.code-input:disabled {
  background: #f5f5f5;
  cursor: not-allowed;
}

.resend-btn {
  background: none;
  border: none;
  color: #2c3e50;
  cursor: pointer;
  font-size: 0.9rem;
  padding: 8px;
  text-decoration: underline;
  transition: color 0.2s;
}

.resend-btn:hover:not(:disabled) {
  color: #34495e;
}

.resend-btn:disabled {
  color: #ccc;
  cursor: not-allowed;
  text-decoration: none;
}

.error-msg {
  background: #ffebee;
  color: #c62828;
  padding: 12px;
  border-radius: 8px;
  font-size: 0.9rem;
  text-align: center;
  margin-top: 15px;
}

@keyframes fadeIn {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}

@keyframes slideUp {
  from {
    opacity: 0;
    transform: translateY(20px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@keyframes scaleIn {
  from {
    opacity: 0;
    transform: scale(0.5);
  }
  to {
    opacity: 1;
    transform: scale(1);
  }
}

@media (max-width: 480px) {
  .modal-card {
    width: 90%;
    max-width: 400px;
  }
}
</style>
