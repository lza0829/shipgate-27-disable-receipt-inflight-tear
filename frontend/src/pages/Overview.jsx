import React, { useEffect, useState } from 'react'
import { api } from '../api'
import { DisableLamp, FrozenBadge, isFrozen } from '../components/FreezeBadge'

const surface_panel = true
export default function Overview() {
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  const load = () => api('/总览').then(setData).catch((e) => setErr(e.message))
  useEffect(() => { load() }, [])
  if (err) return <div className="panel err">{err}</div>
  if (!data) return <div className="panel">加载中</div>
  const d = data.分布 || {}
  const summary = data.汇总 || {}
  const inflight = data.在途 || []
  const frozenCount = summary.冻结在途数 ?? inflight.filter(isFrozen).length
  const inflightCount = summary.在途数 ?? inflight.length
  const disableCore = data.停用总览 || {}
  const disableLamp = data.停用灯 || disableCore.灯 || 'off'
  const disableGaps = data.停用缺口 || disableCore.缺口 || []
  const disableGapCount = data.停用缺口数 ?? disableCore.缺口数 ?? disableGaps.length
  return (
    <div className="panel">
      <h2>总览</h2>
      <p className="muted">退役命运：{data.退役策略 || '带在途退役并冻结写口'}。冻结单不删除、不隐身，仍计入在途并单独露出。</p>

      <section className={`overview-disable lamp-border-${disableLamp}`} data-testid="overview-disable-panel">
        <div className="row">
          <DisableLamp light={disableLamp} text={data.停用灯文案 || disableCore.灯文案} count={disableGapCount} data-testid="overview-disable-lamp" />
          <span className="muted">总览末段对齐停用核、对账差额与审计；写口仍开时只允许缺口灯，不得无缺口长亮绿灯。</span>
        </div>
        {disableGaps.length > 0 && (
          <ul className="gap-list compact" data-testid="overview-gap-list">
            {disableGaps.slice(0, 8).map((g, i) => (
              <li key={`${g.code}-${i}`} data-overview-gap={g.code}>
                <b>{g.应用 || `应用#${g.应用编号 ?? ''}`}</b>：{g.缺口 || g.message}
              </li>
            ))}
          </ul>
        )}
      </section>

      <div className="grid">
        <div className="stat"><div className="n" data-field="在途数">{inflightCount}</div><div className="l">在途（未收口）</div></div>
        <div className={`stat ${frozenCount ? 'frozen-stat' : ''}`}><div className="n" data-field="冻结在途数">{frozenCount}</div><div className="l">冻结在途</div></div>
        {Object.entries(d).map(([k, v]) => (
          <div className="stat" key={k}><div className="n">{v}</div><div className="l">{k}</div></div>
        ))}
      </div>
      <h2>在途发版{frozenCount ? `（其中 ${frozenCount} 单冻结）` : ''}</h2>
      <div className="table-wrap">
        <table>
          <thead><tr><th>发版单号</th><th>应用</th><th>目标版本</th><th>状态</th><th>当前环境</th><th>流水线</th><th>冻结标</th><th>读写态</th></tr></thead>
          <tbody>
            {inflight.map((r) => (
              <tr key={r.编号} className={isFrozen(r) ? 'row-frozen' : ''} data-frozen={isFrozen(r) ? '1' : '0'}>
                <td>{r.发版单号}</td>
                <td>{r.应用}</td>
                <td>{r.目标版本}</td>
                <td>{r.状态}</td>
                <td>{r.当前环境 || '-'}</td>
                <td>{r.流水线}</td>
                <td><FrozenBadge row={r} /></td>
                <td>{r.读写态 || (isFrozen(r) ? '只读' : '可写')}</td>
              </tr>
            ))}
            {inflight.length === 0 && (
              <tr><td colSpan={8} className="muted">当前无在途发版单</td></tr>
            )}
          </tbody>
        </table>
      </div>
      <h2>各环境版本</h2>
      <div className="table-wrap">
        <table>
          <thead><tr><th>应用</th><th>环境</th><th>版本</th><th>更新时间</th><th>冻结标</th></tr></thead>
          <tbody>
            {(data.环境版本 || []).map((v, i) => (
              <tr key={i} className={v.应用退役 ? 'row-frozen' : ''}>
                <td>{v.应用}</td><td>{v.环境}</td><td>{v.版本}</td><td>{v.更新时间}</td>
                <td>{v.冻结标 ? <span className="badge badge-frozen">{v.冻结标}</span> : <span className="muted">—</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="row"><button type="button" className="secondary" onClick={load}>刷新</button></div>
    </div>
  )
}
