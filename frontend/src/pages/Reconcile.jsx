import React, { useEffect, useState } from 'react'
import { api } from '../api'
import { DisableLamp } from '../components/FreezeBadge'

const surface_panel = true
export default function Reconcile() {
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  const load = () => api('/对账').then(setData).catch((e) => setErr(e.message))
  useEffect(() => { load() }, [])
  if (err) return <div className="panel err">{err}</div>
  if (!data) return <div className="panel">加载中</div>
  const s = data.发版统计 || {}
  const disable = data.停用对账 || {}
  const gaps = data.gaps || data.缺口 || disable.缺口 || []
  const gapCount = data.停用差额 ?? data.差额 ?? gaps.length
  return (
    <div className="panel">
      <h2>发布对账 · 停用差额</h2>
      <div className="row">
        <DisableLamp light={disable.灯 || (gapCount ? 'gap' : 'clean')} text={disable.灯文案} count={gapCount} data-testid="reconcile-disable-lamp" />
        <span data-field="停用差额" data-gap-count={gapCount}>停用事件/写口/在途差额：{gapCount}</span>
        <span data-field="ledger_ok">ledger_ok={String(data.ledger_ok ?? disable.ledger_ok ?? gapCount === 0)}</span>
      </div>
      {gapCount > 0 && (
        <ul className="gap-list" data-testid="reconcile-gap-list">
          {gaps.map((g, i) => (
            <li key={`${g.code}-${i}`} data-reconcile-gap={g.code}>
              <b>{g.code}</b>{g.应用 ? ` · ${g.应用}` : ''}：{g.缺口 || g.message}
            </li>
          ))}
        </ul>
      )}
      <div className="grid">
        {Object.entries(s).map(([k, v]) => (
          <div className="stat" key={k}><div className="n">{v}</div><div className="l">{k}</div></div>
        ))}
        <div className="stat"><div className="n">{data.晋升事件数}</div><div className="l">晋升事件数</div></div>
        <div className={`stat ${gapCount ? 'stat-gap' : ''}`}><div className="n">{gapCount}</div><div className="l">停用差额/缺口</div></div>
      </div>
      <h2>名册与实例</h2>
      <div className="table-wrap">
        <table>
          <thead><tr><th>应用</th><th>环境</th><th>名册版本</th><th>实例版本们</th><th>红灯数</th></tr></thead>
          <tbody>
            {(data.名册与实例 || []).map((r, i) => (
              <tr key={i}><td>{r.应用}</td><td>{r.环境}</td><td>{r.名册版本}</td><td>{r.实例版本们 || '-'}</td><td>{r.红灯数}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="row"><button type="button" className="secondary" onClick={load}>刷新</button></div>
    </div>
  )
}
