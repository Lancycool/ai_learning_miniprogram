export type TabIndex = 0 | 1

let activeTab: TabIndex = 0
const listeners = new Set<() => void>()

export function getActiveTab(): TabIndex {
  return activeTab
}

export function setActiveTab(tab: TabIndex): void {
  if (tab === activeTab) return
  activeTab = tab
  listeners.forEach((listener) => listener())
}

export function subscribeTabBar(listener: () => void): () => void {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}
