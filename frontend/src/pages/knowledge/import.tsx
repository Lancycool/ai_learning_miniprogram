import { useRef, useState } from 'react'
import Taro, { useDidHide, useDidShow, useRouter } from '@tarojs/taro'
import { Button, Checkbox, CheckboxGroup, Label, Picker, Text, Textarea, View } from '@tarojs/components'
import { ensureLogin } from '@/services/api'
import { confirmOriginalDraft, editOriginalDraft, getOriginalDraft, knowledgeRequestId } from '@/services/knowledge'
import type { OriginalDraft, OriginalDraftItem } from '@/types/knowledge'
import { KnowledgeShell, showKnowledgeError } from './shared'
import { getAuth } from '@/store/auth'

const types = ['single', 'multiple', 'judge', 'unsupported', 'unknown'] as const
const typeNames = ['单选题', '多选题', '判断题', '暂不支持', '待核对题型']
const issueNames: Record<string, string> = { missing_answer: '原文没有答案，请你补齐', conflicting_answer: '原文答案冲突，请你核对', duplicate_number: '同一章节有重复题号，请你核对', unsupported_type: '这个题型暂不支持，请你排除或修正', unknown_type: '题型尚未确定，请你选择', invalid_options: '选项不完整或有重复标号，请你修正', invalid_answer: '答案不能对应当前选项，请你修正', missing_explanation: '原文没有讲解，系统没有替原题补写', image_dependent: '原题依赖图片，本期暂不支持' }

