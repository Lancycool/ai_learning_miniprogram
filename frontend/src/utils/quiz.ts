import type { Question } from '@/types/api'

export function isAnswerCorrect(question: Question, selected: string[]): boolean {
  if (!question.answer || selected.length !== question.answer.length) return false
  const actual = [...selected].sort()
  const expected = [...question.answer].sort()
  return actual.every((value, index) => value === expected[index])
}

export function questionTypeLabel(question: Question): string {
  if (question.type === 'multiple') return '多选题'
  if (question.type === 'judge') return '判断题'
  return '单选题'
}
