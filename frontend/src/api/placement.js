import request from './request'

export function getPlacementOverview(params) {
  return request({
    url: '/placement/overview',
    method: 'get',
    params
  })
}

export function generatePlacementWithProfile(data) {
  return request({
    url: '/placement/generate-with-profile',
    method: 'post',
    data
  })
}

export function validatePlacement(data) {
  return request({
    url: '/placement/validate',
    method: 'post',
    data
  })
}

export function confirmPlacement(data) {
  return request({
    url: '/placement/confirm',
    method: 'post',
    data
  })
}

export function getPlacementBatches(params) {
  return request({
    url: '/placement/batches',
    method: 'get',
    params
  })
}

export function getPlacementBatchDetail(id) {
  return request({
    url: `/placement/batches/${id}`,
    method: 'get'
  })
}
