import type { Quiz, Report } from '@/types/api'

export const PRIVATE_SHARE_QUOTE = '每一次练习，都是新的进步'
export function privateLearning(quiz?: Quiz | null, report?: Report | null): boolean {
  return Boolean(report?.is_private || quiz?.is_private || ['original', 'knowledge'].includes(quiz?.source_type || '') || quiz?.questions.some(q => q.sources))
}
export function shareContent(quiz: Quiz, report: Report) {
  const privateSource = privateLearning(quiz, report)
  return { quote: privateSource ? PRIVATE_SHARE_QUOTE : report.share_quote,
    score: privateSource ? `本次练习 · 掌握度 ${report.accuracy}%` : `《${quiz.title.replace('闯关', '').trim()}》 · 掌握度 ${report.accuracy}%` }
}
