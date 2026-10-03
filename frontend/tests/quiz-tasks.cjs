const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const ts = require('typescript')

const compiled = ts.transpileModule(fs.readFileSync('src/services/api.ts', 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, esModuleInterop: true } }).outputText
const quiz = { quiz_id: 'quiz_1', attempt_id: 'att_1', questions: [{ question_id: 'q1' }], web_search: { status: 'fallback' } }
const state = (status, extra = {}) => ({ task_id: 'task_1', status, poll_after_ms: 5000, error: null, result: status === 'succeeded' ? quiz : null, ...extra })
const response = (data) => ({ statusCode: 200, data: { code: 0, data } })

function harness(replies) {
  const storage = new Map(), calls = [], delays = [], timers = new Map()
  let nextTimer = 0, aborts = 0, active = 0, maxActive = 0, userId = 'usr_1', autoTimers = true
  const taro = {
    getStorageSync: (key) => storage.get(key),
    setStorageSync: (key, value) => storage.set(key, JSON.parse(JSON.stringify(value))),
    removeStorageSync: (key) => storage.delete(key),
    request(options) {
      calls.push(options)
      active++; maxActive = Math.max(active, maxActive)
      let rejectPending
      const reply = replies.shift()
      let operation = reply === 'pending' ? new Promise((_, reject) => { rejectPending = reject }) : reply instanceof Error ? Promise.reject(reply) : Promise.resolve(response(reply))
      operation = operation.finally(() => active--)
      operation.abort = () => { aborts++; rejectPending?.(new Error('abort')) }
      return operation
    }
  }
  const api = {}
  vm.runInNewContext(compiled, {
    exports: api, process,
    setTimeout(callback, ms) {
      const id = ++nextTimer
      timers.set(id, callback); delays.push(ms)
      if (autoTimers) queueMicrotask(() => { if (timers.has(id)) callback() })
      return id
    },
    clearTimeout: (id) => timers.delete(id),
    require(name) {
      if (name === '@tarojs/taro') return taro
      if (name === '@/store/auth') return { getAuth: () => ({ accessToken: 'fake', user: { user_id: userId } }) }
      throw new Error(name)
    }
  })
  return { api, calls, storage, delays, timers, replies, get aborts() { return aborts }, get maxActive() { return maxActive }, setUser(id) { userId = id }, pauseTimers() { autoTimers = false } }
}

async function flush() { for (let i = 0; i < 15; i++) await Promise.resolve() }

