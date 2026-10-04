import Taro from '@tarojs/taro'
import type { AnswerRecord, Quiz, Report } from '@/types/api'
import { getAuth } from './auth'

const STORAGE_KEY = 'bamboo_quiz_session_v1'

export interface LearningSession {
  quiz: Quiz | null
  answerRecords: AnswerRecord[]
  report: Report | null
  attemptId: string
  baseXp: number
  ownerId?: string
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
  if (session.ownerId && session.ownerId !== getAuth().user?.user_id) {
    clearSession()
  }
  return session
}

export function startSession(quiz: Quiz): void {
  session = { ...emptySession, quiz, attemptId: quiz.attempt_id, ownerId: getAuth().user?.user_id }
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
