import Taro from '@tarojs/taro'
import type { AnswerRecord, ApiEnvelope, Question, Quiz, Report } from '@/types/api'

const API_BASE_URL = process.env.TARO_APP_API_BASE_URL || 'http://127.0.0.1:8000'

export class ApiError extends Error {
  constructor(message: string, public code = -1) {
    super(message)
    this.name = 'ApiError'
  }
}

async function post<T>(path: string, data: unknown): Promise<T> {
  try {
    const response = await Taro.request<ApiEnvelope<T>>({
      url: `${API_BASE_URL}${path}`,
      method: 'POST',
      data,
      timeout: 60_000,
      header: { 'content-type': 'application/json' },
    })
    const envelope = response.data
    if (response.statusCode < 200 || response.statusCode >= 300 || envelope.code !== 0 || !envelope.data) {
      throw new ApiError(envelope.message || '请求失败，请稍后重试', envelope.code)
    }
    return envelope.data
  } catch (error) {
    if (error instanceof ApiError) throw error
    throw new ApiError('网络连接失败，请检查后重试')
  }
}

export function generateQuiz(userInput: string): Promise<Quiz> {
  return post('/api/v1/quiz/generate', {
    user_input: userInput,
    question_count: 5,
    difficulty: 'mixed',
  })
}

export function generateReport(
  quiz: Quiz,
  answerRecords: AnswerRecord[],
): Promise<Report> {
  return post('/api/v1/report/generate', {
    quiz_id: quiz.quiz_id,
    topic: quiz.title,
    questions: quiz.questions as Question[],
    answer_records: answerRecords,
  })
}

