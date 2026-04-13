import request from './request'

export function getGroupingSchemes(params) {
  return request({
    url: '/grouping/schemes',
    method: 'get',
    params
  })
}

export function generateGroupingWithProfile(data) {
  return request({
    url: '/grouping/generate-with-profile',
    method: 'post',
    data
  })
}

export function getGroupingSchemeDetail(id) {
  return request({
    url: `/grouping/schemes/${id}`,
    method: 'get'
  })
}

export function createGroupingScheme(data) {
  return request({
    url: '/grouping/schemes',
    method: 'post',
    data
  })
}

export function updateGroupingScheme(id, data) {
  return request({
    url: `/grouping/schemes/${id}`,
    method: 'put',
    data
  })
}

export function deleteGroupingScheme(id) {
  return request({
    url: `/grouping/schemes/${id}`,
    method: 'delete'
  })
}
