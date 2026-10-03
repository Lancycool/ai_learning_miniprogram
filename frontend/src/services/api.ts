import Taro from '@tarojs/taro'
import { clearAuth, getAuth, saveAuth, updateUser } from '@/store/auth'
import type { AnswerResult, ApiEnvelope, CompletionResult, HistoryItem, LearningOverview, LoginData, Quiz, Report, UserProfile } from '@/types/api'

const API_BASE_URL = process.env.TARO_APP_API_BASE_URL || 'http://127.0.0.1:8000'
export class ApiError extends Error { constructor(message: string, public code = -1) { super(message); this.name = 'ApiError' } }
let refreshPromise: Promise<void> | null = null
let loginPromise: Promise<UserProfile> | null = null

async function raw<T>(path: string, method: 'GET' | 'POST' | 'PATCH' = 'GET', data?: unknown, authenticated = true, retry = true): Promise<T> {
  const token = getAuth().accessToken
  try {
    const response = await Taro.request<ApiEnvelope<T>>({ url: `${API_BASE_URL}${path}`, method, data, timeout: 60_000, header: { 'content-type': 'application/json', ...(authenticated && token ? { Authorization: `Bearer ${token}` } : {}) } })
    const envelope = response.data
    if (response.statusCode === 401 && authenticated && retry && getAuth().refreshToken) { await refreshAuth(); return raw<T>(path, method, data, authenticated, false) }
    if (response.statusCode < 200 || response.statusCode >= 300 || envelope.code !== 0 || envelope.data == null) throw new ApiError(envelope.message || '请求失败，请稍后重试', envelope.code)
    return envelope.data
  } catch (error) { if (error instanceof ApiError) throw error; throw new ApiError('网络连接失败，请检查后重试') }
}

async function refreshAuth(): Promise<void> {
  if (!refreshPromise) refreshPromise = raw<LoginData>('/api/v1/auth/refresh', 'POST', { refresh_token: getAuth().refreshToken }, false, false).then(saveAuth).catch((error) => { clearAuth(); throw error }).finally(() => { refreshPromise = null })
  return refreshPromise
}
export async function ensureLogin(): Promise<UserProfile> {
  if (getAuth().accessToken && getAuth().user) return getAuth().user!
  if (!loginPromise) {
    loginPromise = Taro.login({ timeout: 10000 }).then(async (result) => {
      if (!result.code) throw new ApiError('没有取得微信登录凭证，请重试')
      const data = await raw<LoginData>('/api/v1/auth/wechat-login', 'POST', { code: result.code }, false)
      saveAuth(data)
      return data.user
    }).finally(() => { loginPromise = null })
  }
  return loginPromise
}
export async function logout(): Promise<void> { try { if (getAuth().accessToken) await raw('/api/v1/auth/logout', 'POST') } finally { clearAuth() } }
export function getMe(): Promise<UserProfile> { return raw('/api/v1/users/me') }
export async function updateProfile(nickname: string): Promise<UserProfile> { const user = await raw<UserProfile>('/api/v1/users/me', 'PATCH', { nickname }); updateUser(user); return user }
export async function uploadAvatar(filePath: string): Promise<UserProfile> { const response = await Taro.uploadFile({ url: `${API_BASE_URL}/api/v1/users/me/avatar`, filePath, name: 'file', header: { Authorization: `Bearer ${getAuth().accessToken}` } }); const envelope = JSON.parse(response.data) as ApiEnvelope<UserProfile>; if (response.statusCode < 200 || response.statusCode >= 300 || !envelope.data) throw new ApiError(envelope.message || '头像上传失败', envelope.code); updateUser(envelope.data); return envelope.data }
export function assetUrl(path: string): string { return path.startsWith('/avatars/') ? `${API_BASE_URL}${path}` : path }
export async function generateQuiz(userInput: string): Promise<Quiz> { await ensureLogin(); return raw('/api/v1/quizzes/generate', 'POST', { user_input: userInput, question_count: 5, difficulty: 'mixed' }) }
export function submitAnswer(attemptId: string, questionId: string, selectedAnswers: string[], durationMs: number, idempotencyKey: string): Promise<AnswerResult> { return raw(`/api/v1/attempts/${attemptId}/answers`, 'POST', { question_id: questionId, selected_answers: selectedAnswers, duration_ms: durationMs, idempotency_key: idempotencyKey }) }
export function completeAttempt(attemptId: string): Promise<CompletionResult> { return raw(`/api/v1/attempts/${attemptId}/complete`, 'POST') }
export function createAttempt(quizId: string, attemptType: 'normal'|'replay'='replay'): Promise<any> { return raw('/api/v1/attempts', 'POST', { quiz_id: quizId, attempt_type: attemptType }) }
export function generateReport(attemptId: string): Promise<Report> { return raw(`/api/v1/attempts/${attemptId}/report`, 'POST') }
export function getOverview(): Promise<LearningOverview> { return raw('/api/v1/learning/overview') }
export function getHistory(keyword = '', status = ''): Promise<HistoryItem[]> {
  const query = [keyword ? `keyword=${encodeURIComponent(keyword)}` : '', status ? `status=${encodeURIComponent(status)}` : ''].filter(Boolean).join('&')
  return raw(`/api/v1/learning/history${query ? `?${query}` : ''}`)
}
export function getAttempt(id: string): Promise<any> { return raw(`/api/v1/attempts/${id}`) }
export function getMistakes(): Promise<any> { return raw('/api/v1/mistakes') }
export function createReview(): Promise<any> { return raw('/api/v1/reviews', 'POST') }
export function getGarden(): Promise<any[]> { return raw('/api/v1/learning/garden') }
export function getMonthly(month: string): Promise<any> { return raw(`/api/v1/learning/monthly-report?month=${month}`) }
