import request from './request'

export function askTeacherRuleAssistant(data) {
  return request({
    url: '/teacher-rule-assistant/ask',
    method: 'post',
    data
  })
}
