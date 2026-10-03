const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const ts = require('typescript')
const calls = []
let result = { statusCode: 202, data: { code: 0, data: { task_id: 'task_test', status: 'succeeded', result: { web_search: { status: 'fallback', context_used: false } } } } }
let aborts = 0
let pending = false
const storage = new Map()
const taro = { getStorageSync: (key) => storage.get(key), setStorageSync: (key, value) => storage.set(key, value), removeStorageSync: (key) => storage.delete(key), request(options) {
  calls.push(options)
  let reject
  const promise = pending ? new Promise((resolve, fail) => { reject = fail }) : Promise.resolve(result)
  promise.abort = () => { aborts++; reject?.(new Error('abort')) }
  return promise
} }
const exportsObject = {}
const compiled = ts.transpileModule(fs.readFileSync('src/services/api.ts', 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, esModuleInterop: true } }).outputText
vm.runInNewContext(compiled, { exports: exportsObject, process, require(name) {
  if (name === '@tarojs/taro') return taro
  if (name === '@/store/auth') return { getAuth: () => ({ accessToken: 'fake', user: { nickname: 'test' } }) }
  throw new Error(name)
} })
;(async () => {
  const quiz = await exportsObject.generateQuiz('HarnessEngineering', false)
  assert.equal(calls[0].data.enable_web_search, false)
  assert.equal(calls[0].timeout, 15000)
  assert(calls[0].url.endsWith('/quizzes/generation-tasks'))
  assert.equal(quiz.web_search.status, 'fallback')
  assert.equal(calls.length, 1, 'a search fallback must not repeat the generation request')
  await exportsObject.getMe()
  assert.equal(calls[1].timeout, 60000)
  const cancelled = exportsObject.createRequestControl()
  cancelled.cancel()
  await assert.rejects(exportsObject.generateQuiz('AI', true, cancelled))
  assert.equal(calls.length, 2, 'cancellation during login must prevent the generation request')
  pending = true
  const control = exportsObject.createRequestControl()
  const operation = exportsObject.generateQuiz('AI', true, control)
  await Promise.resolve(); await Promise.resolve()
  control.cancel()
  await assert.rejects(operation)
  assert.equal(aborts, 1)
  assert.equal(calls.length, 3)
  const componentExports = {}
  const component = ts.transpileModule(fs.readFileSync('src/components/WebSearchInfo.tsx', 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText
  vm.runInNewContext(component, { exports: componentExports, require(name) {
    if (name === '@tarojs/taro') return taro
    if (name === '@tarojs/components') return { Text: 'span', View: 'div' }
    if (name.endsWith('.scss')) return {}
    return require(name)
  } })
  const render = require('react-dom/server').renderToStaticMarkup
  const metadata = { status: 'success', context_used: true, sources: [{ source_id: 'src_1', title: 'Official source', url: 'https://example.com', content: 'hidden answer' }] }
  const before = render(componentExports.default({ metadata, completed: false }))
  assert(!before.includes('hidden answer') && !before.includes('Official source'))
  const after = render(componentExports.default({ metadata, completed: true }))
  assert(after.includes('hidden answer') && after.includes('复制来源链接'))
  assert(render(componentExports.default({})).includes('历史题库未记录搜索状态'))
  assert(render(componentExports.default({ metadata: { ...metadata, status: 'disabled' } })).includes('系统本次未开启联网搜索'))
  assert(render(componentExports.default({ metadata: { ...metadata, status: 'fallback', context_used: false } })).includes('题目由模型已有知识生成'))
  console.log('Web search request and cancellation checks passed')
})().catch((error) => { console.error(error); process.exitCode = 1 })
