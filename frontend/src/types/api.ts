export type QuestionType = 'single' | 'multiple' | 'judge'
export type Difficulty = 'easy' | 'medium' | 'hard'

export interface Option {
  key: string
  text: string
}

export interface Question {
  id?: string
  question_id: string
  type: QuestionType
  stem: string
  options: Option[]
  answer?: string[]
  explanation?: string
  knowledge_point: string
  difficulty: Difficulty
}

export interface Quiz {
  quiz_id: string
  attempt_id: string
  title: string
  summary: string
  user_input: string
  questions: Question[]
}

export interface UserProfile { user_id: string; nickname: string; avatar_url: string; profile_completed: boolean; xp_total: number; current_streak_days: number; joined_at: string }
export interface LoginData { access_token: string; access_token_expires_in: number; refresh_token: string; refresh_token_expires_in: number; is_new_user: boolean; user: UserProfile }
export interface AnswerResult { is_correct: boolean; correct_answers: string[]; explanation: string; knowledge_point: string; earned_xp_delta: number; progress: { answered: number; total: number } }
export interface CompletionResult { attempt_id: string; status: string; correct_count: number; total_count: number; accuracy: number; earned_xp: number; xp_total: number; current_streak_days: number }

export interface HistoryItem {
  attempt_id: string
  title: string
  status: 'in_progress' | 'completed' | 'abandoned'
  correct_count: number
  total_count: number
  accuracy: number
  earned_xp: number
  duration_ms: number
  started_at: string
  completed_at: string | null
}

export interface LearningOverview {
  user: Pick<UserProfile, 'nickname' | 'avatar_url' | 'xp_total' | 'current_streak_days'>
  total_completed: number
  total_answered: number
  total_correct: number
  average_accuracy: number
  week_completed: number
  week_xp: number
  recent_attempt_id: string | null
  recent_remaining: number
  recent_history: HistoryItem[]
  week_days: Record<string, { completed: number; xp: number }>
}

export interface AnswerRecord {
  question_id: string
  selected_answers: string[]
  is_correct: boolean
  duration_ms: number
}

export interface Report {
  accuracy: number
  correct_count: number
  total_count: number
  earned_xp: number
  mastered_points: string[]
  weak_points: string[]
  three_line_summary: string[]
  advice: string[]
  share_quote: string
}

export interface ApiEnvelope<T> {
  code: number
  message: string
  data: T | null
}
