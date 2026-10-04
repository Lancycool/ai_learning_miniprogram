import { useEffect, useRef, useState } from 'react'
import Taro, { useDidHide, useDidShow, useRouter } from '@tarojs/taro'
import { Button, Checkbox, CheckboxGroup, Input, Label, Switch, Text, Textarea, View } from '@tarojs/components'
import { createRequestControl, ensureLogin } from '@/services/api'
import type { RequestControl } from '@/services/api'
import { getAuth } from '@/store/auth'
import { startSession } from '@/store/session'
import { clearKnowledgePending, createKnowledgeQuiz, createOriginalImport, deleteKnowledgeDocument, getKnowledgeCapabilities,
  getKnowledgeDocument, getKnowledgePending, knowledgeRequestId, listDocumentBanks, patchKnowledgeChapters, pollPrivateQuizTask,
  previewKnowledgeDocument, retryKnowledgeDocument, saveKnowledgePending } from '@/services/knowledge'
import type { DocumentPreview, KnowledgeCapabilities, KnowledgeDocument, KnowledgeScope } from '@/types/knowledge'
import { KnowledgeShell, ProcessingPanel, showKnowledgeError, useKnowledgeFlow } from './shared'

export default function KnowledgeDocumentPage() {
  const params = useRouter().params, documentId = params.documentId || ''
  const [doc, setDoc] = useState<KnowledgeDocument | null>(null), [preview, setPreview] = useState<DocumentPreview | null>(null)
  const baseId = doc?.knowledge_base_id || params.baseId || ''
  const [banks, setBanks] = useState<Awaited<ReturnType<typeof listDocumentBanks>>['items']>([]), [bankTotal, setBankTotal] = useState(0), [bankPage, setBankPage] = useState(1)
  const [capabilities, setCapabilities] = useState<KnowledgeCapabilities | null>(null), [selected, setSelected] = useState<string[] | null>(null)
  const [error, setError] = useState(''), [userInput, setUserInput] = useState('根据所选资料学习核心知识'), [enableWeb, setEnableWeb] = useState(false)
  const [publicTopic, setPublicTopic] = useState(''), [confirmed, setConfirmed] = useState(false), [generating, setGenerating] = useState(false)
  const [generationStatus, setGenerationStatus] = useState(''), [editing, setEditing] = useState(false)
  const [chapterEdits, setChapterEdits] = useState<{ title: string; level: number; start_offset: number; end_offset: number }[]>([])
  const generationControl = useRef<RequestControl | null>(null), epoch = useRef(0), visible = useRef(true)
  const boundOwner = useRef(getAuth().user?.user_id), loadToken = useRef(0)
  const flow = useKnowledgeFlow(async (task, valid) => {
    if (task.result?.draft_id && valid()) await Taro.navigateTo({ url: `/pages/knowledge/import?draftId=${task.result.draft_id}` })
    else { await load(); if (valid() && task.task_type === 'index') { setEditing(false); setSelected(null) } }
  })
  async function load() {
    const token = ++loadToken.current
    try {
      await ensureLogin()
      const owner = getAuth().user?.user_id
      const valid = () => visible.current && token === loadToken.current && owner === getAuth().user?.user_id
      const [current, available] = await Promise.all([getKnowledgeDocument(documentId), getKnowledgeCapabilities()])
      if (!valid()) return
      setDoc(current); setCapabilities(available)
      if (current.parse_status === 'ready') { const [detail, knownBanks] = await Promise.all([previewKnowledgeDocument(documentId), listDocumentBanks(documentId)]); if (!valid()) return; setPreview(detail); setBanks(knownBanks.items); setBankTotal(knownBanks.total); setBankPage(1); setChapterEdits(detail.chapters.map(c => ({ title: c.title, level: c.level, start_offset: c.start_offset, end_offset: c.end_offset }))) }
      setError('')
    } catch (reason) { if (visible.current && token === loadToken.current) setError(reason instanceof Error ? reason.message : '资料读取失败') }
  }
  useDidShow(() => { visible.current = true; if (boundOwner.current !== getAuth().user?.user_id) { boundOwner.current = getAuth().user?.user_id; setDoc(null); setPreview(null); setBanks([]); setCapabilities(null); setSelected(null); setChapterEdits([]); setUserInput('根据所选资料学习核心知识'); setPublicTopic(''); setEnableWeb(false); setConfirmed(false); setEditing(false) } void load() })
  function pauseGeneration() { epoch.current++; generationControl.current?.cancel(); generationControl.current = null; setGenerating(false) }
  useDidHide(() => { visible.current = false; loadToken.current++; pauseGeneration() })
  useEffect(() => () => { visible.current = false; pauseGeneration() }, [])
  async function morePreview() {
    if (!preview) return
    try { const more = await previewKnowledgeDocument(documentId, preview.offset+preview.text.length); setPreview(old => old ? { ...more, offset: 0, text: old.text+more.text } : more) } catch (reason) { showKnowledgeError(reason) }
  }
  async function importOriginals() {
    if (!doc) return
    const requestId = knowledgeRequestId()
    await flow.run({ requestId, kind: 'import', documentId, baseId }, () => createOriginalImport(documentId, doc.version_id, selected, requestId))
  }
  async function retry() { const requestId = knowledgeRequestId(); await flow.run({ requestId, kind: 'retry', documentId, baseId }, () => retryKnowledgeDocument(documentId, requestId)) }
  async function watch() { if (doc?.task_id) await flow.run({ requestId: knowledgeRequestId(), kind: 'retry', documentId, baseId, taskId: doc.task_id }) }
  async function remove() {
    const answer = await Taro.showModal({ title: '删除这份资料？', content: '系统会清理原文件和检索索引。已经生成的题目、引用快照和成绩会保留。' })
    if (!answer.confirm) return
    try { await deleteKnowledgeDocument(documentId); await Taro.navigateBack() } catch (reason) { showKnowledgeError(reason) }
  }
  async function saveChapters() {
    if (!doc) return
    const requestId = knowledgeRequestId()
    await flow.run({ requestId, kind: 'chapters', documentId, baseId }, () => patchKnowledgeChapters(documentId, doc.version_id, chapterEdits))
  }
  async function generate(resume = false) {
    if (generationControl.current || !doc) return
    const previous = getKnowledgePending()
    const current = ++epoch.current, owner = getAuth().user?.user_id, control = createRequestControl()
    generationControl.current = control; setGenerating(true); setError(''); setGenerationStatus('系统正在保存或恢复出题任务')
    try {
      const scope: KnowledgeScope = { knowledge_base_id: baseId, documents: [{ document_id: documentId, version_id: doc.version_id, chapter_ids: selected }] }
      const pending = resume && previous?.kind === 'generate' ? previous : { requestId: knowledgeRequestId(), kind: 'generate' as const, documentId, baseId,
        payload: { userInput: userInput.trim(), scope, enabled: enableWeb, publicTopic, confirmed } }
      saveKnowledgePending(pending)
      let taskId = pending.taskId
      if (!taskId) {
        const data = pending.payload as { userInput: string; scope: KnowledgeScope; enabled: boolean; publicTopic: string; confirmed: boolean }
        const created = await createKnowledgeQuiz(data.userInput, data.scope, data.enabled, data.publicTopic, data.confirmed, pending.requestId, control)
        if (!valid()) return
        taskId = created.task_id; saveKnowledgePending({ ...pending, taskId })
      }
      const completed = await pollPrivateQuizTask(taskId, control, task => { if (valid()) { setGenerationStatus(task.status === 'queued' ? '任务正在排队，系统每 5 秒查询一次' : '系统正在检索资料并生成题目'); if (task.status === 'failed') clearKnowledgePending() } })
      if (!valid() || !completed.result) return
      clearKnowledgePending(); startSession(completed.result); await Taro.navigateTo({ url: '/pages/quiz/index' })
    } catch (reason) { if (valid()) setError(reason instanceof Error ? reason.message : '知识库出题失败') }
    finally { if (generationControl.current === control) { generationControl.current = null; setGenerating(false) } }
    function valid() { return visible.current && epoch.current === current && !control.cancelled && owner === getAuth().user?.user_id }
  }
  const pending = getKnowledgePending(), busy = flow.busy || generating, noChapters = selected !== null && selected.length === 0
  return <KnowledgeShell title={doc?.title || '资料与章节'}>
    {error && <View className='knowledge-alert'><Text>{error}</Text><Button onClick={load}>重新读取</Button></View>}
    {flow.error && <View className='knowledge-alert'>{flow.error}</View>}
    {!doc && !error && <Text className='muted'>系统正在读取资料…</Text>}
    {doc && <>
      <View className='knowledge-card'><Text className='knowledge-heading'>{doc.title}</Text><Text className='muted'>{doc.file_type.toUpperCase()} · 版本 {doc.version_no}</Text>
        <Text className='knowledge-badge'>{doc.parse_status === 'ready' ? '完整正文已解析' : doc.parse_status === 'failed' ? '资料解析失败' : '资料正在后台处理'}</Text>
        {doc.index_status !== 'ready' && <Text className='muted'>索引尚未就绪。已解析的原文仍可预览，原题导入和练习可以独立使用。</Text>}
        {!busy && <Button className='secondary-button' onClick={watch}>查看处理任务</Button>}
        {!busy && (doc.parse_status === 'failed' || doc.parse_status === 'ready') && <Button className='secondary-button' onClick={retry}>{doc.parse_status === 'ready' ? '重新建立检索索引' : '重试解析'}</Button>}
      </View>
      {pending?.documentId === documentId && !busy && <Button className='secondary-button' onClick={() => pending.kind === 'generate' ? void generate(true) : flow.resume()}>继续查看未结束的任务</Button>}
      {flow.busy && <ProcessingPanel status={flow.status} onPause={flow.pause} />}
      {generating && <View className='knowledge-card'><Text className='knowledge-heading'>{generationStatus}</Text><Text className='muted'>你离开页面后，后台任务会继续。</Text><Button className='quiet-action' onClick={pauseGeneration}>暂停查看</Button></View>}
      {preview && <>
        {preview.warnings.map(w => <View className='knowledge-alert' key={w.code}>{w.message}</View>)}
        <View className='knowledge-card'><Text className='knowledge-section'>选择学习章节</Text><Button className={selected === null ? 'primary-button' : 'secondary-button'} onClick={() => setSelected(null)}>全文 · 所有章节</Button>
          <CheckboxGroup onChange={e => setSelected(e.detail.value)}>{preview.chapters.map(c => <Label className='chapter-line' key={c.chapter_id} style={{ paddingLeft: `${(c.level-1)*16}px` }}><Checkbox value={c.chapter_id} checked={selected?.includes(c.chapter_id) || false} color='#2f7d59' /><Text className='chapter-name'>{c.title}</Text></Label>)}</CheckboxGroup>
          <Text className='muted'>{selected === null ? '你已选择全文。' : `你已选择 ${selected.length} 个章节。子章节会包含在父章节范围中。`}</Text>
          <Button className='quiet-action' onClick={() => setEditing(!editing)}>修正章节</Button>
        </View>
        {editing && <View className='knowledge-card'><Text className='muted'>正文共有 {preview.total_characters} 个字符。章节需要覆盖全文，子章节需要位于父章节范围内。</Text>
          {chapterEdits.map((c, index) => <View className='draft-source' key={index}><Input className='knowledge-input' maxlength={160} value={c.title} placeholder='章节标题' onInput={e => setChapterEdits(old => old.map((v, i) => i === index ? { ...v, title: e.detail.value } : v))} />
            <View className='knowledge-columns'>{(['level', 'start_offset', 'end_offset'] as const).map((key, j) => <View key={key}><Text className='muted'>{['层级', '正文起点', '正文终点'][j]}</Text><Input type='number' className='knowledge-input' value={String(c[key])} onInput={e => setChapterEdits(old => old.map((v, i) => i === index ? { ...v, [key]: Number(e.detail.value) } : v))} /></View>)}</View>
            <Button className='quiet-action danger' onClick={() => setChapterEdits(old => old.filter((_, i) => i !== index))}>移除该章节范围</Button>
          </View>)}
          <Button className='secondary-button' onClick={() => setChapterEdits(old => [...old, { title: '新增子章节', level: 2, start_offset: 0, end_offset: preview.total_characters }])}>＋ 添加章节</Button>
          <Button className='primary-button' disabled={busy || !chapterEdits.length} onClick={saveChapters}>保存为新资料版本</Button>
        </View>}
        <View className='knowledge-card'><Text className='knowledge-section'>完整正文预览</Text><Text className='muted'>系统已显示 {preview.text.length} / {preview.total_characters} 个字符。原题提取会遍历所选范围的全文。</Text><Text className='knowledge-body'>{preview.text}</Text>{preview.has_more && <Button className='quiet-action' onClick={morePreview}>继续查看原文</Button>}</View>
        <View className='knowledge-card'><Text className='knowledge-heading'>根据资料生成新题</Text><Input className='knowledge-input' maxlength={2000} value={userInput} onInput={e => setUserInput(e.detail.value)} placeholder='你希望重点学习什么？' />
          <View className='knowledge-option'><Text>允许公开资料补充</Text><Switch checked={enableWeb} color='#2f7d59' onChange={e => { setEnableWeb(e.detail.value); setConfirmed(false) }} /></View>
          <Text className='muted'>系统默认只依据你的资料出题。资料不足时，系统会提示你补充材料。</Text>
          {enableWeb && <><Input className='knowledge-input' maxlength={300} placeholder='单独填写可公开的搜索主题' value={publicTopic} onInput={e => { setPublicTopic(e.detail.value); setConfirmed(false) }} /><CheckboxGroup onChange={e => setConfirmed(e.detail.value.includes('confirmed'))}><Label className='chapter-line'><Checkbox value='confirmed' checked={confirmed} color='#2f7d59' /><Text className='muted'>我确认这个主题可以发送给公开搜索服务，其中没有私有正文、原题、答案或内部地址。</Text></Label></CheckboxGroup></>}
          <Button className='primary-button' disabled={busy || noChapters || !userInput.trim() || doc.index_status !== 'ready' || !capabilities?.index_available || (enableWeb && (!confirmed || !publicTopic.trim()))} onClick={() => void generate()}>生成五道新题</Button>
          {doc.index_status !== 'ready' && <Text className='muted'>资料索引就绪后，你可以生成新题。你现在可以先导入原题。</Text>}
        </View>
        <View className='knowledge-card'><Text className='knowledge-heading'>导入资料中的原题</Text><Text className='muted'>系统完整提取单选、多选和判断题。你需要核对原文、选项、答案和章节，再确认入库。其他题型暂不支持。</Text><Button className='secondary-button' disabled={busy || noChapters} onClick={importOriginals}>提取原题并进入审核</Button></View>
      </>}
      {banks.length > 0 && <View className='knowledge-card'><Text className='knowledge-heading'>已确认的原题题库</Text>{banks.map(bank => <Button className='secondary-button' key={bank.bank_id} onClick={() => Taro.navigateTo({ url: `/pages/knowledge/bank?bankId=${bank.bank_id}` })}>{bank.title} · {bank.question_count} 题 · 审核版本 {bank.draft_revision}{bank.is_current_version ? '' : '（旧资料版本）'}</Button>)}{banks.length < bankTotal && <Button className='quiet-action' onClick={async () => { try { const next = await listDocumentBanks(documentId, bankPage+1); if (visible.current) { setBanks(old => [...old, ...next.items]); setBankPage(bankPage+1) } } catch (reason) { showKnowledgeError(reason) } }}>查看更多题库</Button>}</View>}
      <Button className='quiet-action danger' disabled={busy} onClick={remove}>删除原资料</Button>
    </>}
  </KnowledgeShell>
}
