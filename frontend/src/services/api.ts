import Taro from '@tarojs/taro'
import { clearAuth, getAuth, saveAuth, updateUser } from '@/store/auth'
import type { AnswerResult, ApiEnvelope, CompletionResult, HistoryItem, LearningOverview, LoginData, Quiz, QuizGenerationTask, Report, UserProfile } from '@/types/api'

export const API_BASE_URL = process.env.TARO_APP_API_BASE_URL || 'http://127.0.0.1:8000'
const QUIZ_REQUEST_TIMEOUT_MS = 60_000
const TASK_REQUEST_TIMEOUT_MS = 15_000
const QUIZ_TASK_POLL_INTERVAL_MS = 3_000
export class ApiError extends Error { constructor(message: string, public code = -1) { super(message); this.name = 'ApiError' } }
export interface KnowledgeTraceBadCase { bad_case_id: string; type: string; severity: string; status: string; details: Record<string, unknown>; created_at: string }
export interface KnowledgeTraceItem { trace_id: string; task_id: string; status: string; knowledge_base_id?: string; document_id?: string; version_id?: string; query?: string; retrievals: Array<Record<string, unknown>>; agent_events: Array<Record<string, unknown>>; selected_source_ids: string[]; validation: Record<string, unknown>; timings: Record<string, unknown>; error_code?: string; error_message?: string; created_at: string; bad_cases: KnowledgeTraceBadCase[] }
export interface KnowledgeTraceResult { items: KnowledgeTraceItem[]; total: number; page: number; page_size: number }
let refreshPromise: Promise<void> | null = null
let loginPromise: Promise<UserProfile> | null = null

export interface RequestControl { cancelled: boolean; task?: { abort(): void }; cancelWait?: () => void; cancel(): void }
export function createRequestControl(): RequestControl {
  return { cancelled: false, cancel() { this.cancelled = true; this.task?.abort(); this.cancelWait?.() } }
}

async function raw<T>(path: string, method: 'GET' | 'POST' | 'PATCH' | 'DELETE' = 'GET', data?: unknown, authenticated = true, retry = true, control?: RequestControl, expectedUserId?: string): Promise<T> {
  if (authenticated && !expectedUserId) expectedUserId = getAuth().user?.user_id
  const token = getAuth().accessToken
  try {
    if (control?.cancelled) throw new ApiError('用户已取消生成')
    if (expectedUserId && getAuth().user?.user_id !== expectedUserId) throw new ApiError('账号已经变化，请重新打开页面')
    const task = Taro.request<ApiEnvelope<T>>({ url: `${API_BASE_URL}${path}`, method, data, timeout: path.startsWith('/api/v1/quizzes/generation-tasks') ? TASK_REQUEST_TIMEOUT_MS : QUIZ_REQUEST_TIMEOUT_MS, header: { 'content-type': 'application/json', ...(authenticated && token ? { Authorization: `Bearer ${token}` } : {}) } })
    if (control) control.task = task
    let response: Awaited<typeof task>
    try { response = await task } finally { if (control?.task === task) control.task = undefined }
    if (control?.cancelled) throw new ApiError('用户已取消生成')
    if (expectedUserId && getAuth().user?.user_id !== expectedUserId) throw new ApiError('账号已经变化，请重新打开页面')
    const envelope = response.data
    if (response.statusCode === 401 && authenticated && retry && getAuth().refreshToken) { await refreshAuth(); return raw<T>(path, method, data, authenticated, false, control, expectedUserId) }
    if (response.statusCode < 200 || response.statusCode >= 300 || envelope.code !== 0 || envelope.data == null) throw new ApiError(envelope.message || '请求失败，请稍后重试', envelope.code)
    return envelope.data
  } catch (error) { if (error instanceof ApiError) throw error; throw new ApiError('网络连接失败，请检查后重试') }
}

