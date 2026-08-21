/**
 * Types for email snippets (text templates with variables)
 */

export interface Snippet {
  id: string
  name: string
  content: string
  subject?: string  // Optional subject line
  to?: string[]     // Optional default recipients
  cc?: string[]     // Optional CC recipients
  bcc?: string[]    // Optional BCC recipients
  category?: string // Optional category for organization
  is_private: boolean
  owner_email?: string | null
  created_at: string
  updated_at: string
  use_count: number
}

export interface CreateSnippetPayload {
  name: string
  content: string
  subject?: string
  to?: string[]
  cc?: string[]
  bcc?: string[]
  category?: string
  is_private?: boolean
}

export interface UpdateSnippetPayload {
  name?: string
  content?: string
  subject?: string
  to?: string[]
  cc?: string[]
  bcc?: string[]
  category?: string
  is_private?: boolean
}

export interface SnippetsResponse {
  snippets: Snippet[]
  total: number
}

// Sharing types
export interface SharedSnippet extends Snippet {
  share_id: string
  shared_by: string
  shared_at: string
}

export interface SnippetShareInfo {
  email: string
  shared_at: string
  share_id: string
}

export interface ShareSnippetPayload {
  email: string
}

export interface SharedSnippetsResponse {
  snippets: SharedSnippet[]
  total: number
}

export interface SnippetSharesResponse {
  shares: SnippetShareInfo[]
  total: number
}

// Available variables that can be used in snippets.
// `name` is the exact token inserted into the snippet body. `labelKey` /
// `descriptionKey` are i18n keys (settings namespace) — resolved at render
// time so the chip labels follow the user's locale.
export const SNIPPET_VARIABLES = [
  { name: '{first_name}', labelKey: 'snippet_var_first_name_label', descriptionKey: 'snippet_var_first_name_description' },
  { name: '{last_name}',  labelKey: 'snippet_var_last_name_label',  descriptionKey: 'snippet_var_last_name_description' },
  { name: '{full_name}',  labelKey: 'snippet_var_full_name_label',  descriptionKey: 'snippet_var_full_name_description' },
  { name: '{date}',       labelKey: 'snippet_var_date_label',       descriptionKey: 'snippet_var_date_description' },
  { name: '{time}',       labelKey: 'snippet_var_time_label',       descriptionKey: 'snippet_var_time_description' },
] as const

export type SnippetVariableName = typeof SNIPPET_VARIABLES[number]['name']

export interface SnippetShareInfo {
  share_id: string
  email: string
  shared_at: string
}
