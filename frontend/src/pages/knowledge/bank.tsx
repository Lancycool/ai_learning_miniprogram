import { useRef, useState } from 'react'
import Taro, { useDidHide, useDidShow, useRouter } from '@tarojs/taro'
import { Button, Checkbox, CheckboxGroup, Label, Text, View } from '@tarojs/components'
import { ensureLogin } from '@/services/api'
import { createOriginalPractice, getKnowledgePending, getQuestionBank, knowledgeRequestId } from '@/services/knowledge'
import { startSession } from '@/store/session'
import { getAuth } from '@/store/auth'
import type { Quiz } from '@/types/api'
import type { QuestionBank } from '@/types/knowledge'
import { KnowledgeShell, ProcessingPanel, useKnowledgeFlow } from './shared'

export default function OriginalBankPage() {
  const bankId = useRouter().params.bankId || ''
  const [bank, setBank] = useState<QuestionBank | null>(null), [selected, setSelected] = useState<string[] | null>(null), [error, setError] = useState('')
  const visible = useRef(true), loadToken = useRef(0)
  const boundOwner = useRef(getAuth().user?.user_id)
  const flow = useKnowledgeFlow(async (task, valid) => { if (!task.result?.attempt_id || !task.result?.questions) throw new Error('系统没有返回完整练习结果'); if (valid()) { startSession(task.result as Quiz); await Taro.navigateTo({ url: '/pages/quiz/index' }) } })
  async function load(chapters = selected) { const token = ++loadToken.current; const owner = getAuth().user?.user_id; setSelected(chapters); if (chapters?.length === 0) { setBank(old => old ? { ...old, groups: [], question_count: 0 } : old); return } try { await ensureLogin(); const data = await getQuestionBank(bankId, chapters); if (visible.current && token === loadToken.current && owner === getAuth().user?.user_id) { setBank(data); setError('') } } catch (reason) { if (visible.current && token === loadToken.current) setError(reason instanceof Error ? reason.message : '题库加载失败') } }
  useDidShow(() => { visible.current = true; if (boundOwner.current !== getAuth().user?.user_id) { boundOwner.current = getAuth().user?.user_id; setBank(null); setSelected(null); void load(null) } else void load() })
  useDidHide(() => { visible.current = false; loadToken.current++ })
  async function practice(index: number) { const requestId = knowledgeRequestId(); await flow.run({ requestId, kind: 'practice', bankId, documentId: bank?.document_id }, () => createOriginalPractice(bankId, index, selected, requestId)) }
  const pending = getKnowledgePending()
  return <KnowledgeShell title='原题分组练习'>
    {error && <View className='knowledge-alert'>{error}</View>}
    {flow.error && <View className='knowledge-alert'>{flow.error}</View>}
    {!bank && !error && <Text className='muted'>系统正在读取确认题库…</Text>}
    {bank && <>
      <View className='knowledge-card'><Text className='knowledge-heading'>{bank.title}</Text><Text className='muted'>你已确认原题。系统保留原来的题型、选项和答案。系统每组最多安排五题，最后一组可以少于五题。</Text>
        <Button disabled={flow.busy} className={selected === null ? 'primary-button' : 'secondary-button'} onClick={() => load(null)}>练习全部章节</Button>
        <CheckboxGroup onChange={e => { if (e.detail.value.length) void load(e.detail.value); else { setSelected([]); setBank(old => old ? { ...old, groups: [], question_count: 0 } : old) } }}>{bank.chapters.map(c => <Label className='chapter-line' key={c.chapter_id} style={{ paddingLeft: `${(c.level-1)*16}px` }}><Checkbox value={c.chapter_id} checked={selected?.includes(c.chapter_id) || false} color='#2f7d59' /><Text>{c.title}</Text></Label>)}</CheckboxGroup>
      </View>
      {pending?.bankId === bankId && !flow.busy && <Button className='secondary-button' onClick={flow.resume}>恢复原题练习任务</Button>}
      {flow.busy && <ProcessingPanel status={flow.status} onPause={flow.pause} />}
      <Text className='knowledge-section'>本次范围共有 {bank.question_count} 题</Text>
      {bank.groups.map(group => <View className='knowledge-card knowledge-row' key={group.group_index}><View><Text className='knowledge-heading'>第 {group.group_index+1} 组</Text><Text className='muted'>{group.question_count} 道原题 · 题型按原文保留</Text></View><Button className='secondary-button' disabled={flow.busy} onClick={() => practice(group.group_index)}>开始练习</Button></View>)}
      {!bank.groups.length && <View className='knowledge-empty'>当前章节没有纳入练习的原题。你可以重新选择章节。</View>}
    </>}
  </KnowledgeShell>
}
