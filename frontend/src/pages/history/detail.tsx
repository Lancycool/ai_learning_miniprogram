import { useEffect, useState } from 'react'
import Taro, { useRouter } from '@tarojs/taro'
import { Text, View } from '@tarojs/components'
import { getAttempt } from '@/services/api'
import '../learning/index.scss'
import './index.scss'

export default function Detail() {
  const id = useRouter().params.attemptId || ''
  const [data, setData] = useState<any>()
  const [error, setError] = useState('')

  useEffect(() => {
    getAttempt(id).then(setData).catch((reason) => setError(reason instanceof Error ? reason.message : '详情加载失败'))
  }, [id])

  if (error) return <View className='center-state'><Text>{error}</Text><Text className='state-action' onClick={() => Taro.navigateBack()}>返回记录</Text></View>
  if (!data) return <View className='center-state'>正在读取闯关详情…</View>

  return (
    <View className='learning-page history-detail-page'>
      <View className='learning-appbar'><Text className='settings' onClick={() => Taro.navigateBack()}>‹</Text><Text>闯关详情</Text><Text className='detail-score'>{data.accuracy}%</Text></View>
      <View className='detail-summary'>
        <Text className='detail-title'>{data.title}</Text>
        <Text className='detail-meta'>答对 {data.correct_count}/{data.total_count} · 获得 {data.earned_xp} XP</Text>
      </View>
      {data.report && <View className='report-recap'><Text className='recap-title'>本次复盘</Text>{data.report.three_line_summary.map((line: string) => <Text className='recap-line' key={line}>· {line}</Text>)}{data.report.weak_points.length > 0 && <Text className='weak-points'>建议再看：{data.report.weak_points.join('、')}</Text>}</View>}
      <Text className='detail-section-title'>答题情况</Text>
      {data.questions.map((question: any, index: number) => (
        <View className='mistake-topic' key={question.question_id}>
          <View className='mistake-head'><Text>第 {index + 1} 题</Text><Text className={question.result?.is_correct ? 'right' : 'wrong'}>{question.result ? (question.result.is_correct ? '答对' : '答错') : '未作答'}</Text></View>
          <Text className='question-copy'>{question.stem}</Text>
          {question.result && <View className='answer-note'><Text>你的答案：{question.result.selected_answers.join('、')}</Text><Text>正确答案：{question.answer.join('、')}</Text><Text>{question.explanation}</Text></View>}
        </View>
      ))}
    </View>
  )
}