export async function refreshAuth(): Promise<void> {
  if (!refreshPromise) {
    const previous = getAuth()
    refreshPromise = raw<LoginData>('/api/v1/auth/refresh', 'POST', { refresh_token: previous.refreshToken }, false, false).then(data => {
      if (getAuth().user?.user_id !== previous.user?.user_id || getAuth().refreshToken !== previous.refreshToken) throw new ApiError('账号已经变化，请重新打开页面')
      saveAuth(data)
    }).catch(error => { if (getAuth().user?.user_id === previous.user?.user_id && getAuth().refreshToken === previous.refreshToken) clearAuth(); throw error }).finally(() => { refreshPromise = null })
  }
  return refreshPromise
}
export function requestKnowledge<T>(path: string, method: 'GET' | 'POST' | 'PATCH' | 'DELETE' = 'GET', data?: unknown, control?: RequestControl): Promise<T> {
  const owner = getAuth().user?.user_id
  if (!owner) return Promise.reject(new ApiError('请先登录'))
  return raw<T>(path, method, data, true, true, control, owner)
}
export async function getKnowledgeTraces(maintenanceKey: string, params: { taskId?: string; documentId?: string; status?: string; caseType?: string; page?: number; pageSize?: number } = {}): Promise<KnowledgeTraceResult> {
  const query = new URLSearchParams()
  if (params.taskId) query.set('task_id', params.taskId)
  if (params.documentId) query.set('document_id', params.documentId)
  if (params.status) query.set('status', params.status)
  if (params.caseType) query.set('case_type', params.caseType)
  query.set('page', String(params.page || 1)); query.set('page_size', String(params.pageSize || 20))
  try {
    const response = await Taro.request<ApiEnvelope<KnowledgeTraceResult>>({
      url: `${API_BASE_URL}/api/v1/maintenance/knowledge-traces?${query.toString()}`,
      method: 'GET', timeout: QUIZ_REQUEST_TIMEOUT_MS,
      header: { 'content-type': 'application/json', 'X-Knowledge-Trace-Key': maintenanceKey.trim() },
    })
    const envelope = response.data
    if (response.statusCode < 200 || response.statusCode >= 300 || envelope.code !== 0 || envelope.data == null) throw new ApiError(envelope.message || '维护数据查询失败，请检查密钥')
    return envelope.data
  } catch (error) { if (error instanceof ApiError) throw error; throw new ApiError('维护数据查询失败，请检查网络') }
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
export interface PendingGeneration { requestId: string; taskId?: string; userInput: string; enableWebSearch: boolean }
function pendingKey(): string { return `bamboo_generation_v1_${getAuth().user?.user_id || 'anonymous'}` }
export function getPendingGeneration(): PendingGeneration | null {
  const pending = Taro.getStorageSync<PendingGeneration>(pendingKey())
  return pending && typeof pending.requestId === 'string' && typeof pending.userInput === 'string' ? pending : null
}
function pausePolling(milliseconds: number, control?: RequestControl): Promise<void> {
  return new Promise((resolve, reject) => {
    if (control?.cancelled) { reject(new ApiError('用户已暂停等待')); return }
    const cleanup = () => { clearTimeout(timer); if (control) control.cancelWait = undefined }
    const timer = setTimeout(() => { cleanup(); resolve() }, milliseconds)
    if (control) control.cancelWait = () => { cleanup(); reject(new ApiError('用户已暂停等待')) }
  })
}
export function getQuizGenerationTask(taskId: string, control?: RequestControl): Promise<QuizGenerationTask> {
  return raw(`/api/v1/quizzes/generation-tasks/${encodeURIComponent(taskId)}`, 'GET', undefined, true, true, control)
}
export async function generateQuiz(userInput: string, enableWebSearch = true, control?: RequestControl, onStatus?: (task: QuizGenerationTask) => void): Promise<Quiz> {
  await ensureLogin()
  if (control?.cancelled) throw new ApiError('用户已暂停等待')
  const key = pendingKey()
  const pending = getPendingGeneration() || { requestId: `req_${Date.now()}_${Math.random().toString(36).slice(2)}`, userInput, enableWebSearch }
  // Save the request identifier before POST. A lost response can be retried safely.
  Taro.setStorageSync(key, pending)
  let task: QuizGenerationTask
  try {
    task = pending.taskId
      ? await getQuizGenerationTask(pending.taskId, control)
      : await raw<QuizGenerationTask>('/api/v1/quizzes/generation-tasks', 'POST', { request_id: pending.requestId, user_input: pending.userInput, question_count: 5, difficulty: 'mixed', enable_web_search: pending.enableWebSearch }, true, true, control)
  } catch (error) {
    if (error instanceof ApiError && [4001, 4002, 4040, 4090].includes(error.code)) Taro.removeStorageSync(key)
    throw error
  }
  pending.taskId = task.task_id
  Taro.setStorageSync(key, pending)
  let failures = 0
  while (true) {
    if (control?.cancelled) throw new ApiError('用户已暂停等待')
    onStatus?.(task)
    if (task.status === 'failed') { Taro.removeStorageSync(key); throw new ApiError(task.error?.message || '题目生成失败，请稍后重试') }
    if (task.status === 'succeeded') {
      if (!task.result) throw new ApiError('任务已完成，但系统没有取得题库')
      Taro.removeStorageSync(key)
      return task.result
    }
    await pausePolling(Math.min(10_000, Math.max(1000, task.poll_after_ms || QUIZ_TASK_POLL_INTERVAL_MS)), control)
    try { task = await getQuizGenerationTask(task.task_id, control); failures = 0 }
    catch (error) {
      if (control?.cancelled) throw error
      if (error instanceof ApiError && error.code === 4040) { Taro.removeStorageSync(key); throw error }
      if (++failures >= 3 || (error instanceof ApiError && error.code === 4010)) throw new ApiError('系统暂时无法查询任务。任务仍会继续，你可以稍后重新查看。')
    }
  }
}
export function submitAnswer(attemptId: string, questionId: string, selectedAnswers: string[], durationMs: number, idempotencyKey: string): Promise<AnswerResult> { return raw(`/api/v1/attempts/${attemptId}/answers`, 'POST', { question_id: questionId, selected_answers: selectedAnswers, duration_ms: durationMs, idempotency_key: idempotencyKey }) }
export function completeAttempt(attemptId: string): Promise<CompletionResult> { return raw(`/api/v1/attempts/${attemptId}/complete`, 'POST') }
export function createAttempt(quizId: string, attemptType: 'normal'|'replay'='replay'): Promise<any> { return raw('/api/v1/attempts', 'POST', { quiz_id: quizId, attempt_type: attemptType }) }
export function generateReport(attemptId: string): Promise<Report> { return raw(`/api/v1/attempts/${attemptId}/report`, 'POST') }
export function getOverview(): Promise<LearningOverview> { return raw('/api/v1/learning/overview') }
export function getHistory(keyword = '', status = ''): Promise<HistoryItem[]> {
  const query = [keyword ? `keyword=${encodeURIComponent(keyword)}` : '', status ? `status=${encodeURIComponent(status)}` : ''].filter(Boolean).join('&')
  return raw(`/api/v1/learning/history${query ? `?${query}` : ''}`)
}
export function getAttempt(id: string): Promise<import('@/types/api').LearningAttemptDetail> { return raw(`/api/v1/attempts/${id}`) }
export function getMistakes(): Promise<any> { return raw('/api/v1/mistakes') }
export function createReview(): Promise<any> { return raw('/api/v1/reviews', 'POST') }
export function getGarden(): Promise<any[]> { return raw('/api/v1/learning/garden') }
export function getMonthly(month: string): Promise<any> { return raw(`/api/v1/learning/monthly-report?month=${month}`) }
