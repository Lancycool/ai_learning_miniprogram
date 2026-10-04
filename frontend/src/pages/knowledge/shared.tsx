import { useEffect, useRef, useState } from 'react'
import Taro, { useDidHide, useDidShow } from '@tarojs/taro'
import { Button, Image, Text, View } from '@tarojs/components'
import pandaThinking from '@/assets/panda-thinking.svg'
import { createRequestControl } from '@/services/api'
import type { RequestControl } from '@/services/api'
import { clearKnowledgePending, getKnowledgePending, pollKnowledgeTask, recoverKnowledgeTask, saveKnowledgePending } from '@/services/knowledge'
import type { KnowledgePending } from '@/services/knowledge'
import type { KnowledgeTask } from '@/types/knowledge'
import { getAuth } from '@/store/auth'
import { useNavigationLayout } from '@/utils/navigation'
import './index.scss'

export const showKnowledgeError = (error: unknown) => Taro.showToast({ title: error instanceof Error ? error.message : '操作失败，请稍后重试', icon: 'none' })
export const stageName = (stage: string) => ({ queued: '任务正在排队', starting: '系统正在准备资料', parsing: '系统正在读取完整正文', chapters: '系统正在整理章节', indexing: '系统正在建立检索索引', extracting: '系统正在逐题提取原题', review_ready: '原题已经准备好，请你核对', preparing_practice: '系统正在准备这一组原题', cleaning: '系统正在清理原文件和索引', complete: '任务已完成' }[stage] || '系统正在处理资料')

export function KnowledgeShell({ title, children }: { title: string; children: React.ReactNode }) {
  const navigation = useNavigationLayout()
  return <View className='page-shell knowledge-page' style={{ paddingTop: `${navigation.statusBarHeight}px` }}>
    <View className='appbar knowledge-bar' style={{ height: `${navigation.navigationBarHeight}px`, paddingRight: `${navigation.rightInset}px` }}>
      <Text className='back' onClick={() => Taro.navigateBack().catch(() => Taro.switchTab({ url: '/pages/index/index' }))}>‹</Text>
      <Text className='appbar-title'>{title}</Text><Text>竹知岛</Text>
    </View><View className='knowledge-content'>{children}</View>
  </View>
}

export function ProcessingPanel({ status, onPause }: { status: KnowledgeTask | null; onPause: () => void }) {
  return <View className='knowledge-card processing-card'>
    <Image src={pandaThinking} mode='aspectFit' />
    <Text className='knowledge-heading'>{status ? stageName(status.stage) : '系统正在保存或恢复任务'}</Text>
    {status?.total_count ? <Text className='muted'>系统已处理 {status.processed_count} / {status.total_count} 项</Text> : null}
    <Text className='muted'>系统每次查询结束后等待 5 秒。你离开页面后，后台任务会继续。</Text>
    <Button className='quiet-action' onClick={onPause}>暂停查看</Button>
  </View>
}

export function useKnowledgeFlow(onDone: (task: KnowledgeTask, valid: () => boolean) => void | Promise<void>) {
  const [busy, setBusy] = useState(false), [status, setStatus] = useState<KnowledgeTask | null>(null), [error, setError] = useState('')
  const control = useRef<RequestControl | null>(null), token = useRef(0), visible = useRef(true)
  const done = useRef(onDone); done.current = onDone
  function pause() { visible.current = false; token.current++; control.current?.cancel(); control.current = null; setBusy(false) }
  useDidHide(pause)
  useDidShow(() => { visible.current = true })
  useEffect(() => () => { visible.current = false; token.current++; control.current?.cancel() }, [])
  async function run(pending: KnowledgePending, submit?: (control: RequestControl) => Promise<KnowledgeTask>) {
    if (control.current) return
    visible.current = true
    const owner = getAuth().user?.user_id, current = ++token.current, request = createRequestControl()
    control.current = request; setBusy(true); setError(''); setStatus(null)
    try {
      saveKnowledgePending(pending)
      const task = submit ? await submit(request) : pending.taskId
        ? await pollKnowledgeTask(pending.taskId, request, update) : await recoverKnowledgeTask(pending.requestId, request)
      if (!valid()) return
      const saved = { ...pending, taskId: task.task_id, documentId: task.document.document_id }
      saveKnowledgePending(saved)
      const complete = task.status === 'succeeded' ? task : await pollKnowledgeTask(task.task_id, request, update)
      if (!valid()) return
      clearKnowledgePending(); await done.current(complete, valid)
    } catch (reason) { if (valid()) setError(reason instanceof Error ? reason.message : '资料处理失败，请重试') }
    finally { if (control.current === request) { control.current = null; setBusy(false) } }
    function valid() { return visible.current && current === token.current && !request.cancelled && owner === getAuth().user?.user_id }
    function update(task: KnowledgeTask) { if (valid()) { setStatus(task); if (task.status === 'failed') clearKnowledgePending() } }
  }
  return { busy, status, error, pause, run, resume: () => { const pending = getKnowledgePending(); if (pending) void run(pending) } }
}
