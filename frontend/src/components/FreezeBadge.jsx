import React from 'react'

// 全站唯一的“退役 / 冻结 / 只读”呈现规则：
// 是否冻结一律看后端按规则派生的 row.冻结（来源 apps.status='退役'）。
export function isFrozen(row) {
  return !!(row && (row.冻结 === true || row.冻结 === 1 || row.是否冻结 === true))
}

export function FrozenBadge({ row }) {
  if (!isFrozen(row)) return null
  return (
    <span className="badge badge-frozen" data-frozen="1" title="应用已退役，未收口发版单冻结只读">
      已冻结
    </span>
  )
}

export function AppStatusBadge({ status, state }) {
  if (status === '退役') {
    return <span className="badge badge-retired" data-retired="1">退役</span>
  }
  if (status === '停用') {
    return <span className="badge badge-suspended">停用</span>
  }
  return <span className="badge badge-open">启用</span>
}

// 锁定但仍可点击：保留“退役后再点晋升/放行”的探针路径，由后端给明确拒绝回执；
// 视觉与 aria 都表达只读，不使用原生 disabled 拦截夹具的点击。
export function LockedButton({ frozen, className = '', children, ...rest }) {
  const cls = `${className} ${frozen ? 'is-locked' : ''}`.trim()
  return (
    <button
      type="button"
      className={cls}
      aria-disabled={frozen ? 'true' : undefined}
      data-frozen-action={frozen ? '1' : undefined}
      title={frozen ? '已退役冻结：写口关闭，点击将由后端驳回' : rest.title}
      {...rest}
    >
      {children}
    </button>
  )
}

export function FateBanner({ row }) {
  if (!isFrozen(row)) return null
  return (
    <p className="fate-banner" data-fate-banner="1">
      该应用已退役：此单为冻结在途单，只读可核；入闸 / 晋升 / 放行写口均已关闭，点击会被驳回且不会推进环境链。
    </p>
  )
}
