import { useRef, useState } from 'react'
import Taro, { useDidHide, useDidShow, useRouter } from '@tarojs/taro'
import { Button, Image, Input, Text, Textarea, View } from '@tarojs/components'
import pandaHappy from '@/assets/panda-happy.svg'
import { ensureLogin } from '@/services/api'
import { getAuth } from '@/store/auth'
import { chooseKnowledgeFile, createKnowledgeBase, deleteKnowledgeBase, getKnowledgeBase, getKnowledgeCapabilities,
  getKnowledgePending, knowledgeRequestId, listKnowledgeBases, listKnowledgeCleanup, listKnowledgeDocuments, patchKnowledgeBase, retryKnowledgeTask, saveKnowledgeText, uploadKnowledgeDocument } from '@/services/knowledge'
import type { KnowledgeBase, KnowledgeCapabilities, KnowledgeDocument, KnowledgeTask } from '@/types/knowledge'
import { KnowledgeShell, ProcessingPanel, showKnowledgeError, useKnowledgeFlow } from './shared'

export default function KnowledgeLibrary() {
  const baseId = useRouter().params.baseId || ''
  const [capabilities, setCapabilities] = useState<KnowledgeCapabilities | null>(null), [bases, setBases] = useState<KnowledgeBase[]>([])
  const [base, setBase] = useState<KnowledgeBase | null>(null), [documents, setDocuments] = useState<KnowledgeDocument[]>([])
  const [name, setName] = useState(''), [description, setDescription] = useState(''), [creating, setCreating] = useState(false)
  const [writing, setWriting] = useState(false), [title, setTitle] = useState(''), [text, setText] = useState('')
  const [page, setPage] = useState(1), [total, setTotal] = useState(0), [error, setError] = useState('')
  const [cleanup, setCleanup] = useState<KnowledgeTask[]>([]), [cleanupTotal, setCleanupTotal] = useState(0), [cleanupPage, setCleanupPage] = useState(1)
  const creatingRequest = useRef(false)
  const boundOwner = useRef(getAuth().user?.user_id), visible = useRef(true), loadToken = useRef(0)
  const flow = useKnowledgeFlow(async (task, valid) => { await load(); if (valid() && task.task_type !== 'cleanup') await Taro.navigateTo({ url: `/pages/knowledge/document?documentId=${task.document.document_id}&baseId=${task.document.knowledge_base_id || baseId}` }) })
  async function load() {
    const token = ++loadToken.current
    try {
      await ensureLogin()
      const owner = getAuth().user?.user_id
      const valid = () => visible.current && token === loadToken.current && owner === getAuth().user?.user_id
      const available = await getKnowledgeCapabilities(); if (!valid()) return; setCapabilities(available)
      if (!available.management_available) return
      const cleaning = await listKnowledgeCleanup(baseId); if (!valid()) return; setCleanup(cleaning.items); setCleanupTotal(cleaning.total); setCleanupPage(1)
      if (baseId) { const [detail, docs] = await Promise.all([getKnowledgeBase(baseId), listKnowledgeDocuments(baseId)]); if (!valid()) return; setBase(detail); setDocuments(docs.items); setTotal(docs.total); setPage(1) }
      else { const data = await listKnowledgeBases(); if (!valid()) return; setBases(data.items) }
      setError('')
    } catch (reason) { if (visible.current && token === loadToken.current) setError(reason instanceof Error ? reason.message : '资料加载失败') }
  }
  useDidShow(() => { visible.current = true; if (boundOwner.current !== getAuth().user?.user_id) { boundOwner.current = getAuth().user?.user_id; setBases([]); setBase(null); setDocuments([]); setCleanup([]); setCapabilities(null); setWriting(false); setCreating(false); setName(''); setDescription(''); setTitle(''); setText('') } void load() })
  useDidHide(() => { visible.current = false; loadToken.current++ })
  async function create() {
    if (!name.trim()) return showKnowledgeError(new Error('请填写知识库名称'))
    if (creatingRequest.current) return
    creatingRequest.current = true
    try { const created = baseId ? await patchKnowledgeBase(baseId, name.trim(), description) : await createKnowledgeBase(name.trim(), description); setCreating(false); if (baseId) setBase(created); else await Taro.navigateTo({ url: `/pages/knowledge/index?baseId=${created.knowledge_base_id}` }) } catch (reason) { showKnowledgeError(reason) } finally { creatingRequest.current = false }
  }
  async function upload() {
    try { const file = await chooseKnowledgeFile(capabilities?.max_file_bytes); const pending = getKnowledgePending();
      const requestId = pending?.kind === 'upload' && pending.baseId === baseId && !pending.taskId ? pending.requestId : knowledgeRequestId()
      await flow.run({ kind: 'upload', baseId, requestId }, control => uploadKnowledgeDocument(baseId, file, requestId, control))
    } catch (reason) { showKnowledgeError(reason) }
  }
  async function saveText() {
    if (!title.trim() || !text.trim()) return showKnowledgeError(new Error('请填写资料标题和正文'))
    const previous = getKnowledgePending()
    const requestId = previous?.kind === 'text' && previous.baseId === baseId && !previous.taskId ? previous.requestId : knowledgeRequestId()
    await flow.run({ kind: 'text', baseId, requestId }, control => saveKnowledgeText(baseId, title.trim(), text, requestId, control))
  }
  async function removeBase() {
    const answer = await Taro.showModal({ title: '删除这个知识库？', content: '系统会清理原文件和检索索引。已经生成的题目、引用快照和成绩会保留。' })
    if (!answer.confirm) return
    try { await deleteKnowledgeBase(baseId); await Taro.redirectTo({ url: '/pages/knowledge/index' }) } catch (reason) { showKnowledgeError(reason) }
  }
  async function more() { try { const next = page+1; const data = await listKnowledgeDocuments(baseId, next); setDocuments(previous => [...previous, ...data.items]); setPage(next) } catch (reason) { showKnowledgeError(reason) } }
  async function moreCleanup() { try { const next = cleanupPage+1; const data = await listKnowledgeCleanup(baseId, next); setCleanup(previous => [...previous, ...data.items]); setCleanupPage(next) } catch (reason) { showKnowledgeError(reason) } }
  async function watchCleanup(task: KnowledgeTask) {
    const requestId = knowledgeRequestId()
    await flow.run({ kind: 'cleanup', baseId: task.document.knowledge_base_id, requestId, taskId: task.status === 'failed' ? undefined : task.task_id },
      task.status === 'failed' ? () => retryKnowledgeTask(task.task_id, requestId) : undefined)
    await load()
  }
  const pending = getKnowledgePending()
  function resume() {
    if (!pending) return
    if (pending.kind === 'practice' && pending.bankId) void Taro.navigateTo({ url: `/pages/knowledge/bank?bankId=${pending.bankId}` })
    else if (['generate', 'import', 'chapters', 'retry'].includes(pending.kind) && pending.documentId) void Taro.navigateTo({ url: `/pages/knowledge/document?documentId=${pending.documentId}&baseId=${pending.baseId || baseId}` })
    else flow.resume()
  }
  return <KnowledgeShell title={base?.name || '我的知识库'}>
    <View className='knowledge-hero'><View><Text className='knowledge-heading'>{baseId ? '把资料变成关卡' : '学习你自己的知识'}</Text><Text className='muted'>你可以根据资料生成新题，也可以完整导入原题。</Text></View><Image src={pandaHappy} mode='aspectFit' /></View>
    {error && <View className='knowledge-alert'><Text>{error}</Text><Button onClick={load}>重新加载</Button></View>}
    {capabilities && !capabilities.enabled && <View className='knowledge-card'><Text>资料功能暂未启用。你可以回到首页继续按主题学习。</Text></View>}
    {!capabilities && !error && <Text className='muted'>系统正在读取资料功能状态…</Text>}
    {capabilities?.management_available && <>
      {pending && (!baseId || pending.baseId === baseId) && !flow.busy && <View className='knowledge-card'><Text>你还有一个资料任务。你可以继续查看。</Text><Button className='secondary-button' onClick={resume}>恢复任务</Button></View>}
      {flow.busy && <ProcessingPanel status={flow.status} onPause={flow.pause} />}
      {flow.error && <View className='knowledge-alert'><Text>{flow.error}</Text><Text className='muted'>如果上传尚未保存，你可以重新选择原文件。系统会沿用原请求编号恢复。</Text></View>}
      {cleanup.length > 0 && <><Text className='knowledge-section'>原资料清理状态</Text>{cleanup.map(task => <View className='knowledge-card' key={task.task_id}><Text className='knowledge-heading'>{task.document.title}</Text><Text className='muted'>{task.status === 'failed' ? '文件或索引尚未完全清理。你可以重试，学习记录会保留。' : '系统正在清理原文件和检索索引。学习记录会保留。'}</Text>{task.error && <Text className='knowledge-alert'>{task.error.message}</Text>}<Button className='secondary-button' disabled={flow.busy} onClick={() => watchCleanup(task)}>{task.status === 'failed' ? '重试清理' : '查看清理进度'}</Button></View>)}{cleanup.length < cleanupTotal && <Button className='quiet-action' onClick={moreCleanup}>查看更多清理任务</Button>}</>}
      {!baseId ? <>
        <Text className='knowledge-section'>我的资料空间</Text>
        {bases.map(item => <View className='knowledge-card knowledge-row' key={item.knowledge_base_id} onClick={() => Taro.navigateTo({ url: `/pages/knowledge/index?baseId=${item.knowledge_base_id}` })}><View><Text className='knowledge-heading'>📚 {item.name}</Text><Text className='muted'>{item.description || '你自己的学习资料'} · {item.document_count} 份资料</Text></View><Text>›</Text></View>)}
        {!bases.length && <View className='knowledge-empty'>你还没有知识库。你可以先创建一个资料空间。</View>}
        <Button className='primary-button' onClick={() => setCreating(!creating)}>＋ 新建知识库</Button>
        {creating && <View className='knowledge-card'><Input className='knowledge-input' maxlength={30} placeholder='例如：企业客服培训' value={name} onInput={e => setName(e.detail.value)} /><Textarea className='knowledge-textarea small' maxlength={300} placeholder='你可以填写资料说明' value={description} onInput={e => setDescription(e.detail.value)} /><Button className='secondary-button' onClick={create}>保存知识库</Button></View>}
      </> : <>
        <Button className='quiet-action' onClick={() => { setName(base?.name || ''); setDescription(base?.description || ''); setCreating(!creating) }}>修改知识库名称和说明</Button>
        {creating && <View className='knowledge-card'><Input className='knowledge-input' maxlength={30} value={name} onInput={e => setName(e.detail.value)} /><Textarea className='knowledge-textarea small' maxlength={300} value={description} onInput={e => setDescription(e.detail.value)} /><Button className='secondary-button' onClick={create}>保存修改</Button></View>}
        <View className='knowledge-card'><Text className='knowledge-section'>添加私有资料</Text><Text className='muted'>系统支持 PDF、DOCX、Markdown 和 TXT。单个文件上限为 30 MB。网页、视频和扫描件后续支持。</Text>
          <Button className='primary-button' disabled={flow.busy || !capabilities.parsing_available} onClick={upload}>选择文档并上传</Button>
          <Button className='secondary-button' disabled={flow.busy || !capabilities.parsing_available} onClick={() => setWriting(!writing)}>粘贴一段文字</Button>
          <Text className='muted'>配置的百炼和 DeepSeek 会处理资料文字，用于检索和出题。私有出题默认关闭联网。</Text>
        </View>
        {writing && <View className='knowledge-card'><Input className='knowledge-input' maxlength={120} placeholder='资料标题' value={title} onInput={e => setTitle(e.detail.value)} /><Textarea className='knowledge-textarea' maxlength={500000} placeholder='你可以粘贴培训知识、学习材料或完整题库' value={text} onInput={e => setText(e.detail.value)} /><Text className='muted'>{text.length} / 500000 字符</Text><Button className='primary-button' disabled={flow.busy} onClick={saveText}>保存文字资料</Button></View>}
        <Text className='knowledge-section'>资料列表 · {total} 份</Text>
        {documents.map(doc => <View className='knowledge-card knowledge-row' key={doc.document_id} onClick={() => Taro.navigateTo({ url: `/pages/knowledge/document?documentId=${doc.document_id}&baseId=${baseId}` })}><View><Text className='knowledge-heading'>{doc.title}</Text><Text className='muted'>{doc.file_type.toUpperCase()} · {(doc.file_size/1024).toFixed(1)} KB · 版本 {doc.version_no}</Text><Text className={`knowledge-badge ${doc.parse_status === 'failed' ? 'warning' : ''}`}>{doc.parse_status === 'ready' ? doc.index_status === 'ready' ? '资料和索引已就绪' : '原文可用 · 索引未就绪' : doc.parse_status === 'failed' ? '解析失败，请检查资料' : '资料正在后台处理'}</Text></View><Text>›</Text></View>)}
        {documents.length < total && <Button className='quiet-action' onClick={more}>查看更多资料</Button>}
        <Button className='quiet-action danger' onClick={removeBase}>删除这个知识库</Button>
      </>}
    </>}
  </KnowledgeShell>
}
