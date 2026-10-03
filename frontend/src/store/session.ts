import Taro from '@tarojs/taro'
import type { AnswerRecord, Quiz, Report } from '@/types/api'

const STORAGE_KEY = 'bamboo_quiz_session_v1'

export interface LearningSession {
  quiz: Quiz | null
  answerRecords: AnswerRecord[]
  report: Report | null
  attemptId: string
  baseXp: number
}

const emptySession: LearningSession = {
  quiz: null,
  answerRecords: [],
  report: null,
  attemptId: '',
  baseXp: 120,
}

let session: LearningSession = loadSession()

function loadSession(): LearningSession {
  try {
    const stored = Taro.getStorageSync<LearningSession>(STORAGE_KEY)
    return stored && typeof stored === 'object' ? { ...emptySession, ...stored } : { ...emptySession }
  } catch {
    return { ...emptySession }
  }
}

function saveSession(): void {
  Taro.setStorageSync(STORAGE_KEY, session)
}

export function getSession(): LearningSession {
  return session
}

export function startSession(quiz: Quiz): void {
  session = { ...emptySession, quiz, attemptId: quiz.attempt_id }
  saveSession()
}

export function saveAnswers(answerRecords: AnswerRecord[]): void {
  session = { ...session, answerRecords }
  saveSession()
}

export function saveReport(report: Report): void {
  session = { ...session, report }
  saveSession()
}

export function clearSession(): void {
  session = { ...emptySession }
  Taro.removeStorageSync(STORAGE_KEY)
}
