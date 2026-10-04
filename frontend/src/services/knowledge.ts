import Taro from '@tarojs/taro'
import { API_BASE_URL, ApiError, refreshAuth, requestKnowledge } from '@/services/api'
import type { RequestControl } from '@/services/api'
import { getAuth } from '@/store/auth'
import type { ApiEnvelope, QuizGenerationTask } from '@/types/api'
import type { DocumentPreview, KnowledgeBase, KnowledgeCapabilities, KnowledgeDocument, KnowledgeFile,
  KnowledgeScope, KnowledgeTask, OriginalDraft, OriginalDraftItem, QuestionBank } from '@/types/knowledge'

const prefix = '/api/v1'
const encoded = encodeURIComponent
export const KNOWLEDGE_POLL_MS = 5000
export const knowledgeRequestId = () => `knowledge_${Date.now()}_${Math.random().toString(36).slice(2, 12)}`
const ownerId = () => getAuth().user?.user_id || ''
function checkOwner(owner: string) { if (!owner || owner !== ownerId()) throw new ApiError('账号已经变化，请重新打开页面') }
function checkControl(control?: RequestControl) { if (control?.cancelled) throw new ApiError('你已暂停等待，任务会在后台继续') }

export const getKnowledgeCapabilities = () => requestKnowledge<KnowledgeCapabilities>(`${prefix}/knowledge-bases/capabilities`)
export const listKnowledgeBases = (page = 1) => requestKnowledge<{ items: KnowledgeBase[]; total: number }>(`${prefix}/knowledge-bases?page=${page}`)
export const createKnowledgeBase = (name: string, description = '') => requestKnowledge<KnowledgeBase>(`${prefix}/knowledge-bases`, 'POST', { name, description })
export const getKnowledgeBase = (id: string) => requestKnowledge<KnowledgeBase>(`${prefix}/knowledge-bases/${encoded(id)}`)
export const patchKnowledgeBase = (id: string, name: string, description: string) => requestKnowledge<KnowledgeBase>(`${prefix}/knowledge-bases/${encoded(id)}`, 'PATCH', { name, description })
export const listDocumentBanks = (id: string, page = 1) => requestKnowledge<{ items: { bank_id: string; title: string; question_count: number; draft_revision: number; is_current_version: boolean }[]; total: number }>(`${prefix}/knowledge-documents/${encoded(id)}/question-banks?page=${page}`)
export const deleteKnowledgeBase = (id: string) => requestKnowledge(`${prefix}/knowledge-bases/${encoded(id)}`, 'DELETE')
export const listKnowledgeDocuments = (id: string, page = 1) => requestKnowledge<{ items: KnowledgeDocument[]; total: number }>(`${prefix}/knowledge-bases/${encoded(id)}/documents?page=${page}`)
export const getKnowledgeDocument = (id: string) => requestKnowledge<KnowledgeDocument>(`${prefix}/knowledge-documents/${encoded(id)}`)
export const deleteKnowledgeDocument = (id: string) => requestKnowledge(`${prefix}/knowledge-documents/${encoded(id)}`, 'DELETE')
export const previewKnowledgeDocument = (id: string, offset = 0) => requestKnowledge<DocumentPreview>(`${prefix}/knowledge-documents/${encoded(id)}/preview?offset=${offset}&limit=4000`)
export const saveKnowledgeText = (baseId: string, title: string, text: string, requestId: string, control?: RequestControl) => requestKnowledge<KnowledgeTask>(`${prefix}/knowledge-bases/${encoded(baseId)}/text-documents`, 'POST', { title, text, request_id: requestId }, control)
export const getKnowledgeTask = (id: string, control?: RequestControl) => requestKnowledge<KnowledgeTask>(`${prefix}/knowledge-processing-tasks/${encoded(id)}`, 'GET', undefined, control)
export const listKnowledgeCleanup = (baseId = '', page = 1) => requestKnowledge<{ items: KnowledgeTask[]; total: number }>(`${prefix}/knowledge-processing-tasks/cleanup?page=${page}${baseId ? '&base_id='+encoded(baseId) : ''}`)
export const recoverKnowledgeTask = (requestId: string, control?: RequestControl) => requestKnowledge<KnowledgeTask>(`${prefix}/knowledge-processing-tasks/by-request/${encoded(requestId)}`, 'GET', undefined, control)
export const retryKnowledgeDocument = (id: string, requestId: string) => requestKnowledge<KnowledgeTask>(`${prefix}/knowledge-documents/${encoded(id)}/processing-tasks`, 'POST', { request_id: requestId })
export const retryKnowledgeTask = (id: string, requestId: string) => requestKnowledge<KnowledgeTask>(`${prefix}/knowledge-processing-tasks/${encoded(id)}/retry`, 'POST', { request_id: requestId })
export const cancelKnowledgeTask = (id: string) => requestKnowledge<KnowledgeTask>(`${prefix}/knowledge-processing-tasks/${encoded(id)}/cancel`, 'POST')
export const patchKnowledgeChapters = (id: string, versionId: string, chapters: { title: string; level: number; start_offset: number; end_offset: number }[]) => requestKnowledge<KnowledgeTask>(`${prefix}/knowledge-documents/${encoded(id)}/chapters`, 'PATCH', { version_id: versionId, chapters })
export const createOriginalImport = (id: string, versionId: string, chapterIds: string[] | null, requestId: string) => requestKnowledge<KnowledgeTask>(`${prefix}/knowledge-documents/${encoded(id)}/question-import-tasks`, 'POST', { version_id: versionId, chapter_ids: chapterIds, request_id: requestId })
export const getOriginalDraft = (id: string, page = 1, coveragePage = 1) => requestKnowledge<OriginalDraft>(`${prefix}/question-imports/${encoded(id)}?page=${page}&coverage_page=${coveragePage}`)
export const editOriginalDraft = (id: string, revision: number, items: OriginalDraftItem[]) => requestKnowledge<OriginalDraft>(`${prefix}/question-imports/${encoded(id)}`, 'PATCH', { revision, items })
export const confirmOriginalDraft = (id: string, revision: number, requestId: string) => requestKnowledge<QuestionBank>(`${prefix}/question-imports/${encoded(id)}/confirm`, 'POST', { revision, request_id: requestId })
export const getQuestionBank = (id: string, chapterIds: string[] | null = null) => {
  if (chapterIds?.length === 0) return Promise.reject(new ApiError('请至少选择一个章节'))
  return requestKnowledge<QuestionBank>(`${prefix}/question-banks/${encoded(id)}${chapterIds ? '?'+chapterIds.map(c => `chapter_ids=${encoded(c)}`).join('&') : ''}`)
}
export const createOriginalPractice = (id: string, groupIndex: number, chapterIds: string[] | null, requestId: string) => requestKnowledge<KnowledgeTask>(`${prefix}/question-banks/${encoded(id)}/practice-tasks`, 'POST', { group_index: groupIndex, chapter_ids: chapterIds, request_id: requestId })
export const createKnowledgeQuiz = (userInput: string, scope: KnowledgeScope, enabled: boolean, publicTopic: string, confirmed: boolean, requestId: string, control?: RequestControl) => requestKnowledge<QuizGenerationTask>(`${prefix}/quizzes/generation-tasks`, 'POST', { user_input: userInput, knowledge_scope: scope, enable_web_search: enabled, public_search_topic: enabled ? publicTopic : null, public_search_confirmed: enabled && confirmed, request_id: requestId }, control)
export const getPrivateQuizTask = (id: string, control?: RequestControl) => requestKnowledge<QuizGenerationTask>(`${prefix}/quizzes/generation-tasks/${encoded(id)}`, 'GET', undefined, control)

