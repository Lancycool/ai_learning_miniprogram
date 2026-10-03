import { useEffect, useState } from 'react'
import Taro from '@tarojs/taro'
import { Input, Text, View } from '@tarojs/components'
import { getHistory } from '@/services/api'
import type { HistoryItem } from '@/types/api'
import '../learning/index.scss'
import './index.scss'

type HistoryFilter = '' | 'completed' | 'in_progress'

const filters: Array<{ label: string; value: HistoryFilter }> = [
  { label: '全部', value: '' },
  { label: '已完成', value: 'completed' },
  { label: '进行中', value: 'in_progress' },
]

export default function HistoryPage() {
  const [items, setItems] = useState<HistoryItem[]>([])
  const [keyword, setKeyword] = useState('')
  const [filter, setFilter] = useState<HistoryFilter>('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  async function load(nextKeyword = keyword, nextFilter = filter): Promise<void> {
    setLoading(true)
    try {
      setItems(await getHistory(nextKeyword.trim(), nextFilter))
      setError('')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '学习记录加载失败')
    } finally {
      setLoading(false)
    }
  }

  function chooseFilter(value: HistoryFilter): void {
    setFilter(value)
    load(keyword, value)
  }

  useEffect(() => { load('', '') }, [])

  return (
    <View className='learning-page'>
      <View className='learning-appbar'><Text className='settings' onClick={() => Taro.navigateBack()}>‹</Text><Text>学习记录</Text><View className='settings-placeholder' /></View>
      <View className='search'><Text>⌕</Text><Input value={keyword} placeholder='搜索学过的知识' onInput={(event) => setKeyword(event.detail.value)} onConfirm={() => load()} /></View>
      <View className='filters'>{filters.map((item) => <Text key={item.value || 'all'} className={filter === item.value ? 'active' : ''} onClick={() => chooseFilter(item.value)}>{item.label}</Text>)}</View>
      {loading ? <View className='empty-line'>正在整理学习记录…</View> : error ? <View className='empty-line'><Text>{error}</Text><Text className='retry-link' onClick={() => load()}>重新加载</Text></View> : items.length ? items.map((item) => (
        <View className='history-item' key={item.attempt_id} onClick={() => Taro.navigateTo({ url: `/pages/history/detail?attemptId=${item.attempt_id}` })}>
          <View className={`history-mark ${item.status === 'in_progress' ? 'pending' : ''}`} />
          <View><Text className='row-title'>{item.title}</Text><Text className='muted'>{item.total_count} 道题 · 用时 {Math.max(1, Math.round(item.duration_ms / 60000))} 分钟</Text><Text className='muted'>{item.status === 'completed' ? `答对 ${item.correct_count} 道 · +${item.earned_xp} XP` : '尚未完成'}</Text></View>
          <View>{item.status === 'completed' ? <><Text className='score'>{item.accuracy}%</Text><Text className='muted'>正确率</Text></> : <Text className='continue-label'>查看</Text>}</View>
        </View>
      )) : <View className='empty-line'>{keyword ? '没有找到相关记录。你可以换一个关键词。' : '还没有学习记录。完成第一次闯关后，记录会出现在这里。'}</View>}
    </View>
  )
}
