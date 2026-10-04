const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const ts = require('typescript')
const compile = path => ts.transpileModule(fs.readFileSync(path, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText

function flowHarness() {
  const hooks = {}, events = [], exported = {}
  let resolveSubmit, resolveLoad, owner = 'owner-one', doneCount = 0
  vm.runInNewContext(compile('src/pages/knowledge/shared.tsx'), { exports: exported, require(name) {
    if (name === 'react') return { useState: x => [x, () => {}], useRef: x => ({ current: x }), useEffect: fn => { hooks.dispose = fn() } }
    if (name === '@tarojs/taro') return { useDidHide: fn => { hooks.hide = fn }, useDidShow: fn => { hooks.show = fn } }
    if (name === '@/store/auth') return { getAuth: () => ({ user: { user_id: owner } }) }
    if (name === '@/utils/navigation') return {}
    if (name === '@/services/api') return { createRequestControl: () => ({ cancelled: false, cancel() { this.cancelled = true; events.push('cancel') } }) }
    if (name === '@/services/knowledge') return { saveKnowledgePending: p => events.push(p), clearKnowledgePending: () => events.push('clear') }
    if (name === 'react/jsx-runtime') return { jsx: () => null, jsxs: () => null }
    return {}
  } })
  const flow = exported.useKnowledgeFlow(async (_, valid) => { await new Promise(resolve => { resolveLoad = resolve }); if (valid()) doneCount++ })
  return { flow, hooks, events, submit: () => new Promise(resolve => { resolveSubmit = resolve }), resolve: () => resolveSubmit({ task_id: 'one', status: 'succeeded', document: { document_id: 'doc' } }), loaded: () => resolveLoad(), switchOwner: () => { owner = 'owner-two' }, get doneCount() { return doneCount } }
}
async function flush() { for (let i = 0; i < 10; i++) await Promise.resolve() }
function homeHarness(capability) {
  const values = [], hooks = {}, home = {}; let cursor = 0
  vm.runInNewContext(compile('src/pages/index/index.tsx'), { exports: home, require(name) {
    if (name === 'react') return { useState(initial) { const index = cursor++; if (!(index in values)) values[index] = initial; return [values[index], value => { values[index] = value }] }, useRef(initial) { const index = cursor++; if (!(index in values)) values[index] = { current: initial }; return values[index] }, useEffect() {} }
    if (name === '@tarojs/taro') return { useDidShow: fn => { hooks.show = fn }, useDidHide: fn => { hooks.hide = fn } }
    if (name === '@/services/api') return { ensureLogin: async () => ({ user_id: 'one' }), getPendingGeneration: () => null }
    if (name === '@/services/knowledge') return { getKnowledgeCapabilities: async () => { if (capability instanceof Error) throw capability; return { management_available: capability } } }
    if (name === '@/store/auth') return { getAuth: () => ({ user: { user_id: 'one' } }) }
    if (name === '@/store/navigation') return { setActiveTab() {} }
    if (name === '@/utils/navigation') return { useNavigationLayout: () => ({ contentTop: 0, statusBarHeight: 0, navigationBarHeight: 44, rightInset: 0 }) }
    if (name === '@tarojs/components') return Object.fromEntries(['Button','Image','Switch','Text','Textarea','View'].map(n => [n,n]))
    if (name === 'react/jsx-runtime') return require(name)
    return {}
  } })
  return { show: () => hooks.show(), render() { cursor = 0; return home.default() } }
}
;(async () => {
  const h = flowHarness(), pending = { kind: 'upload', requestId: 'same-request' }
  const first = h.flow.run(pending, h.submit)
  await h.flow.run(pending, () => { throw new Error('duplicate submission') })
  h.hooks.hide(); h.resolve(); await first
  assert.equal(h.doneCount, 0); assert(h.events.includes('cancel'))
  const afterLoad = flowHarness(); const wait = afterLoad.flow.run(pending, afterLoad.submit)
  afterLoad.resolve(); await flush(); afterLoad.hooks.hide(); afterLoad.loaded(); await wait
  assert.equal(afterLoad.doneCount, 0)
  const account = flowHarness(); const switched = account.flow.run(pending, account.submit)
  account.switchOwner(); account.resolve(); await switched; assert.equal(account.doneCount, 0)
  const privateUtils = {}; vm.runInNewContext(compile('src/utils/private-learning.ts'), { exports: privateUtils })
  const report = { accuracy: 80, share_quote: '内部客户原文', is_private: true }
  const content = privateUtils.shareContent({ title: '内部资料名称', questions: [] }, report)
  assert(!JSON.stringify(content).includes('内部'))
  let owner = 'one'; const values = new Map(), session = {}
  vm.runInNewContext(compile('src/store/session.ts'), { exports: session, require(name) {
    if (name === '@tarojs/taro') return { getStorageSync: key => values.get(key), setStorageSync: (key, value) => values.set(key, value), removeStorageSync: key => values.delete(key) }
    if (name === './auth') return { getAuth: () => ({ user: { user_id: owner } }) }
    throw new Error(name)
  } })
  session.startSession({ quiz_id: 'private', attempt_id: 'attempt', title: '私有原题', questions: [] }); owner = 'two'
  assert.equal(session.getSession().quiz, null); assert.equal(values.size, 0)
  const searchInfo = {}
  vm.runInNewContext(compile('src/components/WebSearchInfo.tsx'), { exports: searchInfo, require(name) {
    if (name === '@tarojs/components') return { Text: 'Text', View: 'View' }
    if (name === 'react/jsx-runtime') return require(name)
    return {}
  } })
  const label = props => searchInfo.default(props).props.children[0].props.children
  assert.equal(label({ privateSource: 'original' }), '系统保留了原题内容')
  assert.equal(label({ privateSource: 'knowledge', metadata: { status: 'fallback', context_used: false } }), '系统本次依据私有资料出题')
  assert.equal(label({ privateSource: 'knowledge', metadata: { status: 'success', context_used: true } }), '系统依据私有资料出题，并参考了公开资料')
  assert.equal(label({}), '历史题库未记录搜索状态')
  for (const capability of [true, false, new Error('optional feature unavailable')]) {
    const home = homeHarness(capability); home.render(); home.show(); await flush()
    const page = JSON.stringify(home.render())
    assert.equal(page.includes('＋ 导入自己的资料'), capability === true)
    assert(page.includes('输入一句话或一段文字'))
  }
  console.log('knowledge page lifecycle and private share tests passed')
})().catch(error => { console.error(error); process.exitCode = 1 })
