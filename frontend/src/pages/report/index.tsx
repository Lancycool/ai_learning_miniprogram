import { useEffect, useState } from 'react'
import Taro, { useShareAppMessage } from '@tarojs/taro'
import { Button, Text, View } from '@tarojs/components'
import { getSession, startSession } from '@/store/session'
import { createAttempt, getAttempt } from '@/services/api'
import WebSearchInfo from '@/components/WebSearchInfo'
import type { WebSearchMetadata } from '@/types/api'
import './index.scss'

export default function ReportPage() {
  const session = getSession()
  const { quiz, report } = session
  const [searchMetadata, setSearchMetadata] = useState<WebSearchMetadata | null | undefined>(quiz?.web_search)
  const [completed, setCompleted] = useState(false)
  useEffect(() => {
    let active = true
    if (quiz?.attempt_id) getAttempt(quiz.attempt_id).then((data) => {
      if (active) { setSearchMetadata(data.web_search); setCompleted(data.status === 'completed') }
    }).catch(() => undefined)
    return () => { active = false }
  }, [quiz?.attempt_id])

  useEffect(() => {
    if (!quiz || !report) Taro.reLaunch({ url: '/pages/index/index' })
  }, [quiz, report])

  useShareAppMessage(() => ({
    title: report?.share_quote || '我在竹知岛完成了一次知识闯关',
    path: '/pages/index/index',
  }))

  if (!quiz || !report) return <View className='page-shell' />

  async function replay(): Promise<void> {
    const attempt = await createAttempt(quiz!.quiz_id, 'replay')
    startSession({ ...quiz!, attempt_id: attempt.attempt_id, questions: attempt.questions, web_search: attempt.web_search })
    Taro.redirectTo({ url: '/pages/quiz/index' })
  }

  return (
    <View className='page-shell report-page'>
      <View className='appbar'><Text className='icon-button' onClick={() => Taro.navigateBack()}>‹</Text><Text className='appbar-title'>本次复盘</Text><Text className='icon-button' onClick={() => Taro.navigateTo({ url: '/pages/poster/index' })}>↗</Text></View>
      <View className='report-content'>
        <WebSearchInfo metadata={searchMetadata} completed={completed} />
        <View className='report-hero'>
          <View className='report-hero-copy'><Text className='report-hero-title'>{report.accuracy >= 80 ? '你已经理解了' : '你正在理解'}{`\n`}{quiz.title.replace('闯关', '').trim()}</Text><Text className='report-hero-description'>{report.weak_points.length ? `你需要再看看“${report.weak_points[0]}”。` : '你已经掌握了本轮的全部知识点。'}</Text></View>
          <View className='score-ring' style={{ background: `conic-gradient(#ffd76a 0 ${report.accuracy}%, rgba(255,255,255,.2) ${report.accuracy}% 100%)` }}><Text>{report.accuracy}%</Text></View>
        </View>
        <View className='report-section'>
          <Text className='section-title'>三句话带走今天的知识</Text>
          <View className='three-lines'>{report.three_line_summary.map((line, index) => <View className='summary-line' key={line}><Text className='line-number'>{index + 1}</Text><Text>{line}</Text></View>)}</View>
        </View>
        <View className='report-section'>
          <Text className='section-title'>你的掌握情况</Text>
          <View className='mastery-grid'>
            <View className='mastery-box'><Text className='mastery-title'>掌握得不错</Text><Text className='mastery-copy'>{report.mastered_points.length ? report.mastered_points.join('\n') : '本轮暂无完全掌握的知识点'}</Text></View>
            <View className='mastery-box weak'><Text className='mastery-title'>建议再看看</Text><Text className='mastery-copy'>{report.weak_points.length ? report.weak_points.join('\n') : '本轮没有明显薄弱点'}</Text></View>
          </View>
        </View>
        <View className='report-section'>
          <Text className='section-title'>团团的复习建议</Text>
          <View className='notice-card'><Text>{report.advice.join('\n')}</Text></View>
        </View>
        <View className='report-actions'>
          <Button className='secondary-button' onClick={replay}>再练一次</Button>
          <Button className='primary-button' onClick={() => Taro.navigateTo({ url: '/pages/poster/index' })}>生成分享卡</Button>
        </View>
      </View>
    </View>
  )
}
