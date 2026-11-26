import React, { useEffect, useState } from 'react'
import { api } from '../api'

const surface_panel = true
export default function Audit() {
  const [rows, setRows] = useState([])
  const [err, setErr] = useState('')
  const [kw, setKw] = useState('')
  const [applied, setApplied] = useState('')

  const load = (keyword = applied) => {
    const q = keyword ? `?关键字=${encodeURIComponent(keyword)}` : ''
    return api('/审计' + q).then(setRows).catch((e) => setErr(e.message))
  }
  useEffect(() => { load('') }, [])

  const search = async () => {
    setApplied(kw)
    try { setRows(await api('/审计' + (kw ? `?关键字=${encodeURIComponent(kw)}` : ''))) }
    catch (e) { setErr(e.message) }
  }

  return (
    <div className="panel">
      <h2>审计流水</h2>
      <p className="muted">退役动作、逐单冻结、半截重放收口都会落审计，可按“退役 / 冻结 / 收口”串查。</p>
      {err && <p className="err">{err}</p>}
      <div className="row">
        <label>关键字
          <input value={kw} placeholder="退役 / 冻结 / 收口 / 单号" onChange={(e) => setKw(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') search() }} />
        </label>
        <button type="button" onClick={search}>查询审计</button>
        <button type="button" className="secondary" onClick={() => { setKw(''); setApplied(''); load('') }}>全部</button>
        <button type="button" className="secondary" onClick={() => load().catch((e) => setErr(e.message))}>刷新</button>
      </div>
      <div className="table-wrap">
        <table>
          <thead><tr><th>时间</th><th>类别</th><th>动作</th><th>关联</th><th>备注</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.编号} data-audit-action={r.动作}>
                <td>{r.时间}</td><td>{r.类别}</td><td>{r.动作}</td><td>{r.关联编号 || '-'}</td><td>{r.备注}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
