import { useEffect, useMemo, useRef, useState } from 'react'
import Taro from '@tarojs/taro'
import { Button, Image, Text, View } from '@tarojs/components'
import pandaHappy from '@/assets/panda-happy.svg'
import pandaSad from '@/assets/panda-sad.svg'
import { generateReport } from '@/services/api'
import { clearSession, getSession, saveAnswers, saveReport } from '@/store/session'
import type { AnswerRecord } from '@/types/api'
import { isAnswerCorrect, questionTypeLabel } from '@/utils/quiz'
import './index.scss'

type QuizView = 'question' | 'feedback' | 'complete'

export default function QuizPage() {
  const initial = getSession()
  const quiz = initial.quiz
  const [view, setView] = useState<QuizView>('question')
  const [questionIndex, setQuestionIndex] = useState(0)
  const [selected, setSelected] = useState<string[]>([])
  const [records, setRecords] = useState<AnswerRecord[]>([])
  const [hearts, setHearts] = useState(3)
  const [earnedXp, setEarnedXp] = useState(0)
  const [reportLoading, setReportLoading] = useState(false)
  const questionStartedAt = useRef(Date.now())

  useEffect(() => {
    if (!quiz) Taro.reLaunch({ url: '/pages/index/index' })
  }, [quiz])

  const question = quiz?.questions[questionIndex]
  const lastRecord = records[records.length - 1]
  const correctCount = useMemo(() => records.filter((record) => record.is_correct).length, [records])

  if (!quiz || !question) return <View className='page-shell' />
  const currentQuiz = quiz
  const currentQuestion = question

  function leaveQuiz(): void {
    Taro.showModal({
      title: '退出本次闯关？',
      content: '当前答题进度不会保留。',
      confirmText: '退出',
      confirmColor: '#e96655',
      success: (result) => {
        if (result.confirm) {
          clearSession()
          Taro.reLaunch({ url: '/pages/index/index' })
        }
      },
    })
  }

  function choose(key: string): void {
    if (currentQuestion.type === 'multiple') {
      setSelected((current) => current.includes(key) ? current.filter((item) => item !== key) : [...current, key])
      return
    }
    setSelected([key])
  }

  function checkAnswer(): void {
    if (!selected.length) return
    const correct = isAnswerCorrect(currentQuestion, selected)
    const record: AnswerRecord = {
      question_id: currentQuestion.id,
      selected_answers: selected,
      is_correct: correct,
      duration_ms: Math.max(0, Date.now() - questionStartedAt.current),
    }
    const nextRecords = [...records, record]
    setRecords(nextRecords)
    saveAnswers(nextRecords)
    if (correct) setEarnedXp((value) => value + 20)
    else setHearts((value) => Math.max(0, value - 1))
    setView('feedback')
  }

  function continueQuiz(): void {
    if (questionIndex === currentQuiz.questions.length - 1) {
      setView('complete')
      return
    }
    setQuestionIndex((value) => value + 1)
    setSelected([])
    questionStartedAt.current = Date.now()
    setView('question')
  }

  async function openReport(): Promise<void> {
    if (reportLoading) return
    setReportLoading(true)
    try {
      const report = await generateReport(currentQuiz, records)
      saveReport(report)
      await Taro.navigateTo({ url: '/pages/report/index' })
    } catch (error) {
      const message = error instanceof Error ? error.message : '报告生成失败，请稍后重试'
      Taro.showToast({ title: message, icon: 'none', duration: 2600 })
    } finally {
      setReportLoading(false)
    }
  }

  if (view === 'feedback' && lastRecord) {
    const correct = lastRecord.is_correct
    const selectedText = question.options.filter((option) => selected.includes(option.key)).map((option) => `${option.key} ${option.text}`).join('、')
    const answerText = question.options.filter((option) => question.answer.includes(option.key)).map((option) => `${option.key} ${option.text}`).join('、')
    return (
      <View className='page-shell feedback-page'>
        <View className='appbar'><Text className='icon-button' onClick={leaveQuiz}>×</Text><Text className='appbar-title'>第 {questionIndex + 1} 题讲解</Text><View className='mini-xp'>☀ {initial.baseXp + earnedXp}</View></View>
        <View className='feedback-stage'><Image className='feedback-panda panda-image' src={correct ? pandaHappy : pandaSad} mode='aspectFit' /></View>
        <Text className={`feedback-heading ${correct ? '' : 'wrong-title'}`}>{correct ? '答对了，竹子长高啦！' : '这一步容易混淆'}</Text>
        {correct ? (
          <View className='reward-line'><Text className='reward-pill'>＋20 XP</Text><Text className='reward-pill'>答对 {correctCount} 题</Text></View>
        ) : (
          <View className='answer-correction'><Text>你的答案：{selectedText}</Text><Text className='right-answer'>正确答案：{answerText}</Text></View>
        )}
        <View className={`explanation ${correct ? '' : 'wrong-note'}`}>
          <Text className='explanation-title'>{correct ? '为什么这样选？' : '团团帮你理一遍'}</Text>
          <Text className='explanation-copy'>{question.explanation}</Text>
          <Text className='knowledge-tag'>{correct ? `知识点：${question.knowledge_point}` : '已加入本轮重点复习'}</Text>
        </View>
        <View className='feedback-action'><Button className='primary-button' onClick={continueQuiz}>{questionIndex === quiz.questions.length - 1 ? '查看通关结果' : correct ? '继续下一题' : '我明白了，继续'}</Button></View>
      </View>
    )
  }

  if (view === 'complete') {
    const accuracy = Math.round(correctCount * 100 / quiz.questions.length)
    return (
      <View className='page-shell complete-page'>
        <View className='appbar'><View className='bar-space' /><Text className='appbar-title'>闯关完成</Text><Text className='icon-button' onClick={() => Taro.reLaunch({ url: '/pages/index/index' })}>×</Text></View>
        <View className='complete-content'>
          <View className='flag-scene'><Image className='complete-panda panda-image' src={pandaHappy} mode='aspectFit' /><View className='flag-pole'><Text className='flag'>通关！</Text></View></View>
          <Text className='complete-title'>你闯过了 {quiz.title.replace('闯关', '').trim()}</Text>
          <Text className='complete-copy'>五节竹子已经全部点亮。</Text>
          <View className='reward-board'>
            <View><Text className='reward-number'>{correctCount} / {quiz.questions.length}</Text><Text className='reward-label'>答对题数</Text></View>
            <View><Text className='reward-number'>{accuracy}%</Text><Text className='reward-label'>正确率</Text></View>
            <View><Text className='reward-number'>＋{earnedXp}</Text><Text className='reward-label'>本次 XP</Text></View>
          </View>
          <View className='complete-actions'>
            <Button className='primary-button' loading={reportLoading} onClick={openReport}>{reportLoading ? '生成复盘中' : '查看复盘报告'}</Button>
            <Button className='secondary-button' onClick={() => { clearSession(); Taro.reLaunch({ url: '/pages/index/index' }) }}>回到首页</Button>
          </View>
        </View>
      </View>
    )
  }

  return (
    <View className='page-shell quiz-page'>
      <View className='appbar'><Text className='icon-button' onClick={leaveQuiz}>×</Text><Text className='appbar-title quiz-app-title'>{quiz.title}</Text><View className='mini-xp'>☀ {initial.baseXp + earnedXp}</View></View>
      <View className='quiz-top'>
        <View className='bamboo-progress'>
          {quiz.questions.map((item, index) => <View key={item.id} className={`progress-piece ${index < questionIndex ? 'done' : index === questionIndex ? 'current' : ''}`} />)}
        </View>
        <Text className='heart'>♥ {hearts}</Text>
      </View>
      <View className='question-meta'><Text className='type-badge'>{questionTypeLabel(question)}</Text><Text>第 {questionIndex + 1} / {quiz.questions.length} 题</Text></View>
      <Text className='question-title'>{question.stem}</Text>
      {question.type === 'multiple' && <Text className='multiple-hint'>请选择全部正确选项</Text>}
      <View className='option-list'>
        {question.options.map((option) => (
          <View key={option.key} className={`option ${selected.includes(option.key) ? 'selected' : ''}`} onClick={() => choose(option.key)}>
            <Text className='option-key'>{option.key}</Text><Text className='option-text'>{option.text}</Text>
          </View>
        ))}
      </View>
      <View className='quiz-submit'><Button className='primary-button' disabled={!selected.length} onClick={checkAnswer}>检查答案</Button></View>
    </View>
  )
}