export interface KnowledgePending { requestId: string; kind: 'upload' | 'text' | 'import' | 'practice' | 'generate' | 'chapters' | 'retry' | 'cleanup'; baseId?: string; documentId?: string; taskId?: string; bankId?: string; payload?: Record<string, unknown> }
const pendingKey = () => `bamboo_knowledge_pending_v1_${ownerId()}`
export function saveKnowledgePending(pending: KnowledgePending) { if (ownerId()) Taro.setStorageSync(pendingKey(), pending) }
export function getKnowledgePending(): KnowledgePending | null { const pending = Taro.getStorageSync<KnowledgePending>(pendingKey()); return pending?.requestId ? pending : null }
export function clearKnowledgePending() { Taro.removeStorageSync(pendingKey()) }

export function validateKnowledgeFile(file: Pick<KnowledgeFile, 'name' | 'size'>, maxBytes = 31457280) {
  if (!/\.(pdf|docx|md|markdown|txt)$/i.test(file.name)) throw new ApiError('系统只支持 PDF、DOCX、Markdown 和 TXT')
  if (file.size <= 0 || file.size > maxBytes) throw new ApiError('文件不能为空，且每个文件不能超过 30 MB')
}
export async function chooseKnowledgeFile(maxBytes = 31457280): Promise<KnowledgeFile> {
  let file: KnowledgeFile
  if (process.env.TARO_ENV === 'h5') {
    file = await new Promise<KnowledgeFile>((resolve, reject) => {
      const input = document.createElement('input'); input.type = 'file'; input.accept = '.pdf,.docx,.md,.markdown,.txt'
      input.onchange = () => { const selected = input.files?.[0]; input.remove(); if (!selected) reject(new ApiError('你已取消选择')); else resolve({ name: selected.name, size: selected.size, file: selected }) }
      input.addEventListener('cancel', () => { input.remove(); reject(new ApiError('你已取消选择')) }, { once: true })
      input.style.display = 'none'; document.body.appendChild(input); input.click()
    })
  } else {
    const result = await Taro.chooseMessageFile({ count: 1, type: 'file', extension: ['pdf', 'docx', 'md', 'markdown', 'txt'] })
    const chosen = result.tempFiles[0]; if (!chosen) throw new ApiError('你已取消选择')
    file = { name: chosen.name, size: chosen.size, path: chosen.path }
  }
  validateKnowledgeFile(file, maxBytes)
  return file
}