export default function OriginalImportPage() {
  const draftId = useRouter().params.draftId || ''
  const [draft, setDraft] = useState<OriginalDraft | null>(null), [items, setItems] = useState<OriginalDraftItem[]>([])
  const [page, setPage] = useState(1), [dirty, setDirty] = useState(false), [busy, setBusy] = useState(false)
  const [checked, setChecked] = useState(false), [error, setError] = useState(''), [sourceOpen, setSourceOpen] = useState<string[]>([])
  const [coveragePage, setCoveragePage] = useState(1), [coverageOpen, setCoverageOpen] = useState(false)
  const visible = useRef(true), epoch = useRef(0), saving = useRef(false)
  const boundOwner = useRef(getAuth().user?.user_id)
  async function load(targetPage = page, targetCoverage = coveragePage) {
    const token = ++epoch.current
    try { await ensureLogin(); const owner = getAuth().user?.user_id; const data = await getOriginalDraft(draftId, targetPage, targetCoverage); if (!visible.current || token !== epoch.current || owner !== getAuth().user?.user_id) return; setDraft(data); setItems(data.items); setPage(targetPage); setCoveragePage(targetCoverage); setDirty(false); setChecked(false); setError('') }
    catch (reason) { if (visible.current && token === epoch.current) setError(reason instanceof Error ? reason.message : '原题读取失败') }
  }
  useDidShow(() => { visible.current = true; if (boundOwner.current !== getAuth().user?.user_id) { boundOwner.current = getAuth().user?.user_id; setDraft(null); setItems([]); setDirty(false); void load() } else if (!dirty) void load() })
  useDidHide(() => { visible.current = false; epoch.current++ })
  function update(id: string, change: Partial<OriginalDraftItem>) { setItems(old => old.map(q => q.id === id ? { ...q, ...change, manually_edited: true } : q)); setDirty(true); setChecked(false) }
  async function save() {
    if (!draft || busy || saving.current) return
    saving.current = true
    setBusy(true)
    try { await editOriginalDraft(draftId, draft.revision, items); await load() }
    catch (reason) { setError(reason instanceof Error ? reason.message : '修改保存失败'); showKnowledgeError(reason) }
    finally { saving.current = false; setBusy(false) }
  }
  async function changePage(next: number) {
    if (dirty) { showKnowledgeError(new Error('请先保存这一页的修改，再翻页')); return }
    await load(next)
  }
  async function confirm() {
    if (!draft || dirty || !checked || !draft.can_confirm || busy || saving.current) return
    saving.current = true
    setBusy(true)
    const owner = getAuth().user?.user_id, token = epoch.current
    try {
      const key = `bamboo_original_confirm_${owner}_${draftId}_${draft.revision}`
      let requestId = Taro.getStorageSync<string>(key)
      if (!requestId) { requestId = knowledgeRequestId(); Taro.setStorageSync(key, requestId) }
      const bank = await confirmOriginalDraft(draftId, draft.revision, requestId)
      if (visible.current && token === epoch.current && owner === getAuth().user?.user_id) await Taro.redirectTo({ url: `/pages/knowledge/bank?bankId=${bank.bank_id}` })
    }
    catch (reason) { setError(reason instanceof Error ? reason.message : '原题确认失败'); showKnowledgeError(reason) }
    finally { saving.current = false; setBusy(false) }
  }
  function addQuestion() {
    if (items.length >= 1000) return
    setItems(old => [...old, { id: knowledgeRequestId(), type: 'single', stem: '', options: [{ key: 'A', text: '' }, { key: 'B', text: '' }],
      answer: [], explanation: null, chapter_id: draft?.chapters[0]?.chapter_id || null, source: { manual: true }, issues: ['missing_answer'], excluded: false, manually_edited: true }]); setDirty(true); setChecked(false)
  }
  return <KnowledgeShell title='核对完整原题'>
    <View className='knowledge-hero'><View><Text className='knowledge-heading'>原题需要你确认</Text><Text className='muted'>系统保留原文、全部选项和原答案。你可以补题、补答案或排除暂不支持的题目。</Text></View></View>
    {error && <View className='knowledge-alert'><Text>{error}</Text><Button onClick={() => { if (!dirty) void load(); else void Taro.showModal({ title: '重新读取会放弃这一页的修改', content: '你可以先复制需要保留的内容。', success: result => { if (result.confirm) void load() } }) }}>重新读取最新版本</Button></View>}
    {!draft && !error && <Text className='muted'>系统正在读取原题预览…</Text>}
    {draft && <>
      <View className='knowledge-card'><Text className='knowledge-heading'>{draft.title}</Text><Text className='muted'>系统已提取 {draft.total} 题 · 当前纳入 {draft.included_count} 题 · 草稿版本 {draft.revision}</Text>
        {!draft.is_current_version && <Text className='knowledge-alert'>原资料版本已变化。你需要从新版本重新提取原题。</Text>}
        {draft.issues.map(issue => <Text className='knowledge-alert' key={issue.code}>{issue.message}</Text>)}
        <Button className='quiet-action' onClick={() => setCoverageOpen(!coverageOpen)}>查看全文覆盖与遗漏清单</Button>
        {coverageOpen && <>{draft.coverage.map((block, index) => <View className='draft-source' key={`${block.start_offset}-${index}`}><Text className='knowledge-badge'>{({ recognized: '已提取', unsupported: '暂不支持', answer_table: '答案表', unrecognized: '待核对文字' } as Record<string, string>)[block.status] || block.status}</Text><Text className='knowledge-body'>{block.quote}</Text></View>)}
          <View className='knowledge-columns'><Button disabled={coveragePage <= 1} onClick={() => { if (!dirty) void load(page, coveragePage-1) }}>上一批文字</Button><Button disabled={coveragePage*20 >= draft.coverage_total} onClick={() => { if (!dirty) void load(page, coveragePage+1) }}>下一批文字</Button></View>
        </>}
      </View>
      {items.map((q, index) => <View className='knowledge-card' key={q.id}>
        <View className='knowledge-option'><Text className='knowledge-heading'>第 {(page-1)*20+index+1} 题</Text><Picker mode='selector' range={typeNames} value={Math.max(0, types.indexOf(q.type))} onChange={e => update(q.id, { type: types[Number(e.detail.value)] })}><Text className='knowledge-badge'>{typeNames[Math.max(0, types.indexOf(q.type))]} ▾</Text></Picker></View>
        <Textarea className='knowledge-textarea' autoHeight maxlength={32000} value={q.stem} placeholder='完整题干' onInput={e => update(q.id, { stem: e.detail.value })} />
        <Text className='knowledge-section'>原文选项 · {q.options.length} 项</Text>
        {q.options.map((option, optionIndex) => <View className='draft-option-row' key={option.key}><Text>{option.key}.</Text><Textarea className='knowledge-textarea small' autoHeight maxlength={8000} value={option.text} onInput={e => update(q.id, { options: q.options.map((v, i) => i === optionIndex ? { ...v, text: e.detail.value } : v) })} /><Text className='danger' onClick={() => update(q.id, { options: q.options.filter(v => v.key !== option.key), answer: q.answer.filter(k => k !== option.key) })}>移除</Text></View>)}
        <Button className='quiet-action' disabled={q.options.length >= 26} onClick={() => { const key = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'.split('').find(k => !q.options.some(o => o.key === k)); if (key) update(q.id, { options: [...q.options, { key, text: '' }] }) }}>＋ 补充选项</Button>
        <Text className='knowledge-section'>核对原答案</Text>
        <CheckboxGroup onChange={e => update(q.id, { answer: e.detail.value })}>{q.options.map(o => <Label className='chapter-line' key={o.key}><Checkbox value={o.key} checked={q.answer.includes(o.key)} color='#2f7d59' /><Text>{o.key} · {o.text}</Text></Label>)}</CheckboxGroup>
        {!q.answer.length && !q.excluded && <Text className='knowledge-alert'>这道题缺少答案。你需要补齐答案或排除这道题。</Text>}
        <Text className='knowledge-section'>原文讲解</Text><Textarea className='knowledge-textarea small' autoHeight maxlength={32000} value={q.explanation || ''} placeholder='原文没有讲解。你可以留空，也可以自行补充。' onInput={e => update(q.id, { explanation: e.detail.value || null })} />
        <Picker mode='selector' range={['未指定章节', ...draft.chapters.map(c => c.title)]} value={draft.chapters.findIndex(c => c.chapter_id === q.chapter_id)+1} onChange={e => update(q.id, { chapter_id: Number(e.detail.value) ? draft.chapters[Number(e.detail.value)-1].chapter_id : null })}><Text className='knowledge-badge'>章节：{draft.chapters.find(c => c.chapter_id === q.chapter_id)?.title || '未指定'} ▾</Text></Picker>
        {q.issues.map(issue => <Text className='muted' key={issue}>· {issueNames[issue] || '请核对原题'}</Text>)}
        <CheckboxGroup onChange={e => update(q.id, { excluded: e.detail.value.includes('exclude') })}><Label className='chapter-line'><Checkbox value='exclude' checked={q.excluded} color='#2f7d59' /><Text>我排除这道题，本次不入库</Text></Label></CheckboxGroup>
        <Button className='quiet-action' onClick={() => setSourceOpen(old => old.includes(q.id) ? old.filter(id => id !== q.id) : [...old, q.id])}>查看原文位置与完整摘录</Button>
        {sourceOpen.includes(q.id) && <View className='draft-source'><Text className='muted'>{q.source.manual ? '这道题由用户补充。' : `原文字符位置 ${q.source.start_offset}—${q.source.end_offset}`}</Text><Text className='knowledge-body'>{q.source.quote || '用户补充或修订内容以确认版本为准。'}</Text></View>}
      </View>)}
      <Button className='secondary-button' disabled={busy} onClick={addQuestion}>＋ 补充漏识别原题</Button>
      <Button className='primary-button' disabled={!dirty || busy} onClick={save}>保存这一页的修改</Button>
      <View className='knowledge-columns'><Button disabled={busy || page <= 1} onClick={() => changePage(page-1)}>上一页</Button><Button disabled={busy || page*20 >= draft.total} onClick={() => changePage(page+1)}>下一页</Button></View>
      <View className='knowledge-card'><Text className='muted'>系统只发布合法的单选、多选和判断题。没有讲解的原题可以入库。缺少答案、冲突答案和不支持题型需要先处理。</Text>
        <CheckboxGroup onChange={e => setChecked(e.detail.value.includes('reviewed'))}><Label className='chapter-line'><Checkbox value='reviewed' checked={checked} color='#2f7d59' /><Text>我已核对所有纳入题目的题干、选项、答案和章节。</Text></Label></CheckboxGroup>
        <Button className='primary-button' disabled={busy || dirty || !checked || !draft.can_confirm || !draft.is_current_version} onClick={confirm}>确认原题入库</Button>
        {dirty && <Text className='muted'>你还有未保存的修改。你需要先保存，再确认。</Text>}
        {!draft.can_confirm && <Text className='muted'>系统仍发现需要处理的题目。你可以逐页核对问题清单。</Text>}
      </View>
    </>}
  </KnowledgeShell>
}
