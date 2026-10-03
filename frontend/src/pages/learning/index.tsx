import { useState } from 'react'
import Taro, { useDidShow } from '@tarojs/taro'
import { Image, Text, View } from '@tarojs/components'
import pandaLogo from '@/assets/panda-logo.svg'
import { assetUrl, ensureLogin, getOverview } from '@/services/api'
import { setActiveTab } from '@/store/navigation'
import type { LearningOverview } from '@/types/api'
import './index.scss'

function formatDate(value: string | null): string {
  if (!value) return '刚刚'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return `${date.getMonth() + 1}月${date.getDate()}日`
}

export default function LearningPage() {
  const [data, setData] = useState<LearningOverview | null>(null)
  const [error, setError] = useState('')

  async function load(): Promise<void> {
    try {
      await ensureLogin()
      setData(await getOverview())
      setError('')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '学习记录加载失败')
    }
  }

  useDidShow(() => {
    setActiveTab(1)
    load()
  })

  if (error) {
    return <View className='center-state tab-page'><Text>{error}</Text><Text className='state-action' onClick={load}>重新加载</Text></View>
  }
  if (!data) return <View className='center-state tab-page'><Text>团团正在整理学习记录…</Text></View>

  return (
    <View className='learning-page tab-page'>
      <View className='learning-appbar'>
        <Text className='page-title'>我的</Text>
        <Text className='settings' onClick={() => Taro.navigateTo({ url: '/pages/settings/index' })}>⚙</Text>
      </View>

      <View className='profile-summary' onClick={() => Taro.navigateTo({ url: '/pages/profile/index' })}>
        <View className='avatar'><Image src={data.user.avatar_url.startsWith('/avatars/') || data.user.avatar_url.startsWith('http') ? assetUrl(data.user.avatar_url) : pandaLogo} mode='aspectFill' /></View>
        <View className='profile-copy'>
          <Text className='profile-name'>{data.user.nickname}</Text>
          <Text className='muted'>连续学习 {data.user.current_streak_days} 天</Text>
        </View>
        <View className='profile-xp'><Text>☀</Text><Text>{data.user.xp_total} XP</Text></View>
        <Text className='profile-go'>›</Text>
      </View>

      <View className='stats-board'>
        <View><Text className='stat-number'>{data.total_completed}</Text><Text className='stat-label'>完成闯关</Text></View>
        <View><Text className='stat-number'>{data.total_correct}</Text><Text className='stat-label'>累计答对</Text></View>
        <View><Text className='stat-number'>{data.average_accuracy}%</Text><Text className='stat-label'>平均正确率</Text></View>
      </View>

      <View className='week-note'>
        <View><Text className='week-title'>这周的竹子</Text><Text className='week-copy'>完成 {data.week_completed} 关，获得 {data.week_xp} XP</Text></View>
        <View className='week-bamboo'><View /><View /><View /></View>
      </View>

      <View className='quick-links'>
        <View onClick={() => Taro.navigateTo({ url: '/pages/history/index' })}><Text className='quick-icon history-icon'>记</Text><Text>全部记录</Text></View>
        <View onClick={() => Taro.navigateTo({ url: '/pages/mistakes/index' })}><Text className='quick-icon mistake-icon'>错</Text><Text>错题本</Text></View>
        <View onClick={() => Taro.navigateTo({ url: '/pages/monthly-report/index' })}><Text className='quick-icon report-icon'>报</Text><Text>月度报告</Text></View>
      </View>

      <View className='section-head'>
        <Text>最近闯关</Text>
        {data.recent_history.length > 0 && <Text onClick={() => Taro.navigateTo({ url: '/pages/history/index' })}>查看全部</Text>}
      </View>

      {data.recent_history.length ? (
        <View className='recent-list'>
          {data.recent_history.map((item) => (
            <View className='history-row' key={item.attempt_id} onClick={() => Taro.navigateTo({ url: `/pages/history/detail?attemptId=${item.attempt_id}` })}>
              <View className={`history-result ${item.accuracy >= 80 ? 'strong' : ''}`}><Text>{item.accuracy}%</Text></View>
              <View className='history-copy'><Text className='row-title'>{item.title}</Text><Text className='muted'>{formatDate(item.completed_at || item.started_at)} · 答对 {item.correct_count}/{item.total_count}</Text></View>
              <Text className='history-xp'>+{item.earned_xp} XP</Text>
              <Text className='history-go'>›</Text>
            </View>
          ))}
        </View>
      ) : (
        <View className='empty-history'>
          <Text className='empty-title'>这里还没有闯关记录</Text>
          <Text className='muted'>完成第一组题后，答题结果会保存在这里。</Text>
          <Text className='empty-action' onClick={() => Taro.switchTab({ url: '/pages/index/index' })}>去闯第一关</Text>
        </View>
      )}
    </View>
  )
}