export async function uploadKnowledgeDocument(baseId: string, file: KnowledgeFile, requestId: string, control?: RequestControl): Promise<KnowledgeTask> {
  validateKnowledgeFile(file)
  const owner = ownerId()
  for (let attempt = 0; attempt < 2; attempt++) {
    checkOwner(owner); checkControl(control)
    let status: number, body: string
    if (process.env.TARO_ENV === 'h5') {
      if (!file.file) throw new ApiError('请重新选择原文件')
      const form = new FormData(); form.append('file', file.file, file.name); form.append('filename', file.name); form.append('request_id', requestId)
      const controller = new AbortController(), abort = { abort: () => controller.abort() }
      const timer = setTimeout(() => controller.abort(), 60000)
      if (control) control.task = abort
      try { const response = await fetch(`${API_BASE_URL}${prefix}/knowledge-bases/${encoded(baseId)}/documents`, { method: 'POST', body: form, headers: { Authorization: `Bearer ${getAuth().accessToken}` }, signal: controller.signal }); status = response.status; body = await response.text() }
      finally { clearTimeout(timer); if (control?.task === abort) control.task = undefined }
    } else {
      if (!file.path) throw new ApiError('请重新选择原文件')
      const task = Taro.uploadFile({ url: `${API_BASE_URL}${prefix}/knowledge-bases/${encoded(baseId)}/documents`, filePath: file.path, name: 'file', formData: { request_id: requestId, filename: file.name }, timeout: 60000, header: { Authorization: `Bearer ${getAuth().accessToken}` } })
      if (control) control.task = task
      try { const response = await task; status = response.statusCode; body = response.data }
      finally { if (control?.task === task) control.task = undefined }
    }
    checkOwner(owner); checkControl(control)
    if (status === 401 && attempt === 0) { await refreshAuth(); continue }
    let envelope: ApiEnvelope<KnowledgeTask>
    try { envelope = JSON.parse(body) } catch { throw new ApiError('上传响应无法读取，请用原请求编号恢复') }
    if (status < 200 || status >= 300 || envelope.code !== 0 || !envelope.data) throw new ApiError(envelope.message || '上传失败，请稍后重试', envelope.code)
    return envelope.data
  }
  throw new ApiError('登录已失效，请重新登录')
}

function pause(control?: RequestControl): Promise<void> {
  return new Promise((resolve, reject) => {
    checkControl(control)
    const timer = setTimeout(() => { if (control) control.cancelWait = undefined; resolve() }, KNOWLEDGE_POLL_MS)
    if (control) control.cancelWait = () => { clearTimeout(timer); control.cancelWait = undefined; reject(new ApiError('你已暂停等待，任务会在后台继续')) }
  })
}
async function poll<T extends KnowledgeTask | QuizGenerationTask>(read: (control?: RequestControl) => Promise<T>, control?: RequestControl, onStatus?: (task: T) => void): Promise<T> {
  const owner = ownerId()
  let failures = 0
  while (true) {
    checkOwner(owner); checkControl(control)
    let task: T
    try { task = await read(control); failures = 0 }
    catch (error) { checkOwner(owner); checkControl(control); if (++failures >= 3) throw error; await pause(control); continue }
    checkOwner(owner); checkControl(control); onStatus?.(task)
    if (task.status === 'succeeded') return task
    if (task.status === 'failed') throw new ApiError(task.error?.message || '资料处理失败，请检查材料后重试')
    await pause(control)
  }
}
export const pollKnowledgeTask = (taskId: string, control?: RequestControl, onStatus?: (task: KnowledgeTask) => void) => poll(c => getKnowledgeTask(taskId, c), control, onStatus)
export const pollPrivateQuizTask = (taskId: string, control?: RequestControl, onStatus?: (task: QuizGenerationTask) => void) => poll(c => getPrivateQuizTask(taskId, c), control, onStatus)
