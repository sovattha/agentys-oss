export type ActivityType =
  | 'sync'
  | 'draft'
  | 'classify'
  | 'critique'
  | 'learning'
  | 'cleanup'
  | 'followup'

export interface ActivityItem {
  id: string
  type: ActivityType
  label: string
  startedAt: number
  progress?: number
  detail?: string
  emailId?: string
}

export interface ActivityState {
  activities: ActivityItem[]
  isActive: boolean
  primaryActivity: ActivityItem | null
  /** Brief "done" state shown after last activity completes */
  justFinished: boolean
  error: { message: string; timestamp: number } | null
}
