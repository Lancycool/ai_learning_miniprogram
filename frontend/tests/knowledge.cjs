const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const ts = require('typescript')

function harness(replies = [], environment = 'weapp') {
  const calls = [], delays = [], storage = new Map()
  let owner = 'user-one', active = 0, maxActive = 0, aborts = 0, refreshes = 0
  const taro = {
    getStorageSync: key => storage.get(key), setStorageSync: (key, value) => storage.set(key, JSON.parse(JSON.stringify(value))),
    removeStorageSync: key => storage.delete(key),
    uploadFile(options) {
      calls.push(options)
      const reply = replies.shift()
      let reject
      const operation = reply === 'pending' ? new Promise((_, fail) => { reject = fail }) : Promise.resolve(reply)
      operation.abort = () => { aborts++; reject?.(new Error('abort')) }
      return operation
    }
  }
  const exports = {}
  const compiled = ts.transpileModule(fs.readFileSync('src/services/knowledge.ts', 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, esModuleInterop: true }
  }).outputText
  vm.runInNewContext(compiled, { exports, process: { env: { TARO_ENV: environment } }, console,
    FormData: class { append(...args) { this.fields ||= []; this.fields.push(args) } }, AbortController,
    fetch: async (url, options) => { calls.push({ url, ...options }); const reply = replies.shift(); return { status: reply.statusCode, text: async () => reply.data } },
    setTimeout: (fn, ms) => { delays.push(ms); if (ms !== 60000) queueMicrotask(fn); return delays.length }, clearTimeout() {},
    require(name) {
      if (name === '@tarojs/taro') return taro
      if (name === '@/store/auth') return { getAuth: () => ({ accessToken: 'synthetic', user: { user_id: owner } }) }
      if (name === '@/services/api') return {
        API_BASE_URL: 'http://test', ApiError: class ApiError extends Error { constructor(message, code) { super(message); this.code = code } },
        refreshAuth: async () => { refreshes++ },
        requestKnowledge: async (path, method, data, control) => {
          calls.push({ path, method, data }); active++; maxActive = Math.max(active, maxActive)
          try { const reply = replies.shift(); if (reply instanceof Error) throw reply; return typeof reply === 'function' ? await reply() : reply }
          finally { active-- }
        }
      }
      throw new Error(name)
    }
  })
  return { api: exports, calls, delays, storage, setOwner: value => { owner = value },
    get maxActive() { return maxActive }, get aborts() { return aborts }, get refreshes() { return refreshes } }
}

const state = status => ({ task_id: 'task-one', status, stage: status, poll_after_ms: 5000,
  result: status === 'succeeded' ? { parsed: true } : null, error: null })
const control = () => ({ cancelled: false, cancel() { this.cancelled = true; this.task?.abort(); this.cancelWait?.() } })

;(async () => {
  const h = harness([state('running'), state('succeeded')])
  const result = await h.api.pollKnowledgeTask('task-one', control())
  assert.equal(result.status, 'succeeded')
  assert.deepEqual(h.delays, [5000])
  assert.equal(h.maxActive, 1)
  const upload = harness([{ statusCode: 401, data: JSON.stringify({ code: 4010 }) },
    { statusCode: 202, data: JSON.stringify({ code: 0, data: state('queued') }) }])
  await upload.api.uploadKnowledgeDocument('base-one', { name: 'notes.txt', size: 30, path: '/tmp/synthetic' }, 'request-upload-one', control())
  assert.equal(upload.refreshes, 1)
  assert.equal(upload.calls.length, 2)
  assert(upload.calls.every(call => call.formData.request_id === 'request-upload-one'))
  assert(upload.calls.every(call => call.header.Authorization === 'Bearer synthetic'))
  assert.throws(() => upload.api.validateKnowledgeFile({ name: 'video.mp4', size: 5 }), /PDF/)
  assert.throws(() => upload.api.validateKnowledgeFile({ name: 'large.pdf', size: 31457281 }), /30/)
  const switching = harness([() => { switching.setOwner('user-two'); return state('succeeded') }])
  await assert.rejects(switching.api.pollKnowledgeTask('task-one', control()), /账号/)
  const paused = harness([state('running')]); const stopped = control(); stopped.cancel()
  await assert.rejects(paused.api.pollKnowledgeTask('task-one', stopped), /暂停/)
  assert.equal(paused.calls.length, 0)
  const remembered = harness()
  remembered.api.saveKnowledgePending({ requestId: 'request-upload-one', kind: 'upload', baseId: 'base-one' })
  assert.equal(remembered.api.getKnowledgePending().requestId, 'request-upload-one')
  remembered.setOwner('user-two'); assert.equal(remembered.api.getKnowledgePending(), null)
  const lost = harness([state('queued')])
  const recovered = await lost.api.recoverKnowledgeTask('request-upload-one')
  assert.equal(recovered.task_id, 'task-one')
  assert(lost.calls[0].path.includes('/by-request/request-upload-one'))
  const twice = harness([{ statusCode: 401, data: JSON.stringify({ code: 4010 }) }, { statusCode: 401, data: JSON.stringify({ code: 4010, message: '登录失效' }) }])
  await assert.rejects(twice.api.uploadKnowledgeDocument('base', { name: 'notes.txt', size: 30, path: '/tmp/test' }, 'request-one', control()), /登录/)
  assert.equal(twice.refreshes, 1)
  const aborted = harness(['pending']), uploadControl = control()
  const inFlight = aborted.api.uploadKnowledgeDocument('base', { name: 'notes.txt', size: 30, path: '/tmp/test' }, 'request-one', uploadControl)
  uploadControl.cancel(); await assert.rejects(inFlight, /abort/); assert.equal(aborted.aborts, 1)
  const h5 = harness([{ statusCode: 202, data: JSON.stringify({ code: 0, data: state('queued') }) }], 'h5')
  await h5.api.uploadKnowledgeDocument('base', { name: '原题.md', size: 30, file: { synthetic: true } }, 'request-h5-one', control())
  assert(h5.calls[0].body.fields.some(field => field[0] === 'filename' && field[1] === '原题.md'))
  assert(h5.calls[0].body.fields.some(field => field[0] === 'request_id' && field[1] === 'request-h5-one'))
  const emptyScope = harness()
  await assert.rejects(emptyScope.api.getQuestionBank('bank-one', []), /至少选择/)
  assert.equal(emptyScope.calls.length, 0)
  let finish
  const late = harness([() => new Promise(resolve => { finish = resolve })]), waitControl = control()
  const query = late.api.pollKnowledgeTask('task-one', waitControl)
  waitControl.cancel(); finish(state('succeeded')); await assert.rejects(query, /暂停/)
  console.log('knowledge frontend tests passed')
})().catch(error => { console.error(error); process.exitCode = 1 })