function pageHarness() {
  const hooks = {}, events = [], pending = { requestId: 'req_existing_123456', taskId: 'task_1', userInput: 'AI 原任务', enableWebSearch: false }
  let resolveGeneration
  const operation = new Promise((resolve) => { resolveGeneration = resolve })
  const taro = { navigateTo: async (options) => events.push(['navigate', options.url]) }
  const exported = {}
  const source = ts.transpileModule(fs.readFileSync('src/pages/index/index.tsx', 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText
  vm.runInNewContext(source, { exports: exported, require(name) {
    if (name === 'react') return { useState: (value) => [value, () => {}], useRef: (value) => ({ current: value }), useEffect: () => {} }
    if (name === '@tarojs/taro') return { __esModule: true, default: taro, useDidShow: (fn) => { hooks.show = fn }, useDidHide: (fn) => { hooks.hide = fn } }
    if (name === '@tarojs/components') return { Button: 'button', Image: 'img', Switch: 'input', Text: 'span', Textarea: 'textarea', View: 'div' }
    if (name === '@/services/api') return {
      ensureLogin: async () => ({ user_id: 'usr_1' }), getPendingGeneration: () => pending,
      ApiError: Error,
      createRequestControl: () => ({ cancelled: false, cancel() { this.cancelled = true; events.push(['pause']) } }),
      generateQuiz: (input, enabled) => { events.push(['generate', input, enabled]); return operation }
    }
    if (name === '@/store/session') return { clearSession: () => {}, startSession: (value) => events.push(['session', value.attempt_id]) }
    if (name === '@/store/auth') return { getAuth: () => ({ user: { user_id: 'usr_1' } }) }
    if (name === '@/store/navigation') return { setActiveTab: () => {} }
    if (name === '@/utils/navigation') return { useNavigationLayout: () => ({ statusBarHeight: 0, navigationBarHeight: 44, contentTop: 44, rightInset: 0 }) }
    if (name.endsWith('.scss') || name.endsWith('.svg')) return ''
    return require(name)
  } })
  exported.default()
  return { hooks, events, complete: () => resolveGeneration(quiz) }
}

;(async () => {
  const h = harness([state('queued'), state('running'), state('succeeded')])
  const statuses = []
  const result = await h.api.generateQuiz('AI', false, undefined, (task) => statuses.push(task.status))
  assert.equal(result.attempt_id, 'att_1')
  assert.deepEqual(statuses, ['queued', 'running', 'succeeded'])
  assert.deepEqual(h.calls.map((call) => call.method), ['POST', 'GET', 'GET'])
  assert(h.calls.every((call) => call.timeout === 15000))
  assert.equal(h.calls[0].data.enable_web_search, false)
  assert.deepEqual(h.delays, [5000, 5000])
  assert.equal(h.maxActive, 1, 'polling requests must never overlap')
  assert.equal(h.storage.size, 0)

  const paused = harness([state('queued')])
  paused.pauseTimers()
  const control = paused.api.createRequestControl()
  const operation = paused.api.generateQuiz('AI', true, control)
  await flush()
  assert.equal(paused.timers.size, 1)
  control.cancel()
  await assert.rejects(operation)
  assert.equal(paused.timers.size, 0)
  assert.equal(paused.aborts, 0, 'pausing a delay must not abort an already completed request')
  assert.equal(paused.api.getPendingGeneration().taskId, 'task_1')
  paused.setUser('usr_2')
  assert.equal(paused.api.getPendingGeneration(), null, 'pending tasks must be scoped to the account')
  paused.setUser('usr_1')
  paused.replies.push(state('succeeded'))
  assert.equal((await paused.api.generateQuiz('another topic')).quiz_id, 'quiz_1')
  assert.deepEqual(paused.calls.map((call) => call.method), ['POST', 'GET'], 'resuming must not create a new task')

  const lost = harness([new Error('response lost'), state('succeeded')])
  await assert.rejects(lost.api.generateQuiz('AI'))
  const id = lost.calls[0].data.request_id
  await lost.api.generateQuiz('different text')
  assert.equal(lost.calls[1].data.request_id, id)
  assert.equal(lost.calls[1].data.user_input, 'AI', 'retry must preserve the original payload')

  const transient = harness([state('queued'), new Error('offline'), state('running'), state('succeeded')])
  await transient.api.generateQuiz('AI')
  assert.equal(transient.calls.filter((call) => call.method === 'POST').length, 1)
  const offline = harness([state('queued'), ...Array.from({ length: 3 }, () => new Error('offline'))])
  await assert.rejects(offline.api.generateQuiz('AI'), /任务仍会继续/)
  assert.equal(offline.api.getPendingGeneration().taskId, 'task_1')

  const failed = harness([state('queued'), state('failed', { error: { code: 'task_timeout', message: '题目生成超时' } })])
  await assert.rejects(failed.api.generateQuiz('AI'), /题目生成超时/)
  assert.equal(failed.storage.size, 0, 'terminal failure must allow a fresh submission')

  const inflight = harness(['pending'])
  const inflightControl = inflight.api.createRequestControl()
  const inflightOperation = inflight.api.generateQuiz('AI', true, inflightControl)
  await flush()
  inflightControl.cancel()
  await assert.rejects(inflightOperation)
  assert.equal(inflight.aborts, 1)
  assert(inflight.api.getPendingGeneration().requestId, 'a cancelled POST may already have created a server task')

  const resumedPage = pageHarness()
  resumedPage.hooks.show()
  await flush()
  assert.deepEqual(resumedPage.events[0], ['generate', 'AI 原任务', false])
  assert(!resumedPage.events.some((event) => event[0] === 'navigate'), 'the page must wait for the task result')
  resumedPage.complete()
  await flush()
  assert.deepEqual(resumedPage.events.slice(1), [['session', 'att_1'], ['navigate', '/pages/quiz/index']])
  const hiddenPage = pageHarness()
  hiddenPage.hooks.show()
  await flush()
  hiddenPage.hooks.hide()
  hiddenPage.complete()
  await flush()
  assert(!hiddenPage.events.some((event) => event[0] === 'navigate' || event[0] === 'session'), 'a hidden page must ignore late task results')
  console.log('Quiz task polling, resume, idempotency and failure checks passed')
})().catch((error) => { console.error(error); process.exitCode = 1 })
