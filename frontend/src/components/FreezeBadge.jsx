import React from 'react'

// 全站唯一的“退役 / 停用收口 / 冻结 / 只读”呈现规则。
// 是否冻结优先看后端按规则派生的 row.冻结；停用与退役的文案分开，避免灯分叉。
export function isFrozen(row) {
  return !!(row && (row.冻结 === true || row.冻结 === 1 || row.是否冻结 === true))
}

export function isDisabledApp(row) {
  return !!(row && (
    row.状态 === '停用'
    || row.应用状态 === '停用'
    || row.停用 === true
    || row.停用标 === true
  ))
}

export function isRetiredApp(row) {
  return !!(row && (
    row.状态 === '退役'
    || row.应用状态 === '退役'
    || row.退役 === true
    || row.是否退役 === true
  ))
}

export function isTraceBypass(row) {
  return !!(row && (row.冻结旁路 === true || row.冻结旁路 === 1))
}

// Prefer the backend's replayable mouth map.  ``becauseStatus`` lets a page
// distinguish a normal state mismatch from a fate/disable closure.
export function isMouthClosed(row, mouth) {
  if (row?.写口 && typeof row.写口[mouth] === 'boolean') return row.写口[mouth] === false
  return isFrozen(row)
}

export function FrozenBadge({ row }) {
  if (!isFrozen(row)) return null
  let cls = 'badge badge-frozen'
  let text = '已冻结'
  let title = '应用已退役，未收口发版单冻结只读'
  let testId = 'frozen'

  if (isDisabledApp(row)) {
    cls = 'badge badge-disabled-close'
    text = '停用收口'
    title = '应用已停用：入闸 / 晋升 / 放行推进写口拒绝，在途单已留下收口痕迹'
    testId = 'disable-closed'
  } else if (isTraceBypass(row)) {
    cls = 'badge badge-bypass'
    text = '冻结旁路待核'
    title = '存在冻结痕迹但停用/退役标不同核，推进写口已失败关闭'
    testId = 'freeze-bypass'
  }

  return (
    <span className={cls} data-frozen="1" data-closure={testId} title={title}>
      {text}
    </span>
  )
}

export function AppStatusBadge({ status, state, light }) {
  if (status === '退役' || String(status || '').includes('退役')) {
    return <span className="badge badge-retired" data-retired="1" data-half-retired={status === '退役' ? undefined : '1'}>
      {status === '退役' ? '退役' : `退役半截·${status}`}
    </span>
  }
  if (status === '停用' || String(status || '').includes('停用')) {
    const half = status !== '停用'
    return (
      <span
        className={`badge badge-suspended ${light === 'gap' || half ? 'badge-gap' : ''}`.trim()}
        data-disabled="1"
        data-half-disable={half ? '1' : undefined}
        data-disable-light={light || (state?.灯 ?? (half ? 'gap' : 'rule-only'))}
      >
        {half ? `停用半截·${status}` : `停用${light === 'gap' ? '·缺口' : ''}`}
      </span>
    )
  }
  if (status && status !== '启用') {
    return (
      <span className="badge badge-gap" data-dirty-closed="1" data-disable-light={light || 'gap'}>
        异常收口·{status}
      </span>
    )
  }
  return <span className="badge badge-open">启用</span>
}

// 锁定但仍可点击：保留“停用/退役后再点写口”的探针路径，由后端给明确拒绝回执；
// 视觉与 aria 都表达关闭，不使用原生 disabled 拦截夹具的点击。
export function LockedButton({ frozen, closed, className = '', children, mouth, ...rest }) {
  const locked = typeof closed === 'boolean' ? closed : frozen
  const cls = `${className} ${locked ? 'is-locked' : ''}`.trim()
  return (
    <button
      type="button"
      className={cls}
      aria-disabled={locked ? 'true' : undefined}
      data-frozen-action={frozen ? '1' : undefined}
      data-mouth={mouth}
      data-mouth-open={mouth && rest['data-open'] === undefined ? undefined : rest['data-open']}
      title={locked ? '写口已收口：点击保留为探针，将由后端驳回且不会推进状态' : rest.title}
      {...rest}
      data-open={rest['data-open'] ?? (mouth ? (!locked ? '1' : '0') : rest['data-open'])}
    >
      {children}
    </button>
  )
}

export function FateBanner({ row }) {
  if (!isFrozen(row)) return null
  const disabled = isDisabledApp(row)
  const bypass = isTraceBypass(row)
  const text = bypass
    ? '检测到冻结旁路半截态：推进写口已失败关闭；请在停用页/应用册重放收口，审计会补全事件。'
    : disabled
      ? '该应用已停用：此单已做停用收口，入闸 / 晋升 / 放行写口均关闭；按钮保留为点按探针，点击会被后端驳回。'
      : '该应用已退役：此单为冻结在途单，只读可核；入闸 / 晋升 / 放行写口均已关闭，点击会被驳回且不会推进环境链。'
  return (
    <p
      className={`fate-banner ${disabled ? 'disable-banner' : ''} ${bypass ? 'bypass-banner' : ''}`.trim()}
      data-fate-banner="1"
      data-disable-banner={disabled ? '1' : undefined}
      data-bypass-banner={bypass ? '1' : undefined}
    >
      {text}
    </p>
  )
}

export function DisableLamp({ light = 'off', text, count = 0, ...rest }) {
  const label = text || (light === 'clean' ? '停用干净' : light === 'gap' ? '停用缺口' : '未停用')
  return (
    <span
      className={`disable-lamp lamp-${light}`}
      data-disable-light={light}
      data-gap-count={count}
      role="status"
      {...rest}
    >
      <span className="lamp-dot" aria-hidden="true" />
      <span className="lamp-text">{label}</span>
      {light === 'gap' && count > 0 && <span className="lamp-count">{count}</span>}
    </span>
  )
}
